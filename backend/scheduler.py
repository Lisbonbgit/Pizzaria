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


def generate_html_report(orders: list, stats: dict, vendus: Optional[dict],
                         report_date: str, vendus_error: Optional[str] = None) -> str:
    """Gera o HTML do relatório diário. `vendus` = resumo de vendas faturadas
    (app_sales_summary) — fonte de verdade da receita; None se o Vendus falhou."""
    
    # Ordenar pedidos por hora
    orders_html = ""
    for order in orders:
        created_at = order.get("created_at", "")
        if created_at:
            try:
                dt = datetime.fromisoformat(created_at.replace('Z', '+00:00'))
                time_str = dt.strftime("%H:%M")
            except:
                time_str = "--:--"
        else:
            time_str = "--:--"
        
        order_number = order.get("order_number", "N/A")
        table_number = order.get("table_number", "N/A")
        total = order.get("total", 0)
        status = order.get("status", "")
        paid = order.get("paid", False)
        
        # Status badge
        status_labels = {
            "received": "Recebido",
            "preparing": "Preparando",
            "ready": "Pronto",
            "delivered": "Entregue"
        }
        status_text = status_labels.get(status, status.capitalize())
        paid_text = "Pago" if paid else "Pendente"
        paid_color = "#22c55e" if paid else "#f59e0b"
        
        orders_html += f"""
        <tr>
            <td style="padding: 10px; border-bottom: 1px solid #e5e7eb; text-align: center;">#{order_number}</td>
            <td style="padding: 10px; border-bottom: 1px solid #e5e7eb; text-align: center;">Mesa {table_number}</td>
            <td style="padding: 10px; border-bottom: 1px solid #e5e7eb; text-align: right; font-weight: 600;">{format_currency(total)}</td>
            <td style="padding: 10px; border-bottom: 1px solid #e5e7eb; text-align: center;">{time_str}</td>
            <td style="padding: 10px; border-bottom: 1px solid #e5e7eb; text-align: center;">
                <span style="background-color: {paid_color}; color: white; padding: 2px 8px; border-radius: 4px; font-size: 12px;">{paid_text}</span>
            </td>
        </tr>
        """
    
    # Se não houver pedidos
    if not orders:
        orders_html = """
        <tr>
            <td colspan="5" style="padding: 30px; text-align: center; color: #6b7280;">
                Nenhum pedido registado neste dia.
            </td>
        </tr>
        """
    
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

    warning_html = ""
    if vendus is None:
        warning_html = f"""
            <div style="background: #fef3c7; color: #92400e; padding: 12px 16px; border-radius: 8px; margin-bottom: 15px; font-size: 13px;">
                Nao foi possivel obter os valores faturados do Vendus ({vendus_error or 'erro'}). A atividade abaixo e apenas indicativa.
            </div>"""

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
                    </td>
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

        <!-- Orders Table -->
        <div style="background: white; padding: 30px; border: 1px solid #e5e7eb; border-top: none;">
            <h2 style="margin: 0 0 6px; font-size: 18px; color: #374151;">Pedidos do dia (atividade)</h2>
            <p style="margin: 0 0 16px; font-size: 12px; color: #9ca3af;">Itens lancados na app. No rodizio aparecem a 0,00 EUR — o valor por pessoa esta no total faturado acima.</p>
            <table style="width: 100%; border-collapse: collapse;">
                <thead>
                    <tr style="background-color: #f9fafb;">
                        <th style="padding: 12px 10px; text-align: center; font-size: 12px; color: #6b7280; text-transform: uppercase; border-bottom: 2px solid #e5e7eb;">Pedido</th>
                        <th style="padding: 12px 10px; text-align: center; font-size: 12px; color: #6b7280; text-transform: uppercase; border-bottom: 2px solid #e5e7eb;">Mesa</th>
                        <th style="padding: 12px 10px; text-align: right; font-size: 12px; color: #6b7280; text-transform: uppercase; border-bottom: 2px solid #e5e7eb;">Valor</th>
                        <th style="padding: 12px 10px; text-align: center; font-size: 12px; color: #6b7280; text-transform: uppercase; border-bottom: 2px solid #e5e7eb;">Hora</th>
                        <th style="padding: 12px 10px; text-align: center; font-size: 12px; color: #6b7280; text-transform: uppercase; border-bottom: 2px solid #e5e7eb;">Pagamento</th>
                    </tr>
                </thead>
                <tbody>
                    {orders_html}
                </tbody>
            </table>
        </div>
        
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
        html_content = generate_html_report(orders, stats, vendus, report_date_str, vendus_error)
        
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
