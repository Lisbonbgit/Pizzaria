"""
Daily Report Scheduler Module
Envia relatórios diários por email às 23:30 (Europe/Lisbon)
"""

import os
import asyncio
import logging
from datetime import datetime, timezone, timedelta
from typing import Optional
from motor.motor_asyncio import AsyncIOMotorClient
import resend

from vendus import VendusConfig, VendusClient

logger = logging.getLogger(__name__)


def _app_sales_summary_sync(date_str: str) -> dict:
    """Lê ao Vendus o resumo de vendas faturadas pela app num dia (YYYY-MM-DD).
    Síncrono (httpx) — chamar via asyncio.to_thread. Fonte de verdade da receita."""
    c = VendusClient(VendusConfig.load(os.environ))
    try:
        return c.app_sales_summary(date_str)
    finally:
        c.close()


async def resolve_resend_config(db) -> dict:
    """Resolve a config do Resend: primeiro do ambiente (.env) e, se faltar, da
    BD (db.settings key 'resend_config', preenchida no painel Relatórios). Assim
    o dono pode colar a chave no admin sem mexer nos ficheiros do servidor."""
    api_key = RESEND_API_KEY
    report_email = REPORT_EMAIL
    sender_email = REPORT_SENDER_EMAIL
    if not api_key or not report_email:
        try:
            doc = await db.settings.find_one({"key": "resend_config"}, {"_id": 0})
            val = (doc or {}).get("value", {}) or {}
        except Exception:
            val = {}
        api_key = api_key or (val.get("api_key") or "")
        report_email = report_email or (val.get("report_email") or "")
        if val.get("sender_email"):
            sender_email = val["sender_email"]
    return {"api_key": api_key, "report_email": report_email, "sender_email": sender_email}

# Configuration
RESEND_API_KEY = os.environ.get('RESEND_API_KEY', '')
REPORT_EMAIL = os.environ.get('REPORT_EMAIL', '')
REPORT_SENDER_EMAIL = os.environ.get('REPORT_SENDER_EMAIL', 'onboarding@resend.dev')
TIMEZONE = 'Europe/Lisbon'

# Initialize Resend
if RESEND_API_KEY:
    resend.api_key = RESEND_API_KEY


async def get_daily_orders(db, date: Optional[datetime] = None) -> list:
    """
    Busca pedidos confirmados ou pagos do dia especificado.
    Se date não for fornecido, usa o dia atual.
    """
    if date is None:
        # Usar timezone Europe/Lisbon
        from zoneinfo import ZoneInfo
        lisbon_tz = ZoneInfo('Europe/Lisbon')
        now = datetime.now(lisbon_tz)
        date = now
    
    # Calcular início e fim do dia
    start_of_day = date.replace(hour=0, minute=0, second=0, microsecond=0)
    end_of_day = date.replace(hour=23, minute=59, second=59, microsecond=999999)
    
    # Converter para UTC para comparação com o banco
    start_utc = start_of_day.astimezone(timezone.utc).isoformat()
    end_utc = end_of_day.astimezone(timezone.utc).isoformat()
    
    # Buscar pedidos do dia que não estão cancelados
    query = {
        "created_at": {"$gte": start_utc, "$lte": end_utc},
        "status": {"$nin": ["cancelled"]}
    }
    
    orders = await db.orders.find(query, {"_id": 0}).sort("created_at", 1).to_list(1000)
    return orders


def _lisbon_day_utc_bounds(date: Optional[datetime] = None):
    """Início/fim do dia (Europe/Lisbon) em ISO UTC — o mesmo eixo usado para
    guardar `closed_at`/`created_at`. Devolve (start_utc, end_utc)."""
    from zoneinfo import ZoneInfo
    lisbon_tz = ZoneInfo('Europe/Lisbon')
    if date is None:
        date = datetime.now(lisbon_tz)
    start = date.replace(hour=0, minute=0, second=0, microsecond=0)
    end = date.replace(hour=23, minute=59, second=59, microsecond=999999)
    return start.astimezone(timezone.utc).isoformat(), end.astimezone(timezone.utc).isoformat()


async def get_daily_cash_sessions(db, date: Optional[datetime] = None) -> list:
    """Sessões de caixa FECHADAS no dia (por `closed_at`, Europe/Lisbon). Cada
    uma traz os dados do fecho: abertura (fundo), movimentos (sangrias/reforços),
    vendas em dinheiro, esperado, contado, DIFERENÇA, quem abriu/fechou e a
    reconciliação. Ordenadas por hora de fecho."""
    start_utc, end_utc = _lisbon_day_utc_bounds(date)
    return await db.cash_sessions.find(
        {"status": "closed", "closed_at": {"$gte": start_utc, "$lte": end_utc}},
        {"_id": 0},
    ).sort("closed_at", 1).to_list(100)


async def get_open_cash_session(db) -> Optional[dict]:
    """A sessão de caixa ainda ABERTA, se houver — o relatório assinala uma caixa
    por fechar (o esperado/diferença só existem depois de fechar)."""
    return await db.cash_sessions.find_one({"status": "open"}, {"_id": 0})


async def get_daily_people(db, date: Optional[datetime] = None) -> dict:
    """Nº de mesas atendidas e de pessoas (covers) do dia — das sessões de mesa
    FECHADAS (por `closed_at`, Europe/Lisbon), repartindo o rodízio em adultos/
    crianças. Uma mesa libertada sem faturar (`free_table`) fica `cancelled` e
    NÃO entra nas contagens."""
    start_utc, end_utc = _lisbon_day_utc_bounds(date)
    sessions = await db.table_sessions.find(
        {"status": "closed", "closed_at": {"$gte": start_utc, "$lte": end_utc}},
        {"_id": 0},
    ).to_list(2000)
    people = rod_adults = rod_children = rod_tables = 0
    for s in sessions:
        people += int(s.get("people", 0) or 0)
        if s.get("rodizio") and s.get("rodizio") != "none":
            rod_tables += 1
            rp = s.get("rodizio_people") or {}
            rod_adults += int(rp.get("adults", 0) or 0)
            rod_children += int(rp.get("children", 0) or 0)
    return {
        "tables": len(sessions), "people": people,
        "rodizio_tables": rod_tables,
        "rodizio_adults": rod_adults, "rodizio_children": rod_children,
    }


def calculate_report_stats(orders: list) -> dict:
    """Estatísticas de ATIVIDADE dos pedidos da app (contagens).
    A RECEITA não vem daqui — vem das faturas do Vendus (ver app_sales_summary),
    porque o `total` do pedido não inclui rodízio nem descontos."""
    total_orders = len(orders)
    paid_orders = sum(1 for order in orders if order.get("paid", False))
    unpaid_orders = total_orders - paid_orders
    return {
        "total_orders": total_orders,
        "paid_orders": paid_orders,
        "unpaid_orders": unpaid_orders,
    }


def format_currency(value: float) -> str:
    """Formata valor como moeda EUR"""
    return f"{value:.2f} EUR"


def _hm_lisbon(iso: Optional[str]) -> str:
    """ISO (UTC) → 'HH:MM' em Europe/Lisbon; '' se ausente/malformado."""
    if not iso:
        return ""
    try:
        from zoneinfo import ZoneInfo
        dt = datetime.fromisoformat(iso)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(ZoneInfo('Europe/Lisbon')).strftime("%H:%M")
    except Exception:
        return ""


def _diff_style(diff: float):
    """Devolve (cor, rótulo) para a diferença de caixa: verde=certo, vermelho=falta,
    âmbar=sobra."""
    if abs(diff) < 0.005:
        return "#16a34a", "Certo (sem diferença)"
    if diff < 0:
        return "#dc2626", f"Falta {format_currency(abs(diff))}"
    return "#d97706", f"Sobra {format_currency(diff)}"


def _cash_movements_rows(movements: list) -> str:
    """Lista de entradas/saídas de dinheiro (movimentos) de uma sessão de caixa."""
    if not movements:
        return ""
    rows = ""
    for m in movements:
        is_in = m.get("type") == "reforco"
        label = "Entrada de dinheiro" if is_in else "Saída de dinheiro"
        color = "#16a34a" if is_in else "#dc2626"
        sign = "+" if is_in else "−"
        amt = round(float(m.get("amount", 0) or 0), 2)
        reason = (m.get("reason") or "").strip()
        hora = _hm_lisbon(m.get("at"))
        rows += f"""
                    <tr>
                        <td style="padding: 8px 10px; border-bottom: 1px solid #f1f5f9; color:{color}; font-weight:600;">{label}</td>
                        <td style="padding: 8px 10px; border-bottom: 1px solid #f1f5f9; color:#6b7280; font-size:12px;">{reason or '—'}</td>
                        <td style="padding: 8px 10px; border-bottom: 1px solid #f1f5f9; text-align:center; color:#9ca3af; font-size:12px;">{hora}</td>
                        <td style="padding: 8px 10px; border-bottom: 1px solid #f1f5f9; text-align:right; color:{color}; font-weight:700;">{sign} {format_currency(amt)}</td>
                    </tr>"""
    return f"""
            <table style="width:100%; border-collapse:collapse; margin-top:10px;">
                <thead><tr style="background:#f9fafb;">
                    <th style="padding:8px 10px; text-align:left; font-size:11px; color:#6b7280; text-transform:uppercase;">Movimento</th>
                    <th style="padding:8px 10px; text-align:left; font-size:11px; color:#6b7280; text-transform:uppercase;">Motivo</th>
                    <th style="padding:8px 10px; text-align:center; font-size:11px; color:#6b7280; text-transform:uppercase;">Hora</th>
                    <th style="padding:8px 10px; text-align:right; font-size:11px; color:#6b7280; text-transform:uppercase;">Valor</th>
                </tr></thead>
                <tbody>{rows}</tbody>
            </table>"""


def _one_cash_session_html(s: dict) -> str:
    """HTML de UMA sessão de caixa fechada — fundo, vendas em dinheiro, entradas/
    saídas, esperado vs contado e a DIFERENÇA em destaque."""
    opening = round(float(s.get("opening_amount", 0) or 0), 2)
    cash_sales = round(float(s.get("cash_sales", 0) or 0), 2)
    expected = round(float(s.get("expected_cash", 0) or 0), 2)
    counted = round(float(s.get("counted_amount", 0) or 0), 2)
    diff = round(float(s.get("difference", 0) or 0), 2)
    movements = s.get("movements") or []
    reforcos = round(sum(float(m.get("amount", 0) or 0) for m in movements if m.get("type") == "reforco"), 2)
    sangrias = round(sum(float(m.get("amount", 0) or 0) for m in movements if m.get("type") == "sangria"), 2)
    diff_color, diff_label = _diff_style(diff)

    def line(label, value, *, sign="", strong=False, color="#111827", border=True):
        b = "border-bottom: 1px solid #e5e7eb;" if border else ""
        w = "font-weight:700;" if strong else ""
        return f"""
                    <tr>
                        <td style="padding:10px; {b} color:#374151; {w}">{label}</td>
                        <td style="padding:10px; {b} text-align:right; {w} color:{color};">{sign}{format_currency(value)}</td>
                    </tr>"""

    rows = line("Fundo de abertura", opening)
    rows += line("Vendas em dinheiro", cash_sales, sign="+ ", color="#16a34a")
    if reforcos > 0:
        rows += line("Entradas de dinheiro", reforcos, sign="+ ", color="#16a34a")
    if sangrias > 0:
        rows += line("Saídas de dinheiro", sangrias, sign="− ", color="#dc2626")
    rows += line("Esperado em caixa", expected, strong=True)
    rows += line("Contado (gaveta)", counted, strong=True, border=False)

    recon = s.get("reconciliation") or {}
    if recon and not recon.get("ok", True):
        recon_html = f"""
            <div style="background:#fef3c7; color:#92400e; padding:10px 14px; border-radius:8px; margin-top:12px; font-size:12px;">
                Reconciliação com divergências — Vendus sem par nas vendas POS: {recon.get('orphans', [])}; vendas POS sem fatura: {recon.get('missing', [])}.
            </div>"""
    elif recon:
        recon_html = """
            <div style="color:#16a34a; font-size:12px; margin-top:10px;">✓ Reconciliação certa (Vendus = vendas POS).</div>"""
    else:
        recon_html = ""

    quem = []
    if s.get("opened_by_name"):
        quem.append(f"Aberta por <strong>{s['opened_by_name']}</strong> às {_hm_lisbon(s.get('opened_at'))}")
    if s.get("closed_by_name"):
        quem.append(f"Fechada por <strong>{s['closed_by_name']}</strong> às {_hm_lisbon(s.get('closed_at'))}")
    quem_html = " &nbsp;·&nbsp; ".join(quem)

    return f"""
        <div style="border:1px solid #e5e7eb; border-radius:10px; padding:18px; margin-bottom:14px;">
            <p style="margin:0 0 12px; font-size:12px; color:#6b7280;">{quem_html}</p>
            <table style="width:100%; border-collapse:collapse;">{rows}</table>
            <div style="margin-top:14px; padding:14px; border-radius:8px; background:{diff_color}12; border:1px solid {diff_color}55; text-align:center;">
                <div style="font-size:12px; color:#6b7280; text-transform:uppercase;">Diferença de caixa</div>
                <div style="font-size:28px; font-weight:800; color:{diff_color}; margin-top:4px;">{format_currency(diff)}</div>
                <div style="font-size:13px; color:{diff_color}; margin-top:2px;">{diff_label}</div>
            </div>
            {_cash_movements_rows(movements)}
            {recon_html}
        </div>"""


def build_cash_section(cash_sessions: Optional[list], open_session: Optional[dict]) -> str:
    """Secção 'Caixa' do relatório — uma ou mais sessões fechadas no dia + aviso se
    ficou alguma por fechar."""
    cash_sessions = cash_sessions or []
    inner = ""
    if cash_sessions:
        inner = "".join(_one_cash_session_html(s) for s in cash_sessions)
    else:
        inner = """<p style="color:#6b7280; padding:12px 0;">Nenhuma caixa foi fechada neste dia.</p>"""

    open_warn = ""
    if open_session is not None:
        open_warn = f"""
            <div style="background:#fef3c7; color:#92400e; padding:12px 16px; border-radius:8px; margin-bottom:14px; font-size:13px;">
                ⚠️ Há uma caixa ainda ABERTA (aberta por {open_session.get('opened_by_name','?')} às {_hm_lisbon(open_session.get('opened_at'))}). O esperado e a diferença só ficam calculados quando a fechares.
            </div>"""

    return f"""
        <div style="background: white; padding: 30px; border: 1px solid #e5e7eb; border-top: none;">
            <h2 style="margin: 0 0 16px; font-size: 18px; color: #374151;">Caixa</h2>
            {open_warn}
            {inner}
        </div>"""


def build_people_section(people: Optional[dict]) -> str:
    """Secção 'Pessoas / Mesas' do relatório."""
    p = people or {}
    tables = int(p.get("tables", 0) or 0)
    covers = int(p.get("people", 0) or 0)
    rod_tables = int(p.get("rodizio_tables", 0) or 0)
    rod_adults = int(p.get("rodizio_adults", 0) or 0)
    rod_children = int(p.get("rodizio_children", 0) or 0)
    rod_line = ""
    if rod_tables > 0:
        rod_line = f"""
            <div style="margin-top:14px; font-size:13px; color:#6b7280;">
                Rodízio: <strong style="color:#374151;">{rod_tables}</strong> mesa(s) &nbsp;·&nbsp;
                <strong style="color:#374151;">{rod_adults}</strong> adulto(s) + <strong style="color:#374151;">{rod_children}</strong> criança(s)
            </div>"""
    return f"""
        <div style="background: white; padding: 30px; border: 1px solid #e5e7eb; border-top: none;">
            <h2 style="margin: 0 0 16px; font-size: 18px; color: #374151;">Pessoas &amp; Mesas</h2>
            <table style="width: 100%; border-collapse: collapse;">
                <tr>
                    <td style="padding: 18px; text-align: center; border: 1px solid #e5e7eb; border-radius: 8px; background:#f8fafc;">
                        <div style="font-size: 30px; font-weight: 700; color: #334155;">{covers}</div>
                        <div style="font-size: 12px; color: #6b7280; text-transform: uppercase; margin-top: 5px;">Pessoas</div>
                    </td>
                    <td style="width: 15px;"></td>
                    <td style="padding: 18px; text-align: center; border: 1px solid #e5e7eb; border-radius: 8px; background:#f8fafc;">
                        <div style="font-size: 30px; font-weight: 700; color: #334155;">{tables}</div>
                        <div style="font-size: 12px; color: #6b7280; text-transform: uppercase; margin-top: 5px;">Mesas atendidas</div>
                    </td>
                </tr>
            </table>
            {rod_line}
            <p style="margin: 14px 0 0; font-size: 12px; color: #9ca3af;">Contagem das mesas fechadas (faturadas) do dia. O balcão (venda rápida) não conta pessoas.</p>
        </div>"""


def generate_html_report(orders: list, stats: dict, vendus: Optional[dict],
                         report_date: str, vendus_error: Optional[str] = None,
                         cash_sessions: Optional[list] = None,
                         open_session: Optional[dict] = None,
                         people: Optional[dict] = None) -> str:
    """Gera o HTML do relatório diário. `vendus` = resumo de vendas faturadas
    (app_sales_summary) — fonte de verdade da receita; None se o Vendus falhou."""

    # --- Dados fiscais (Vendus) — receita real faturada pela app ---
    if vendus is not None:
        fiscal_total_str = format_currency(vendus.get("total", 0))
        invoices_count = vendus.get("count", 0)
        by_method = vendus.get("by_method", {})
    else:
        fiscal_total_str = "indisponivel"
        invoices_count = 0
        by_method = {}

    if by_method:
        payments_rows = ""
        for name, d in sorted(by_method.items(), key=lambda kv: -kv[1]["total"]):
            payments_rows += f"""
                    <tr>
                        <td style="padding: 12px 10px; border-bottom: 1px solid #e5e7eb;">{name}</td>
                        <td style="padding: 12px 10px; border-bottom: 1px solid #e5e7eb; text-align: center; color: #6b7280;">{d['count']}</td>
                        <td style="padding: 12px 10px; border-bottom: 1px solid #e5e7eb; text-align: right; font-weight: 700; color: #111827;">{format_currency(d['total'])}</td>
                    </tr>"""
    else:
        payments_rows = """
                    <tr><td colspan="3" style="padding: 20px; text-align: center; color: #6b7280;">Sem faturas emitidas neste dia.</td></tr>"""

    # Contas fechadas (uma linha por fatura) — soma bate certo com o total
    invoices = vendus.get("invoices", []) if vendus is not None else []
    if invoices:
        invoices_rows = ""
        for inv in invoices:
            invoices_rows += f"""
                    <tr>
                        <td style="padding: 12px 10px; border-bottom: 1px solid #e5e7eb;">{inv.get('label','')}</td>
                        <td style="padding: 12px 10px; border-bottom: 1px solid #e5e7eb; text-align: center; color: #6b7280;">{inv.get('time','')}</td>
                        <td style="padding: 12px 10px; border-bottom: 1px solid #e5e7eb; text-align: center; color: #6b7280;">{inv.get('method','')}</td>
                        <td style="padding: 12px 10px; border-bottom: 1px solid #e5e7eb; text-align: right; font-weight: 700;">{format_currency(inv.get('amount',0))}</td>
                    </tr>"""
    else:
        invoices_rows = """
                    <tr><td colspan="4" style="padding: 20px; text-align: center; color: #6b7280;">Sem contas fechadas neste dia.</td></tr>"""

    warning_html = ""
    if vendus is None:
        warning_html = f"""
            <div style="background: #fef3c7; color: #92400e; padding: 12px 16px; border-radius: 8px; margin-bottom: 15px; font-size: 13px;">
                Nao foi possivel obter os valores faturados do Vendus ({vendus_error or 'erro'}). A atividade abaixo e apenas indicativa.
            </div>"""

    # Secções novas (caixa + pessoas)
    cash_section = build_cash_section(cash_sessions, open_session)
    people_section = build_people_section(people)

    # KPI da diferença de caixa (soma das sessões fechadas do dia) para o topo.
    _sessions = cash_sessions or []
    total_diff = round(sum(float(s.get("difference", 0) or 0) for s in _sessions), 2)
    total_counted = round(sum(float(s.get("counted_amount", 0) or 0) for s in _sessions), 2)
    covers = int((people or {}).get("people", 0) or 0)
    if _sessions:
        _dc, _dl = _diff_style(total_diff)
        diff_kpi = f"""
                    <td style="width: 15px;"></td>
                    <td style="padding: 18px; text-align: center; border: 1px solid #e5e7eb; border-radius: 8px; background:{_dc}10;">
                        <div style="font-size: 30px; font-weight: 700; color: {_dc};">{format_currency(total_diff)}</div>
                        <div style="font-size: 12px; color: #6b7280; text-transform: uppercase; margin-top: 5px;">Diferença de caixa</div>
                    </td>"""
    else:
        diff_kpi = ""

    html = f"""
<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
</head>
<body style="margin: 0; padding: 0; font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; background-color: #f3f4f6;">
    <div style="max-width: 600px; margin: 0 auto; padding: 20px;">
        <!-- Header -->
        <div style="background: linear-gradient(135deg, #dc2626 0%, #991b1b 100%); padding: 30px; text-align: center; border-radius: 12px 12px 0 0;">
            <h1 style="margin: 0; color: white; font-size: 24px;">Relatorio Diario</h1>
            <p style="margin: 10px 0 0; color: rgba(255,255,255,0.9); font-size: 16px;">{report_date}</p>
        </div>
        
        <!-- Faturado + formas de pagamento (Vendus) -->
        <div style="background: white; padding: 30px; border-left: 1px solid #e5e7eb; border-right: 1px solid #e5e7eb;">
            {warning_html}
            <table style="width: 100%; border-collapse: collapse;">
                <tr>
                    <td style="padding: 18px; text-align: center; border: 1px solid #e5e7eb; border-radius: 8px; background-color: #f0fdf4;">
                        <div style="font-size: 30px; font-weight: 700; color: #16a34a;">{fiscal_total_str}</div>
                        <div style="font-size: 12px; color: #6b7280; text-transform: uppercase; margin-top: 5px;">Faturado (app)</div>
                    </td>
                    <td style="width: 15px;"></td>
                    <td style="padding: 18px; text-align: center; border: 1px solid #e5e7eb; border-radius: 8px; background-color: #f8fafc;">
                        <div style="font-size: 30px; font-weight: 700; color: #334155;">{invoices_count}</div>
                        <div style="font-size: 12px; color: #6b7280; text-transform: uppercase; margin-top: 5px;">Faturas</div>
                    </td>{diff_kpi}
                </tr>
            </table>

            <h3 style="margin: 22px 0 8px; font-size: 14px; color: #374151; text-transform: uppercase;">Por forma de pagamento</h3>
            <table style="width: 100%; border-collapse: collapse;">
                <thead>
                    <tr style="background-color: #f9fafb;">
                        <th style="padding: 10px; text-align: left; font-size: 12px; color: #6b7280; text-transform: uppercase; border-bottom: 2px solid #e5e7eb;">Forma</th>
                        <th style="padding: 10px; text-align: center; font-size: 12px; color: #6b7280; text-transform: uppercase; border-bottom: 2px solid #e5e7eb;">Faturas</th>
                        <th style="padding: 10px; text-align: right; font-size: 12px; color: #6b7280; text-transform: uppercase; border-bottom: 2px solid #e5e7eb;">Valor</th>
                    </tr>
                </thead>
                <tbody>{payments_rows}
                    <tr style="background-color: #f0fdf4;">
                        <td style="padding: 12px 10px; font-weight: 700;">Total</td>
                        <td style="padding: 12px 10px; text-align: center; font-weight: 700;">{invoices_count}</td>
                        <td style="padding: 12px 10px; text-align: right; font-weight: 700; color: #16a34a;">{fiscal_total_str}</td>
                    </tr>
                </tbody>
            </table>

            <div style="margin-top: 18px; font-size: 13px; color: #6b7280; text-align: center;">
                Atividade: <strong style="color:#374151;">{stats['total_orders']}</strong> pedidos lancados
                &nbsp;|&nbsp; <span style="color:#22c55e;">{stats['paid_orders']} pagos</span>
                &nbsp;|&nbsp; <span style="color:#f59e0b;">{stats['unpaid_orders']} pendentes</span>
            </div>
        </div>

        <!-- Caixa (fundo, movimentos, esperado vs contado, diferença) -->
        {cash_section}

        <!-- Contas fechadas (faturas) -->
        <div style="background: white; padding: 30px; border: 1px solid #e5e7eb; border-top: none;">
            <h2 style="margin: 0 0 6px; font-size: 18px; color: #374151;">Contas fechadas do dia</h2>
            <p style="margin: 0 0 16px; font-size: 12px; color: #9ca3af;">Cada linha e uma conta faturada (mesa). A soma bate certo com o total faturado.</p>
            <table style="width: 100%; border-collapse: collapse;">
                <thead>
                    <tr style="background-color: #f9fafb;">
                        <th style="padding: 12px 10px; text-align: left; font-size: 12px; color: #6b7280; text-transform: uppercase; border-bottom: 2px solid #e5e7eb;">Conta</th>
                        <th style="padding: 12px 10px; text-align: center; font-size: 12px; color: #6b7280; text-transform: uppercase; border-bottom: 2px solid #e5e7eb;">Hora</th>
                        <th style="padding: 12px 10px; text-align: center; font-size: 12px; color: #6b7280; text-transform: uppercase; border-bottom: 2px solid #e5e7eb;">Pagamento</th>
                        <th style="padding: 12px 10px; text-align: right; font-size: 12px; color: #6b7280; text-transform: uppercase; border-bottom: 2px solid #e5e7eb;">Valor</th>
                    </tr>
                </thead>
                <tbody>{invoices_rows}
                    <tr style="background-color: #f0fdf4;">
                        <td colspan="3" style="padding: 12px 10px; font-weight: 700;">Total</td>
                        <td style="padding: 12px 10px; text-align: right; font-weight: 700; color: #16a34a;">{fiscal_total_str}</td>
                    </tr>
                </tbody>
            </table>
            <p style="margin: 14px 0 0; font-size: 12px; color: #9ca3af;">Foram lancados {stats['total_orders']} itens/pedidos na app (no rodizio muitos vao a 0,00 EUR porque o cliente paga por pessoa, nao por item).</p>
        </div>
        
        <!-- Pessoas & Mesas -->
        {people_section}

        <!-- Footer -->
        <div style="background: #374151; padding: 20px; text-align: center; border-radius: 0 0 12px 12px;">
            <p style="margin: 0; color: rgba(255,255,255,0.7); font-size: 12px;">
                Relatorio gerado automaticamente pelo sistema de gestao.
            </p>
            <p style="margin: 5px 0 0; color: rgba(255,255,255,0.5); font-size: 11px;">
                Este email foi enviado para {REPORT_EMAIL}
            </p>
        </div>
    </div>
</body>
</html>
"""
    return html


async def send_daily_report(db, date: Optional[datetime] = None, force: bool = False) -> dict:
    """
    Gera e envia o relatório diário por email.
    
    Args:
        db: Conexão com o banco de dados
        date: Data do relatório (opcional, usa hoje por padrão)
        force: Se True, envia mesmo sem API key configurada (para teste)
    
    Returns:
        dict com status do envio
    """
    from zoneinfo import ZoneInfo
    lisbon_tz = ZoneInfo('Europe/Lisbon')
    
    if date is None:
        date = datetime.now(lisbon_tz)
    
    report_date_str = date.strftime("%d/%m/%Y")
    
    logger.info(f"Gerando relatório diário para {report_date_str}")

    # Verificar configuração (ambiente OU painel/BD)
    rcfg = await resolve_resend_config(db)
    if not rcfg["api_key"]:
        error_msg = "RESEND_API_KEY não configurada"
        logger.error(error_msg)
        await log_report_attempt(db, report_date_str, False, error_msg)
        return {"success": False, "error": error_msg}

    if not rcfg["report_email"]:
        error_msg = "REPORT_EMAIL não configurado"
        logger.error(error_msg)
        await log_report_attempt(db, report_date_str, False, error_msg)
        return {"success": False, "error": error_msg}

    resend.api_key = rcfg["api_key"]

    try:
        # Buscar pedidos do dia (atividade)
        orders = await get_daily_orders(db, date)
        logger.info(f"Encontrados {len(orders)} pedidos para o relatório")

        # Caixa (sessões fechadas do dia + eventual caixa aberta) e pessoas/mesas.
        cash_sessions = await get_daily_cash_sessions(db, date)
        open_session = await get_open_cash_session(db)
        people = await get_daily_people(db, date)
        logger.info(f"Caixa: {len(cash_sessions)} sessão(ões) fechada(s); "
                    f"pessoas: {people.get('people')} em {people.get('tables')} mesa(s)")

        # Estatísticas de atividade
        stats = calculate_report_stats(orders)

        # Receita REAL: faturas do Vendus (caixa da app). Se o Vendus falhar, o
        # relatório sai na mesma, com aviso, em vez de não sair de todo.
        vendus = None
        vendus_error = None
        try:
            vendus = await asyncio.to_thread(_app_sales_summary_sync, date.strftime("%Y-%m-%d"))
            logger.info(f"Vendus: {vendus.get('count')} faturas, total {vendus.get('total')} EUR")
        except Exception as e:
            vendus_error = str(e)
            logger.error(f"Relatório: falha ao obter vendas do Vendus: {vendus_error}")

        # Enriquecer o registo com os valores faturados
        stats = {**stats, "faturado": (vendus or {}).get("total"),
                 "faturas": (vendus or {}).get("count", 0)}

        # Gerar HTML
        html_content = generate_html_report(
            orders, stats, vendus, report_date_str, vendus_error,
            cash_sessions=cash_sessions, open_session=open_session, people=people)
        
        # Preparar email
        subject = f"Relatorio Diario - {report_date_str}"
        
        params = {
            "from": rcfg["sender_email"],
            "to": [rcfg["report_email"]],
            "subject": subject,
            "html": html_content
        }
        
        # Enviar email de forma assíncrona (não bloqueante)
        logger.info(f"Enviando relatório para {rcfg['report_email']}")
        email_result = await asyncio.to_thread(resend.Emails.send, params)
        
        email_id = email_result.get("id") if isinstance(email_result, dict) else str(email_result)
        logger.info(f"Email enviado com sucesso. ID: {email_id}")
        
        # Registar sucesso
        await log_report_attempt(db, report_date_str, True, None, email_id, stats)
        
        return {
            "success": True,
            "email_id": email_id,
            "report_date": report_date_str,
            "stats": stats,
            "orders_count": len(orders)
        }
        
    except Exception as e:
        error_msg = str(e)
        logger.error(f"Erro ao enviar relatório: {error_msg}")
        await log_report_attempt(db, report_date_str, False, error_msg)
        return {"success": False, "error": error_msg}


async def log_report_attempt(
    db,
    report_date: str,
    success: bool,
    error: Optional[str] = None,
    email_id: Optional[str] = None,
    stats: Optional[dict] = None
):
    """Regista tentativa de envio do relatório no banco de dados"""
    log_entry = {
        "report_date": report_date,
        "success": success,
        "error": error,
        "email_id": email_id,
        "stats": stats,
        "timestamp": datetime.now(timezone.utc).isoformat()
    }
    
    await db.report_logs.insert_one(log_entry)
    logger.info(f"Log de relatório registado: success={success}")


def run_daily_report_sync(mongo_url: str, db_name: str):
    """
    Função síncrona para executar o relatório diário.
    Usada pelo APScheduler que não suporta funções async diretamente.
    """
    async def _run():
        client = AsyncIOMotorClient(mongo_url)
        db = client[db_name]
        try:
            result = await send_daily_report(db)
            logger.info(f"Resultado do relatório diário: {result}")
        finally:
            client.close()
    
    # Executar em um novo event loop
    asyncio.run(_run())
