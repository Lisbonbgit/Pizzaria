"""
Daily Report Scheduler Module
Envia relatórios diários por email à 00:00 (Europe/Lisbon) — reporta o dia anterior
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


# ---- Paleta e helpers de estilo do email (design suave, cartões arredondados) ----
_INK = "#2a221e"
_MUTED = "#8c817a"
_HAIR = "#efe9e4"
_MAROON = "#5a1a1a"
_GREEN = "#16a34a"
_PAGE_BG = "#efe9e4"

_CARD = ("background:#ffffff; border:1px solid #efe9e4; border-radius:18px; "
         "box-shadow:0 2px 6px rgba(60,40,30,0.06); padding:26px 26px; margin:0 0 16px;")


def _section_title(text: str, icon: str = "") -> str:
    ic = f'<span style="margin-right:8px;">{icon}</span>' if icon else ""
    return (f'<h2 style="margin:0 0 4px; font-size:17px; font-weight:800; color:{_MAROON}; '
            f'letter-spacing:-0.02em;">{ic}{text}</h2>')


def _subtle(text: str) -> str:
    return f'<p style="margin:0 0 16px; font-size:12px; color:{_MUTED};">{text}</p>'


def _stat_tile(value, label, color=_INK, tint="#f6f2ef") -> str:
    return (f'<td style="padding:18px 8px; text-align:center; background:{tint}; border-radius:14px; '
            f'vertical-align:top;">'
            f'<div style="font-size:25px; font-weight:800; color:{color}; letter-spacing:-0.02em; white-space:nowrap;">{value}</div>'
            f'<div style="font-size:11px; color:{_MUTED}; text-transform:uppercase; letter-spacing:0.05em; margin-top:6px;">{label}</div>'
            f'</td>')


def _money_row(label, value, *, sign="", color=_INK, strong=False, hair=True) -> str:
    b = f"border-bottom:1px solid {_HAIR};" if hair else ""
    fw = "800" if strong else "500"
    lc = _INK if strong else "#5a534d"
    return (f'<tr>'
            f'<td style="padding:9px 2px; {b} color:{lc}; font-size:14px; font-weight:{"700" if strong else "400"};">{label}</td>'
            f'<td style="padding:9px 2px; {b} text-align:right; color:{color}; font-size:14px; font-weight:{fw}; white-space:nowrap;">{sign}{format_currency(value)}</td>'
            f'</tr>')


def _cash_movements_rows(movements: list) -> str:
    """Lista suave de entradas/saídas de dinheiro (movimentos) de uma sessão."""
    if not movements:
        return ""
    rows = ""
    for m in movements:
        is_in = m.get("type") == "reforco"
        label = "Entrada de dinheiro" if is_in else "Saída de dinheiro"
        color = _GREEN if is_in else "#dc2626"
        sign = "+ " if is_in else "− "
        amt = round(float(m.get("amount", 0) or 0), 2)
        reason = (m.get("reason") or "").strip()
        hora = _hm_lisbon(m.get("at"))
        meta = " · ".join([x for x in [reason, hora] if x]) or "—"
        rows += (f'<tr>'
                 f'<td style="padding:7px 2px; border-bottom:1px solid {_HAIR};">'
                 f'<span style="color:{color}; font-weight:700; font-size:13px;">{label}</span>'
                 f'<span style="color:{_MUTED}; font-size:12px;"> &nbsp;{meta}</span></td>'
                 f'<td style="padding:7px 2px; border-bottom:1px solid {_HAIR}; text-align:right; color:{color}; font-weight:700; font-size:13px; white-space:nowrap;">{sign}{format_currency(amt)}</td>'
                 f'</tr>')
    return (f'<div style="margin-top:14px;">'
            f'<div style="font-size:11px; color:{_MUTED}; text-transform:uppercase; letter-spacing:0.05em; margin-bottom:4px;">Movimentos</div>'
            f'<table style="width:100%; border-collapse:collapse;">{rows}</table></div>')


def _one_cash_session_html(s: dict) -> str:
    """Painel suave de UMA sessão de caixa fechada — fundo, vendas em dinheiro,
    entradas/saídas, esperado vs contado e a DIFERENÇA em pílula destacada."""
    opening = round(float(s.get("opening_amount", 0) or 0), 2)
    cash_sales = round(float(s.get("cash_sales", 0) or 0), 2)
    expected = round(float(s.get("expected_cash", 0) or 0), 2)
    counted = round(float(s.get("counted_amount", 0) or 0), 2)
    diff = round(float(s.get("difference", 0) or 0), 2)
    movements = s.get("movements") or []
    reforcos = round(sum(float(m.get("amount", 0) or 0) for m in movements if m.get("type") == "reforco"), 2)
    sangrias = round(sum(float(m.get("amount", 0) or 0) for m in movements if m.get("type") == "sangria"), 2)
    diff_color, diff_label = _diff_style(diff)

    rows = _money_row("Fundo de abertura", opening)
    rows += _money_row("Vendas em dinheiro", cash_sales, sign="+ ", color=_GREEN)
    if reforcos > 0:
        rows += _money_row("Entradas de dinheiro", reforcos, sign="+ ", color=_GREEN)
    if sangrias > 0:
        rows += _money_row("Saídas de dinheiro", sangrias, sign="− ", color="#dc2626")
    rows += _money_row("Esperado em caixa", expected, strong=True)
    rows += _money_row("Contado (gaveta)", counted, strong=True, hair=False)

    recon = s.get("reconciliation") or {}
    if recon and not recon.get("ok", True):
        recon_html = (f'<div style="background:#fdf6e3; color:#92400e; padding:10px 14px; border-radius:12px; '
                      f'margin-top:12px; font-size:12px;">Reconciliação com divergências — Vendus sem par: '
                      f'{recon.get("orphans", [])}; vendas POS sem fatura: {recon.get("missing", [])}.</div>')
    elif recon:
        recon_html = (f'<div style="margin-top:12px; font-size:12px; color:{_GREEN}; font-weight:600;">'
                      f'✓ Reconciliação certa (Vendus = vendas POS)</div>')
    else:
        recon_html = ""

    quem = []
    if s.get("opened_by_name"):
        quem.append(f'Aberta por <strong style="color:{_INK};">{s["opened_by_name"]}</strong> · {_hm_lisbon(s.get("opened_at"))}')
    if s.get("closed_by_name"):
        quem.append(f'Fechada por <strong style="color:{_INK};">{s["closed_by_name"]}</strong> · {_hm_lisbon(s.get("closed_at"))}')
    quem_html = " &nbsp;&nbsp;·&nbsp;&nbsp; ".join(quem)

    return (f'<div style="background:#faf7f4; border-radius:14px; padding:20px; margin-bottom:12px;">'
            f'<p style="margin:0 0 14px; font-size:12px; color:{_MUTED};">{quem_html}</p>'
            f'<table style="width:100%; border-collapse:collapse;">{rows}</table>'
            f'<div style="margin-top:16px; padding:16px; border-radius:14px; background:{diff_color}14; text-align:center;">'
            f'<div style="font-size:11px; color:{_MUTED}; text-transform:uppercase; letter-spacing:0.06em;">Diferença de caixa</div>'
            f'<div style="font-size:30px; font-weight:800; color:{diff_color}; margin-top:4px; letter-spacing:-0.02em;">{format_currency(diff)}</div>'
            f'<div style="font-size:13px; color:{diff_color}; font-weight:600; margin-top:2px;">{diff_label}</div>'
            f'</div>{_cash_movements_rows(movements)}{recon_html}</div>')


def build_cash_section(cash_sessions: Optional[list], open_session: Optional[dict]) -> str:
    """Secção 'Caixa' (cartão) — sessões fechadas do dia + aviso se ficou por fechar."""
    cash_sessions = cash_sessions or []
    if cash_sessions:
        inner = "".join(_one_cash_session_html(s) for s in cash_sessions)
    else:
        inner = f'<p style="color:{_MUTED}; font-size:14px; margin:6px 0;">Nenhuma caixa foi fechada neste dia.</p>'

    open_warn = ""
    if open_session is not None:
        open_warn = (f'<div style="background:#fdf6e3; color:#92400e; padding:12px 16px; border-radius:14px; '
                     f'margin-bottom:14px; font-size:13px;">⚠️ Há uma caixa ainda <strong>aberta</strong> '
                     f'(por {open_session.get("opened_by_name", "?")} às {_hm_lisbon(open_session.get("opened_at"))}). '
                     f'O esperado e a diferença só ficam calculados quando a fechares.</div>')

    return (f'<div style="{_CARD}">{_section_title("Caixa", "💶")}'
            f'{_subtle("Fundo, entradas/saídas, esperado vs contado e a diferença.")}'
            f'{open_warn}{inner}</div>')


def build_people_section(people: Optional[dict]) -> str:
    """Secção 'Pessoas & Mesas' (cartão)."""
    p = people or {}
    tables = int(p.get("tables", 0) or 0)
    covers = int(p.get("people", 0) or 0)
    rod_tables = int(p.get("rodizio_tables", 0) or 0)
    rod_adults = int(p.get("rodizio_adults", 0) or 0)
    rod_children = int(p.get("rodizio_children", 0) or 0)
    rod_line = ""
    if rod_tables > 0:
        rod_line = (f'<div style="margin-top:16px; padding:12px 16px; background:#f6f2ef; border-radius:12px; '
                    f'font-size:13px; color:{_MUTED};">🍢 Rodízio: <strong style="color:{_INK};">{rod_tables}</strong> mesa(s) '
                    f'&nbsp;·&nbsp; <strong style="color:{_INK};">{rod_adults}</strong> adulto(s) + '
                    f'<strong style="color:{_INK};">{rod_children}</strong> criança(s)</div>')
    tiles = (f'<table style="width:100%; border-collapse:separate; border-spacing:10px 0;"><tr>'
             f'{_stat_tile(covers, "Pessoas", color=_MAROON)}'
             f'{_stat_tile(tables, "Mesas atendidas", color=_INK)}'
             f'</tr></table>')
    return (f'<div style="{_CARD}">{_section_title("Pessoas &amp; Mesas", "👥")}'
            f'{_subtle("Contagem das mesas faturadas do dia (o balcão não conta pessoas).")}'
            f'{tiles}{rod_line}</div>')


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
        fiscal_total_str = "indisponível"
        invoices_count = 0
        by_method = {}

    # Linhas de "por forma de pagamento" (suaves)
    if by_method:
        payments_rows = ""
        for name, d in sorted(by_method.items(), key=lambda kv: -kv[1]["total"]):
            payments_rows += (f'<tr>'
                              f'<td style="padding:11px 2px; border-bottom:1px solid {_HAIR}; color:{_INK}; font-size:14px;">{name}</td>'
                              f'<td style="padding:11px 2px; border-bottom:1px solid {_HAIR}; text-align:center; color:{_MUTED}; font-size:13px;">{d["count"]}</td>'
                              f'<td style="padding:11px 2px; border-bottom:1px solid {_HAIR}; text-align:right; font-weight:700; color:{_INK}; font-size:14px; white-space:nowrap;">{format_currency(d["total"])}</td>'
                              f'</tr>')
    else:
        payments_rows = (f'<tr><td colspan="3" style="padding:18px; text-align:center; color:{_MUTED};">'
                         f'Sem faturas emitidas neste dia.</td></tr>')

    # Linhas de "contas fechadas" (suaves)
    invoices = vendus.get("invoices", []) if vendus is not None else []
    if invoices:
        invoices_rows = ""
        for inv in invoices:
            invoices_rows += (f'<tr>'
                              f'<td style="padding:11px 2px; border-bottom:1px solid {_HAIR}; color:{_INK}; font-size:14px;">{inv.get("label", "")}</td>'
                              f'<td style="padding:11px 2px; border-bottom:1px solid {_HAIR}; text-align:center; color:{_MUTED}; font-size:13px;">{inv.get("time", "")}</td>'
                              f'<td style="padding:11px 2px; border-bottom:1px solid {_HAIR}; text-align:center; color:{_MUTED}; font-size:13px;">{inv.get("method", "")}</td>'
                              f'<td style="padding:11px 2px; border-bottom:1px solid {_HAIR}; text-align:right; font-weight:700; color:{_INK}; font-size:14px; white-space:nowrap;">{format_currency(inv.get("amount", 0))}</td>'
                              f'</tr>')
    else:
        invoices_rows = (f'<tr><td colspan="4" style="padding:18px; text-align:center; color:{_MUTED};">'
                         f'Sem contas fechadas neste dia.</td></tr>')

    warning_html = ""
    if vendus is None:
        warning_html = (f'<div style="background:#fdf6e3; color:#92400e; padding:12px 16px; border-radius:14px; '
                        f'margin-bottom:16px; font-size:13px;">Não foi possível obter os valores faturados do Vendus '
                        f'({vendus_error or "erro"}). A atividade abaixo é apenas indicativa.</div>')

    # Secções (cartões) novas
    cash_section = build_cash_section(cash_sessions, open_session)
    people_section = build_people_section(people)

    # KPIs do topo: Faturado + (Diferença de caixa OU Faturas) + Pessoas
    _sessions = cash_sessions or []
    total_diff = round(sum(float(s.get("difference", 0) or 0) for s in _sessions), 2)
    covers = int((people or {}).get("people", 0) or 0)
    kpi_faturado = _stat_tile(fiscal_total_str, "Faturado", color=_GREEN, tint="#eef7f0")
    if _sessions:
        _dc, _dl = _diff_style(total_diff)
        kpi_mid = _stat_tile(format_currency(total_diff), "Diferença de caixa", color=_dc, tint=f"{_dc}14")
    else:
        kpi_mid = _stat_tile(invoices_count, "Faturas", color=_INK)
    kpi_pessoas = _stat_tile(covers, "Pessoas", color=_MAROON, tint="#f6f2ef")
    kpi_row = (f'<table style="width:100%; border-collapse:separate; border-spacing:10px 0;"><tr>'
               f'{kpi_faturado}{kpi_mid}{kpi_pessoas}</tr></table>')

    # Cartão de vendas (KPIs + por forma de pagamento + atividade)
    vendas_card = (
        f'<div style="{_CARD}">'
        f'{warning_html}{kpi_row}'
        f'<div style="height:8px;"></div>'
        f'{_section_title("Vendas", "🧾")}'
        f'{_subtle("Receita faturada (Vendus) e repartição por forma de pagamento.")}'
        f'<table style="width:100%; border-collapse:collapse;">'
        f'<thead><tr>'
        f'<th style="padding:8px 2px; text-align:left; font-size:11px; color:{_MUTED}; text-transform:uppercase; letter-spacing:0.05em; border-bottom:2px solid {_HAIR};">Forma</th>'
        f'<th style="padding:8px 2px; text-align:center; font-size:11px; color:{_MUTED}; text-transform:uppercase; letter-spacing:0.05em; border-bottom:2px solid {_HAIR};">Faturas</th>'
        f'<th style="padding:8px 2px; text-align:right; font-size:11px; color:{_MUTED}; text-transform:uppercase; letter-spacing:0.05em; border-bottom:2px solid {_HAIR};">Valor</th>'
        f'</tr></thead><tbody>{payments_rows}'
        f'<tr><td style="padding:12px 2px; font-weight:800; color:{_INK};">Total</td>'
        f'<td style="padding:12px 2px; text-align:center; font-weight:700; color:{_MUTED};">{invoices_count}</td>'
        f'<td style="padding:12px 2px; text-align:right; font-weight:800; color:{_GREEN}; font-size:15px; white-space:nowrap;">{fiscal_total_str}</td></tr>'
        f'</tbody></table>'
        f'<div style="margin-top:16px; padding-top:14px; border-top:1px solid {_HAIR}; font-size:12px; color:{_MUTED}; text-align:center;">'
        f'Atividade: <strong style="color:{_INK};">{stats["total_orders"]}</strong> pedidos'
        f' &nbsp;·&nbsp; <span style="color:{_GREEN};">{stats["paid_orders"]} pagos</span>'
        f' &nbsp;·&nbsp; <span style="color:#d97706;">{stats["unpaid_orders"]} pendentes</span></div>'
        f'</div>'
    )

    # Cartão de contas fechadas
    contas_card = (
        f'<div style="{_CARD}">{_section_title("Contas fechadas", "📋")}'
        f'{_subtle("Cada linha é uma conta faturada; a soma bate com o total faturado.")}'
        f'<table style="width:100%; border-collapse:collapse;">'
        f'<thead><tr>'
        f'<th style="padding:8px 2px; text-align:left; font-size:11px; color:{_MUTED}; text-transform:uppercase; letter-spacing:0.05em; border-bottom:2px solid {_HAIR};">Conta</th>'
        f'<th style="padding:8px 2px; text-align:center; font-size:11px; color:{_MUTED}; text-transform:uppercase; letter-spacing:0.05em; border-bottom:2px solid {_HAIR};">Hora</th>'
        f'<th style="padding:8px 2px; text-align:center; font-size:11px; color:{_MUTED}; text-transform:uppercase; letter-spacing:0.05em; border-bottom:2px solid {_HAIR};">Pagamento</th>'
        f'<th style="padding:8px 2px; text-align:right; font-size:11px; color:{_MUTED}; text-transform:uppercase; letter-spacing:0.05em; border-bottom:2px solid {_HAIR};">Valor</th>'
        f'</tr></thead><tbody>{invoices_rows}'
        f'<tr><td colspan="3" style="padding:12px 2px; font-weight:800; color:{_INK};">Total</td>'
        f'<td style="padding:12px 2px; text-align:right; font-weight:800; color:{_GREEN}; font-size:15px; white-space:nowrap;">{fiscal_total_str}</td></tr>'
        f'</tbody></table></div>'
    )

    html = f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
</head>
<body style="margin:0; padding:0; font-family:-apple-system,'Segoe UI',Roboto,Helvetica,Arial,sans-serif; background-color:{_PAGE_BG};">
    <div style="max-width: 600px; margin: 0 auto; padding: 22px 16px 30px;">
        <!-- Header -->
        <div style="background:linear-gradient(135deg,#6d2119 0%,#3f120f 100%); padding:34px 30px; text-align:center; border-radius:20px; box-shadow:0 4px 14px rgba(90,26,26,0.28);">
            <div style="font-size:12px; letter-spacing:0.18em; color:rgba(255,255,255,0.72); text-transform:uppercase; margin-bottom:8px;">🔥 Lenha e Brasa</div>
            <h1 style="margin:0; color:#ffffff; font-size:26px; font-weight:800; letter-spacing:-0.02em;">Relatório do dia</h1>
            <p style="margin:8px 0 0; color:rgba(255,255,255,0.82); font-size:15px;">{report_date}</p>
        </div>

        <div style="height:18px;"></div>

        {vendas_card}
        {cash_section}
        {contas_card}
        {people_section}

        <!-- Footer -->
        <div style="text-align:center; padding:8px 10px 0;">
            <p style="margin:0; color:{_MUTED}; font-size:12px;">Relatório gerado automaticamente pelo sistema de gestão.</p>
            <p style="margin:4px 0 0; color:#b8aca3; font-size:11px;">Enviado para {REPORT_EMAIL}</p>
        </div>
    </div>
</body>
</html>"""
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
