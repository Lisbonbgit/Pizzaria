"""
Daily Report Scheduler Module
Envia relatórios diários por email às 23:59 (Europe/Lisbon)
"""

import os
import asyncio
import logging
from datetime import datetime, timezone, timedelta
from typing import Optional
from motor.motor_asyncio import AsyncIOMotorClient
import resend

logger = logging.getLogger(__name__)

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
    """Calcula estatísticas do relatório"""
    if not orders:
        return {
            "total_orders": 0,
            "total_revenue": 0.0,
            "average_ticket": 0.0,
            "payment_methods": {},
            "paid_orders": 0,
            "unpaid_orders": 0
        }
    
    total_orders = len(orders)
    total_revenue = sum(order.get("total", 0) for order in orders)
    average_ticket = total_revenue / total_orders if total_orders > 0 else 0
    
    # Contagem de pedidos pagos vs não pagos
    paid_orders = sum(1 for order in orders if order.get("paid", False))
    unpaid_orders = total_orders - paid_orders
    
    return {
        "total_orders": total_orders,
        "total_revenue": total_revenue,
        "average_ticket": average_ticket,
        "paid_orders": paid_orders,
        "unpaid_orders": unpaid_orders
    }


def format_currency(value: float) -> str:
    """Formata valor como moeda EUR"""
    return f"{value:.2f} EUR"


def generate_html_report(orders: list, stats: dict, report_date: str) -> str:
    """Gera o HTML do relatório diário"""
    
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
        
        <!-- Stats Cards -->
        <div style="background: white; padding: 30px; border-left: 1px solid #e5e7eb; border-right: 1px solid #e5e7eb;">
            <table style="width: 100%; border-collapse: collapse;">
                <tr>
                    <td style="padding: 15px; text-align: center; border: 1px solid #e5e7eb; border-radius: 8px; background-color: #fef2f2;">
                        <div style="font-size: 28px; font-weight: 700; color: #dc2626;">{stats['total_orders']}</div>
                        <div style="font-size: 12px; color: #6b7280; text-transform: uppercase; margin-top: 5px;">Pedidos</div>
                    </td>
                    <td style="width: 15px;"></td>
                    <td style="padding: 15px; text-align: center; border: 1px solid #e5e7eb; border-radius: 8px; background-color: #f0fdf4;">
                        <div style="font-size: 28px; font-weight: 700; color: #22c55e;">{format_currency(stats['total_revenue'])}</div>
                        <div style="font-size: 12px; color: #6b7280; text-transform: uppercase; margin-top: 5px;">Receita Bruta</div>
                    </td>
                </tr>
            </table>
            
            <table style="width: 100%; border-collapse: collapse; margin-top: 15px;">
                <tr>
                    <td style="padding: 15px; text-align: center; border: 1px solid #e5e7eb; border-radius: 8px; background-color: #eff6ff;">
                        <div style="font-size: 20px; font-weight: 700; color: #3b82f6;">{format_currency(stats['average_ticket'])}</div>
                        <div style="font-size: 12px; color: #6b7280; text-transform: uppercase; margin-top: 5px;">Ticket Medio</div>
                    </td>
                    <td style="width: 15px;"></td>
                    <td style="padding: 15px; text-align: center; border: 1px solid #e5e7eb; border-radius: 8px;">
                        <div style="font-size: 14px;">
                            <span style="color: #22c55e; font-weight: 600;">{stats['paid_orders']} pagos</span>
                            <span style="color: #9ca3af; margin: 0 5px;">|</span>
                            <span style="color: #f59e0b; font-weight: 600;">{stats['unpaid_orders']} pendentes</span>
                        </div>
                        <div style="font-size: 12px; color: #6b7280; text-transform: uppercase; margin-top: 5px;">Estado Pagamentos</div>
                    </td>
                </tr>
            </table>
        </div>
        
        <!-- Orders Table -->
        <div style="background: white; padding: 30px; border: 1px solid #e5e7eb; border-top: none;">
            <h2 style="margin: 0 0 20px; font-size: 18px; color: #374151;">Lista de Pedidos</h2>
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
    
    # Verificar configuração
    if not RESEND_API_KEY:
        error_msg = "RESEND_API_KEY não configurada"
        logger.error(error_msg)
        await log_report_attempt(db, report_date_str, False, error_msg)
        return {"success": False, "error": error_msg}
    
    if not REPORT_EMAIL:
        error_msg = "REPORT_EMAIL não configurado"
        logger.error(error_msg)
        await log_report_attempt(db, report_date_str, False, error_msg)
        return {"success": False, "error": error_msg}
    
    try:
        # Buscar pedidos do dia
        orders = await get_daily_orders(db, date)
        logger.info(f"Encontrados {len(orders)} pedidos para o relatório")
        
        # Calcular estatísticas
        stats = calculate_report_stats(orders)
        
        # Gerar HTML
        html_content = generate_html_report(orders, stats, report_date_str)
        
        # Preparar email
        subject = f"Relatorio Diario - {report_date_str}"
        
        params = {
            "from": REPORT_SENDER_EMAIL,
            "to": [REPORT_EMAIL],
            "subject": subject,
            "html": html_content
        }
        
        # Enviar email de forma assíncrona (não bloqueante)
        logger.info(f"Enviando relatório para {REPORT_EMAIL}")
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
