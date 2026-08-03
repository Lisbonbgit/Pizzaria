from fastapi import FastAPI, APIRouter, HTTPException, Depends, UploadFile, File, Query, BackgroundTasks, Header, Request
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from dotenv import load_dotenv
from starlette.middleware.cors import CORSMiddleware
from motor.motor_asyncio import AsyncIOMotorClient
import os
import logging
import re
from pathlib import Path
from pydantic import BaseModel, Field, ConfigDict, EmailStr
from typing import List, Optional, Dict, Any
import uuid
from datetime import datetime, timezone, timedelta
from zoneinfo import ZoneInfo
import bcrypt
import jwt
import socket
import asyncio
import qrcode
import io
import base64
import secrets
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from pymongo.errors import DuplicateKeyError, BulkWriteError
from pymongo import ReturnDocument
from vendus import VendusConfig, VendusClient, VendusError
from pos.auth import hash_token, verify_token, create_pos_token, decode_pos_token
from pos.cash import pick_open_session
from pos.sales import build_pos_sales_rows
from pos.idempotency import stable_ext_ref
from pos.cash_math import cash_sales_from_vendus, expected_cash, movements_breakdown, reconciliation_diff
from pos.z_report import build_z_escpos
from pos.counter import build_counter_items, counter_ext_ref
from pos.app_products import extract_app_products, is_app_product
from pos.pricing import line_vendus, combine_global

ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / '.env')

# Create uploads directory
UPLOADS_DIR = ROOT_DIR / 'uploads'
UPLOADS_DIR.mkdir(exist_ok=True)

# Ficheiros para download (ex.: APK da ponte de impressão). Montado por volume em
# produção (./backend/appfiles:/app/appfiles), atualizável sem rebuild da imagem.
APP_FILES_DIR = ROOT_DIR / 'appfiles'
APP_FILES_DIR.mkdir(exist_ok=True)
PRINT_BRIDGE_APK = APP_FILES_DIR / 'print-bridge.apk'

# MongoDB connection
mongo_url = os.environ['MONGO_URL']
client = AsyncIOMotorClient(mongo_url)
db = client[os.environ['DB_NAME']]

# JWT Configuration
# Fail-closed: sem um JWT_SECRET forte a app NÃO arranca (senão qualquer pessoa que
# conheça o default committado forjaria tokens de admin).
JWT_SECRET = os.environ.get('JWT_SECRET', '')
if not JWT_SECRET or JWT_SECRET == 'pizzaria-secret-key-2024':
    raise RuntimeError(
        "JWT_SECRET em falta ou a usar o valor por defeito. "
        "Defina um segredo forte em backend/.env (ex.: openssl rand -hex 32)."
    )
JWT_ALGORITHM = "HS256"

# Print Agent API Key (generate on first run or from env)
PRINT_AGENT_API_KEY = os.environ.get('PRINT_AGENT_API_KEY', None)

# Daily Report Scheduler
scheduler = AsyncIOScheduler(timezone='Europe/Lisbon')
SCHEDULER_ENABLED = False  # Desativado por padrão, ativado após teste manual

from contextlib import asynccontextmanager


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Ciclo de vida da app (substitui os antigos @app.on_event)."""
    global SCHEDULER_ENABLED

    # --- Avisos de configuração ---
    if not ADMIN_PASSWORD_HASH:
        logger.warning(
            "ADMIN_PASSWORD_HASH não configurado — o login de admin vai falhar. "
            "Gere com: python scripts/generate_password_hash.py"
        )

    # --- Chave do Print Agent ---
    # Se PRINT_AGENT_API_KEY estiver no .env, provisiona-a (sem sobrepor uma já
    # existente/gerada no Admin). Senão, a chave é gerida no painel de Admin.
    if PRINT_AGENT_API_KEY:
        try:
            await db.settings.update_one(
                {"key": "print_agent"},
                {"$setOnInsert": {
                    "key": "print_agent",
                    "value": {
                        "api_key": PRINT_AGENT_API_KEY,
                        "created_at": datetime.now(timezone.utc).isoformat(),
                    },
                }},
                upsert=True,
            )
        except Exception as e:
            logger.error(f"Não foi possível provisionar PRINT_AGENT_API_KEY: {e}")

    # --- Índice único parcial da caixa (uma só sessão aberta de cada vez) ---
    # Garante a unicidade atómica ao nível da BD (§4.1): duas aberturas em
    # concorrência só conseguem UM insert_one bem-sucedido, a outra apanha
    # DuplicateKeyError (tratado em open_cash_session). Falha aqui não deve
    # impedir o arranque da API — fica registada e revista manualmente.
    try:
        await db.cash_sessions.create_index(
            [("status", 1)], unique=True, partialFilterExpression={"status": "open"}
        )
    except Exception as e:
        logger.error(f"Não foi possível criar o índice único de cash_sessions: {e}")

    # --- Índice único de pos_sales (uma linha por documento fiscal) ---
    # Cada venda POS = uma FS emitida no Vendus. O índice único em
    # `vendus_document_id` torna a gravação idempotente: um retry de um fecho já
    # registado não duplica linhas (o insert_many em close_table absorve os
    # duplicados). Falha aqui não deve impedir o arranque — fica registada.
    try:
        await db.pos_sales.create_index("vendus_document_id", unique=True)
    except Exception as e:
        logger.error(f"Não foi possível criar o índice único de pos_sales: {e}")

    # --- Índice único de credit_notes (uma NC por fatura de origem) ---
    # RESERVA atómica: antes de emitir uma nota de crédito, reserva-se a fatura
    # de origem aqui. O índice único em `source_document_id` serializa retries e
    # duplo-toque concorrentes — impede uma 2ª NC REAL à AT para a mesma fatura
    # (o scan de `related_docs`/ext_ref no Vendus é eventualmente-consistente e
    # não chega sozinho). Uma tentativa falhada remove a reserva (não bloqueia).
    try:
        await db.credit_notes.create_index("source_document_id", unique=True)
    except Exception as e:
        logger.error(f"Não foi possível criar o índice único de credit_notes: {e}")

    # --- Scheduler do relatório diário ---
    # Protegido: uma falha/lentidão da BD no arranque não deve impedir a API de servir.
    try:
        config = await db.settings.find_one({"key": "scheduler_config"}, {"_id": 0})
        if config and config.get("value", {}).get("enabled"):
            rcfg = await resolve_resend_config(db)
            if rcfg["api_key"] and rcfg["report_email"]:
                SCHEDULER_ENABLED = True
                scheduler.add_job(
                    run_scheduled_report,
                    CronTrigger(hour=0, minute=0, timezone='Europe/Lisbon'),
                    id='daily_report',
                    name='Daily Report Email',
                    replace_existing=True
                )
                scheduler.start()
                logger.info("Scheduler de relatórios diários iniciado automaticamente")
            else:
                logger.warning("Scheduler configurado mas falta a chave do Resend ou o email de destino")
    except Exception as e:
        logger.error(f"Não foi possível carregar a config do scheduler no arranque: {e}")

    yield

    # --- Encerramento ---
    if scheduler.running:
        scheduler.shutdown()
    client.close()


# Create the main app
app = FastAPI(title="Pizzaria API", lifespan=lifespan)

# Create router with /api prefix
api_router = APIRouter(prefix="/api")


@api_router.get("/health")
async def health_check():
    """Liveness check para o Docker/monitorização (não toca na base de dados)."""
    return {"status": "ok"}


@api_router.get("/app/print-bridge/info")
async def print_bridge_info():
    """Metadados do APK da ponte de impressão (para o botão de download no admin)."""
    if PRINT_BRIDGE_APK.exists():
        size = PRINT_BRIDGE_APK.stat().st_size
        return {"available": True, "size_bytes": size, "size_kb": round(size / 1024)}
    return {"available": False, "size_bytes": 0, "size_kb": 0}


@api_router.get("/app/print-bridge.apk")
async def download_print_bridge_apk():
    """Descarrega o APK da ponte de impressão (público — não contém segredos)."""
    if not PRINT_BRIDGE_APK.exists():
        raise HTTPException(status_code=404, detail="APK ainda não publicado")
    return FileResponse(
        path=str(PRINT_BRIDGE_APK),
        media_type="application/vnd.android.package-archive",
        filename="lenhaebrasa-print-bridge.apk",
    )

# Mount static files for uploads under /api prefix for Kubernetes ingress routing
app.mount("/api/uploads", StaticFiles(directory=str(UPLOADS_DIR)), name="uploads")

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# ==================== MODELS ====================

class AdminUserCreate(BaseModel):
    email: EmailStr
    password: str
    name: str

class AdminUserLogin(BaseModel):
    email: EmailStr
    password: str

class AdminUserResponse(BaseModel):
    id: str
    email: str
    name: str

class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: AdminUserResponse

class CategoryCreate(BaseModel):
    name: str
    order: int = 0
    active: bool = True
    available_days: List[int] = []  # 0=Seg..6=Dom; vazio = todos os dias
    pos_only: bool = False  # só no balcão/POS (staff); escondida do menu do cliente

class CategoryUpdate(BaseModel):
    name: Optional[str] = None
    order: Optional[int] = None
    active: Optional[bool] = None
    available_days: Optional[List[int]] = None
    pos_only: Optional[bool] = None

class CategoryResponse(BaseModel):
    id: str
    name: str
    order: int
    active: bool
    available_days: List[int] = []
    pos_only: bool = False
    created_at: str

class VariationCreate(BaseModel):
    name: str
    price: float

class ExtraCreate(BaseModel):
    name: str
    price: float

class ComplementItem(BaseModel):
    name: str
    price: float = 0.0

class ComplementGroup(BaseModel):
    name: str
    min_selections: int = 0
    max_selections: int = 4
    items: List[ComplementItem] = []

class PreferenceOptions(BaseModel):
    enabled: bool = False
    label: str = "Preferências"
    required: bool = True
    options: List[str] = []

class ProductCreate(BaseModel):
    name: str
    description: str
    category_id: str
    base_price: float
    image_url: Optional[str] = None
    variations: List[VariationCreate] = []
    extras: List[ExtraCreate] = []
    complement_groups: List[ComplementGroup] = []
    preference_options: Optional[PreferenceOptions] = None
    available: bool = True
    featured: bool = False
    rodizio_incluido: str = "nao"  # nao | ambos | completo
    rodizio_only: bool = False     # só aparece no menu quando a mesa está em rodízio
    vendus_tax_id: Optional[str] = None  # IVA p/ fatura: INT=13% | NOR=23%

class ProductUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    category_id: Optional[str] = None
    base_price: Optional[float] = None
    image_url: Optional[str] = None
    variations: Optional[List[VariationCreate]] = None
    extras: Optional[List[ExtraCreate]] = None
    complement_groups: Optional[List[ComplementGroup]] = None
    preference_options: Optional[PreferenceOptions] = None
    available: Optional[bool] = None
    featured: Optional[bool] = None
    rodizio_incluido: Optional[str] = None
    rodizio_only: Optional[bool] = None
    vendus_tax_id: Optional[str] = None

class ProductResponse(BaseModel):
    id: str
    name: str
    description: str
    category_id: str
    base_price: float
    image_url: Optional[str]
    variations: List[dict]
    extras: List[dict]
    complement_groups: List[dict] = []
    preference_options: Optional[dict] = None
    available: bool
    featured: bool
    rodizio_incluido: str = "nao"
    rodizio_only: bool = False
    vendus_tax_id: Optional[str] = None
    order: int = 0
    created_at: str

class TableCreate(BaseModel):
    number: int
    name: Optional[str] = None
    active: bool = True

class TableUpdate(BaseModel):
    number: Optional[int] = None
    name: Optional[str] = None
    active: Optional[bool] = None

class TableResponse(BaseModel):
    id: str
    number: int
    name: Optional[str]
    active: bool
    qr_code: Optional[str] = None
    created_at: str

class OrderItemCreate(BaseModel):
    product_id: str
    product_name: str
    quantity: int
    variation: Optional[dict] = None
    extras: List[dict] = []
    selected_complements: List[dict] = []
    selected_preference: Optional[str] = None
    notes: Optional[str] = None
    unit_price: float
    total_price: float

class OrderCreate(BaseModel):
    table_id: str
    table_number: int
    items: List[OrderItemCreate]
    notes: Optional[str] = None
    total: float
    source: Optional[str] = None  # 'client' (QR) | 'manual' (staff no balcão)

class OrderStatusUpdate(BaseModel):
    status: str

class OrderPaymentUpdate(BaseModel):
    payment_method: str

class OrderResponse(BaseModel):
    id: str
    order_number: int
    table_id: Optional[str] = None  # None nos pedidos de balcão (sem mesa)
    table_number: Optional[int] = None  # idem
    items: List[dict]
    notes: Optional[str]
    total: float
    status: str
    paid: bool
    payment_method: Optional[str] = None
    print_status: str
    source: Optional[str] = None
    created_at: str

# ==================== PRINTER MODELS ====================

class PrinterCreate(BaseModel):
    name: str
    ip: str
    port: int = 9100
    width: int = 80  # 58 or 80mm
    cut_paper: bool = True
    active: bool = True
    printer_type: str = "kitchen"  # kitchen or cashier

class PrinterUpdate(BaseModel):
    name: Optional[str] = None
    ip: Optional[str] = None
    port: Optional[int] = None
    width: Optional[int] = None
    cut_paper: Optional[bool] = None
    active: Optional[bool] = None
    printer_type: Optional[str] = None

class PrinterResponse(BaseModel):
    id: str
    name: str
    ip: str
    port: int
    width: int
    cut_paper: bool
    active: bool
    printer_type: str
    created_at: str

class PrintJobResponse(BaseModel):
    id: str
    order_id: str
    printer_id: str
    printer_name: str
    status: str
    attempts: int
    error: Optional[str]
    created_at: str
    updated_at: str

class PrintJobStatusUpdate(BaseModel):
    status: str
    error: Optional[str] = None

class DashboardStats(BaseModel):
    total_orders_today: int
    total_revenue_today: float
    orders_by_status: Dict[str, int]
    orders_by_table: List[dict]

# ==================== POS USER MODELS ====================
# Utilizadores do POS/Caixa (staff que opera o balcão) — autenticam por PIN,
# não confundir com AdminUser (login por email/password do painel de admin).

class PosUserCreate(BaseModel):
    name: str
    pin: str

class PosUserUpdate(BaseModel):
    name: Optional[str] = None
    pin: Optional[str] = None
    active: Optional[bool] = None

class PosUserResponse(BaseModel):
    """Nunca inclui `pin_hash` — o PIN nunca é devolvido pela API."""
    id: str
    name: str
    active: bool
    created_at: str

class PosUserPublic(BaseModel):
    """Versão pública (tela de bloqueio do POS) — só {id, name}, sem
    `pin_hash` nem `active`/`created_at`."""
    id: str
    name: str

# ==================== POS DEVICE TOKEN MODELS ====================
# Tokens de dispositivo (terminais POS) — servem para o auth-duplo dos
# terminais (tarefa futura). Só existe o hash (bcrypt, via pos/auth.py) em
# `pos_devices.token_hash`; o token em claro é devolvido UMA ÚNICA VEZ,
# na resposta da criação, e nunca mais é recuperável depois disso.

class PosDeviceTokenCreate(BaseModel):
    label: str
    days: Optional[int] = None

class PosDeviceTokenResponse(BaseModel):
    """Única resposta que inclui o token em claro — não usar noutro sítio."""
    id: str
    label: str
    active: bool
    created_at: str
    expires_at: str
    token: str

# ==================== AUTH HELPERS ====================

def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')

def verify_password(password: str, hashed: str) -> bool:
    return bcrypt.checkpw(password.encode('utf-8'), hashed.encode('utf-8'))

def valid_pin(pin: str) -> bool:
    """PIN dos utilizadores POS: exatamente 4 dígitos numéricos."""
    return bool(re.fullmatch(r"\d{4}", pin or ""))

def create_token(user_id: str, email: str) -> str:
    payload = {
        "user_id": user_id,
        "email": email,
        "typ": "admin",  # marca de tipo — distingue de tokens POS (typ="pos")
        "exp": datetime.now(timezone.utc).timestamp() + 86400 * 7  # 7 days
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)

async def get_current_user(authorization: Optional[str] = Header(None)) -> dict:
    """Verify JWT token and return user info - no database required"""
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Token não fornecido")
    
    token = authorization.replace("Bearer ", "")
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
        # Só tokens de admin dão acesso aqui. Um token POS (typ="pos"), embora
        # assinado com o mesmo JWT_SECRET, NÃO é aceite como admin — evita a
        # escalada de privilégio (operador do POS a passar-se por admin).
        if payload.get("typ") != "admin":
            raise HTTPException(status_code=401, detail="Token inválido")
        # Return user info from token payload (no database lookup)
        return {
            "id": payload.get("user_id", "admin-env"),
            "email": payload.get("email", ""),
            "name": "Administrador"
        }
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token expirado")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Token inválido")

async def verify_print_agent_key(x_api_key: Optional[str] = Header(None)) -> bool:
    """Verify Print Agent API Key"""
    if not x_api_key:
        raise HTTPException(status_code=401, detail="API Key não fornecida")
    
    # Check in database
    agent_config = await db.settings.find_one({"key": "print_agent"}, {"_id": 0})
    if not agent_config or agent_config.get("value", {}).get("api_key") != x_api_key:
        raise HTTPException(status_code=401, detail="API Key inválida")
    
    return True

# ==================== ESC/POS FORMATTING ====================

class ESCPOSFormatter:
    """Format orders for ESC/POS thermal printers"""
    ESC = b'\x1b'
    GS = b'\x1d'
    
    # Commands
    INIT = ESC + b'@'
    CUT = GS + b'V\x00'
    PARTIAL_CUT = GS + b'V\x01'
    BOLD_ON = ESC + b'E\x01'
    BOLD_OFF = ESC + b'E\x00'
    CENTER = ESC + b'a\x01'
    LEFT = ESC + b'a\x00'
    RIGHT = ESC + b'a\x02'
    DOUBLE_HEIGHT = GS + b'!\x10'
    DOUBLE_WIDTH = GS + b'!\x20'
    DOUBLE_SIZE = GS + b'!\x30'
    NORMAL_SIZE = GS + b'!\x00'
    UNDERLINE_ON = ESC + b'-\x01'
    UNDERLINE_OFF = ESC + b'-\x00'
    
    def __init__(self, width: int = 80):
        self.width = width
        self.chars_per_line = 48 if width == 80 else 32
    
    def _line(self, char: str = '-') -> bytes:
        return (char * self.chars_per_line + '\n').encode('cp860', errors='replace')
    
    def _text(self, text: str) -> bytes:
        # Replace special characters for thermal printers
        replacements = {
            'ã': 'a', 'õ': 'o', 'á': 'a', 'é': 'e', 'í': 'i', 'ó': 'o', 'ú': 'u',
            'à': 'a', 'è': 'e', 'ì': 'i', 'ò': 'o', 'ù': 'u',
            'â': 'a', 'ê': 'e', 'î': 'i', 'ô': 'o', 'û': 'u',
            'ç': 'c', 'Ç': 'C', 'ñ': 'n', 'Ñ': 'N',
            'Ã': 'A', 'Õ': 'O', 'Á': 'A', 'É': 'E', 'Í': 'I', 'Ó': 'O', 'Ú': 'U',
            '€': 'EUR', '£': 'GBP', '¥': 'JPY'
        }
        for old, new in replacements.items():
            text = text.replace(old, new)
        try:
            return text.encode('cp860', errors='replace')
        except:
            return text.encode('ascii', errors='replace')
    
    def _get_datetime(self, order: dict) -> datetime:
        created_at = order.get('created_at', datetime.now(timezone.utc).isoformat())
        if isinstance(created_at, str):
            return datetime.fromisoformat(created_at.replace('Z', '+00:00'))
        return created_at
    
    def format_kitchen(self, order: dict, printer_name: str = "COZINHA") -> bytes:
        """Format for KITCHEN printer - focus on preparation details"""
        data = bytearray()
        data.extend(self.INIT)
        
        # Header - NEW ORDER alert
        data.extend(self.CENTER)
        data.extend(self.BOLD_ON)
        data.extend(self.DOUBLE_HEIGHT)
        data.extend(self._text("NOVO PEDIDO\n"))
        data.extend(self.NORMAL_SIZE)
        data.extend(self.BOLD_OFF)
        
        data.extend(self._line('='))
        
        # Order number - BIG
        data.extend(self.CENTER)
        data.extend(self.DOUBLE_SIZE)
        data.extend(self.BOLD_ON)
        data.extend(self._text(f"PEDIDO #{order['order_number']}\n"))
        data.extend(self.NORMAL_SIZE)
        data.extend(self.BOLD_OFF)
        
        # Table number - BIG (balcão não tem mesa: imprime "BALCAO" em vez de
        # "MESA: None")
        table_number = order.get('table_number')
        data.extend(self.DOUBLE_SIZE)
        if table_number and order.get('source') != 'balcao':
            data.extend(self._text(f"MESA: {table_number}\n"))
        else:
            data.extend(self._text("BALCAO\n"))
        data.extend(self.NORMAL_SIZE)
        
        # Date/time
        dt = self._get_datetime(order)
        data.extend(self._text(f"{dt.strftime('%d/%m/%Y %H:%M')}\n"))
        
        data.extend(self._line('='))
        
        # Items - detailed for preparation
        data.extend(self.LEFT)
        
        for item in order.get('items', []):
            qty = item.get('quantity', 1)
            name = item.get('product_name', 'Item')
            variation = item.get('variation', {})
            
            # Item name with quantity - BOLD
            data.extend(self.BOLD_ON)
            data.extend(self.DOUBLE_HEIGHT)
            data.extend(self._text(f"{qty}x {name}\n"))
            data.extend(self.NORMAL_SIZE)
            data.extend(self.BOLD_OFF)
            
            # Size/Variation
            if variation and variation.get('name'):
                data.extend(self._text(f"   Tamanho: {variation['name']}\n"))
            
            # Extras
            for extra in item.get('extras', []):
                data.extend(self._text(f"   + {extra.get('name', '')}\n"))
            
            # Complements
            for comp_group in item.get('selected_complements', []):
                group_name = comp_group.get('group_name', '')
                if group_name:
                    data.extend(self.BOLD_ON)
                    data.extend(self._text(f"   [{group_name}]\n"))
                    data.extend(self.BOLD_OFF)
                for comp_item in comp_group.get('items', []):
                    data.extend(self._text(f"   + {comp_item.get('name', '')}\n"))
            
            # Preference
            if item.get('selected_preference'):
                data.extend(self.BOLD_ON)
                data.extend(self._text(f"   >> {item['selected_preference'].upper()} <<\n"))
                data.extend(self.BOLD_OFF)
            
            # Item notes - HIGHLIGHTED
            if item.get('notes'):
                data.extend(self.BOLD_ON)
                data.extend(self._text(f"   >>> {item['notes'].upper()} <<<\n"))
                data.extend(self.BOLD_OFF)
            
            data.extend(self._text("\n"))
        
        data.extend(self._line('-'))
        
        # Order notes - VERY HIGHLIGHTED
        if order.get('notes'):
            data.extend(self.CENTER)
            data.extend(self.BOLD_ON)
            data.extend(self.DOUBLE_SIZE)
            data.extend(self._text("OBSERVACOES:\n"))
            data.extend(self.NORMAL_SIZE)
            data.extend(self._text(f"{order['notes'].upper()}\n"))
            data.extend(self.BOLD_OFF)
            data.extend(self._line('-'))
        
        data.extend(self.CENTER)
        data.extend(self._text(f"[{printer_name}]\n"))

        data.extend(self._line('='))
        data.extend(self._text("\n\n\n"))
        data.extend(self.CUT)

        return bytes(data)

    def format_cashier(self, order: dict, printer_name: str = "CAIXA") -> bytes:
        """Format for CASHIER printer - focus on pricing"""
        data = bytearray()
        data.extend(self.INIT)
        
        # Header
        data.extend(self.CENTER)
        data.extend(self.BOLD_ON)
        data.extend(self._text(f"[{printer_name}]\n"))
        data.extend(self.BOLD_OFF)
        
        data.extend(self._line('='))
        
        # Order number
        data.extend(self.DOUBLE_HEIGHT)
        data.extend(self.BOLD_ON)
        data.extend(self._text(f"PEDIDO #{order['order_number']}\n"))
        data.extend(self.NORMAL_SIZE)
        data.extend(self.BOLD_OFF)
        
        # Table (balcão não tem mesa: imprime "BALCAO" em vez de "MESA: None")
        table_number = order.get('table_number')
        data.extend(self.BOLD_ON)
        if table_number and order.get('source') != 'balcao':
            data.extend(self._text(f"MESA: {table_number}\n"))
        else:
            data.extend(self._text("BALCAO\n"))
        data.extend(self.BOLD_OFF)
        
        data.extend(self._line('-'))
        
        # Items with prices
        data.extend(self.LEFT)
        
        for item in order.get('items', []):
            qty = item.get('quantity', 1)
            name = item.get('product_name', 'Item')
            variation = item.get('variation', {})
            unit_price = item.get('unit_price', 0)
            total_price = item.get('total_price', 0)
            
            # Item line
            item_desc = f"{qty}x {name}"
            if variation and variation.get('name'):
                item_desc += f" ({variation['name']})"
            
            data.extend(self._text(f"{item_desc}\n"))
            
            # Extras with price
            for extra in item.get('extras', []):
                data.extend(self._text(f"   + {extra.get('name', '')} (+{extra.get('price', 0):.2f})\n"))
            
            # Complement groups with price
            for comp_group in item.get('selected_complements', []):
                for comp_item in comp_group.get('items', []):
                    price = comp_item.get('price', 0)
                    if price > 0:
                        data.extend(self._text(f"   + {comp_item.get('name', '')} (+{price:.2f})\n"))
                    else:
                        data.extend(self._text(f"   + {comp_item.get('name', '')}\n"))
            
            # Preference
            if item.get('selected_preference'):
                data.extend(self._text(f"   {item['selected_preference']}\n"))
            
            # Price line
            data.extend(self.RIGHT)
            data.extend(self._text(f"EUR {total_price:.2f}\n"))
            data.extend(self.LEFT)
            
            data.extend(self._text("\n"))
        
        data.extend(self._line('-'))
        
        # Total - BIG
        data.extend(self.CENTER)
        data.extend(self.DOUBLE_HEIGHT)
        data.extend(self.BOLD_ON)
        data.extend(self._text(f"TOTAL: EUR {order.get('total', 0):.2f}\n"))
        data.extend(self.NORMAL_SIZE)
        data.extend(self.BOLD_OFF)
        
        data.extend(self._line('-'))
        
        # Footer info
        data.extend(self.LEFT)
        dt = self._get_datetime(order)
        data.extend(self._text(f"Data: {dt.strftime('%d/%m/%Y %H:%M')}\n"))
        data.extend(self._text(f"ID: {order.get('id', '')[:8]}\n"))

        data.extend(self._line('='))
        data.extend(self._text("\n\n\n"))
        data.extend(self.CUT)

        return bytes(data)
    
    def format_order(self, order: dict, printer_name: str = "", printer_type: str = "kitchen", restaurant_name: str = "Pizzaria") -> bytes:
        """Format order based on printer type"""
        if printer_type == "cashier":
            return self.format_cashier(order, printer_name)
        else:
            return self.format_kitchen(order, printer_name)
    
    def format_test(self, printer_name: str = "", restaurant_name: str = "Pizzaria") -> bytes:
        data = bytearray()
        data.extend(self.INIT)
        data.extend(self.CENTER)
        data.extend(self.BOLD_ON)
        data.extend(self.DOUBLE_SIZE)
        data.extend(self._text(f"{restaurant_name}\n"))
        data.extend(self.NORMAL_SIZE)
        if printer_name:
            data.extend(self._text(f"[{printer_name}]\n"))
        data.extend(self._line('='))
        data.extend(self._text("TESTE DE IMPRESSAO\n"))
        data.extend(self._text(f"Data: {datetime.now().strftime('%d/%m/%Y %H:%M')}\n"))
        data.extend(self._line('='))
        data.extend(self._text("Impressora configurada com sucesso!\n"))
        data.extend(self._line('='))
        data.extend(self._text("\n\n\n"))
        data.extend(self.BOLD_OFF)
        data.extend(self.CUT)
        return bytes(data)

# ==================== AUTH ROUTES ====================

# Get admin credentials from environment
ADMIN_EMAIL = os.environ.get('ADMIN_EMAIL', 'admin@pizzaria.pt')
ADMIN_PASSWORD_HASH = os.environ.get('ADMIN_PASSWORD_HASH', '')

@api_router.post("/auth/login", response_model=TokenResponse)
async def login_admin(credentials: AdminUserLogin):
    """Login using environment variables - no database required"""
    logger.info(f"Login attempt for email: {credentials.email}")
    
    # Check email
    if credentials.email != ADMIN_EMAIL:
        logger.warning(f"Login failed: email mismatch. Got '{credentials.email}', expected '{ADMIN_EMAIL}'")
        raise HTTPException(status_code=401, detail="Email ou senha inválidos")
    
    # Verify password against hash from environment
    if not ADMIN_PASSWORD_HASH:
        logger.error("ADMIN_PASSWORD_HASH not configured")
        raise HTTPException(status_code=500, detail="Configuração de autenticação incompleta")
    
    try:
        if not bcrypt.checkpw(credentials.password.encode('utf-8'), ADMIN_PASSWORD_HASH.encode('utf-8')):
            logger.warning(f"Login failed: password mismatch for {credentials.email}")
            raise HTTPException(status_code=401, detail="Email ou senha inválidos")
    except ValueError as e:
        logger.error(f"Auth bcrypt error: {e}")
        raise HTTPException(status_code=401, detail="Email ou senha inválidos")
    except Exception as e:
        logger.error(f"Auth unexpected error: {e}")
        raise HTTPException(status_code=401, detail="Email ou senha inválidos")
    
    # Create token
    user_id = "admin-env"
    token = create_token(user_id, ADMIN_EMAIL)
    
    return TokenResponse(
        access_token=token,
        user=AdminUserResponse(id=user_id, email=ADMIN_EMAIL, name="Administrador")
    )

@api_router.get("/auth/me", response_model=AdminUserResponse)
async def get_me(authorization: Optional[str] = Header(None)):
    """Get current user info"""
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Token não fornecido")
    
    token = authorization.replace("Bearer ", "")
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
        if payload.get("typ") != "admin":
            raise HTTPException(status_code=401, detail="Token inválido")
        return AdminUserResponse(
            id=payload.get("user_id", "admin-env"),
            email=payload.get("email", ADMIN_EMAIL),
            name="Administrador"
        )
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token expirado")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Token inválido")

# ==================== CATEGORY ROUTES ====================

@api_router.post("/categories", response_model=CategoryResponse)
async def create_category(category: CategoryCreate, authorization: Optional[str] = Header(None)):
    await get_current_user(authorization)
    
    cat_id = str(uuid.uuid4())
    cat_doc = {
        "id": cat_id,
        "name": category.name,
        "order": category.order,
        "active": category.active,
        "available_days": category.available_days,
        "pos_only": category.pos_only,
        "created_at": datetime.now(timezone.utc).isoformat()
    }
    await db.categories.insert_one(cat_doc)
    return CategoryResponse(**cat_doc)

@api_router.get("/categories", response_model=List[CategoryResponse])
async def list_categories(active_only: bool = False):
    query = {"active": True} if active_only else {}
    categories = await db.categories.find(query, {"_id": 0}).sort("order", 1).to_list(100)
    if active_only:
        # Só as categorias disponíveis HOJE (dia da semana, Europe/Lisbon).
        today = datetime.now(ZoneInfo("Europe/Lisbon")).weekday()  # 0=Seg..6=Dom
        categories = [c for c in categories
                      if not c.get("available_days") or today in c.get("available_days", [])]
    return [CategoryResponse(**cat) for cat in categories]

class CategoryReorderItem(BaseModel):
    id: str
    order: int

@api_router.put("/categories/reorder")
async def reorder_categories(items: List[CategoryReorderItem], authorization: Optional[str] = Header(None)):
    """Reorder multiple categories at once"""
    await get_current_user(authorization)
    
    for item in items:
        await db.categories.update_one(
            {"id": item.id},
            {"$set": {"order": item.order}}
        )
    
    categories = await db.categories.find({}, {"_id": 0}).sort("order", 1).to_list(100)
    return [CategoryResponse(**cat) for cat in categories]

@api_router.put("/categories/{category_id}", response_model=CategoryResponse)
async def update_category(category_id: str, update: CategoryUpdate, authorization: Optional[str] = Header(None)):
    await get_current_user(authorization)
    
    update_data = {k: v for k, v in update.model_dump().items() if v is not None}
    if not update_data:
        raise HTTPException(status_code=400, detail="Nenhum campo para atualizar")
    
    result = await db.categories.update_one({"id": category_id}, {"$set": update_data})
    if result.matched_count == 0:
        raise HTTPException(status_code=404, detail="Categoria não encontrada")
    
    cat = await db.categories.find_one({"id": category_id}, {"_id": 0})
    return CategoryResponse(**cat)

@api_router.delete("/categories/{category_id}")
async def delete_category(category_id: str, authorization: Optional[str] = Header(None)):
    await get_current_user(authorization)
    
    result = await db.categories.delete_one({"id": category_id})
    if result.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Categoria não encontrada")
    return {"message": "Categoria eliminada"}

# ==================== PRODUCT ROUTES ====================

@api_router.post("/products", response_model=ProductResponse)
async def create_product(product: ProductCreate, authorization: Optional[str] = Header(None)):
    await get_current_user(authorization)
    
    prod_id = str(uuid.uuid4())
    prod_doc = {
        "id": prod_id,
        "name": product.name,
        "description": product.description,
        "category_id": product.category_id,
        "base_price": product.base_price,
        "image_url": product.image_url,
        "variations": [v.model_dump() for v in product.variations],
        "extras": [e.model_dump() for e in product.extras],
        "complement_groups": [g.model_dump() for g in product.complement_groups],
        "preference_options": product.preference_options.model_dump() if product.preference_options else None,
        "available": product.available,
        "featured": product.featured,
        "rodizio_incluido": product.rodizio_incluido,
        "rodizio_only": product.rodizio_only,
        "vendus_tax_id": product.vendus_tax_id,
        "order": await db.products.count_documents({"category_id": product.category_id}),
        "created_at": datetime.now(timezone.utc).isoformat()
    }
    await db.products.insert_one(prod_doc)
    return ProductResponse(**prod_doc)


@api_router.post("/products/rodizio-defaults")
async def seed_rodizio_defaults(authorization: Optional[str] = Header(None)):
    """Aplica os defaults de inclusão no rodízio por categoria aos produtos que
    ainda não têm (Pizzas→ambos; Entradas/Sobremesas→completo)."""
    await get_current_user(authorization)
    cats = {c["id"]: (c.get("name") or "").strip().lower()
            for c in await db.categories.find({}, {"_id": 0, "id": 1, "name": 1}).to_list(500)}
    n = 0
    async for p in db.products.find(
        {"$or": [{"rodizio_incluido": {"$exists": False}}, {"rodizio_incluido": None},
                 {"rodizio_incluido": "nao"}]}, {"_id": 0, "id": 1, "category_id": 1}):
        cat = cats.get(p.get("category_id"), "")
        val = "ambos" if "pizza" in cat else ("completo" if cat in ("entradas", "sobremesas") else "nao")
        if val != "nao":
            await db.products.update_one({"id": p["id"]}, {"$set": {"rodizio_incluido": val}})
            n += 1
    return {"updated": n}


@api_router.post("/products/iva-defaults")
async def seed_iva_defaults(authorization: Optional[str] = Header(None)):
    """Acerta o IVA (vendus_tax_id) dos produtos que ainda NÃO o têm, para não
    caírem no fallback ao faturar: bebidas → NOR (23%), restante comida → INT (13%).
    Nunca sobrescreve produtos que já têm IVA definido."""
    await get_current_user(authorization)
    cats = {c["id"]: (c.get("name") or "").strip().lower()
            for c in await db.categories.find({}, {"_id": 0, "id": 1, "name": 1}).to_list(500)}
    n_int = n_nor = 0
    async for p in db.products.find({}, {"_id": 0, "id": 1, "category_id": 1, "name": 1, "vendus_tax_id": 1}):
        cat = cats.get(p.get("category_id"), "")
        name = (p.get("name") or "").lower()
        current = p.get("vendus_tax_id")
        is_agua = "agua" in name or "água" in name
        if is_agua:
            target = "INT"          # águas = 13% (corrige mesmo as que estão a NOR)
        elif not current:
            target = "NOR" if "bebida" in cat else "INT"  # bebidas 23%, comida 13%
        else:
            continue                # já tem IVA e não é água → não mexer
        if current == target:
            continue
        await db.products.update_one({"id": p["id"]}, {"$set": {"vendus_tax_id": target}})
        if target == "INT":
            n_int += 1
        else:
            n_nor += 1
    return {"int_13": n_int, "nor_23": n_nor, "updated": n_int + n_nor}

@api_router.get("/products", response_model=List[ProductResponse])
async def list_products(category_id: Optional[str] = None, available_only: bool = False):
    query = {}
    if category_id:
        query["category_id"] = category_id
    if available_only:
        query["available"] = True
    
    products = await db.products.find(query, {"_id": 0}).sort([("order", 1), ("created_at", 1)]).to_list(500)
    return [ProductResponse(**prod) for prod in products]

@api_router.put("/products/reorder")
async def reorder_products(items: List[CategoryReorderItem], authorization: Optional[str] = Header(None)):
    """Reordena produtos (dentro da categoria) de uma vez."""
    await get_current_user(authorization)
    for item in items:
        await db.products.update_one({"id": item.id}, {"$set": {"order": item.order}})
    products = await db.products.find({}, {"_id": 0}).sort([("order", 1), ("created_at", 1)]).to_list(500)
    return [ProductResponse(**prod) for prod in products]

@api_router.get("/products/{product_id}", response_model=ProductResponse)
async def get_product(product_id: str):
    product = await db.products.find_one({"id": product_id}, {"_id": 0})
    if not product:
        raise HTTPException(status_code=404, detail="Produto não encontrado")
    return ProductResponse(**product)

@api_router.put("/products/{product_id}", response_model=ProductResponse)
async def update_product(product_id: str, update: ProductUpdate, authorization: Optional[str] = Header(None)):
    await get_current_user(authorization)
    
    update_data = {}
    for k, v in update.model_dump().items():
        if v is not None:
            if k == "variations":
                update_data[k] = [var for var in v]
            elif k == "extras":
                update_data[k] = [ext for ext in v]
            elif k == "complement_groups":
                update_data[k] = [g for g in v]
            elif k == "preference_options":
                update_data[k] = v
            else:
                update_data[k] = v
    
    if not update_data:
        raise HTTPException(status_code=400, detail="Nenhum campo para atualizar")
    
    result = await db.products.update_one({"id": product_id}, {"$set": update_data})
    if result.matched_count == 0:
        raise HTTPException(status_code=404, detail="Produto não encontrado")
    
    prod = await db.products.find_one({"id": product_id}, {"_id": 0})
    return ProductResponse(**prod)

@api_router.delete("/products/{product_id}")
async def delete_product(product_id: str, authorization: Optional[str] = Header(None)):
    await get_current_user(authorization)
    
    result = await db.products.delete_one({"id": product_id})
    if result.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Produto não encontrado")
    return {"message": "Produto eliminado"}

@api_router.post("/products/upload-image")
async def upload_product_image(file: UploadFile = File(...), authorization: Optional[str] = Header(None)):
    await get_current_user(authorization)
    
    if not file.content_type.startswith("image/"):
        raise HTTPException(status_code=400, detail="Ficheiro deve ser uma imagem")
    
    # Read file content
    content = await file.read()
    
    # Limit: 5MB
    if len(content) > 5 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="Imagem demasiado grande (máx. 5MB)")
    
    # Store in MongoDB for persistence
    image_id = str(uuid.uuid4())
    ext = file.filename.split(".")[-1] if "." in file.filename else "jpg"
    
    image_doc = {
        "id": image_id,
        "filename": f"{image_id}.{ext}",
        "content_type": file.content_type,
        "data": base64.b64encode(content).decode('utf-8'),
        "size": len(content),
        "created_at": datetime.now(timezone.utc).isoformat()
    }
    await db.images.insert_one(image_doc)
    
    logger.info(f"Image uploaded and stored in DB: {image_id} ({len(content)} bytes)")
    
    return {"url": f"/api/images/{image_id}"}

from starlette.responses import Response

@api_router.get("/images/{image_id}")
async def serve_image(image_id: str):
    """Serve image from MongoDB storage"""
    image = await db.images.find_one({"id": image_id}, {"_id": 0})
    if not image:
        raise HTTPException(status_code=404, detail="Imagem não encontrada")
    
    # Decode base64 data
    image_data = base64.b64decode(image["data"])
    content_type = image.get("content_type", "image/jpeg")
    
    return Response(
        content=image_data,
        media_type=content_type,
        headers={
            "Cache-Control": "public, max-age=31536000, immutable"
        }
    )

# ==================== TABLE ROUTES ====================

@api_router.post("/tables", response_model=TableResponse)
async def create_table(table: TableCreate, authorization: Optional[str] = Header(None)):
    await get_current_user(authorization)
    
    # Check if table number exists
    existing = await db.tables.find_one({"number": table.number})
    if existing:
        raise HTTPException(status_code=400, detail="Número da mesa já existe")
    
    table_id = str(uuid.uuid4())
    table_doc = {
        "id": table_id,
        "number": table.number,
        "name": table.name or f"Mesa {table.number}",
        "active": table.active,
        "created_at": datetime.now(timezone.utc).isoformat()
    }
    await db.tables.insert_one(table_doc)
    
    return TableResponse(**table_doc)

@api_router.get("/tables", response_model=List[TableResponse])
async def list_tables(active_only: bool = False):
    query = {"active": True} if active_only else {}
    tables = await db.tables.find(query, {"_id": 0}).sort("number", 1).to_list(100)
    return [TableResponse(**t) for t in tables]

@api_router.get("/tables/{table_id}", response_model=TableResponse)
async def get_table(table_id: str):
    table = await db.tables.find_one({"id": table_id}, {"_id": 0})
    if not table:
        raise HTTPException(status_code=404, detail="Mesa não encontrada")
    return TableResponse(**table)

@api_router.get("/tables/by-number/{table_number}", response_model=TableResponse)
async def get_table_by_number(table_number: int):
    table = await db.tables.find_one({"number": table_number, "active": True}, {"_id": 0})
    if not table:
        raise HTTPException(status_code=404, detail="Mesa não encontrada")
    return TableResponse(**table)

@api_router.put("/tables/{table_id}", response_model=TableResponse)
async def update_table(table_id: str, update: TableUpdate, authorization: Optional[str] = Header(None)):
    await get_current_user(authorization)
    
    update_data = {k: v for k, v in update.model_dump().items() if v is not None}
    if not update_data:
        raise HTTPException(status_code=400, detail="Nenhum campo para atualizar")
    
    if "number" in update_data:
        existing = await db.tables.find_one({"number": update_data["number"], "id": {"$ne": table_id}})
        if existing:
            raise HTTPException(status_code=400, detail="Número da mesa já existe")
    
    result = await db.tables.update_one({"id": table_id}, {"$set": update_data})
    if result.matched_count == 0:
        raise HTTPException(status_code=404, detail="Mesa não encontrada")
    
    table = await db.tables.find_one({"id": table_id}, {"_id": 0})
    return TableResponse(**table)

@api_router.delete("/tables/{table_id}")
async def delete_table(table_id: str, authorization: Optional[str] = Header(None)):
    await get_current_user(authorization)
    
    result = await db.tables.delete_one({"id": table_id})
    if result.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Mesa não encontrada")
    return {"message": "Mesa eliminada"}

@api_router.get("/tables/{table_id}/qrcode")
async def get_table_qrcode(table_id: str, base_url: str = Query(...)):
    table = await db.tables.find_one({"id": table_id}, {"_id": 0})
    if not table:
        raise HTTPException(status_code=404, detail="Mesa não encontrada")
    
    # Generate QR Code
    qr_url = f"{base_url}/pedir?mesa={table['number']}"
    qr = qrcode.QRCode(version=1, box_size=10, border=5)
    qr.add_data(qr_url)
    qr.make(fit=True)
    
    img = qr.make_image(fill_color="black", back_color="white")
    buffer = io.BytesIO()
    img.save(buffer, format="PNG")
    buffer.seek(0)
    
    qr_base64 = base64.b64encode(buffer.getvalue()).decode()
    
    return {
        "qr_code": f"data:image/png;base64,{qr_base64}",
        "url": qr_url,
        "table_number": table["number"]
    }

# ==================== ORDER ROUTES ====================

async def get_next_order_number():
    """Get next order number for today"""
    today_start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    
    # Count orders today
    count = await db.orders.count_documents({
        "created_at": {"$gte": today_start.isoformat()}
    })
    return count + 1


async def _enqueue_order_prints(order_id: str):
    """Cria os print jobs (cozinha + caixa) de um pedido — extraído de
    `create_order` para ser reutilizado também pelos pedidos de balcão
    (POS, Fase 2 Task 1). Comportamento inalterado."""
    # Create print jobs for all active printers
    active_printers = await db.printers.find({"active": True}, {"_id": 0}).to_list(100)

    if active_printers:
        for printer in active_printers:
            print_job_id = str(uuid.uuid4())
            print_job = {
                "id": print_job_id,
                "order_id": order_id,
                "printer_id": printer["id"],
                "printer_name": printer["name"],
                "printer_type": printer.get("printer_type", "kitchen"),
                "status": "pending",
                "attempts": 0,
                "error": None,
                "created_at": datetime.now(timezone.utc).isoformat(),
                "updated_at": datetime.now(timezone.utc).isoformat()
            }
            await db.print_jobs.insert_one(print_job)

        # Log print jobs created
        logger.info(f"Order {order_id}: Created {len(active_printers)} print jobs for printers: {[p['name'] for p in active_printers]}")
    else:
        # Sem impressoras registadas: cria um job para a COZINHA e outro para a CAIXA.
        # O app-ponte encaminha por printer_type para o IP configurado de cada uma,
        # imprimindo automaticamente nos dois sítios a cada pedido.
        for ptype in ("kitchen", "cashier"):
            print_job = {
                "id": str(uuid.uuid4()),
                "order_id": order_id,
                "printer_id": None,
                "printer_name": "Cozinha" if ptype == "kitchen" else "Caixa",
                "printer_type": ptype,
                "status": "pending",
                "attempts": 0,
                "error": None,
                "created_at": datetime.now(timezone.utc).isoformat(),
                "updated_at": datetime.now(timezone.utc).isoformat()
            }
            await db.print_jobs.insert_one(print_job)
        logger.info(f"Order {order_id}: sem impressoras registadas — criados jobs cozinha + caixa")


@api_router.post("/orders", response_model=OrderResponse)
async def create_order(order: OrderCreate):
    order_number = await get_next_order_number()
    order_id = str(uuid.uuid4())
    
    order_doc = {
        "id": order_id,
        "order_number": order_number,
        "table_id": order.table_id,
        "table_number": order.table_number,
        "items": [item.model_dump() for item in order.items],
        "notes": order.notes,
        "total": order.total,
        "status": "received",
        "paid": False,
        "print_status": "pending",
        "source": order.source or "client",
        "created_at": datetime.now(timezone.utc).isoformat()
    }
    await db.orders.insert_one(order_doc)

    await _enqueue_order_prints(order_id)

    return OrderResponse(**order_doc)

@api_router.get("/orders", response_model=List[OrderResponse])
async def list_orders(
    status: Optional[str] = None,
    table_number: Optional[int] = None,
    date: Optional[str] = None,
    authorization: Optional[str] = Header(None)
):
    await get_current_user(authorization)
    
    query = {}
    if status:
        query["status"] = status
    if table_number:
        query["table_number"] = table_number
    if date:
        # Parse date and filter
        try:
            dt = datetime.fromisoformat(date)
            start = dt.replace(hour=0, minute=0, second=0)
            end = dt.replace(hour=23, minute=59, second=59)
            query["created_at"] = {"$gte": start.isoformat(), "$lte": end.isoformat()}
        except:
            pass
    
    orders = await db.orders.find(query, {"_id": 0}).sort("created_at", -1).to_list(500)
    return [OrderResponse(**o) for o in orders]

@api_router.get("/orders/{order_id}", response_model=OrderResponse)
async def get_order(order_id: str):
    order = await db.orders.find_one({"id": order_id}, {"_id": 0})
    if not order:
        raise HTTPException(status_code=404, detail="Pedido não encontrado")
    return OrderResponse(**order)

@api_router.put("/orders/{order_id}/status", response_model=OrderResponse)
async def update_order_status(order_id: str, update: OrderStatusUpdate, authorization: Optional[str] = Header(None)):
    await get_current_user(authorization)
    
    valid_statuses = ["received", "preparing", "ready", "delivered", "cancelled"]
    if update.status not in valid_statuses:
        raise HTTPException(status_code=400, detail=f"Estado inválido. Valores válidos: {valid_statuses}")
    
    result = await db.orders.update_one(
        {"id": order_id},
        {"$set": {"status": update.status}}
    )
    if result.matched_count == 0:
        raise HTTPException(status_code=404, detail="Pedido não encontrado")
    
    order = await db.orders.find_one({"id": order_id}, {"_id": 0})
    return OrderResponse(**order)

@api_router.put("/orders/{order_id}/paid", response_model=OrderResponse)
async def mark_order_paid(order_id: str, payment: Optional[OrderPaymentUpdate] = None, authorization: Optional[str] = Header(None)):
    await get_current_user(authorization)
    
    update_data = {"paid": True}
    if payment and payment.payment_method:
        update_data["payment_method"] = payment.payment_method
    
    result = await db.orders.update_one(
        {"id": order_id},
        {"$set": update_data}
    )
    if result.matched_count == 0:
        raise HTTPException(status_code=404, detail="Pedido não encontrado")
    
    order = await db.orders.find_one({"id": order_id}, {"_id": 0})
    return OrderResponse(**order)


@api_router.post("/orders/{order_id}/items/{idx}/void")
async def void_order_item(order_id: str, idx: int, authorization: Optional[str] = Header(None),
                           x_device_token: Optional[str] = Header(None)):
    """Remove um item da conta da mesa SEM faturar (adicionado por engano pelo
    staff ou pelo cliente). Soft-void: marca items.{idx}.removed=True (mantém
    rasto). Um item já faturado não pode ser removido. Devolve um dict simples
    (não o OrderResponse, que era frágil com orders antigas sem todos os campos)."""
    await get_pos_or_admin(authorization, x_device_token)
    order = await db.orders.find_one({"id": order_id}, {"_id": 0})
    if not order:
        raise HTTPException(status_code=404, detail="Pedido não encontrado")
    items = order.get("items", [])
    if idx < 0 or idx >= len(items):
        raise HTTPException(status_code=404, detail="Item não encontrado")
    if items[idx].get("paid"):
        raise HTTPException(status_code=400, detail="Item já faturado — não pode ser removido")
    await db.orders.update_one({"id": order_id}, {"$set": {f"items.{idx}.removed": True}})
    od = await db.orders.find_one({"id": order_id}, {"_id": 0, "items": 1})
    cancelled = False
    # Se já não sobra nada por faturar, cancela a order (sai do conjunto "aberto").
    if all(it.get("paid") or it.get("removed") for it in (od or {}).get("items", [])):
        await db.orders.update_one({"id": order_id}, {"$set": {"status": "cancelled"}})
        cancelled = True
    return {"ok": True, "order_id": order_id, "idx": idx, "order_cancelled": cancelled}


class ItemEdit(BaseModel):
    unit_price: Optional[float] = None
    quantity: Optional[int] = None
    vendus_tax_id: Optional[str] = None  # INT=13% | NOR=23%


@api_router.post("/orders/{order_id}/items/{idx}/edit")
async def edit_order_item(order_id: str, idx: int, body: ItemEdit,
                          authorization: Optional[str] = Header(None),
                          x_device_token: Optional[str] = Header(None)):
    """Edita preço/quantidade/IVA de um item da mesa (correção de um erro de
    lançamento ou override do IVA do produto para este item). Grava SÓ os
    campos presentes no corpo; quando o preço OU a quantidade mudam, recalcula
    `total_price` (lê o outro valor no item atual, para não o perder). Devolve
    um dict simples (não o OrderResponse, que era frágil com orders antigas
    sem todos os campos — mesmo problema do `void_order_item`)."""
    await get_pos_or_admin(authorization, x_device_token)
    if body.unit_price is not None and body.unit_price < 0:
        raise HTTPException(status_code=400, detail="Preço inválido")
    if body.quantity is not None and body.quantity < 1:
        raise HTTPException(status_code=400, detail="Quantidade inválida")
    if body.vendus_tax_id is not None and body.vendus_tax_id not in ("INT", "NOR"):
        raise HTTPException(status_code=400, detail="IVA inválido")

    order = await db.orders.find_one({"id": order_id}, {"_id": 0, "items": 1})
    if not order:
        raise HTTPException(status_code=404, detail="Pedido não encontrado")
    items = order.get("items", [])
    if idx < 0 or idx >= len(items):
        raise HTTPException(status_code=404, detail="Item não encontrado")
    item = items[idx]
    if item.get("paid"):
        raise HTTPException(status_code=400, detail="Item já faturado — não pode ser editado")

    updates = {}
    if body.unit_price is not None:
        updates[f"items.{idx}.unit_price"] = body.unit_price
    if body.quantity is not None:
        updates[f"items.{idx}.quantity"] = body.quantity
    if body.vendus_tax_id is not None:
        updates[f"items.{idx}.vendus_tax_id"] = body.vendus_tax_id
    if body.unit_price is not None or body.quantity is not None:
        new_price = body.unit_price if body.unit_price is not None else item.get("unit_price", 0)
        new_qty = body.quantity if body.quantity is not None else item.get("quantity", 1)
        updates[f"items.{idx}.total_price"] = round(float(new_price or 0) * float(new_qty or 0), 2)

    if updates:
        await db.orders.update_one({"id": order_id}, {"$set": updates})

    resp = {"ok": True, "order_id": order_id, "idx": idx}
    resp.update({k.rsplit(".", 1)[-1]: v for k, v in updates.items()})
    return resp


class ItemDiscount(BaseModel):
    pct: Optional[float] = None     # 0..100
    amount: Optional[float] = None  # € — mutuamente exclusivo com pct (amount ganha)


@api_router.post("/orders/{order_id}/items/{idx}/discount")
async def set_item_discount(order_id: str, idx: int, body: ItemDiscount,
                            authorization: Optional[str] = Header(None),
                            x_device_token: Optional[str] = Header(None)):
    """Define um desconto num item da mesa — percentagem (`pct`, 0..100) OU
    montante em euros (`amount`); são mutuamente exclusivos, dar um limpa o
    outro. Fica gravado no item e reflete-se na conta, na consulta e na
    fatura (enviado ao Vendus como discount_percentage ou discount_amount)."""
    await get_pos_or_admin(authorization, x_device_token)
    order = await db.orders.find_one({"id": order_id}, {"_id": 0, "items": 1})
    if not order:
        raise HTTPException(status_code=404, detail="Pedido não encontrado")
    items = order.get("items", [])
    if idx < 0 or idx >= len(items):
        raise HTTPException(status_code=404, detail="Item não encontrado")
    if items[idx].get("paid"):
        raise HTTPException(status_code=400, detail="Item já faturado")

    if body.amount is not None:
        amount = round(max(0.0, float(body.amount or 0)), 2)
        await db.orders.update_one(
            {"id": order_id},
            {"$set": {f"items.{idx}.discount_amount": amount},
             "$unset": {f"items.{idx}.discount_pct": ""}},
        )
        return {"ok": True, "order_id": order_id, "idx": idx, "discount_amount": amount}

    pct = max(0.0, min(100.0, float(body.pct or 0)))
    await db.orders.update_one(
        {"id": order_id},
        {"$set": {f"items.{idx}.discount_pct": pct},
         "$unset": {f"items.{idx}.discount_amount": ""}},
    )
    return {"ok": True, "order_id": order_id, "idx": idx, "discount_pct": pct}

# ==================== VENDUS: FECHO DE MESA ====================

VENDUS_DEFAULT_TAX_ID = os.environ.get("VENDUS_DEFAULT_TAX_ID", "NOR")


def _vendus_client(timeout: float = 30.0) -> VendusClient:
    return VendusClient(VendusConfig.load(os.environ), timeout=timeout)


async def _open_orders_for_table(table_number: int) -> list:
    return await db.orders.find(
        {"table_number": table_number, "paid": False, "status": {"$ne": "cancelled"}},
        {"_id": 0},
    ).sort("created_at", 1).to_list(500)


async def _open_bill_lines(table_number: int) -> list:
    """Linhas por faturar da mesa (itens ainda NÃO pagos), com referência
    order_id + idx — permite faturar/pagar item a item ("Separar Conta")."""
    orders = await _open_orders_for_table(table_number)
    lines = []
    for o in orders:
        src = o.get("source", "client")
        for idx, it in enumerate(o.get("items", [])):
            if it.get("paid") or it.get("removed"):
                continue
            dpct = float(it.get("discount_pct", 0) or 0)
            damt = float(it.get("discount_amount", 0) or 0)
            gross = round(float(it.get("total_price", 0) or 0), 2)
            # `pct` e `amount` são mutuamente exclusivos (só um está gravado), mas
            # subtraímos ambos em segurança. O `net` é o que o ecrã mostra e tem
            # de bater com a FS real (que também aplica o desconto da linha).
            net = round(max(0.0, gross * (1 - dpct / 100.0) - damt), 2)
            lines.append({
                "order_id": o["id"], "idx": idx,
                "product_id": it.get("product_id"),
                "product_name": it.get("product_name"),
                "quantity": it.get("quantity", 1),
                "unit_price": it.get("unit_price", 0),
                "total_price": net,          # já com o desconto do item aplicado
                "gross_total": gross,        # antes do desconto
                "discount_pct": dpct,
                "discount_amount": it.get("discount_amount"),  # desconto em € (override), se houver
                "vendus_tax_id": it.get("vendus_tax_id"),      # IVA override da linha, se houver
                "variation": it.get("variation"),
                "source": src,
            })
    return lines


class CloseTableItemRef(BaseModel):
    order_id: str
    idx: int


class CloseTableRequest(BaseModel):
    payment_method_id: int
    nif: Optional[str] = None
    split_count: int = 1  # >1 => divide a conta TODA em N faturas iguais
    items: Optional[List[CloseTableItemRef]] = None  # subconjunto: "Separar Conta"
    # Rodízio (all-you-can-eat): cobra por pessoa + extras à la carte + taxa desperdício
    rodizio_tier: Optional[str] = None  # simples | completo | None (à la carte)
    adults: int = 0
    children_half: int = 0   # crianças a meia (ex.: 6–12 anos)
    children_free: int = 0   # crianças grátis (ex.: ≤5 anos) — apenas informativo
    waste_boxes: int = 0     # nº de taxas de desperdício a cobrar
    global_discount_pct: float = 0  # desconto (%) sobre TODA a fatura (0..100)


@api_router.get("/tables/{table_number}/bill")
async def get_table_bill(table_number: int, authorization: Optional[str] = Header(None),
                          x_device_token: Optional[str] = Header(None)):
    """Conta em aberto da mesa (linhas por faturar, item a item)."""
    await get_pos_or_admin(authorization, x_device_token)
    lines = await _open_bill_lines(table_number)
    total = round(sum((l.get("total_price", 0) or 0) for l in lines), 2)
    n_orders = len({l["order_id"] for l in lines})
    return {"table_number": table_number, "orders": n_orders,
            "lines": lines, "total": total}


@api_router.get("/tables-overview")
async def tables_overview(authorization: Optional[str] = Header(None),
                           x_device_token: Optional[str] = Header(None)):
    """Resumo de TODAS as mesas com a respetiva conta em aberto — para a grelha
    de mesas (uma só chamada)."""
    await get_pos_or_admin(authorization, x_device_token)
    tables = await db.tables.find({"active": True}, {"_id": 0}).sort("number", 1).to_list(300)
    open_orders = await db.orders.find(
        {"paid": False, "status": {"$ne": "cancelled"}}, {"_id": 0}
    ).to_list(2000)
    agg: dict = {}
    for o in open_orders:
        n = o.get("table_number")
        a = agg.setdefault(n, {"total": 0.0, "count": 0, "last": None})
        a["total"] += sum((it.get("total_price", 0) or 0)
                          for it in o.get("items", []) if not it.get("paid") and not it.get("removed"))
        a["count"] += 1
        ca = o.get("created_at")
        if ca and (a["last"] is None or ca > a["last"]):
            a["last"] = ca
    sessions = await db.table_sessions.find({"status": "open"}, {"_id": 0}).to_list(1000)
    sess_by = {s["table_number"]: s for s in sessions}
    rcfg = await _rodizio_config()
    out = []
    for t in tables:
        a = agg.get(t["number"], {"total": 0.0, "count": 0, "last": None})
        s = sess_by.get(t["number"])
        rodizio = (s or {}).get("rodizio", "none")
        rp = (s or {}).get("rodizio_people")
        # No rodízio a conta já inclui o valor fixo por pessoa (adultos + crianças
        # a meia), somado aos extras à la carte (itens com preço > 0).
        r_charge = _rodizio_charge(rodizio, rp, rcfg, (s or {}).get("rodizio_paid"))
        out.append({
            "id": t["id"], "number": t["number"], "name": t.get("name"),
            "open_total": round(a["total"] + r_charge, 2), "open_orders": a["count"],
            "occupied": a["count"] > 0 or s is not None,
            "people": _rodizio_headcount(rodizio, rp, (s or {}).get("people")),
            "rodizio": rodizio,
            "rodizio_people": rp,
            "rodizio_paid": (s or {}).get("rodizio_paid") or {"adults": 0, "children": 0, "waste": 0},
            "rodizio_charge": r_charge,
            "last_activity": a["last"] or (s or {}).get("opened_at"),
        })
    return out


# ---- Sessões de mesa (fluxo do cliente por QR) ----

async def _open_session(table_number: int):
    return await db.table_sessions.find_one(
        {"table_number": table_number, "status": "open"}, {"_id": 0}
    )


def _rodizio_charge(rodizio: Optional[str], rodizio_people: Optional[dict], cfg: dict,
                    paid: Optional[dict] = None) -> float:
    """Conta do rodízio AINDA por pagar: (adultos-pagos)×preço + (crianças-pagas)×meia.
    Com `paid` (o que já foi faturado à parte) devolve só o remanescente."""
    if not rodizio or rodizio == "none":
        return 0.0
    tier = (cfg.get("tiers") or {}).get(rodizio)
    if not tier:
        return 0.0
    price = round(float(tier.get("price", 0) or 0), 2)
    rp = rodizio_people or {}
    pd = paid or {}
    adults = max(0, int(rp.get("adults", 0) or 0) - int(pd.get("adults", 0) or 0))
    children = max(0, int(rp.get("children", 0) or 0) - int(pd.get("children", 0) or 0))
    return round(adults * price + children * (price / 2), 2)


def _rodizio_headcount(rodizio: Optional[str], rodizio_people: Optional[dict], fallback) -> int:
    """Nº de pessoas real numa mesa de rodízio = adultos + crianças."""
    if rodizio and rodizio != "none":
        rp = rodizio_people or {}
        n = int(rp.get("adults", 0) or 0) + int(rp.get("children", 0) or 0)
        return n or (fallback or 1)
    return fallback


class OpenTableRequest(BaseModel):
    people: int = 1
    rodizio: str = "none"       # none | simples | completo
    adults: int = 0
    children: int = 0


@api_router.post("/tables/{table_number}/open")
async def open_table_session(table_number: int, req: OpenTableRequest):
    """PÚBLICO — o cliente abre a mesa (nº de pessoas e, se aplicável, o rodízio)
    na 1ª leitura do QR."""
    # No rodízio o nº de pessoas vem de adultos+crianças (o default people=1 é
    # "truthy" e escondia a lotação real); à la carte usa o campo people.
    if req.rodizio and req.rodizio != "none":
        people = max(1, (req.adults or 0) + (req.children or 0))
    else:
        people = max(1, req.people or 1)
    existing = await _open_session(table_number)
    if existing:
        # Mesa já aberta mas sem rodízio: o cliente pode escolher rodízio agora.
        if req.rodizio != "none" and existing.get("rodizio", "none") == "none":
            rp = {"adults": req.adults, "children": req.children}
            await db.table_sessions.update_one(
                {"id": existing["id"]},
                {"$set": {"rodizio": req.rodizio, "rodizio_people": rp, "people": people}},
            )
            existing["rodizio"] = req.rodizio
            existing["rodizio_people"] = rp
            existing["people"] = people
        return existing
    session = {
        "id": str(uuid.uuid4()),
        "table_number": table_number,
        "people": people,
        "rodizio": req.rodizio,
        "rodizio_people": {"adults": req.adults, "children": req.children},
        "rodizio_paid": {"adults": 0, "children": 0, "waste": 0},
        "opened_at": datetime.now(timezone.utc).isoformat(),
        "status": "open",
        "closed_at": None,
    }
    await db.table_sessions.insert_one(session)
    session.pop("_id", None)
    return session


class SetRodizioRequest(BaseModel):
    tier: str = "none"      # none | simples | completo
    adults: int = 0
    children: int = 0


@api_router.post("/tables/{table_number}/rodizio")
async def set_table_rodizio(
    table_number: int, req: SetRodizioRequest,
    authorization: Optional[str] = Header(None),
    x_device_token: Optional[str] = Header(None),
):
    """Staff define/ajusta o rodízio de uma mesa: nível (`tier`) e nº de pessoas
    (adultos/crianças). É a FONTE DE VERDADE que o `close_table` usa para saber
    quantas pessoas há para faturar — o fecho LIMITA o que fatura ao que está na
    sessão, por isso ADICIONAR um rodízio ou CORRIGIR uma contagem errada
    (colocar mais pessoas) passa por aqui. Cria a sessão se a mesa ainda não
    tiver uma aberta (staff a iniciar a mesa). Auth-duplo (admin JWT ou device
    token POS). Números são ABSOLUTOS (o total da mesa), não incrementos."""
    await get_pos_or_admin(authorization, x_device_token)
    tier = req.tier if req.tier in ("none", "simples", "completo") else "none"
    adults = max(0, int(req.adults or 0))
    children = max(0, int(req.children or 0))

    if tier != "none":
        cfg = await _rodizio_config()
        if tier not in (cfg.get("tiers") or {}):
            raise HTTPException(status_code=400, detail="Nível de rodízio inválido")
        if adults + children < 1:
            raise HTTPException(status_code=400, detail="Indica pelo menos 1 pessoa no rodízio")

    rp = {"adults": adults, "children": children}
    people = max(1, adults + children)

    s = await _open_session(table_number)
    if s:
        # Não deixar reduzir abaixo do que já foi FATURADO (rodizio_paid) — senão
        # o fecho parcial ficaria inconsistente.
        pd = s.get("rodizio_paid") or {}
        if tier != "none" and (adults < int(pd.get("adults", 0) or 0)
                               or children < int(pd.get("children", 0) or 0)):
            raise HTTPException(
                status_code=400,
                detail="Já foi faturado mais do que este número; não pode reduzir")
        updates = {"rodizio": tier, "rodizio_people": rp}
        if tier != "none":
            updates["people"] = people   # à la carte (none) mantém o `people` atual
        await db.table_sessions.update_one({"id": s["id"]}, {"$set": updates})
        s.update(updates)
        s.pop("_id", None)
        return s

    session = {
        "id": str(uuid.uuid4()),
        "table_number": table_number,
        "people": people,
        "rodizio": tier,
        "rodizio_people": rp,
        "rodizio_paid": {"adults": 0, "children": 0, "waste": 0},
        "opened_at": datetime.now(timezone.utc).isoformat(),
        "status": "open",
        "closed_at": None,
    }
    await db.table_sessions.insert_one(session)
    session.pop("_id", None)
    return session


@api_router.get("/tables/{table_number}/session")
async def get_table_session(table_number: int):
    """PÚBLICO — estado da mesa para o cliente: aberta?, nº de pessoas, conta atual."""
    s = await _open_session(table_number)
    lines = await _open_bill_lines(table_number)
    items_total = round(sum((l.get("total_price", 0) or 0) for l in lines), 2)
    n_orders = len({l["order_id"] for l in lines})
    rodizio = (s or {}).get("rodizio", "none")
    rp = (s or {}).get("rodizio_people")
    rcfg = await _rodizio_config()
    r_charge = _rodizio_charge(rodizio, rp, rcfg, (s or {}).get("rodizio_paid"))
    # No rodízio a conta arranca logo no valor fixo por pessoa (+ extras à la carte).
    total = round(items_total + r_charge, 2)
    return {
        "open": s is not None,
        "people": _rodizio_headcount(rodizio, rp, (s or {}).get("people")),
        "opened_at": (s or {}).get("opened_at"),
        "rodizio": rodizio,
        "rodizio_people": rp,
        "rodizio_charge": r_charge,
        "bill": {"total": total, "lines": lines, "orders": n_orders,
                 "items_total": items_total, "rodizio_charge": r_charge},
    }


@api_router.get("/vendus/payment-methods")
async def vendus_payment_methods(authorization: Optional[str] = Header(None),
                                  x_device_token: Optional[str] = Header(None)):
    """Métodos de pagamento do Vendus (para o ecrã de fecho)."""
    await get_pos_or_admin(authorization, x_device_token)

    def _fetch():
        c = _vendus_client()
        try:
            return c.list_payment_methods()
        finally:
            c.close()
    try:
        methods = await asyncio.to_thread(_fetch)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Vendus indisponível: {e}")
    return [{"id": m.get("id"), "title": m.get("title")} for m in methods]


@api_router.post("/tables/{table_number}/close")
async def close_table(table_number: int, req: CloseTableRequest,
                      authorization: Optional[str] = Header(None),
                      x_device_token: Optional[str] = Header(None),
                      x_pos_token: Optional[str] = Header(None)):
    """Fecha a mesa: emite a Fatura Simplificada (FS) no Vendus com os itens da
    conta e o pagamento, imprime-a na caixa (ESC/POS do Vendus) e marca os
    pedidos como pagos."""
    auth = await get_pos_or_admin(authorization, x_device_token)

    # Operador da venda: vem SEMPRE do token POS (nunca do corpo do pedido), para
    # a responsabilização não ser falsificável (§2.6). No caminho admin legado
    # (só JWT, sem token POS) fica `None` e não se grava pos_sales.
    pos_user_id = None
    if x_pos_token:
        try:
            pos_user_id = decode_pos_token(x_pos_token).get("pos_user_id")
        except Exception:
            pos_user_id = None

    # Sessão de caixa resolvida no SERVIDOR (nunca do corpo). No caminho POS, se
    # as definições exigem caixa aberta e não há sessão, recusa ANTES de faturar
    # — não se emite FS sem caixa aberta. O admin legado (JWT) segue sem caixa.
    sess = await db.cash_sessions.find_one({"status": "open"})
    if auth.get("kind") == "pos":
        pos_cfg = await _pos_settings_config()
        if pos_cfg.get("require_open_cash", True) and not sess:
            raise HTTPException(status_code=409, detail="Abra a caixa primeiro")

    all_lines = await _open_bill_lines(table_number)
    if not all_lines and not req.rodizio_tier:
        raise HTTPException(status_code=400, detail="Mesa sem conta em aberto")

    # Sessão de caixa para a referência fiscal ESTÁVEL (idempotência): a mesma
    # (mesa, sessão, itens) gera sempre a MESMA external_reference, por isso um
    # retry do mesmo fecho é detetado no Vendus e reutiliza o documento em vez de
    # emitir 2ª FS (cobrança dupla). Sem caixa aberta (admin legado) usa-se
    # "legacy" — continua determinístico.
    cash_session_id = sess["id"] if sess else "legacy"
    rodizio_pay = None  # {adults, children, waste} faturado agora (rodízio parcial)

    # Desconto GLOBAL (%) sobre toda a fatura; combina-se com o desconto próprio
    # de cada linha (pos.pricing.combine_global), aplicando-se SEMPRE por cima.
    g_disc = max(0.0, min(100.0, float(req.global_discount_pct or 0)))

    if req.rodizio_tier:
        # ---- RODÍZIO: fatura por pessoa (adultos/crianças) — pode ser PARCIAL
        # (pagar só algumas pessoas + alguns extras). O que já foi pago fica
        # contabilizado em session.rodizio_paid. Extras vêm em req.items (subconjunto).
        s = await _open_session(table_number)
        rp = (s or {}).get("rodizio_people") or {}
        pd = (s or {}).get("rodizio_paid") or {}
        rem_adults = max(0, int(rp.get("adults", 0) or 0) - int(pd.get("adults", 0) or 0))
        rem_children = max(0, int(rp.get("children", 0) or 0) - int(pd.get("children", 0) or 0))

        cfg = await _rodizio_config()
        tier = (cfg.get("tiers") or {}).get(req.rodizio_tier)
        if not tier:
            raise HTTPException(status_code=400, detail="Nível de rodízio inválido")
        rtax = cfg.get("tax_id", "INT")
        price = round(float(tier["price"]), 2)
        half = round(price / 2, 2)

        # Pessoas a faturar AGORA (não pode exceder o que falta).
        pay_adults = min(max(0, int(req.adults or 0)), rem_adults)
        pay_half = max(0, int(req.children_half or 0))
        pay_free = max(0, int(req.children_free or 0))
        if pay_half + pay_free > rem_children:
            pay_half = min(pay_half, rem_children)
            pay_free = max(0, rem_children - pay_half)
        pay_children = pay_half + pay_free

        # Extras selecionados (subconjunto de itens com preço > 0); sem req.items → nenhum.
        if req.items:
            sel = {(i.order_id, i.idx) for i in req.items}
            extra_lines = [l for l in all_lines
                           if (l["order_id"], l["idx"]) in sel and (l.get("total_price", 0) or 0) > 0]
        else:
            extra_lines = []
        prod_ids = list({l.get("product_id") for l in extra_lines if l.get("product_id")})
        tax_by_prod = {}
        if prod_ids:
            async for p in db.products.find({"id": {"$in": prod_ids}}, {"_id": 0, "id": 1, "vendus_tax_id": 1}):
                if p.get("vendus_tax_id"):
                    tax_by_prod[p["id"]] = p["vendus_tax_id"]

        vendus_items = []
        total = 0.0

        # Item SINTÉTICO do rodízio (adulto/criança/taxa): não é linha da conta,
        # não tem override de IVA nem desconto próprio — só o desconto GLOBAL se
        # aplica (combine_global sobre uma linha sem desconto próprio).
        def _add(title, qty, gross, tax):
            li, net = combine_global(
                {"title": title, "qty": qty, "gross_price": gross, "tax_id": tax}, g_disc)
            vendus_items.append(li)
            return net

        if pay_adults > 0:
            total += _add(f"{tier['name']} (adulto)", pay_adults, price, rtax)
        if pay_half > 0:
            total += _add(f"{tier['name']} (criança)", pay_half, half, rtax)
        for l in extra_lines:
            # Extra à la carte: line_vendus resolve título/qtd/preço/IVA (com os
            # overrides do item) e combine_global aplica o desconto global por cima.
            li, net = combine_global(
                line_vendus(l, tax_by_prod.get(l.get("product_id")), VENDUS_DEFAULT_TAX_ID), g_disc)
            vendus_items.append(li)
            total += net
        if req.waste_boxes and req.waste_boxes > 0:
            wfee = round(float(cfg.get("waste_fee", 5.0)), 2)
            total += _add("Taxa de desperdício", req.waste_boxes, wfee, cfg.get("waste_fee_tax_id", "INT"))
        total = round(total, 2)
        if not vendus_items or total <= 0:
            raise HTTPException(status_code=400, detail="Nada selecionado para faturar")

        lines = extra_lines     # só os extras selecionados ficam pagos como itens
        partial = False
        n = 1
        # Chave de idempotência do rodízio: estado pago-ANTES (pd) + pessoas pagas
        # AGORA + extras faturados. Estável no retry (o pago-antes ainda não foi
        # commitado); distinta do próximo pagamento (o pago-antes muda).
        invoices = [{"items": vendus_items, "amount": total,
                     "ext_ref": stable_ext_ref(
                         table_number, cash_session_id,
                         {"paid_before": pd, "adults": pay_adults, "half": pay_half,
                          "free": pay_free, "waste": int(req.waste_boxes or 0),
                          "extras": sorted((l["order_id"], l["idx"]) for l in extra_lines)},
                         rodizio=True)}]
        client = {"fiscal_id": req.nif} if req.nif else None
        rodizio_pay = {"adults": pay_adults, "children": pay_children, "waste": int(req.waste_boxes or 0)}
    else:
        # "Separar Conta": se vier um subconjunto de itens, fatura só esses.
        if req.items:
            sel = {(i.order_id, i.idx) for i in req.items}
            lines = [l for l in all_lines if (l["order_id"], l["idx"]) in sel]
            if not lines:
                raise HTTPException(status_code=400, detail="Nenhum item selecionado válido")
        else:
            lines = all_lines
        partial = len(lines) < len(all_lines)

        # IVA por produto (do que foi importado do Vendus); fallback ao default
        prod_ids = list({l.get("product_id") for l in lines if l.get("product_id")})
        tax_by_prod = {}
        if prod_ids:
            async for p in db.products.find({"id": {"$in": prod_ids}}, {"_id": 0, "id": 1, "vendus_tax_id": 1}):
                if p.get("vendus_tax_id"):
                    tax_by_prod[p["id"]] = p["vendus_tax_id"]

        # Itens (fatura única/subconjunto) + subtotais por IVA (para dividir).
        vendus_items = []
        by_tax = {}
        total = 0.0
        for l in lines:
            # line_vendus resolve título/qtd/preço/IVA da linha (com os overrides
            # do item: vendus_tax_id, desconto em €); combine_global funde o
            # desconto da linha com o desconto GLOBAL num único discount_percentage
            # e devolve o líquido EXATO que o Vendus calcula (sem desvio).
            li, amt = combine_global(
                line_vendus(l, tax_by_prod.get(l.get("product_id")), VENDUS_DEFAULT_TAX_ID), g_disc)
            tax = li["tax_id"]                                  # IVA efetivo (override incluído)
            vendus_items.append(li)
            by_tax[tax] = round(by_tax.get(tax, 0.0) + amt, 2)
            total += amt
        total = round(total, 2)

        # A divisão igual só se aplica à conta TODA (não a uma separação por itens).
        n = 1 if partial else max(1, min(int(req.split_count or 1), 50))

        # Constrói as faturas a emitir. n==1: uma fatura itemizada. n>1: uma fatura por
        # pessoa com a sua parte, agrupada por IVA (o resto do arredondamento vai para a
        # última, para as n faturas somarem EXATAMENTE o total).
        invoices = []  # {"items": [...], "amount": float, "ext_ref": str}
        # Chave de idempotência à la carte/dividir: a IDENTIDADE das linhas
        # faturadas (order_id, idx) — não o conteúdo. Fica estável no retry (as
        # linhas só ficam pagas no fim) e distinta de outro fecho (outras linhas).
        line_ids = sorted((l["order_id"], l["idx"]) for l in lines)
        if n == 1:
            invoices.append({"items": vendus_items, "amount": total,
                             "ext_ref": stable_ext_ref(table_number, cash_session_id, line_ids)})
        else:
            shares_by_tax = {}
            for tax, sub in by_tax.items():
                base = round(sub / n, 2)
                shares_by_tax[tax] = [base] * (n - 1) + [round(sub - base * (n - 1), 2)]
            for i in range(n):
                items_i, amount_i = [], 0.0
                for tax, parts in shares_by_tax.items():
                    share = parts[i]
                    if share and share > 0:
                        items_i.append({"title": f"Conta dividida Mesa {table_number} ({i+1}/{n})",
                                        "qty": 1, "gross_price": share, "tax_id": tax})
                        amount_i += share
                if items_i:
                    base = stable_ext_ref(table_number, cash_session_id, line_ids)
                    invoices.append({"items": items_i, "amount": round(amount_i, 2),
                                     "ext_ref": f"{base}-{i+1}de{n}"})

        client = {"fiscal_id": req.nif} if (req.nif and n == 1) else None

    # Dias (Europe/Lisbon) a consultar na DEDUP fiscal. Tem de cobrir toda a
    # sessão de caixa — NÃO só hoje — senão um retry de um fecho a atravessar a
    # meia-noite (23:59 → 00:0x, a hora a que a pizzaria fecha mesas) não
    # encontrava a FS de ontem e EMITIA 2ª FS (cobrança dupla). Espelha a janela
    # midnight-safe da reconciliação (Task 10).
    _lisbon = ZoneInfo("Europe/Lisbon")
    _hoje = datetime.now(_lisbon).date()
    if sess and sess.get("opened_at"):
        try:
            _inicio = datetime.fromisoformat(sess["opened_at"]).astimezone(_lisbon).date()
        except Exception:
            _inicio = _hoje - timedelta(days=1)
    else:
        _inicio = _hoje - timedelta(days=1)   # legado (sem caixa): cobre a viragem do dia
    dedup_dates = []
    _d = _inicio
    while _d <= _hoje:
        dedup_dates.append(_d.isoformat())
        _d += timedelta(days=1)

    def _emit_all():
        c = _vendus_client()
        docs = []
        try:
            # DEDUP FISCAL (proteção nº1 contra cobrança dupla): antes de emitir,
            # lê os documentos da SESSÃO na caixa da app (todos os `dedup_dates`) e
            # indexa-os pela external_reference. Como a ref é ESTÁVEL, um retry do
            # mesmo fecho cai aqui — reutiliza-se o documento já emitido em vez de
            # criar 2ª FS. Se a CONSULTA falhar, fica a proteção parcial já indexada
            # e segue-se a emitir (não bloquear o fecho); o retry seguinte protege.
            by_ref = {}
            try:
                for _ds in dedup_dates:
                    for d in c.list_app_invoices(date=_ds):
                        ref = d.get("external_reference")
                        if ref:
                            by_ref[str(ref)] = d
            except VendusError as e:
                logger.warning(f"dedup fiscal: consulta a documentos falhou, emito na mesma: {e}")
            for inv in invoices:
                existente = by_ref.get(inv["ext_ref"])
                if existente is not None:
                    # Já existe FS com esta ref: REUTILIZA (sem 2ª emissão). Pode
                    # não trazer o `output` (escpos) — a reimpressão é best-effort.
                    logger.warning(
                        f"dedup fiscal: ref {inv['ext_ref']} já emitida "
                        f"(doc {existente.get('id')}), reutilizada sem nova FS")
                    docs.append(existente)
                else:
                    docs.append(c.create_invoice(
                        items=inv["items"],
                        payments=[{"id": req.payment_method_id, "amount": inv["amount"]}],
                        client=client, external_reference=inv["ext_ref"],
                        doc_type="FS", output="escpos"))
        finally:
            c.close()
        return docs
    try:
        docs = await asyncio.to_thread(_emit_all)
    except VendusError as e:
        raise HTTPException(status_code=502, detail=f"Erro ao faturar no Vendus: {e}")
    if not docs:
        raise HTTPException(status_code=502, detail="Vendus não devolveu documento")

    # Marca como pagos SÓ os itens faturados (item a item). Um pedido fica "paid"
    # quando todos os seus itens ficam pagos.
    by_order = {}
    for l in lines:
        by_order.setdefault(l["order_id"], []).append(l["idx"])
    for oid, idxs in by_order.items():
        await db.orders.update_one({"id": oid}, {"$set": {f"items.{i}.paid": True for i in idxs}})
        od = await db.orders.find_one({"id": oid}, {"_id": 0, "items": 1})
        if od and all(it.get("paid") for it in od.get("items", [])):
            await db.orders.update_one({"id": oid}, {"$set": {
                "paid": True, "status": "delivered",
                "payment_method": str(req.payment_method_id),
                "vendus_document_id": docs[0].get("id")}})

    # Regista uma linha de venda POS por documento emitido (fecho Z + reconciliação
    # da Task 10). SÓ no caminho POS com caixa aberta — o admin legado (JWT) não
    # movimenta caixa. A sessão foi resolvida no servidor e o operador vem do token
    # POS: nunca do corpo. A FS JÁ está emitida e válida neste ponto, por isso uma
    # falha a gravar pos_sales NUNCA pode derrubar o fecho (500) — é registada e a
    # reconciliação apanha órfãos. O índice único em `vendus_document_id` absorve
    # duplicados de um retry (idempotente).
    if auth.get("kind") == "pos" and sess:
        # TUDO dentro do try: a FS já está emitida, por isso NADA aqui (nem o
        # build, nem o insert) pode derrubar o fecho com 500 (senão o cliente
        # julgava que falhou e refaturava = cobrança dupla). Estrutural, não por sorte.
        try:
            rows = build_pos_sales_rows(
                invoices, docs, req.payment_method_id, sess["id"], pos_user_id,
                "rodizio" if rodizio_pay is not None else "mesa", table_number,
            )
            if rows:
                await db.pos_sales.insert_many(rows, ordered=False)
        except (BulkWriteError, DuplicateKeyError) as e:
            logger.warning(f"pos_sales: documento(s) já registado(s), ignorado (idempotente): {e}")
        except Exception as e:
            logger.error(f"pos_sales: falha a gravar, ignorado (FS já emitida e válida): {e}")

    # Fecho da sessão. Rodízio: contabiliza as pessoas pagas e salda quando o
    # rodízio todo + todos os extras com preço estiverem pagos. À la carte: salda
    # quando já não há linhas por faturar.
    if rodizio_pay is not None:
        s2 = await _open_session(table_number)
        pd2 = (s2 or {}).get("rodizio_paid") or {"adults": 0, "children": 0, "waste": 0}
        new_paid = {
            "adults": int(pd2.get("adults", 0) or 0) + rodizio_pay["adults"],
            "children": int(pd2.get("children", 0) or 0) + rodizio_pay["children"],
            "waste": int(pd2.get("waste", 0) or 0) + rodizio_pay["waste"],
        }
        await db.table_sessions.update_many(
            {"table_number": table_number, "status": "open"},
            {"$set": {"rodizio_paid": new_paid}})
        rp2 = (s2 or {}).get("rodizio_people") or {}
        rcfg2 = await _rodizio_config()
        rodizio_left = _rodizio_charge((s2 or {}).get("rodizio", "none"), rp2, rcfg2, new_paid)
        priced_remaining = [l for l in await _open_bill_lines(table_number) if (l.get("total_price", 0) or 0) > 0]
        settled = (rodizio_left <= 0) and not priced_remaining
        remaining_total = round(rodizio_left + sum((l.get("total_price", 0) or 0) for l in priced_remaining), 2)
        if settled:
            # marca TODOS os itens restantes (incl. incluídos €0) pagos e fecha a sessão
            for l in await _open_bill_lines(table_number):
                await db.orders.update_one({"id": l["order_id"]}, {"$set": {f"items.{l['idx']}.paid": True}})
            await db.orders.update_many(
                {"table_number": table_number, "paid": False, "status": {"$ne": "cancelled"}},
                {"$set": {"paid": True, "status": "delivered"}})
            await db.table_sessions.update_many(
                {"table_number": table_number, "status": "open"},
                {"$set": {"status": "closed", "closed_at": datetime.now(timezone.utc).isoformat()}})
    else:
        remaining = await _open_bill_lines(table_number)
        settled = not remaining
        remaining_total = round(sum((l.get("total_price", 0) or 0) for l in remaining), 2)
        if settled:
            await db.table_sessions.update_many(
                {"table_number": table_number, "status": "open"},
                {"$set": {"status": "closed", "closed_at": datetime.now(timezone.utc).isoformat()}},
            )
    # imprime cada fatura (ESC/POS certificado do Vendus, com corte) na CAIXA
    for d in docs:
        escpos_b64 = d.get("output")
        if not escpos_b64:
            continue
        try:
            raw = base64.b64decode(escpos_b64) + b"\n\n\n\x1d\x56\x00"
            escpos_b64 = base64.b64encode(raw).decode("ascii")
        except Exception:
            pass
        await db.print_jobs.insert_one({
            "id": str(uuid.uuid4()),
            "order_id": None,
            "escpos_direct_b64": escpos_b64,
            "printer_id": None,
            "printer_name": "Caixa",
            "printer_type": "cashier",
            "status": "pending",
            "attempts": 0,
            "error": None,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "updated_at": datetime.now(timezone.utc).isoformat(),
        })
    return {"table_number": table_number, "total": total,
            "invoices": len(docs), "split": n, "partial": partial,
            "table_free": settled,
            "remaining_total": remaining_total,
            "vendus": {"id": docs[0].get("id"), "number": docs[0].get("number"),
                       "atcud": docs[0].get("atcud")},
            "numbers": [d.get("number") for d in docs]}


@api_router.post("/tables/{table_number}/free")
async def free_table(table_number: int, authorization: Optional[str] = Header(None),
                      x_device_token: Optional[str] = Header(None)):
    """Liberta a mesa SEM faturar: cancela os pedidos em aberto e fecha a sessão.
    Para quando alguém lê o QR mas não pede, ou o cliente sai sem consumir."""
    await get_pos_or_admin(authorization, x_device_token)
    orders = await _open_orders_for_table(table_number)
    order_ids = [o["id"] for o in orders]
    cancelled = 0
    if order_ids:
        r = await db.orders.update_many(
            {"id": {"$in": order_ids}},
            {"$set": {"status": "cancelled",
                      "cancelled_at": datetime.now(timezone.utc).isoformat()}},
        )
        cancelled = r.modified_count
    await db.table_sessions.update_many(
        {"table_number": table_number, "status": "open"},
        {"$set": {"status": "closed", "closed_at": datetime.now(timezone.utc).isoformat()}},
    )
    return {"table_number": table_number, "freed": True, "cancelled_orders": cancelled}


@api_router.post("/tables/{table_number}/print-consulta")
async def print_table_consulta(table_number: int, authorization: Optional[str] = Header(None),
                                x_device_token: Optional[str] = Header(None)):
    """Imprime uma CONTA PROVISÓRIA (consulta de mesa) para mostrar ao cliente.
    NÃO é fatura — a fatura só sai no fecho (Vendus). Enfileira um print job tipo
    'cashier' com um snapshot da conta atual; o agente imprime quando ligar."""
    await get_pos_or_admin(authorization, x_device_token)
    orders = await _open_orders_for_table(table_number)

    items = []
    total = 0.0
    for o in orders:
        for it in o.get("items", []):
            if it.get("paid") or it.get("removed"):
                continue  # itens já faturados ou removidos NÃO entram na consulta
            items.append({
                "product_name": it.get("product_name"),
                "quantity": it.get("quantity", 1),
                "variation": it.get("variation"),
                "extras": it.get("extras", []),
                "selected_complements": it.get("selected_complements", []),
                "selected_preference": it.get("selected_preference"),
                "unit_price": it.get("unit_price", 0),
                "total_price": it.get("total_price", 0),
            })
            total += it.get("total_price", 0) or 0
    total = round(total, 2)

    # Rodízio: a parcela fixa por pessoa vive na SESSÃO, não nas orders. Sem isto
    # a consulta só mostrava os extras à la carte (os incluídos entram a €0).
    s = await _open_session(table_number)
    rodizio = (s or {}).get("rodizio", "none")
    rp = (s or {}).get("rodizio_people")
    if rodizio and rodizio != "none":
        rcfg = await _rodizio_config()
        tier = (rcfg.get("tiers") or {}).get(rodizio) or {}
        price = round(float(tier.get("price", 0) or 0), 2)
        half = round(price / 2, 2)
        pd = (s or {}).get("rodizio_paid") or {}
        adults = max(0, int((rp or {}).get("adults", 0) or 0) - int(pd.get("adults", 0) or 0))
        children = max(0, int((rp or {}).get("children", 0) or 0) - int(pd.get("children", 0) or 0))
        tier_name = tier.get("name", "Rodízio")
        rodizio_lines = []
        if adults > 0:
            rodizio_lines.append({
                "product_name": f"{tier_name} (adulto)", "quantity": adults,
                "variation": None, "extras": [], "selected_complements": [],
                "selected_preference": None, "unit_price": price,
                "total_price": round(adults * price, 2),
            })
        if children > 0:
            rodizio_lines.append({
                "product_name": f"{tier_name} (criança)", "quantity": children,
                "variation": None, "extras": [], "selected_complements": [],
                "selected_preference": None, "unit_price": half,
                "total_price": round(children * half, 2),
            })
        items = rodizio_lines + items
        total = round(total + _rodizio_charge(rodizio, rp, rcfg, pd), 2)

    if not items:
        raise HTTPException(status_code=400, detail="Mesa sem conta em aberto")

    # snapshot com a forma que o formatador 'cashier' espera (order-like)
    snapshot = {
        "id": f"consulta-{table_number}",
        "order_number": "CONSULTA",
        "table_number": table_number,
        "items": items,
        "total": total,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }

    # impressoras de caixa ativas; fallback: todas as ativas; senão job default
    printers = await db.printers.find({"active": True}, {"_id": 0}).to_list(100)
    cashier = [p for p in printers if p.get("printer_type") == "cashier"]
    targets = cashier or printers or [None]

    job_ids = []
    for printer in targets:
        job = {
            "id": str(uuid.uuid4()),
            "order_id": None,
            "order_snapshot": snapshot,
            "printer_id": printer["id"] if printer else None,
            "printer_name": printer["name"] if printer else "Caixa",
            "printer_type": "cashier",
            "status": "pending",
            "attempts": 0,
            "error": None,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        await db.print_jobs.insert_one(job)
        job_ids.append(job["id"])

    logger.info(f"Consulta da mesa {table_number}: {len(job_ids)} print job(s) criados")
    return {"table_number": table_number, "total": total, "jobs": len(job_ids)}


@api_router.post("/menu/import-vendus")
async def import_menu_from_vendus(authorization: Optional[str] = Header(None)):
    """Importa produtos + categorias (com o IVA) do Vendus para o menu da app.
    Faz upsert por referência/nome, para poder correr mais que uma vez."""
    await get_current_user(authorization)

    def _fetch():
        c = _vendus_client()
        try:
            return c.list_categories(), c.list_products()
        finally:
            c.close()
    try:
        vcats, vprods = await asyncio.to_thread(_fetch)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Vendus indisponível: {e}")

    existing_cats = await db.categories.find({}, {"_id": 0}).to_list(500)
    by_name = {c["name"].strip().lower(): c for c in existing_cats}
    order = len(existing_cats)
    cat_map = {}
    cats_created = 0

    async def _ensure_category(title):
        nonlocal order, cats_created
        key = title.strip().lower()
        if key in by_name:
            return by_name[key]["id"]
        cid = str(uuid.uuid4())
        doc = {"id": cid, "name": title.strip(), "order": order, "active": True,
               "created_at": datetime.now(timezone.utc).isoformat()}
        await db.categories.insert_one(doc)
        by_name[key] = doc
        order += 1
        cats_created += 1
        return cid

    for vc in vcats:
        title = (vc.get("title") or "").strip()
        if title:
            cat_map[str(vc.get("id"))] = await _ensure_category(title)

    prods_created = prods_updated = 0
    app_skipped = 0
    for vp in vprods:
        name = (vp.get("title") or "").strip()
        if not name:
            continue
        if is_app_product(name):
            # Produtos "App" (preços de delivery) são geridos SÓ pelo import
            # dedicado (/admin/pos/import-app-products) na categoria pos_only
            # "Venda Aplicações". O import geral do menu SALTA-os — senão puxava-os
            # de volta para a categoria nativa (não-pos_only) e re-expunha os
            # preços de delivery no menu do cliente por QR.
            app_skipped += 1
            continue
        ref = vp.get("reference")
        price = float(vp.get("gross_price") or 0)
        tax_id = vp.get("tax_id")
        app_cat = cat_map.get(str(vp.get("category_id") or ""))
        if not app_cat:
            app_cat = await _ensure_category("Importados")
        query = {"vendus_reference": ref} if ref else {"name": name}
        existing = await db.products.find_one(query, {"_id": 0})
        if existing:
            await db.products.update_one({"id": existing["id"]}, {"$set": {
                "name": name, "base_price": price, "category_id": app_cat,
                "vendus_tax_id": tax_id, "vendus_reference": ref,
            }})
            prods_updated += 1
        else:
            await db.products.insert_one({
                "id": str(uuid.uuid4()), "name": name,
                "description": vp.get("description") or "",
                "category_id": app_cat, "base_price": price, "image_url": None,
                "variations": [], "extras": [], "complement_groups": [],
                "preference_options": None, "available": True, "featured": False,
                "vendus_tax_id": tax_id, "vendus_reference": ref,
                "created_at": datetime.now(timezone.utc).isoformat(),
            })
            prods_created += 1

    return {"categories_created": cats_created,
            "products_created": prods_created, "products_updated": prods_updated,
            "app_products_skipped": app_skipped}


class ReprintRequest(BaseModel):
    printer_ids: List[str] = []

@api_router.post("/orders/{order_id}/reprint")
async def reprint_order(order_id: str, request: Optional[ReprintRequest] = None,
                        authorization: Optional[str] = Header(None),
                        x_device_token: Optional[str] = Header(None)):
    """Reprint order to specific printers or all active printers"""
    # Auth-duplo: o botão "Cozinha" do checkout é usado também no /pos (device token).
    await get_pos_or_admin(authorization, x_device_token)
    
    order = await db.orders.find_one({"id": order_id}, {"_id": 0})
    if not order:
        raise HTTPException(status_code=404, detail="Pedido não encontrado")
    
    printer_ids = request.printer_ids if request and request.printer_ids else []
    
    if printer_ids:
        # Reprint to selected printers only
        job_ids = []
        for pid in printer_ids:
            printer = await db.printers.find_one({"id": pid}, {"_id": 0})
            if not printer:
                continue
            
            print_job_id = str(uuid.uuid4())
            print_job = {
                "id": print_job_id,
                "order_id": order_id,
                "printer_id": pid,
                "printer_name": printer["name"],
                "printer_type": printer.get("printer_type", "kitchen"),
                "status": "pending",
                "attempts": 0,
                "error": None,
                "created_at": datetime.now(timezone.utc).isoformat(),
                "updated_at": datetime.now(timezone.utc).isoformat()
            }
            await db.print_jobs.insert_one(print_job)
            job_ids.append(print_job_id)
        
        if not job_ids:
            raise HTTPException(status_code=400, detail="Nenhuma impressora válida selecionada")
        
        return {"message": f"Impressão agendada para {len(job_ids)} impressora(s)", "print_job_ids": job_ids}
    else:
        # Reprint to all active printers
        printers = await db.printers.find({"active": True}, {"_id": 0}).to_list(100)
        if not printers:
            # Sem impressoras registadas (setup com app-ponte): reimprime o talão de
            # COZINHA deste pedido — o app-ponte encaminha por printer_type.
            job_id = str(uuid.uuid4())
            await db.print_jobs.insert_one({
                "id": job_id,
                "order_id": order_id,
                "printer_id": None,
                "printer_name": "Cozinha",
                "printer_type": "kitchen",
                "status": "pending",
                "attempts": 0,
                "error": None,
                "created_at": datetime.now(timezone.utc).isoformat(),
                "updated_at": datetime.now(timezone.utc).isoformat(),
            })
            return {"message": "Reimpressão agendada (cozinha)", "print_job_ids": [job_id]}

        job_ids = []
        for printer in printers:
            print_job_id = str(uuid.uuid4())
            print_job = {
                "id": print_job_id,
                "order_id": order_id,
                "printer_id": printer["id"],
                "printer_name": printer["name"],
                "printer_type": printer.get("printer_type", "kitchen"),
                "status": "pending",
                "attempts": 0,
                "error": None,
                "created_at": datetime.now(timezone.utc).isoformat(),
                "updated_at": datetime.now(timezone.utc).isoformat()
            }
            await db.print_jobs.insert_one(print_job)
            job_ids.append(print_job_id)
        
        return {"message": f"Impressão agendada para {len(printers)} impressoras", "print_job_ids": job_ids}

# ==================== PRINTER MANAGEMENT ROUTES ====================

@api_router.post("/printers", response_model=PrinterResponse)
async def create_printer(printer: PrinterCreate, authorization: Optional[str] = Header(None)):
    await get_current_user(authorization)
    
    printer_id = str(uuid.uuid4())
    printer_doc = {
        "id": printer_id,
        "name": printer.name,
        "ip": printer.ip,
        "port": printer.port,
        "width": printer.width,
        "cut_paper": printer.cut_paper,
        "active": printer.active,
        "printer_type": printer.printer_type,
        "created_at": datetime.now(timezone.utc).isoformat()
    }
    await db.printers.insert_one(printer_doc)
    return PrinterResponse(**printer_doc)

@api_router.get("/printers", response_model=List[PrinterResponse])
async def list_printers(active_only: bool = False, authorization: Optional[str] = Header(None)):
    await get_current_user(authorization)
    
    query = {"active": True} if active_only else {}
    printers = await db.printers.find(query, {"_id": 0}).to_list(100)
    # Add default printer_type for backwards compatibility
    for p in printers:
        if "printer_type" not in p:
            p["printer_type"] = "kitchen"
    return [PrinterResponse(**p) for p in printers]

@api_router.get("/printers/{printer_id}", response_model=PrinterResponse)
async def get_printer(printer_id: str, authorization: Optional[str] = Header(None)):
    await get_current_user(authorization)
    
    printer = await db.printers.find_one({"id": printer_id}, {"_id": 0})
    if not printer:
        raise HTTPException(status_code=404, detail="Impressora não encontrada")
    return PrinterResponse(**printer)

@api_router.put("/printers/{printer_id}", response_model=PrinterResponse)
async def update_printer(printer_id: str, update: PrinterUpdate, authorization: Optional[str] = Header(None)):
    await get_current_user(authorization)
    
    update_data = {k: v for k, v in update.model_dump().items() if v is not None}
    if not update_data:
        raise HTTPException(status_code=400, detail="Nenhum campo para atualizar")
    
    result = await db.printers.update_one({"id": printer_id}, {"$set": update_data})
    if result.matched_count == 0:
        raise HTTPException(status_code=404, detail="Impressora não encontrada")
    
    printer = await db.printers.find_one({"id": printer_id}, {"_id": 0})
    return PrinterResponse(**printer)

@api_router.delete("/printers/{printer_id}")
async def delete_printer(printer_id: str, authorization: Optional[str] = Header(None)):
    await get_current_user(authorization)
    
    result = await db.printers.delete_one({"id": printer_id})
    if result.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Impressora não encontrada")
    return {"message": "Impressora eliminada"}

@api_router.post("/printers/{printer_id}/test")
async def test_printer_connection(printer_id: str, authorization: Optional[str] = Header(None)):
    """Test printer connection - creates a test print job for the agent"""
    await get_current_user(authorization)
    
    printer = await db.printers.find_one({"id": printer_id}, {"_id": 0})
    if not printer:
        raise HTTPException(status_code=404, detail="Impressora não encontrada")
    
    # Get restaurant name from settings
    settings = await db.settings.find_one({"key": "restaurant"}, {"_id": 0})
    restaurant_name = settings.get("value", {}).get("name", "Pizzaria") if settings else "Pizzaria"
    
    # Create a test print job
    print_job_id = str(uuid.uuid4())
    print_job = {
        "id": print_job_id,
        "order_id": None,  # Test job, no order
        "printer_id": printer_id,
        "printer_name": printer["name"],
        "status": "pending",
        "is_test": True,
        "attempts": 0,
        "error": None,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "updated_at": datetime.now(timezone.utc).isoformat()
    }
    await db.print_jobs.insert_one(print_job)
    
    return {"message": "Teste de impressão agendado", "print_job_id": print_job_id}

# ==================== PRINT JOBS ROUTES ====================

@api_router.get("/print-jobs")
async def list_print_jobs(
    status: Optional[str] = None,
    order_id: Optional[str] = None,
    printer_id: Optional[str] = None,
    authorization: Optional[str] = Header(None)
):
    await get_current_user(authorization)
    
    query = {}
    if status:
        query["status"] = status
    if order_id:
        query["order_id"] = order_id
    if printer_id:
        query["printer_id"] = printer_id
    
    jobs = await db.print_jobs.find(query, {"_id": 0}).sort("created_at", -1).to_list(200)
    return jobs

@api_router.get("/print-jobs/{job_id}")
async def get_print_job(job_id: str, authorization: Optional[str] = Header(None)):
    await get_current_user(authorization)
    
    job = await db.print_jobs.find_one({"id": job_id}, {"_id": 0})
    if not job:
        raise HTTPException(status_code=404, detail="Print job não encontrado")
    return job

# ==================== PRINT AGENT API ====================

@api_router.get("/agent/pending-jobs")
async def get_pending_jobs_for_agent(x_api_key: Optional[str] = Header(None)):
    """Get pending print jobs for the print agent"""
    await verify_print_agent_key(x_api_key)
    
    # Get pending jobs with their printer info and order info
    jobs = await db.print_jobs.find(
        {"status": "pending"},
        {"_id": 0}
    ).sort("created_at", 1).to_list(50)
    
    result = []
    for job in jobs:
        # Get printer info
        printer = None
        if job.get("printer_id"):
            printer = await db.printers.find_one({"id": job["printer_id"]}, {"_id": 0})
            # Add default printer_type for backwards compatibility
            if printer and "printer_type" not in printer:
                printer["printer_type"] = "kitchen"
        
        # Get order info (if not a test job). Um job de "consulta de mesa" traz um
        # snapshot embutido (order-like) em vez de um order_id real.
        order = None
        if job.get("order_snapshot"):
            order = job["order_snapshot"]
        elif job.get("order_id"):
            order = await db.orders.find_one({"id": job["order_id"]}, {"_id": 0})
        
        # Get restaurant name
        settings = await db.settings.find_one({"key": "restaurant"}, {"_id": 0})
        restaurant_name = settings.get("value", {}).get("name", "Pizzaria") if settings else "Pizzaria"
        
        # Include printer_type in result
        printer_type = job.get("printer_type") or (printer.get("printer_type") if printer else "kitchen")

        # Render ESC/POS server-side (base64) para o app-ponte (APK) ser "burro":
        # só recebe bytes, abre socket :9100 e imprime. Não quebra o agente python
        # (campo extra, ignorado por ele).
        printer_name = (printer.get("name") if printer else None) or job.get("printer_name") \
            or ("CAIXA" if printer_type == "cashier" else "COZINHA")
        # Jobs de fatura trazem o ESC/POS já pronto do Vendus (escpos_direct_b64);
        # os restantes são renderizados aqui a partir do pedido/snapshot.
        escpos_b64 = job.get("escpos_direct_b64") or ""
        if not escpos_b64:
            try:
                fmt = ESCPOSFormatter()
                if job.get("is_test"):
                    raw = fmt.format_test(printer_name, restaurant_name)
                elif order:
                    raw = fmt.format_order(order, printer_name, printer_type, restaurant_name)
                else:
                    raw = b""
                if raw:
                    escpos_b64 = base64.b64encode(raw).decode("ascii")
            except Exception as e:
                logger.warning(f"Falha a renderizar ESC/POS do job {job.get('id')}: {e}")

        result.append({
            "job": job,
            "printer": printer,
            "printer_type": printer_type,
            "order": order,
            "restaurant_name": restaurant_name,
            "is_test": job.get("is_test", False),
            "escpos_base64": escpos_b64,
        })
    
    return result

@api_router.put("/agent/jobs/{job_id}/status")
async def update_job_status_from_agent(
    job_id: str,
    update: PrintJobStatusUpdate,
    x_api_key: Optional[str] = Header(None)
):
    """Update print job status from the print agent"""
    await verify_print_agent_key(x_api_key)
    
    valid_statuses = ["printing", "printed", "failed"]
    if update.status not in valid_statuses:
        raise HTTPException(status_code=400, detail=f"Estado inválido. Valores válidos: {valid_statuses}")
    
    job = await db.print_jobs.find_one({"id": job_id}, {"_id": 0})
    if not job:
        raise HTTPException(status_code=404, detail="Print job não encontrado")
    
    update_data = {
        "status": update.status,
        "updated_at": datetime.now(timezone.utc).isoformat()
    }
    
    if update.status == "failed":
        update_data["error"] = update.error
        update_data["attempts"] = job.get("attempts", 0) + 1
    
    await db.print_jobs.update_one({"id": job_id}, {"$set": update_data})
    
    # Update order print status if this is not a test job
    if job.get("order_id"):
        # Check all print jobs for this order
        order_jobs = await db.print_jobs.find(
            {"order_id": job["order_id"]},
            {"_id": 0, "status": 1}
        ).to_list(100)
        
        # Determine overall print status
        statuses = [j["status"] for j in order_jobs]
        if update.status == "printed":
            # Check if this was the status update we just made
            statuses = [s if s != "pending" else update.status for s in statuses]
        
        if all(s == "printed" for s in statuses):
            order_print_status = "printed"
        elif any(s == "failed" for s in statuses):
            order_print_status = "partial" if any(s == "printed" for s in statuses) else "failed"
        elif any(s == "printing" for s in statuses):
            order_print_status = "printing"
        else:
            order_print_status = "pending"
        
        await db.orders.update_one(
            {"id": job["order_id"]},
            {"$set": {"print_status": order_print_status}}
        )
    
    return {"message": "Status atualizado", "status": update.status}

@api_router.get("/agent/printers")
async def get_printers_for_agent(x_api_key: Optional[str] = Header(None)):
    """Get all printers configuration for the agent"""
    await verify_print_agent_key(x_api_key)
    
    printers = await db.printers.find({"active": True}, {"_id": 0}).to_list(100)
    return printers

# ==================== PRINT AGENT CONFIGURATION ====================

@api_router.get("/settings/print-agent")
async def get_print_agent_settings(authorization: Optional[str] = Header(None)):
    """Get or generate print agent API key"""
    await get_current_user(authorization)
    
    settings = await db.settings.find_one({"key": "print_agent"}, {"_id": 0})
    if not settings:
        # Generate new API key
        api_key = secrets.token_urlsafe(32)
        settings = {
            "key": "print_agent",
            "value": {
                "api_key": api_key,
                "created_at": datetime.now(timezone.utc).isoformat()
            }
        }
        await db.settings.insert_one(settings)
    
    return settings.get("value", {})

@api_router.post("/settings/print-agent/regenerate")
async def regenerate_print_agent_key(authorization: Optional[str] = Header(None)):
    """Regenerate print agent API key"""
    await get_current_user(authorization)
    
    api_key = secrets.token_urlsafe(32)
    await db.settings.update_one(
        {"key": "print_agent"},
        {"$set": {
            "key": "print_agent",
            "value": {
                "api_key": api_key,
                "created_at": datetime.now(timezone.utc).isoformat()
            }
        }},
        upsert=True
    )
    
    return {"api_key": api_key, "message": "Nova API key gerada"}

# ==================== RESTAURANT SETTINGS ====================

@api_router.get("/settings/restaurant/public")
async def get_restaurant_settings_public():
    """Public endpoint for restaurant settings (for menu page)"""
    settings = await db.settings.find_one({"key": "restaurant"}, {"_id": 0})
    if not settings:
        return {"name": "Pizzaria"}
    return settings.get("value", {"name": "Pizzaria"})

@api_router.get("/settings/restaurant")
async def get_restaurant_settings(authorization: Optional[str] = Header(None)):
    await get_current_user(authorization)
    
    settings = await db.settings.find_one({"key": "restaurant"}, {"_id": 0})
    if not settings:
        return {"name": "Pizzaria"}
    return settings.get("value", {"name": "Pizzaria"})

@api_router.put("/settings/restaurant")
async def update_restaurant_settings(data: dict, authorization: Optional[str] = Header(None)):
    await get_current_user(authorization)
    
    await db.settings.update_one(
        {"key": "restaurant"},
        {"$set": {"key": "restaurant", "value": data}},
        upsert=True
    )
    return data

# ==================== RODÍZIO (all-you-can-eat) ====================

RODIZIO_DEFAULT = {
    "enabled": False,
    "days": [],                 # 0=Seg..6=Dom
    "child_free_max_age": 5,
    "child_half_max_age": 12,
    "tax_id": "INT",            # IVA do rodízio (13%)
    "waste_fee": 5.0,
    "waste_fee_tax_id": "INT",
    "tiers": {
        "simples": {"name": "Rodízio Simples", "price": 18.90,
                    "description": "Pizzas médias e bebidas (limonadas, frutos vermelhos e hortelã) à vontade."},
        "completo": {"name": "Rodízio Completo", "price": 22.90,
                     "description": "Entradas, pizzas médias, bebidas e sobremesas — tudo à vontade."},
    },
}


class RodizioTier(BaseModel):
    name: str
    price: float
    description: str = ""


class RodizioConfig(BaseModel):
    enabled: bool = False
    days: List[int] = []
    child_free_max_age: int = 5
    child_half_max_age: int = 12
    tax_id: str = "INT"
    waste_fee: float = 5.0
    waste_fee_tax_id: str = "INT"
    tiers: Dict[str, RodizioTier]


async def _rodizio_config() -> dict:
    doc = await db.settings.find_one({"key": "rodizio"}, {"_id": 0})
    cfg = dict(RODIZIO_DEFAULT)
    if doc and isinstance(doc.get("value"), dict):
        cfg.update(doc["value"])
    # Backfill de campos novos nos níveis (ex.: description) p/ configs já gravadas.
    tiers = dict(cfg.get("tiers") or {})
    for key, dflt in RODIZIO_DEFAULT["tiers"].items():
        t = dict(tiers.get(key) or {})
        for f, v in dflt.items():
            if not t.get(f):
                t[f] = v
        tiers[key] = t
    cfg["tiers"] = tiers
    return cfg


@api_router.get("/settings/rodizio")
async def get_rodizio_settings(authorization: Optional[str] = Header(None)):
    await get_current_user(authorization)
    return await _rodizio_config()


@api_router.put("/settings/rodizio")
async def update_rodizio_settings(cfg: RodizioConfig, authorization: Optional[str] = Header(None)):
    await get_current_user(authorization)
    value = cfg.model_dump()
    await db.settings.update_one(
        {"key": "rodizio"}, {"$set": {"key": "rodizio", "value": value}}, upsert=True
    )
    return value


@api_router.get("/settings/rodizio/public")
async def get_rodizio_public():
    """Público — o menu do cliente usa isto para saber se hoje há rodízio."""
    cfg = await _rodizio_config()
    today = datetime.now(ZoneInfo("Europe/Lisbon")).weekday()
    available = bool(cfg.get("enabled")) and today in (cfg.get("days") or [])
    fee = cfg.get("waste_fee", 5.0)
    return {
        "available_today": available,
        "enabled": cfg.get("enabled"),
        "days": cfg.get("days"),
        "tiers": cfg.get("tiers"),
        "child_free_max_age": cfg.get("child_free_max_age"),
        "child_half_max_age": cfg.get("child_half_max_age"),
        "waste_fee": fee,
        "waste_note": f"As sobras podem ter uma taxa de {fee:.0f} € por box.",
    }

# ==================== POS: UTILIZADORES (pos_users) ====================
# CRUD de utilizadores do POS/Caixa, geridos pelo admin. O PIN nunca é guardado
# nem devolvido em claro — só o hash (bcrypt, via hash_password/verify_password
# já existentes para o login de admin).

@api_router.post("/admin/pos/users", response_model=PosUserResponse)
async def create_pos_user(user: PosUserCreate, authorization: Optional[str] = Header(None)):
    await get_current_user(authorization)

    if not valid_pin(user.pin):
        raise HTTPException(status_code=400, detail="PIN deve ter exatamente 4 dígitos")

    user_id = str(uuid.uuid4())
    user_doc = {
        "id": user_id,
        "name": user.name,
        "pin_hash": hash_password(user.pin),
        "active": True,
        "created_at": datetime.now(timezone.utc).isoformat()
    }
    await db.pos_users.insert_one(user_doc)
    return PosUserResponse(**user_doc)

@api_router.get("/admin/pos/users", response_model=List[PosUserResponse])
async def list_pos_users(authorization: Optional[str] = Header(None)):
    await get_current_user(authorization)

    users = await db.pos_users.find({}, {"_id": 0}).sort("created_at", 1).to_list(200)
    return [PosUserResponse(**u) for u in users]

@api_router.put("/admin/pos/users/{user_id}", response_model=PosUserResponse)
async def update_pos_user(user_id: str, update: PosUserUpdate, authorization: Optional[str] = Header(None)):
    await get_current_user(authorization)

    update_data = {k: v for k, v in update.model_dump().items() if v is not None}
    if not update_data:
        raise HTTPException(status_code=400, detail="Nenhum campo para atualizar")

    if "pin" in update_data:
        pin = update_data.pop("pin")
        if not valid_pin(pin):
            raise HTTPException(status_code=400, detail="PIN deve ter exatamente 4 dígitos")
        update_data["pin_hash"] = hash_password(pin)

    result = await db.pos_users.update_one({"id": user_id}, {"$set": update_data})
    if result.matched_count == 0:
        raise HTTPException(status_code=404, detail="Utilizador POS não encontrado")

    pos_user = await db.pos_users.find_one({"id": user_id}, {"_id": 0})
    return PosUserResponse(**pos_user)

@api_router.delete("/admin/pos/users/{user_id}")
async def delete_pos_user(user_id: str, authorization: Optional[str] = Header(None)):
    await get_current_user(authorization)

    result = await db.pos_users.delete_one({"id": user_id})
    if result.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Utilizador POS não encontrado")
    return {"message": "Utilizador POS eliminado"}

@api_router.get("/pos/users-public", response_model=List[PosUserPublic])
async def list_pos_users_public(
    authorization: Optional[str] = Header(None),
    x_device_token: Optional[str] = Header(None),
):
    """Lista pública (auth-duplo) dos utilizadores POS ativos — só `{id, name}`,
    nunca `pin_hash`. Usada pela tela de bloqueio/descanso do POS para mostrar
    os avatares/nomes sem precisar do JWT de admin (basta o device token)."""
    await get_pos_or_admin(authorization, x_device_token)

    users = await db.pos_users.find(
        {"active": True}, {"_id": 0, "id": 1, "name": 1}
    ).sort("name", 1).to_list(1000)
    return [PosUserPublic(**u) for u in users]

# ==================== POS: DISPOSITIVOS (pos_devices) ====================
# Tokens de dispositivo para os terminais POS (auth-duplo, tarefa futura).
# O token em claro (secrets.token_urlsafe) só existe no momento da criação —
# a partir daí só fica o hash (bcrypt, hash_token/verify_token de pos/auth.py).

@api_router.post("/admin/pos/device-token", response_model=PosDeviceTokenResponse)
async def create_pos_device_token(payload: PosDeviceTokenCreate, authorization: Optional[str] = Header(None)):
    await get_current_user(authorization)

    days = payload.days or 90
    raw_token = secrets.token_urlsafe(32)
    now = datetime.now(timezone.utc)
    device_doc = {
        "id": str(uuid.uuid4()),
        "token_hash": hash_token(raw_token),
        "label": payload.label,
        "active": True,
        "created_at": now.isoformat(),
        "expires_at": (now + timedelta(days=days)).isoformat(),
    }
    await db.pos_devices.insert_one(device_doc)
    return PosDeviceTokenResponse(**device_doc, token=raw_token)

@api_router.post("/admin/pos/device-token/{device_id}/revoke")
async def revoke_pos_device_token(device_id: str, authorization: Optional[str] = Header(None)):
    await get_current_user(authorization)

    result = await db.pos_devices.update_one({"id": device_id}, {"$set": {"active": False}})
    if result.matched_count == 0:
        raise HTTPException(status_code=404, detail="Dispositivo POS não encontrado")
    return {"message": "Token de dispositivo revogado"}

async def valid_device_token(raw: str) -> bool:
    """Testa um token de dispositivo em claro contra os `pos_devices` ativos
    e não expirados. Usado pelo auth-duplo dos terminais POS (tarefa futura)."""
    now = datetime.now(timezone.utc)
    devices = await db.pos_devices.find({"active": True}, {"_id": 0}).to_list(1000)
    for device in devices:
        expires_at = datetime.fromisoformat(device["expires_at"])
        if expires_at <= now:
            continue
        if verify_token(raw, device["token_hash"]):
            return True
    return False

# ==================== POS: LOGIN + SESSÃO + AUTH-DUPLO ====================
# Login por PIN dos operadores POS: valida o PIN contra os `pos_users` ativos
# e devolve um token de sessão curto (12h). A identidade do operador vem SEMPRE
# do token — nunca de um corpo de pedido.

class PosLoginRequest(BaseModel):
    pin: str

# Rate-limit simples e best-effort do login POS (sem dependências novas):
# contador em memória por device token (preferido) ou IP do cliente. Não
# substitui um rate-limit a sério, mas trava força-bruta de PIN num terminal.
_POS_LOGIN_ATTEMPTS: Dict[str, List[float]] = {}
_POS_LOGIN_WINDOW_S = 60.0
_POS_LOGIN_MAX = 10

def _pos_login_rate_check(key: str) -> None:
    agora = datetime.now(timezone.utc).timestamp()
    janela = [t for t in _POS_LOGIN_ATTEMPTS.get(key, []) if agora - t < _POS_LOGIN_WINDOW_S]
    if len(janela) >= _POS_LOGIN_MAX:
        _POS_LOGIN_ATTEMPTS[key] = janela
        raise HTTPException(status_code=429, detail="Demasiadas tentativas. Aguarde um momento.")
    janela.append(agora)
    _POS_LOGIN_ATTEMPTS[key] = janela

@api_router.post("/pos/login")
async def pos_login(
    body: PosLoginRequest,
    request: Request,
    x_device_token: Optional[str] = Header(None),
):
    # Chave do rate-limit: device token se existir, senão o IP do socket
    # (não é um header falsificável, é o peer TCP).
    rate_key = x_device_token or (request.client.host if request.client else "desconhecido")
    _pos_login_rate_check(rate_key)

    # Recolhe TODOS os utilizadores POS ativos cujo PIN bate (bcrypt).
    # Se houver colisão de PIN (>1), recusamos e obrigamos o gestor a corrigir —
    # nunca adivinhamos qual operador é (fecha a falha conhecida de PIN duplicado).
    ativos = await db.pos_users.find({"active": True}, {"_id": 0}).to_list(1000)
    correspondencias = [
        u for u in ativos
        if u.get("pin_hash") and verify_password(body.pin, u["pin_hash"])
    ]

    if len(correspondencias) == 0:
        raise HTTPException(status_code=401, detail="PIN inválido")
    if len(correspondencias) > 1:
        raise HTTPException(status_code=401, detail="PIN duplicado, contacte o gestor")

    operador = correspondencias[0]
    token = create_pos_token(operador["id"], operador["name"])
    return {"token": token, "user": {"id": operador["id"], "name": operador["name"]}}

async def get_pos_operator(x_pos_token: Optional[str] = Header(None)) -> dict:
    """Dependência dos endpoints só-POS: exige um `X-POS-Token` válido e devolve
    o operador {id, name}. 401 se faltar, for inválido ou estiver expirado."""
    if not x_pos_token:
        raise HTTPException(status_code=401, detail="Token POS não fornecido")
    try:
        payload = decode_pos_token(x_pos_token)
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Sessão POS expirada")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Token POS inválido")
    return {"id": payload.get("pos_user_id"), "name": payload.get("name")}

async def get_pos_or_admin(
    authorization: Optional[str] = Header(None),
    x_device_token: Optional[str] = Header(None),
) -> dict:
    """Auth-duplo: aceita o JWT de admin OU um device token POS válido.

    Tenta primeiro o admin (`get_current_user`); se o JWT falhar (HTTPException),
    cai para o device token. Devolve `{"kind": "admin", "user": ...}` ou
    `{"kind": "pos"}` para o chamador distinguir. 401 se nenhum for válido.
    """
    try:
        user = await get_current_user(authorization)
        return {"kind": "admin", "user": user}
    except HTTPException:
        pass  # JWT de admin ausente/inválido — tentar device token
    if x_device_token and await valid_device_token(x_device_token):
        return {"kind": "pos"}
    raise HTTPException(status_code=401, detail="Autenticação necessária (admin ou dispositivo POS)")

# ==================== POS: CAIXA (cash_sessions) ====================
# Sessão de caixa (spec §4.1). Esta tarefa (Task 6) implementa só a ABERTURA
# e a consulta da sessão atual; movimentos (Task 8) e fecho/reconciliação
# (Task 10) chegam depois. Unicidade atómica de "uma só caixa aberta":
# índice único parcial em {status:"open"} (criado no arranque, ver lifespan)
# + tratamento de DuplicateKeyError no insert — a abertura é idempotente,
# nunca cria uma segunda sessão aberta (pick_open_session em pos/cash.py).

# ---- Sincronização best-effort da caixa da app <-> registador Vendus -----
# (Fase 4.) Espelha abrir/fechar/entrada/saída da caixa da app no registador
# Vendus e, no fecho, pede o talão Z REAL do Vendus (ESC/POS) para imprimir na
# caixa. A caixa da app é SEMPRE a fonte de verdade — estas chamadas correm
# DEPOIS da operação da app já ter sido decidida/commitada e NUNCA podem
# bloquear nem desfazer essa operação: qualquer erro do Vendus fica só em
# `logger.warning`. São chamadas síncronas (httpx) e por isso correm em
# thread (`asyncio.to_thread`); cada helper cria o seu PRÓPRIO
# `VendusClient` (não partilhado entre threads) e fecha-o sempre no fim, com
# um TIMEOUT CURTO (bem abaixo do default de 30s usado na emissão de FS) para
# que uma falha/lentidão do Vendus nunca prenda a operação da app por muito
# tempo.

_VENDUS_MIRROR_TIMEOUT = 6.0


def _vendus_safe_close(c: VendusClient) -> None:
    """Fecha o cliente Vendus sem deixar propagar exceção — o `close()` é só
    limpeza de recursos HTTP e nunca deve rebentar uma operação best-effort."""
    try:
        c.close()
    except Exception as e:
        logger.warning(f"Vendus: falha (ignorada) a fechar o cliente ({e})")


def _vendus_cash_open_sync(opening_amount: float) -> None:
    """Abre o registador Vendus a espelhar a abertura da caixa da app — a
    menos que já esteja positivamente aberto (evita reabrir um registador já
    aberto, ex.: reposto manualmente na app do Vendus). Reabrir por defeito
    quando o estado não é claramente 'open' é mais robusto do que exigir
    'close': um registador preso a meio ou com estado inesperado não deve
    ficar fechado e bloquear a emissão de FS."""
    try:
        c = _vendus_client(timeout=_VENDUS_MIRROR_TIMEOUT)
    except Exception as e:
        logger.warning(f"Vendus: não foi possível sincronizar a abertura da caixa ({e})")
        return
    try:
        if c.register_status() != "open":
            c.register_movement("open", "NU", opening_amount)
    except Exception as e:
        logger.warning(f"Vendus: falha a abrir o registador ({e})")
    finally:
        _vendus_safe_close(c)


def _vendus_cash_movement_sync(operation: str, amount: float, obs: Optional[str]) -> None:
    """Espelha uma sangria/reforço da app como movimento 'out'/'in' no
    registador Vendus."""
    try:
        c = _vendus_client(timeout=_VENDUS_MIRROR_TIMEOUT)
    except Exception as e:
        logger.warning(f"Vendus: não foi possível sincronizar o movimento de caixa ({e})")
        return
    try:
        c.register_movement(operation, "NU", amount, obs=obs)
    except Exception as e:
        logger.warning(f"Vendus: falha a registar o movimento de caixa ({e})")
    finally:
        _vendus_safe_close(c)


def _vendus_cash_close_sync(counted_amount: float) -> Optional[dict]:
    """Fecha o registador Vendus a espelhar o fecho da caixa da app e pede o
    talão Z já em ESC/POS. Devolve a resposta do Vendus (pode ter 'output' em
    base64) ou None se falhar — NUNCA lança (best-effort)."""
    try:
        c = _vendus_client(timeout=_VENDUS_MIRROR_TIMEOUT)
    except Exception as e:
        logger.warning(f"Vendus: não foi possível sincronizar o fecho da caixa ({e})")
        return None
    try:
        return c.register_movement("close", "NU", counted_amount, output="escpos")
    except Exception as e:
        logger.warning(f"Vendus: falha a fechar o registador ({e})")
        return None
    finally:
        _vendus_safe_close(c)


def _cash_expected_vendus_read(inicio_iso: str, fim_iso: str, cash_method_id: Any) -> float:
    """Leitura SÍNCRONA (thread) do Vendus por janela para a pré-visualização
    do esperado (`GET /pos/cash/expected`) — mesmo padrão curto/best-effort
    dos `_vendus_cash_*_sync` acima (timeout `_VENDUS_MIRROR_TIMEOUT`, cliente
    próprio, fecha sempre), e o MESMO `cash_sales_from_vendus` usado pelo
    fecho (`close_cash_session`) — garante que os dois nunca divergem.

    Ao contrário dos helpers acima, esta função LANÇA em caso de falha — o
    chamador (`get_cash_expected`) é que decide apanhar a exceção e devolver
    uma estimativa (`vendus_ok: false`); o fecho em si não usa este helper
    (não é best-effort lá — Vendus indisponível no fecho dá 502)."""
    c = _vendus_client(timeout=_VENDUS_MIRROR_TIMEOUT)
    try:
        vendus = c.app_sales_summary_window(inicio_iso, fim_iso)
        metodos = c.list_payment_methods()
        return cash_sales_from_vendus(vendus, metodos, cash_method_id)["cash_sales"]
    finally:
        _vendus_safe_close(c)


class CashOpenRequest(BaseModel):
    opening_amount: float = 0


@api_router.post("/pos/cash/open")
async def open_cash_session(
    body: CashOpenRequest,
    operador: dict = Depends(get_pos_operator),
):
    """Abre a caixa. O operador vem SEMPRE do token POS (`get_pos_operator`),
    nunca do corpo do pedido — responsabilização não-falsificável (§2.6).

    Idempotente: se já existir uma sessão aberta, esta chamada devolve-a em
    vez de criar uma segunda (o índice único parcial garante que só um
    `insert_one` concorrente pode ter sucesso; os restantes apanham
    `DuplicateKeyError` e vão buscar a sessão já aberta)."""
    if body.opening_amount < 0:
        raise HTTPException(status_code=400, detail="Montante de abertura não pode ser negativo")

    nova_sessao = {
        "id": str(uuid.uuid4()),
        "status": "open",
        "opened_by": operador["id"],
        "opened_by_name": operador["name"],
        "opened_at": datetime.now(timezone.utc).isoformat(),
        "opening_amount": round(float(body.opening_amount), 2),
        "movements": [],
    }
    try:
        # Copia para o insert: o motor acrescenta "_id" ao dict passado, e
        # queremos devolver `nova_sessao` limpo (sem _id) quando não há conflito.
        await db.cash_sessions.insert_one(dict(nova_sessao))
        sessao_final = nova_sessao
    except DuplicateKeyError:
        existente = await db.cash_sessions.find_one({"status": "open"}, {"_id": 0})
        sessao_final = pick_open_session(existente, nova_sessao)

    # Espelho best-effort no Vendus — NUNCA bloqueia/falha a abertura da app,
    # que já está decidida e commitada acima (ver `_vendus_cash_open_sync`).
    await asyncio.to_thread(_vendus_cash_open_sync, sessao_final["opening_amount"])
    return sessao_final


@api_router.get("/pos/cash/current")
async def get_current_cash_session(operador: dict = Depends(get_pos_operator)):
    """Devolve a sessão de caixa aberta atual (dict achatado, `status:"open"`
    incluído) mais `last_close` — o fecho FECHADO mais recente, resumido a
    `{closed_by_name, closed_at, counted_amount}` (ou `None` se nunca houve
    nenhum fecho).

    Sem sessão aberta, devolve só `{"last_close": ...}` (sem `status`) — os
    chamadores que precisam de saber "há caixa aberta?" têm de verificar
    `status == "open"`, nunca a verdade do payload inteiro (Fase 4b: este
    endpoint deixou de poder devolver `null` liso, porque agora carrega
    sempre o último fecho para o ecrã "Caixa Fechada" mostrar "Último
    fecho: ..."). Leitura extra barata (find + sort + limit 1) — aceitável
    neste poll frequente."""
    aberta = await db.cash_sessions.find_one({"status": "open"}, {"_id": 0})

    ultimos_fechados = await db.cash_sessions.find(
        {"status": "closed"}, {"_id": 0}
    ).sort("closed_at", -1).to_list(1)
    ultimo_fechado = ultimos_fechados[0] if ultimos_fechados else None
    last_close = None
    if ultimo_fechado:
        last_close = {
            "closed_by_name": ultimo_fechado.get("closed_by_name"),
            "closed_at": ultimo_fechado.get("closed_at"),
            "counted_amount": ultimo_fechado.get("counted_amount"),
        }

    if aberta:
        aberta["last_close"] = last_close
        return aberta
    return {"last_close": last_close}


class CashMovementRequest(BaseModel):
    type: str
    amount: float
    reason: Optional[str] = None


@api_router.post("/pos/cash/movement")
async def add_cash_movement(
    body: CashMovementRequest,
    operador: dict = Depends(get_pos_operator),
):
    """Regista uma sangria ou reforço na sessão de caixa ABERTA.

    O operador (`by`) vem SEMPRE do token POS (`get_pos_operator`), nunca do
    corpo do pedido — mesma responsabilização não-falsificável do `open`
    (§2.6). A sessão é resolvida aqui no servidor (a única aberta), nunca por
    um id vindo do corpo; sem caixa aberta, 409."""
    if body.type not in ("sangria", "reforco"):
        raise HTTPException(status_code=400, detail="Tipo de movimento inválido")
    if body.amount <= 0:
        raise HTTPException(status_code=400, detail="Montante do movimento tem de ser positivo")

    sessao = await db.cash_sessions.find_one({"status": "open"})
    if not sessao:
        raise HTTPException(status_code=409, detail="Abra a caixa primeiro")

    movimento = {
        "type": body.type,
        "amount": round(float(body.amount), 2),
        "by": operador["id"],
        "at": datetime.now(timezone.utc).isoformat(),
    }
    if body.reason:
        movimento["reason"] = body.reason

    # Filtro repete "status": "open" (não só o id) — se a caixa fechar mesmo
    # entre o find_one e este update, o movimento não fica preso a uma sessão
    # já fechada.
    resultado = await db.cash_sessions.update_one(
        {"id": sessao["id"], "status": "open"}, {"$push": {"movements": movimento}}
    )
    if resultado.matched_count == 0:
        raise HTTPException(status_code=409, detail="Abra a caixa primeiro")

    # Espelho best-effort no Vendus: sangria -> "out", reforço -> "in". Só
    # corre depois do movimento da app já estar gravado (nunca bloqueia/falha
    # o registo da app — ver `_vendus_cash_movement_sync`).
    await asyncio.to_thread(
        _vendus_cash_movement_sync,
        "out" if body.type == "sangria" else "in",
        movimento["amount"],
        body.reason,
    )
    return await db.cash_sessions.find_one({"id": sessao["id"]}, {"_id": 0})


@api_router.post("/pos/cash/drawer")
async def open_cash_drawer(
    authorization: Optional[str] = Header(None),
    x_device_token: Optional[str] = Header(None),
):
    """Abre a gaveta do dinheiro (menu Caixa, "Abrir Gaveta"): enfileira o comando
    ESC/POS padrão de pulso ("kick") na impressora da CAIXA, pelo mesmo mecanismo
    `print_jobs` + `escpos_direct_b64` + `printer_type="cashier"` usado pelas
    faturas (`close_table`) e pelo talão Z (`close_cash_session`) — o app-ponte
    apanha o job e pulsa a gaveta ligada a essa impressora."""
    await get_pos_or_admin(authorization, x_device_token)
    kick_bytes = b"\x1b\x70\x00\x19\xfa"  # ESC p 0 25 250 — pulso padrão da gaveta
    await db.print_jobs.insert_one({
        "id": str(uuid.uuid4()),
        "order_id": None,
        "escpos_direct_b64": base64.b64encode(kick_bytes).decode("ascii"),
        "printer_id": None,
        "printer_name": "Caixa",
        "printer_type": "cashier",
        "status": "pending",
        "attempts": 0,
        "error": None,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "updated_at": datetime.now(timezone.utc).isoformat(),
    })
    return {"ok": True}


@api_router.get("/pos/cash/expected")
async def get_cash_expected(
    authorization: Optional[str] = Header(None),
    x_device_token: Optional[str] = Header(None),
):
    """Pré-visualização do dinheiro esperado em caixa para a sessão ABERTA
    atual — ecrã "Contagem de Caixa" (Fase 4b), ANTES do operador contar a
    gaveta, para poder comparar com o que vai contar.

    Usa o MESMO cálculo do fecho (`POST /pos/cash/close`): janela
    `opened_at` → agora (Lisboa) lida no Vendus, `cash_sales` identificado
    pelo método de pagamento 'Dinheiro' configurado
    (`cash_sales_from_vendus`, partilhada com o fecho — nunca pode divergir),
    e `expected_cash` = abertura + cash_sales + reforços - sangrias (mesma
    função pura do fecho).

    BEST-EFFORT: ao contrário do fecho (que dá 502 se o Vendus falhar —
    fechar às cegas contra a verdade fiscal seria pior), esta pré-visualização
    NUNCA falha por causa do Vendus: timeout curto (`_VENDUS_MIRROR_TIMEOUT`)
    e, se a leitura falhar, devolve o esperado só com abertura+movimentos
    (`cash_sales=0`) e `vendus_ok: false` — o operador vê uma estimativa em
    vez de um erro. Só dá 409 se não houver caixa aberta."""
    await get_pos_or_admin(authorization, x_device_token)

    sessao = await db.cash_sessions.find_one({"status": "open"}, {"_id": 0})
    if not sessao:
        raise HTTPException(status_code=409, detail="Não há caixa aberta")

    pos_cfg = await _pos_settings_config()
    cash_method_id = pos_cfg.get("cash_payment_method_id")

    lisbon = ZoneInfo("Europe/Lisbon")
    inicio_lisboa = datetime.fromisoformat(sessao["opened_at"]).astimezone(lisbon)
    fim_lisboa = datetime.now(lisbon)

    cash_sales = 0.0
    vendus_ok = True
    try:
        cash_sales = await asyncio.to_thread(
            _cash_expected_vendus_read, inicio_lisboa.isoformat(), fim_lisboa.isoformat(), cash_method_id
        )
    except Exception as e:
        logger.warning(f"Vendus: pré-visualização do esperado sem ligação, a usar só abertura+movimentos ({e})")
        vendus_ok = False

    movimentos = sessao.get("movements") or []
    abertura = round(float(sessao.get("opening_amount", 0.0) or 0.0), 2)
    soma = movements_breakdown(movimentos)

    return {
        "expected_cash": expected_cash(abertura, cash_sales, movimentos),
        "opening_amount": abertura,
        "cash_sales": cash_sales,
        "reforcos": soma["reforcos"],
        "sangrias": soma["sangrias"],
        "vendus_ok": vendus_ok,
    }


class CashCloseRequest(BaseModel):
    counted_amount: float = 0


@api_router.post("/pos/cash/close")
async def close_cash_session(
    body: CashCloseRequest,
    operador: dict = Depends(get_pos_operator),
):
    """Fecha a caixa e reconcilia contra o Vendus POR JANELA temporal.

    Passos (§Task 10):
      1. Exige uma sessão ABERTA (senão 409). Operador vem do token POS.
      2. Janela = `opened_at` (UTC, convertido para Lisboa) → agora (Lisboa). Lê o
         Vendus SÓ dessa janela (`app_sales_summary_window`, mesmo `register_id`) —
         nunca por string de data (uma sessão pode atravessar a meia-noite).
      3. `cash_sales` = total Vendus do método cujo id == `cash_payment_method_id`
         (identificado por ID, nunca pela string "Dinheiro"). Se não estiver
         configurado → 0 + aviso no Z.
      4. `expected = expected_cash(abertura, cash_sales, movimentos)`;
         `difference = contado - esperado`.
      5. Reconcilia o Vendus (verdade fiscal) com as `pos_sales` da sessão. Se
         divergir, o Z leva o aviso — a reconciliação NUNCA bloqueia o fecho.
      6. Fecho ATÓMICO (`find_one_and_update` com filtro `status:"open"`) — um
         duplo-fecho concorrente não corre duas vezes (o 2.º apanha 409).

    Devolve os DADOS do Z (a Task 11 é que os imprime). Se o Vendus estiver
    indisponível → 502 e a caixa fica aberta (não se fecha às cegas contra a
    verdade fiscal)."""
    sessao = await db.cash_sessions.find_one({"status": "open"})
    if not sessao:
        raise HTTPException(status_code=409, detail="Não há caixa aberta")

    avisos: list = []

    # Janela: opened_at (UTC) → Lisboa; fim = agora (Lisboa). A conversão explícita
    # para Lisboa é o que alinha com o `local_time` das FS do Vendus.
    lisbon = ZoneInfo("Europe/Lisbon")
    inicio_lisboa = datetime.fromisoformat(sessao["opened_at"]).astimezone(lisbon)
    fim_lisboa = datetime.now(lisbon)

    # Vendus por janela + o mapa id→título dos métodos de pagamento (para
    # identificar o dinheiro por ID e para alinhar as pos_sales com o Vendus, que
    # vem repartido por título). Tudo numa só sessão HTTP.
    c = _vendus_client()
    try:
        vendus = c.app_sales_summary_window(inicio_lisboa.isoformat(), fim_lisboa.isoformat())
        metodos = c.list_payment_methods()
    except VendusError as e:
        raise HTTPException(status_code=502, detail=f"Vendus indisponível para reconciliar: {e}")
    finally:
        c.close()

    # Dinheiro identificado pelo ID configurado, nunca pela string "Dinheiro".
    # `cash_sales_from_vendus` (pos/cash_math.py) é a MESMA função usada pela
    # pré-visualização best-effort (`GET /pos/cash/expected`) — garante que os
    # dois nunca calculam valores diferentes (DRY, Fase 4b).
    pos_cfg = await _pos_settings_config()
    cash_method_id = pos_cfg.get("cash_payment_method_id")
    resultado_cash = cash_sales_from_vendus(vendus, metodos, cash_method_id)
    cash_sales = resultado_cash["cash_sales"]
    vendus_by_method = resultado_cash["vendus_by_method"]
    id_to_title = resultado_cash["id_to_title"]
    avisos.extend(resultado_cash["warnings"])

    movimentos = sessao.get("movements") or []
    abertura = round(float(sessao.get("opening_amount", 0.0) or 0.0), 2)
    esperado = expected_cash(abertura, cash_sales, movimentos)
    contado = round(float(body.counted_amount or 0.0), 2)
    diferenca = round(contado - esperado, 2)

    # pos_sales da sessão, repartidas por MÉTODO (título, para alinhar com o
    # Vendus). Cada linha tem `payment_method_id`; traduz-se para título pelo mapa
    # do Vendus (fallback: o próprio id em texto → sairá em "missing").
    pos_rows = await db.pos_sales.find({"cash_session_id": sessao["id"]}, {"_id": 0}).to_list(length=None)
    pos_sales_by_method: dict = {}
    for r in pos_rows:
        titulo = r.get("payment_method_title") or id_to_title.get(str(r.get("payment_method_id"))) or str(r.get("payment_method_id"))
        cur = pos_sales_by_method.setdefault(titulo, {"count": 0, "total": 0.0})
        cur["count"] += 1
        cur["total"] = round(cur["total"] + float(r.get("amount", 0.0) or 0.0), 2)

    reconciliacao = reconciliation_diff(vendus_by_method, pos_sales_by_method)
    if not reconciliacao["ok"]:
        # NUNCA bloqueia o fecho — só sinaliza. As divergências ficam no Z.
        avisos.append(
            "Reconciliação com divergências: "
            f"Vendus sem par nas vendas POS {reconciliacao['orphans']}; "
            f"vendas POS sem fatura {reconciliacao['missing']}."
        )

    # Ler dados só-de-leitura ANTES do fecho atómico: nada que possa falhar deve
    # correr DEPOIS do commit (senão a caixa fica fechada mas o operador não
    # recebe o Z, e o retry dá 409 "Caixa já fechada").
    rest = await db.settings.find_one({"key": "restaurant"}, {"_id": 0})
    restaurant_name = ((rest or {}).get("value") or {}).get("name", "Pizzaria")

    fechado_em = datetime.now(timezone.utc).isoformat()
    # Fecho ATÓMICO: só corre se a sessão ainda estiver aberta. Um duplo-fecho
    # concorrente falha aqui (matched=None) → 409, sem re-gravar/re-executar.
    atualizada = await db.cash_sessions.find_one_and_update(
        {"id": sessao["id"], "status": "open"},
        {"$set": {
            "status": "closed",
            "closed_at": fechado_em,
            "closed_by": operador["id"],
            "closed_by_name": operador["name"],
            "counted_amount": contado,
            "cash_sales": cash_sales,
            "expected_cash": esperado,
            "difference": diferenca,
            "totals_by_method": vendus_by_method,
            "reconciliation": reconciliacao,
        }},
        return_document=ReturnDocument.AFTER,
        projection={"_id": 0},
    )
    if atualizada is None:
        raise HTTPException(status_code=409, detail="Caixa já fechada")

    # Espelho best-effort no Vendus: fecha o registador Vendus (mirror) e pede
    # o talão Z REAL do Vendus em ESC/POS. A caixa da app já fechou
    # ATOMICAMENTE acima — isto NUNCA bloqueia nem desfaz esse fecho (ver
    # `_vendus_cash_close_sync`, que nunca lança).
    vendus_resp = await asyncio.to_thread(_vendus_cash_close_sync, contado)
    vendus_closed = vendus_resp is not None

    # DADOS do Z (a Task 11 renderiza/imprime). Snapshot completo do fecho.
    z_data = {
        "restaurant": restaurant_name,
        "z_footer_text": pos_cfg.get("z_footer_text", ""),
        "session_id": sessao["id"],
        "opened_by": sessao.get("opened_by_name") or sessao.get("opened_by"),
        "opened_at": sessao.get("opened_at"),
        "closed_by": operador["name"],
        "closed_at": fechado_em,
        "opening_amount": abertura,
        "movements": movimentos,
        "cash_sales": cash_sales,
        "totals_by_method": vendus_by_method,
        "vendus_total": vendus.get("total", 0.0),
        "vendus_count": vendus.get("count", 0),
        "expected_cash": esperado,
        "counted_amount": contado,
        "difference": diferenca,
        "reconciliation": reconciliacao,
        "warnings": avisos,
        "vendus_closed": vendus_closed,
    }

    # Imprime o talão Z na CAIXA — mesmo mecanismo (`print_jobs` +
    # `escpos_direct_b64` + `printer_type="cashier"`) usado pelas faturas em
    # `close_table`. O fecho já está COMMITADO acima (`find_one_and_update`);
    # uma falha aqui é só registada — NUNCA transforma um fecho bem-sucedido
    # num 500 (o operador ainda vê o Z no ecrã e pode reimprimir via
    # `GET /pos/cash/{id}/z`).
    try:
        escpos_bytes = build_z_escpos(z_data)
        await db.print_jobs.insert_one({
            "id": str(uuid.uuid4()),
            "order_id": None,
            "escpos_direct_b64": base64.b64encode(escpos_bytes).decode("ascii"),
            "printer_id": None,
            "printer_name": "Caixa",
            "printer_type": "cashier",
            "status": "pending",
            "attempts": 0,
            "error": None,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "updated_at": datetime.now(timezone.utc).isoformat(),
        })
    except Exception as e:
        logger.error(f"Falha a enfileirar impressão do Z (fecho já commitado, sessão {sessao['id']}): {e}")

    # Imprime o talão Z REAL do Vendus, se a sincronização acima teve sucesso e
    # devolveu o ESC/POS — job de impressão SEPARADO do Z da app, mesma
    # impressora da CAIXA. Best-effort: uma falha aqui também é só registada.
    if vendus_resp and vendus_resp.get("output"):
        try:
            await db.print_jobs.insert_one({
                "id": str(uuid.uuid4()),
                "order_id": None,
                "escpos_direct_b64": vendus_resp["output"],
                "printer_id": None,
                "printer_name": "Caixa",
                "printer_type": "cashier",
                "status": "pending",
                "attempts": 0,
                "error": None,
                "created_at": datetime.now(timezone.utc).isoformat(),
                "updated_at": datetime.now(timezone.utc).isoformat(),
            })
        except Exception as e:
            logger.error(f"Falha a enfileirar impressão do Z do Vendus (sessão {sessao['id']}): {e}")

    return z_data


@api_router.get("/pos/cash/{session_id}/z")
async def get_cash_session_z(session_id: str, authorization: Optional[str] = Header(None),
                              x_device_token: Optional[str] = Header(None)):
    """Devolve os DADOS do Z de uma sessão de caixa FECHADA — para consulta no
    ecrã ou reimpressão (o mesmo `build_z_escpos` do fecho). Reconstrói o
    mesmo dict devolvido por `close_cash_session` a partir do documento
    persistido: `vendus_total`/`vendus_count` NÃO são persistidos, por isso
    são re-derivados de `totals_by_method` (soma dos `total`/`count` por
    método). 404 se a sessão não existir; 409 se ainda estiver aberta (o Z só
    existe depois do fecho)."""
    await get_pos_or_admin(authorization, x_device_token)

    sessao = await db.cash_sessions.find_one({"id": session_id}, {"_id": 0})
    if not sessao:
        raise HTTPException(status_code=404, detail="Sessão de caixa não encontrada")
    if sessao.get("status") != "closed":
        raise HTTPException(status_code=409, detail="Sessão de caixa ainda está aberta — o Z só existe após o fecho")

    rest = await db.settings.find_one({"key": "restaurant"}, {"_id": 0})
    restaurant_name = ((rest or {}).get("value") or {}).get("name", "Pizzaria")
    pos_cfg = await _pos_settings_config()

    totals_by_method = sessao.get("totals_by_method") or {}
    vendus_total = round(sum(float(v.get("total", 0) or 0) for v in totals_by_method.values()), 2)
    vendus_count = sum(int(v.get("count", 0) or 0) for v in totals_by_method.values())

    return {
        "restaurant": restaurant_name,
        "z_footer_text": pos_cfg.get("z_footer_text", ""),
        "session_id": sessao["id"],
        "opened_by": sessao.get("opened_by_name") or sessao.get("opened_by"),
        "opened_at": sessao.get("opened_at"),
        "closed_by": sessao.get("closed_by_name") or sessao.get("closed_by"),
        "closed_at": sessao.get("closed_at"),
        "opening_amount": sessao.get("opening_amount", 0.0),
        "movements": sessao.get("movements") or [],
        "cash_sales": sessao.get("cash_sales", 0.0),
        "totals_by_method": totals_by_method,
        "vendus_total": vendus_total,
        "vendus_count": vendus_count,
        "expected_cash": sessao.get("expected_cash", 0.0),
        "counted_amount": sessao.get("counted_amount", 0.0),
        "difference": sessao.get("difference", 0.0),
        "reconciliation": sessao.get("reconciliation") or {"ok": True, "orphans": [], "missing": [], "details": {}},
    }

# ==================== POS: DEFINIÇÕES (pos_settings) ====================
# Definições do POS/Caixa: exigir caixa aberta antes de faturar, o método de
# pagamento "Dinheiro" do Vendus (o id escolhe-se em /vendus/payment-methods,
# tarefa à parte) e o texto de rodapé impresso no fecho (Z). Guardado em
# db.settings sob a chave "pos" — mesmo padrão do "rodizio"/"restaurant".

POS_SETTINGS_DEFAULT = {
    "require_open_cash": True,
    "cash_payment_method_id": None,
    "z_footer_text": "",
}


class PosSettingsConfig(BaseModel):
    require_open_cash: bool = True
    cash_payment_method_id: Optional[int] = None
    z_footer_text: str = ""


async def _pos_settings_config() -> dict:
    doc = await db.settings.find_one({"key": "pos"}, {"_id": 0})
    cfg = dict(POS_SETTINGS_DEFAULT)
    if doc and isinstance(doc.get("value"), dict):
        cfg.update(doc["value"])
    return cfg


@api_router.get("/admin/pos/settings")
async def get_pos_settings(authorization: Optional[str] = Header(None)):
    await get_current_user(authorization)
    return await _pos_settings_config()


@api_router.put("/admin/pos/settings")
async def update_pos_settings(cfg: PosSettingsConfig, authorization: Optional[str] = Header(None)):
    await get_current_user(authorization)
    value = cfg.model_dump()
    await db.settings.update_one(
        {"key": "pos"}, {"$set": {"key": "pos", "value": value}}, upsert=True
    )
    return value

# ==================== POS: BALCÃO (pedidos sem mesa) ====================
# Pedido de balcão (Fase 2, Task 1): o operador escolhe produtos diretamente
# no POS, sem passar por uma mesa (`table_number=None`, `table_id=None`). O
# pedido fica "received" e imprime na cozinha pelo MESMO mecanismo de
# `create_order` (`_enqueue_order_prints`, extraído dali).


class CounterOrderItem(BaseModel):
    product_id: str
    quantity: int = Field(gt=0)
    # Overrides opcionais do staff (diálogo do produto no balcão). Sem eles, usa-se
    # o preço/IVA do produto e sem desconto — comportamento de venda rápida.
    unit_price: Optional[float] = None       # override do preço unitário
    vendus_tax_id: Optional[str] = None      # override do IVA: INT (13%) | NOR (23%)
    discount_pct: Optional[float] = None     # desconto % (0..100)
    discount_amount: Optional[float] = None  # desconto € (mutuamente exclusivo com pct)


class CounterOrderRequest(BaseModel):
    items: List[CounterOrderItem]


@api_router.post("/pos/counter/order")
async def create_counter_order(
    body: CounterOrderRequest,
    authorization: Optional[str] = Header(None),
    x_device_token: Optional[str] = Header(None),
    x_pos_token: Optional[str] = Header(None),
):
    """Cria um pedido de balcão (sem mesa). Auth-duplo (admin JWT ou device
    token POS) para entrar; o OPERADOR responsável vem sempre do token POS
    (`X-POS-Token`), nunca do corpo — mesma responsabilização não-falsificável
    do resto do POS (§2.6)."""
    auth = await get_pos_or_admin(authorization, x_device_token)
    operador = await get_pos_operator(x_pos_token)

    # Sessão de caixa resolvida no SERVIDOR (nunca do corpo) — mesmo mecanismo
    # de `close_table`: sem sessão aberta e definições a exigir caixa, recusa
    # ANTES de criar o pedido.
    sess = await db.cash_sessions.find_one({"status": "open"})
    if auth.get("kind") == "pos":
        pos_cfg = await _pos_settings_config()
        if pos_cfg.get("require_open_cash", True) and not sess:
            raise HTTPException(status_code=409, detail="Abra a caixa primeiro")

    # Carrega só os produtos do carrinho (evita puxar o catálogo inteiro).
    # Descarta produtos rodizio_only (só entram em conta no rodízio, nunca à
    # peça no balcão) ou indisponíveis — defesa contra cache do frontend
    # desatualizada ou um pedido manual/malicioso; `build_counter_items` já
    # ignora entradas do carrinho sem produto correspondente em
    # `products_by_id`, por isso basta não os incluir aqui.
    product_ids = [i.product_id for i in body.items]
    prods = await db.products.find({"id": {"$in": product_ids}}, {"_id": 0}).to_list(1000)
    products_by_id = {
        p["id"]: p
        for p in prods
        if not p.get("rodizio_only", False) and p.get("available", True)
    }

    # Valida os overrides do staff (diálogo do produto): preço/desconto não
    # negativos, IVA só INT/NOR (classes usadas nas FS), percentagem 0..100.
    for i in body.items:
        if i.unit_price is not None and i.unit_price < 0:
            raise HTTPException(status_code=400, detail="Preço inválido")
        if i.vendus_tax_id is not None and i.vendus_tax_id not in ("INT", "NOR"):
            raise HTTPException(status_code=400, detail="IVA inválido")
        if i.discount_pct is not None and not (0 <= i.discount_pct <= 100):
            raise HTTPException(status_code=400, detail="Desconto % inválido")
        if i.discount_amount is not None and i.discount_amount < 0:
            raise HTTPException(status_code=400, detail="Desconto € inválido")

    cart = [{
        "product_id": i.product_id, "quantity": i.quantity,
        "unit_price": i.unit_price, "vendus_tax_id": i.vendus_tax_id,
        "discount_pct": i.discount_pct, "discount_amount": i.discount_amount,
    } for i in body.items]
    built = build_counter_items(products_by_id, cart, default_tax=VENDUS_DEFAULT_TAX_ID)

    if not built["items"]:
        raise HTTPException(status_code=400, detail="Nada para faturar")

    order_number = await get_next_order_number()
    order_id = str(uuid.uuid4())
    order_doc = {
        "id": order_id,
        "order_number": order_number,
        "table_id": None,
        "table_number": None,
        "items": built["items"],
        "notes": None,
        "total": built["total"],
        "status": "received",
        "paid": False,
        "print_status": "pending",
        "source": "balcao",
        "pos_user_id": operador["id"],
        "cash_session_id": sess["id"] if sess else "legacy",
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    await db.orders.insert_one(order_doc)

    await _enqueue_order_prints(order_id)

    return {
        "order_id": order_id,
        "order_number": order_number,
        "items": built["items"],
        "total": built["total"],
    }


@api_router.post("/pos/counter/{order_id}/cancel")
async def cancel_counter_order(
    order_id: str,
    authorization: Optional[str] = Header(None),
    x_device_token: Optional[str] = Header(None),
):
    """Cancela um pedido de balcão ainda NÃO faturado (cliente desistiu, erro do
    operador) — marca `status=cancelled` para o operador poder sair do balcão
    sem deixar um pedido pendente sem documento fiscal. Um pedido JÁ pago NÃO
    pode ser cancelado (tem FS emitida). Auth-duplo (admin JWT ou device token
    POS)."""
    await get_pos_or_admin(authorization, x_device_token)
    order = await db.orders.find_one({"id": order_id, "source": "balcao"}, {"_id": 0})
    if not order:
        raise HTTPException(status_code=404, detail="Pedido de balcão não encontrado")
    if order.get("paid"):
        raise HTTPException(status_code=400, detail="Pedido já faturado — não pode ser cancelado")
    await db.orders.update_one({"id": order_id}, {"$set": {"status": "cancelled"}})
    return {"ok": True, "order_id": order_id, "cancelled": True}


class CounterCheckoutRequest(BaseModel):
    order_id: str
    payment_method_id: int
    nif: Optional[str] = None


@api_router.post("/pos/counter/checkout")
async def checkout_counter_order(
    body: CounterCheckoutRequest,
    authorization: Optional[str] = Header(None),
    x_device_token: Optional[str] = Header(None),
    x_pos_token: Optional[str] = Header(None),
):
    """Fatura um pedido de balcão: emite UMA Fatura Simplificada (FS) no Vendus
    com os itens do pedido, regista a venda POS (fecho Z + reconciliação),
    imprime o recibo (ESC/POS do Vendus) na caixa e marca o pedido pago.

    FISCAL-CRÍTICO — nunca emite uma 2ª FS para o mesmo pedido. Três camadas
    combinam-se para o garantir:
      1. `paid`-guard: pedido já pago → devolve o documento guardado, sem emitir.
      2. ext_ref ESTÁVEL (`balcao-{order_id}`) + dedup no Vendus antes de emitir:
         cobre a janela entre a emissão e o `paid=True` (crash/retry) — um retry
         encontra a FS já emitida e reutiliza-a.
      3. índice único em `pos_sales.vendus_document_id`: absorve retries do
         registo da venda.

    Auth-duplo para entrar (admin JWT ou device token POS); o OPERADOR vem
    SEMPRE do token POS (`get_pos_operator`), nunca do corpo — responsabilização
    não-falsificável (§2.6). A sessão de caixa é resolvida no SERVIDOR."""
    auth = await get_pos_or_admin(authorization, x_device_token)
    operador = await get_pos_operator(x_pos_token)
    pos_user_id = operador["id"]

    # Sessão de caixa resolvida no SERVIDOR (nunca do corpo). Sem sessão aberta e
    # definições a exigir caixa, recusa ANTES de faturar — não se emite FS sem
    # caixa aberta (mesmo mecanismo de `close_table`/`create_counter_order`).
    sess = await db.cash_sessions.find_one({"status": "open"})
    if auth.get("kind") == "pos":
        pos_cfg = await _pos_settings_config()
        if pos_cfg.get("require_open_cash", True) and not sess:
            raise HTTPException(status_code=409, detail="Abra a caixa primeiro")

    # Carrega o pedido de balcão (só balcão; mesas/QR fecham por `close_table`).
    order = await db.orders.find_one({"id": body.order_id, "source": "balcao"}, {"_id": 0})
    if not order:
        raise HTTPException(status_code=404, detail="Pedido de balcão não encontrado")

    # CANCELADO-GUARD: um pedido cancelado (operador desistiu) NUNCA pode ser
    # faturado — fecha a janela de corrida entre "Cancelar venda" e "Emitir
    # Documento" (o cancel só marca status, não `paid`).
    if order.get("status") == "cancelled":
        raise HTTPException(status_code=400, detail="Pedido cancelado — não pode ser faturado")

    # PAID-GUARD (proteção nº1): pedido já pago → devolve o documento guardado,
    # IDEMPOTENTE, sem re-emitir. É o caso comum de um duplo-clique/refresh depois
    # de faturar com sucesso.
    if order.get("paid"):
        return {
            "doc_number": order.get("vendus_document_number"),
            "total": round(float(order.get("total", 0) or 0), 2),
            "already_paid": True,
        }

    # Itens Vendus a partir dos itens do pedido (formato OrderItem gravado na
    # Task 1). `tax_id` = imposto do item ou o default; título com a variação
    # entre parênteses, tal como `close_table`.
    # Linhas Vendus a partir dos itens do pedido, com os overrides do staff
    # (preço/IVA/desconto do diálogo do balcão) resolvidos pelos MESMOS helpers
    # da mesa — o IVA e o desconto por linha chegam à FS real; o desconto vai
    # como `discount_percentage` (nunca o campo `discount`, que dá 403). Não há
    # desconto GLOBAL no balcão (0). O total pago é a soma dos líquidos das
    # linhas (bate com o `order.total` gravado por `build_counter_items`).
    vendus_items = []
    total = 0.0
    for l in order.get("items", []):
        li = line_vendus(l, None, VENDUS_DEFAULT_TAX_ID)
        out, liquido = combine_global(li, 0)
        vendus_items.append(out)
        total += liquido
    total = round(total, 2)
    if not vendus_items or total <= 0:
        raise HTTPException(status_code=400, detail="Pedido sem itens para faturar")

    ext_ref = counter_ext_ref(body.order_id)
    client = {"fiscal_id": body.nif} if body.nif else None

    # Janela de dedup (Europe/Lisbon): cobre toda a sessão de caixa — não só hoje
    # — para um retry a atravessar a meia-noite ainda encontrar a FS de ontem
    # (midnight-safe, espelha `close_table` e a reconciliação).
    _lisbon = ZoneInfo("Europe/Lisbon")
    _hoje = datetime.now(_lisbon).date()
    if sess and sess.get("opened_at"):
        try:
            _inicio = datetime.fromisoformat(sess["opened_at"]).astimezone(_lisbon).date()
        except Exception:
            _inicio = _hoje - timedelta(days=1)
    else:
        _inicio = _hoje - timedelta(days=1)   # legado (sem caixa): cobre a viragem do dia
    dedup_dates = []
    _d = _inicio
    while _d <= _hoje:
        dedup_dates.append(_d.isoformat())
        _d += timedelta(days=1)

    def _emit():
        c = _vendus_client()
        try:
            # DEDUP FISCAL (proteção nº2): antes de emitir, procura no Vendus um
            # documento com esta external_reference ESTÁVEL. Se existir, um retry
            # do mesmo checkout cai aqui e reutiliza-o, sem 2ª FS. Se a CONSULTA
            # falhar, segue-se a emitir (não bloquear o balcão); o retry protege.
            existente = None
            try:
                for _ds in dedup_dates:
                    for d in c.list_app_invoices(date=_ds):
                        if str(d.get("external_reference") or "") == ext_ref:
                            existente = d
                            break
                    if existente is not None:
                        break
            except VendusError as e:
                logger.warning(f"dedup fiscal balcão: consulta falhou, emito na mesma: {e}")
            if existente is not None:
                logger.warning(
                    f"dedup fiscal balcão: ref {ext_ref} já emitida "
                    f"(doc {existente.get('id')}), reutilizada sem nova FS")
                return existente
            return c.create_invoice(
                items=vendus_items,
                payments=[{"id": body.payment_method_id, "amount": total}],
                client=client, external_reference=ext_ref,
                doc_type="FS", output="escpos")
        finally:
            c.close()

    try:
        doc = await asyncio.to_thread(_emit)
    except VendusError as e:
        raise HTTPException(status_code=502, detail=f"Erro ao faturar no Vendus: {e}")
    if not doc:
        raise HTTPException(status_code=502, detail="Vendus não devolveu documento")

    # Marca o pedido pago com o documento (id + número, para a reconsulta
    # idempotente do paid-guard devolver o número sem chamar o Vendus).
    await db.orders.update_one({"id": body.order_id}, {"$set": {
        "paid": True, "status": "delivered",
        "payment_method": str(body.payment_method_id),
        "vendus_document_id": doc.get("id"),
        "vendus_document_number": doc.get("number"),
    }})

    # Regista a venda POS (fecho Z + reconciliação). SÓ com caixa aberta. A FS JÁ
    # está emitida e válida neste ponto, por isso uma falha aqui NUNCA pode
    # derrubar o checkout (500) — senão o cliente refaturava = cobrança dupla. O
    # índice único em `vendus_document_id` absorve duplicados de um retry
    # (proteção nº3).
    if sess:
        try:
            rows = build_pos_sales_rows(
                [{"amount": total}], [doc], body.payment_method_id,
                sess["id"], pos_user_id, "balcao", None,
            )
            if rows:
                await db.pos_sales.insert_many(rows, ordered=False)
        except (BulkWriteError, DuplicateKeyError) as e:
            logger.warning(f"pos_sales balcão: documento já registado, ignorado (idempotente): {e}")
        except Exception as e:
            logger.error(f"pos_sales balcão: falha a gravar, ignorado (FS já emitida e válida): {e}")

    # Imprime o recibo (ESC/POS certificado do Vendus, com corte) na CAIXA. Um
    # documento reutilizado no dedup pode não trazer `output` — impressão
    # best-effort, como em `close_table`.
    escpos_b64 = doc.get("output")
    if escpos_b64:
        try:
            raw = base64.b64decode(escpos_b64) + b"\n\n\n\x1d\x56\x00"
            escpos_b64 = base64.b64encode(raw).decode("ascii")
        except Exception:
            pass
        await db.print_jobs.insert_one({
            "id": str(uuid.uuid4()),
            "order_id": None,
            "escpos_direct_b64": escpos_b64,
            "printer_id": None,
            "printer_name": "Caixa",
            "printer_type": "cashier",
            "status": "pending",
            "attempts": 0,
            "error": None,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "updated_at": datetime.now(timezone.utc).isoformat(),
        })

    return {"doc_number": doc.get("number"), "total": total}


# ==================== POS: NOTA DE CRÉDITO ====================

@api_router.get("/pos/credit-note/invoices")
async def list_credit_note_invoices(
    authorization: Optional[str] = Header(None),
    x_device_token: Optional[str] = Header(None),
):
    """Lista as faturas recentes (hoje + ontem) da caixa da app que se PODEM
    creditar (FS/FR/FT; exclui NC e RG) — para o operador escolher qual creditar.
    Auth-duplo (admin JWT ou device token POS)."""
    await get_pos_or_admin(authorization, x_device_token)

    def _fetch():
        c = _vendus_client()
        try:
            lisbon = ZoneInfo("Europe/Lisbon")
            hoje = datetime.now(lisbon).date()
            out = []
            for i in range(2):  # hoje + ontem
                out.extend(c.list_creditable(date=(hoje - timedelta(days=i)).isoformat()))
            return out
        finally:
            c.close()
    try:
        invoices = await asyncio.to_thread(_fetch)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Vendus indisponível: {e}")
    # Esconde as faturas que a app já creditou (a reserva marca-as) — assim não
    # reaparecem no picker e o operador não é levado a tentar creditar de novo.
    # As NC feitas à mão no Vendus são apanhadas na emissão (guard related_docs).
    credited = set()
    async for cn in db.credit_notes.find({}, {"_id": 0, "source_document_id": 1}):
        credited.add(cn.get("source_document_id"))
    invoices = [inv for inv in invoices if inv.get("id") not in credited]
    invoices.sort(key=lambda x: (x.get("date", ""), x.get("time", "")), reverse=True)
    return {"invoices": invoices}


class CreditNoteRequest(BaseModel):
    document_id: int


@api_router.post("/pos/credit-note")
async def create_credit_note(
    body: CreditNoteRequest,
    authorization: Optional[str] = Header(None),
    x_device_token: Optional[str] = Header(None),
    x_pos_token: Optional[str] = Header(None),
):
    """Emite uma NOTA DE CRÉDITO TOTAL de uma fatura da caixa da app: cria a NC
    no Vendus (a referenciar a FS pelos itens, `type=NC`), imprime o talão na
    caixa e regista uma venda NEGATIVA (para o Z, a reconciliação e o relatório
    baterem). FISCAL-CRÍTICO — valida que é uma fatura DESTA caixa e que AINDA
    não tem NC (o Vendus liga via `related_docs`), para nunca creditar duas
    vezes. Auth-duplo; o operador vem do token POS; exige caixa aberta."""
    await get_pos_or_admin(authorization, x_device_token)
    operador = await get_pos_operator(x_pos_token)
    pos_user_id = operador["id"]

    # A NC é um estorno que afeta a caixa e o Z — exige SEMPRE uma caixa aberta,
    # para a venda negativa ficar registada na sessão (senão a reconciliação
    # veria uma NC no Vendus sem par nas vendas POS = órfã, e o esperado ficava
    # errado). Vale para admin e operador.
    sess = await db.cash_sessions.find_one({"status": "open"})
    if not sess:
        raise HTTPException(status_code=409, detail="Abra a caixa primeiro")

    # RESERVA ATÓMICA da fatura de origem (índice único em `source_document_id`):
    # serializa duplo-toque/retry concorrentes ANTES de chamar o Vendus, para
    # nunca emitir 2 NC reais à AT para a mesma fatura. Uma falha adiante REMOVE
    # a reserva (não bloqueia tentativas legítimas futuras).
    guard_id = str(uuid.uuid4())
    try:
        await db.credit_notes.insert_one({
            "id": guard_id,
            "source_document_id": body.document_id,
            "status": "pending",
            "pos_user_id": pos_user_id,
            "cash_session_id": sess["id"],
            "created_at": datetime.now(timezone.utc).isoformat(),
        })
    except DuplicateKeyError:
        raise HTTPException(status_code=409, detail="Esta fatura já tem (ou está a emitir) nota de crédito.")

    def _emit():
        c = _vendus_client()
        try:
            fs = c.get_document_detail(body.document_id)
            if fs.get("type") not in ("FS", "FR", "FT"):
                raise HTTPException(status_code=400, detail="Só se pode creditar uma fatura (FS/FR).")
            if c._cfg.register_id is not None and str(fs.get("register_id")) != str(c._cfg.register_id):
                raise HTTPException(status_code=400, detail="Esta fatura não é da caixa da app.")
            for rd in fs.get("related_docs") or []:
                if rd.get("type") == "NC":
                    raise HTTPException(
                        status_code=409,
                        detail=f"Esta fatura já tem nota de crédito ({rd.get('number')}).")
            fs_items = fs.get("items") or []
            items = [{"id": it.get("id"), "qty": it.get("qty")} for it in fs_items]
            # Todos os itens TÊM de ter id (a NC credita a linha original por id);
            # senão o valor creditado não bateria com o total registado.
            if not items or any(it["id"] is None for it in items):
                raise HTTPException(status_code=400, detail="Fatura sem itens válidos para creditar.")
            payments = [{"id": p.get("id"), "amount": round(float(p.get("amount") or 0), 2)}
                        for p in (fs.get("payments") or []) if p.get("id")]
            ext_ref = f"nc-{body.document_id}"
            # DEDUP fiscal (defesa nº2): se JÁ existe uma NC da app com esta ref
            # estável (retry cuja resposta se perdeu depois da NC criada),
            # reutiliza-a em vez de emitir uma 2ª. As NC manuais têm ref vazia, por
            # isso só apanha as da app — exatamente o caso de retry.
            try:
                lisbon = ZoneInfo("Europe/Lisbon")
                hoje = datetime.now(lisbon).date()
                for i in range(3):
                    for d in c.list_app_invoices(date=(hoje - timedelta(days=i)).isoformat()):
                        if d.get("type") == "NC" and str(d.get("external_reference") or "") == ext_ref:
                            return fs, d
            except VendusError:
                pass  # não bloquear — a reserva atómica + related_docs já protegem
            nc = c.create_invoice(items=items, payments=payments, doc_type="NC",
                                  external_reference=ext_ref, output="escpos")
            return fs, nc
        finally:
            c.close()

    try:
        fs, nc = await asyncio.to_thread(_emit)
    except HTTPException:
        await db.credit_notes.delete_one({"id": guard_id})   # rollback: liberta a fatura
        raise
    except VendusError as e:
        await db.credit_notes.delete_one({"id": guard_id})
        raise HTTPException(status_code=502, detail=f"Erro ao emitir a nota de crédito no Vendus: {e}")

    if not nc or not nc.get("id"):
        await db.credit_notes.delete_one({"id": guard_id})
        raise HTTPException(status_code=502, detail="Vendus não devolveu a nota de crédito")

    total = round(float(fs.get("amount_gross") or 0), 2)
    fs_pays = fs.get("payments") or []
    pm_id = fs_pays[0].get("id") if fs_pays else None

    # Marca a reserva como concluída (com a NC emitida).
    await db.credit_notes.update_one({"id": guard_id}, {"$set": {
        "status": "done", "nc_id": nc.get("id"), "nc_number": nc.get("number"),
        "amount": total, "payment_method_id": pm_id,
    }})

    # Venda NEGATIVA (estorno) — para o Z/reconciliação/relatório baterem. A NC
    # JÁ está emitida e válida; uma falha aqui NUNCA a desfaz. O índice único em
    # `vendus_document_id` absorve retries.
    if sess:
        try:
            await db.pos_sales.insert_one({
                "id": str(uuid.uuid4()),
                "cash_session_id": sess["id"],
                "pos_user_id": pos_user_id,
                "vendus_document_id": nc.get("id"),
                "doc_number": nc.get("number"),
                "amount": round(-total, 2),
                "payment_method_id": pm_id,
                "kind": "credit_note",
                "table_number": None,
                "created_at": datetime.now(timezone.utc).isoformat(),
            })
        except (BulkWriteError, DuplicateKeyError) as e:
            logger.warning(f"pos_sales NC: já registada, ignorado (idempotente): {e}")
        except Exception as e:
            logger.error(f"pos_sales NC: falha a gravar, ignorado (NC já emitida): {e}")

    # Imprime o talão da NC (ESC/POS certificado do Vendus, com corte) na caixa.
    escpos_b64 = nc.get("output")
    if escpos_b64:
        try:
            raw = base64.b64decode(escpos_b64) + b"\n\n\n\x1d\x56\x00"
            escpos_b64 = base64.b64encode(raw).decode("ascii")
        except Exception:
            pass
        await db.print_jobs.insert_one({
            "id": str(uuid.uuid4()),
            "order_id": None,
            "escpos_direct_b64": escpos_b64,
            "printer_id": None,
            "printer_name": "Caixa",
            "printer_type": "cashier",
            "status": "pending",
            "attempts": 0,
            "error": None,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "updated_at": datetime.now(timezone.utc).isoformat(),
        })

    return {"ok": True, "nc_number": nc.get("number"), "nc_id": nc.get("id"),
            "credited_total": total, "original_number": fs.get("number")}


@api_router.post("/admin/pos/import-app-products")
async def import_app_products(authorization: Optional[str] = Header(None)):
    """Importa os produtos "App" do Vendus (preços de entrega/delivery, ex.:
    "Pizza Calabresa App") para uma categoria própria "Venda Aplicações",
    para ficarem vendáveis no balcão. Upsert idempotente por
    `vendus_reference` (ou nome, se sem referência) — reutiliza a MESMA
    extração de preço/IVA que `import_menu_from_vendus`
    (`pos.app_products.extract_app_products`). Nunca mexe em produtos que não
    sejam "App"."""
    await get_current_user(authorization)

    def _fetch():
        c = _vendus_client()
        try:
            return c.list_products(per_page=500)
        finally:
            c.close()
    try:
        vprods = await asyncio.to_thread(_fetch)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Vendus indisponível: {e}")

    # Garante a categoria "Venda Aplicações", ativa (reativa-a se já existir
    # mas estivesse desativada) — mesmo mecanismo de `_ensure_category` do
    # `import_menu_from_vendus`, mas por nome fixo em vez de vindo do Vendus.
    existing_cats = await db.categories.find({}, {"_id": 0}).to_list(500)
    by_name = {c["name"].strip().lower(): c for c in existing_cats}
    cat_key = "venda aplicações"
    if cat_key in by_name:
        app_cat_id = by_name[cat_key]["id"]
        # Garante ativa E pos_only (staff-only): estes são preços de delivery,
        # NUNCA podem aparecer no menu do cliente por QR (só no balcão/POS).
        await db.categories.update_one(
            {"id": app_cat_id}, {"$set": {"active": True, "pos_only": True}})
    else:
        app_cat_id = str(uuid.uuid4())
        await db.categories.insert_one({
            "id": app_cat_id, "name": "Venda Aplicações", "order": len(existing_cats),
            "active": True, "available_days": [], "pos_only": True,
            "created_at": datetime.now(timezone.utc).isoformat(),
        })

    imported = 0
    for ap in extract_app_products(vprods):
        ref = ap["vendus_reference"]
        query = {"vendus_reference": ref} if ref else {"name": ap["name"]}
        existing = await db.products.find_one(query, {"_id": 0})
        if existing:
            await db.products.update_one({"id": existing["id"]}, {"$set": {
                "name": ap["name"], "base_price": ap["base_price"],
                "category_id": app_cat_id, "vendus_tax_id": ap["vendus_tax_id"],
                "vendus_reference": ref, "available": True, "rodizio_only": False,
            }})
        else:
            await db.products.insert_one({
                "id": str(uuid.uuid4()), "name": ap["name"], "description": "",
                "category_id": app_cat_id, "base_price": ap["base_price"], "image_url": None,
                "variations": [], "extras": [], "complement_groups": [],
                "preference_options": None, "available": True, "featured": False,
                "rodizio_only": False, "vendus_tax_id": ap["vendus_tax_id"], "vendus_reference": ref,
                "created_at": datetime.now(timezone.utc).isoformat(),
            })
        imported += 1

    return {"imported": imported, "category_id": app_cat_id}

# ==================== DASHBOARD ROUTES ====================

@api_router.get("/dashboard/stats", response_model=DashboardStats)
async def get_dashboard_stats(authorization: Optional[str] = Header(None)):
    await get_current_user(authorization)
    
    today_start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    
    # Orders today
    orders_today = await db.orders.find(
        {"created_at": {"$gte": today_start.isoformat()}},
        {"_id": 0}
    ).to_list(1000)
    
    total_orders = len(orders_today)
    total_revenue = sum(o.get("total", 0) for o in orders_today)
    
    # Orders by status
    status_counts = {}
    for order in orders_today:
        status = order.get("status", "unknown")
        status_counts[status] = status_counts.get(status, 0) + 1
    
    # Orders by table
    table_counts = {}
    for order in orders_today:
        table = order.get("table_number", 0)
        if table not in table_counts:
            table_counts[table] = {"table_number": table, "count": 0, "total": 0}
        table_counts[table]["count"] += 1
        table_counts[table]["total"] += order.get("total", 0)
    
    return DashboardStats(
        total_orders_today=total_orders,
        total_revenue_today=total_revenue,
        orders_by_status=status_counts,
        orders_by_table=list(table_counts.values())
    )

# ==================== SEED DATA ====================

@api_router.post("/seed")
async def seed_database(authorization: Optional[str] = Header(None)):
    """Seed database with sample data (apenas admin autenticado)."""
    await get_current_user(authorization)

    # Check if already seeded
    existing_cats = await db.categories.count_documents({})
    if existing_cats > 0:
        return {"message": "Base de dados já contém dados"}
    
    # Create categories
    categories = [
        {"id": str(uuid.uuid4()), "name": "Pizzas", "order": 1, "active": True, "created_at": datetime.now(timezone.utc).isoformat()},
        {"id": str(uuid.uuid4()), "name": "Bebidas", "order": 2, "active": True, "created_at": datetime.now(timezone.utc).isoformat()},
        {"id": str(uuid.uuid4()), "name": "Entradas", "order": 3, "active": True, "created_at": datetime.now(timezone.utc).isoformat()},
        {"id": str(uuid.uuid4()), "name": "Sobremesas", "order": 4, "active": True, "created_at": datetime.now(timezone.utc).isoformat()},
    ]
    await db.categories.insert_many(categories)
    
    pizza_cat_id = categories[0]["id"]
    drinks_cat_id = categories[1]["id"]
    starters_cat_id = categories[2]["id"]
    desserts_cat_id = categories[3]["id"]
    
    # Create products
    products = [
        {
            "id": str(uuid.uuid4()),
            "name": "Margherita",
            "description": "Molho de tomate, mozzarella fresca, manjericão e azeite virgem extra",
            "category_id": pizza_cat_id,
            "base_price": 9.50,
            "image_url": "https://images.unsplash.com/photo-1574071318508-1cdbab80d002?w=800",
            "variations": [{"name": "Pequena", "price": 7.50}, {"name": "Média", "price": 9.50}, {"name": "Grande", "price": 12.50}],
            "extras": [{"name": "Borda recheada", "price": 2.00}, {"name": "Extra queijo", "price": 1.50}],
            "available": True,
            "featured": True,
            "created_at": datetime.now(timezone.utc).isoformat()
        },
        {
            "id": str(uuid.uuid4()),
            "name": "Pepperoni",
            "description": "Molho de tomate, mozzarella e pepperoni picante",
            "category_id": pizza_cat_id,
            "base_price": 11.00,
            "image_url": "https://images.unsplash.com/photo-1621510564330-c87695020b53?w=800",
            "variations": [{"name": "Pequena", "price": 9.00}, {"name": "Média", "price": 11.00}, {"name": "Grande", "price": 14.00}],
            "extras": [{"name": "Borda recheada", "price": 2.00}, {"name": "Extra pepperoni", "price": 2.00}],
            "available": True,
            "featured": True,
            "created_at": datetime.now(timezone.utc).isoformat()
        },
        {
            "id": str(uuid.uuid4()),
            "name": "Quatro Queijos",
            "description": "Mozzarella, gorgonzola, parmesão e provolone",
            "category_id": pizza_cat_id,
            "base_price": 12.50,
            "image_url": "https://images.unsplash.com/photo-1513104890138-7c749659a591?w=800",
            "variations": [{"name": "Pequena", "price": 10.50}, {"name": "Média", "price": 12.50}, {"name": "Grande", "price": 15.50}],
            "extras": [{"name": "Borda recheada", "price": 2.00}, {"name": "Mel", "price": 1.00}],
            "available": True,
            "featured": False,
            "created_at": datetime.now(timezone.utc).isoformat()
        },
        {
            "id": str(uuid.uuid4()),
            "name": "Vegetariana",
            "description": "Molho de tomate, mozzarella, pimentos, cogumelos, cebola e azeitonas",
            "category_id": pizza_cat_id,
            "base_price": 10.50,
            "image_url": "https://images.unsplash.com/photo-1511689660979-10d2b1aada49?w=800",
            "variations": [{"name": "Pequena", "price": 8.50}, {"name": "Média", "price": 10.50}, {"name": "Grande", "price": 13.50}],
            "extras": [{"name": "Borda recheada", "price": 2.00}, {"name": "Extra cogumelos", "price": 1.50}],
            "available": True,
            "featured": False,
            "created_at": datetime.now(timezone.utc).isoformat()
        },
        {
            "id": str(uuid.uuid4()),
            "name": "Coca-Cola",
            "description": "Refrigerante 330ml",
            "category_id": drinks_cat_id,
            "base_price": 2.50,
            "image_url": "https://images.unsplash.com/photo-1554866585-cd94860890b7?w=800",
            "variations": [],
            "extras": [],
            "available": True,
            "featured": False,
            "created_at": datetime.now(timezone.utc).isoformat()
        },
        {
            "id": str(uuid.uuid4()),
            "name": "Água Mineral",
            "description": "Água mineral natural 500ml",
            "category_id": drinks_cat_id,
            "base_price": 1.50,
            "image_url": "https://images.unsplash.com/photo-1559839914-17aae19cec71?w=800",
            "variations": [{"name": "Com gás", "price": 1.50}, {"name": "Sem gás", "price": 1.50}],
            "extras": [],
            "available": True,
            "featured": False,
            "created_at": datetime.now(timezone.utc).isoformat()
        },
        {
            "id": str(uuid.uuid4()),
            "name": "Vinho da Casa",
            "description": "Taça de vinho tinto ou branco da região",
            "category_id": drinks_cat_id,
            "base_price": 4.50,
            "image_url": "https://images.unsplash.com/photo-1649695121711-2f2ea8e8faf4?w=800",
            "variations": [{"name": "Tinto", "price": 4.50}, {"name": "Branco", "price": 4.50}],
            "extras": [],
            "available": True,
            "featured": False,
            "created_at": datetime.now(timezone.utc).isoformat()
        },
        {
            "id": str(uuid.uuid4()),
            "name": "Bruschetta",
            "description": "Pão italiano torrado com tomate, alho e manjericão fresco",
            "category_id": starters_cat_id,
            "base_price": 5.50,
            "image_url": "https://images.unsplash.com/photo-1626634896715-88334e9da24f?w=800",
            "variations": [],
            "extras": [{"name": "Extra queijo parmesão", "price": 1.00}],
            "available": True,
            "featured": False,
            "created_at": datetime.now(timezone.utc).isoformat()
        },
        {
            "id": str(uuid.uuid4()),
            "name": "Pão de Alho",
            "description": "Pão artesanal com manteiga de alho e ervas",
            "category_id": starters_cat_id,
            "base_price": 4.00,
            "image_url": "https://images.unsplash.com/photo-1619535860434-ba1d8fa12536?w=800",
            "variations": [],
            "extras": [{"name": "Com queijo", "price": 1.50}],
            "available": True,
            "featured": False,
            "created_at": datetime.now(timezone.utc).isoformat()
        },
        {
            "id": str(uuid.uuid4()),
            "name": "Tiramisù",
            "description": "Clássico italiano com café, mascarpone e cacau",
            "category_id": desserts_cat_id,
            "base_price": 6.00,
            "image_url": "https://images.unsplash.com/photo-1569153421157-7f8fc8a4badc?w=800",
            "variations": [],
            "extras": [],
            "available": True,
            "featured": True,
            "created_at": datetime.now(timezone.utc).isoformat()
        },
        {
            "id": str(uuid.uuid4()),
            "name": "Panna Cotta",
            "description": "Creme italiano com frutos vermelhos",
            "category_id": desserts_cat_id,
            "base_price": 5.50,
            "image_url": "https://images.unsplash.com/photo-1488477181946-6428a0291777?w=800",
            "variations": [],
            "extras": [],
            "available": True,
            "featured": False,
            "created_at": datetime.now(timezone.utc).isoformat()
        }
    ]
    await db.products.insert_many(products)
    
    # Create tables
    tables = [
        {"id": str(uuid.uuid4()), "number": i, "name": f"Mesa {i}", "active": True, "created_at": datetime.now(timezone.utc).isoformat()}
        for i in range(1, 11)
    ]
    await db.tables.insert_many(tables)
    
    # Create default admin user
    admin_id = str(uuid.uuid4())
    admin = {
        "id": admin_id,
        "email": "admin@pizzaria.pt",
        "password": hash_password("admin123"),
        "name": "Administrador",
        "created_at": datetime.now(timezone.utc).isoformat()
    }
    await db.admin_users.insert_one(admin)
    
    # Create default printer
    printer_id = str(uuid.uuid4())
    printer = {
        "id": printer_id,
        "name": "Cozinha",
        "ip": "192.168.1.100",
        "port": 9100,
        "width": 80,
        "cut_paper": True,
        "active": False,  # Inactive by default until configured
        "created_at": datetime.now(timezone.utc).isoformat()
    }
    await db.printers.insert_one(printer)
    
    # Generate print agent API key
    api_key = secrets.token_urlsafe(32)
    await db.settings.update_one(
        {"key": "print_agent"},
        {"$set": {
            "key": "print_agent",
            "value": {
                "api_key": api_key,
                "created_at": datetime.now(timezone.utc).isoformat()
            }
        }},
        upsert=True
    )
    
    # Set restaurant name
    await db.settings.update_one(
        {"key": "restaurant"},
        {"$set": {"key": "restaurant", "value": {"name": "Pizzaria"}}},
        upsert=True
    )
    
    return {
        "message": "Base de dados inicializada com sucesso",
        "data": {
            "categories": len(categories),
            "products": len(products),
            "tables": len(tables)
        }
    }

# ==================== REPORT DATA & EMAIL ROUTES ====================

from scheduler import send_daily_report, resolve_resend_config, RESEND_API_KEY, REPORT_EMAIL

class SendReportRequest(BaseModel):
    date: Optional[str] = None  # ISO date string e.g. "2025-07-04"

class ResendConfigRequest(BaseModel):
    api_key: Optional[str] = None      # chave do Resend (re_...); vazio = manter a atual
    report_email: Optional[str] = None # destinatário do relatório
    sender_email: Optional[str] = None # remetente (default onboarding@resend.dev)

@api_router.get("/admin/report-data")
async def get_report_data(date: Optional[str] = None, authorization: Optional[str] = Header(None)):
    """
    Get comprehensive report data for a given date.
    If no date provided, uses today.
    """
    await get_current_user(authorization)
    
    from zoneinfo import ZoneInfo
    lisbon_tz = ZoneInfo('Europe/Lisbon')
    
    if date:
        try:
            target_date = datetime.fromisoformat(date).replace(tzinfo=lisbon_tz)
        except:
            target_date = datetime.now(lisbon_tz)
    else:
        target_date = datetime.now(lisbon_tz)
    
    # Calculate day range in UTC
    start_of_day = target_date.replace(hour=0, minute=0, second=0, microsecond=0)
    end_of_day = target_date.replace(hour=23, minute=59, second=59, microsecond=999999)
    start_utc = start_of_day.astimezone(timezone.utc).isoformat()
    end_utc = end_of_day.astimezone(timezone.utc).isoformat()
    
    # Fetch orders for the day
    query = {
        "created_at": {"$gte": start_utc, "$lte": end_utc}
    }
    orders = await db.orders.find(query, {"_id": 0}).sort("created_at", 1).to_list(1000)
    
    # Basic stats
    total_orders = len(orders)
    non_cancelled = [o for o in orders if o.get("status") != "cancelled"]
    cancelled_orders = total_orders - len(non_cancelled)
    delivered_orders = len([o for o in orders if o.get("status") == "delivered"])
    
    paid_orders = len([o for o in non_cancelled if o.get("paid", False)])
    unpaid_orders = len(non_cancelled) - paid_orders

    # Receita REAL: lida das faturas do Vendus (caixa da app), não do `total` dos
    # pedidos. No rodízio os itens estão a €0 e o valor por pessoa só é cobrado no
    # fecho; os descontos também não ficam no pedido. A fonte de verdade é o Vendus.
    total_revenue = 0.0
    avg_ticket = 0.0
    invoices_count = 0
    payment_methods = {}
    revenue_source = "vendus"
    revenue_error = None
    try:
        c = _vendus_client()
        try:
            _summ = c.app_sales_summary(target_date.strftime("%Y-%m-%d"))
        finally:
            c.close()
        total_revenue = _summ["total"]
        payment_methods = _summ["by_method"]
        invoices_count = _summ["count"]
        avg_ticket = (total_revenue / invoices_count) if invoices_count else 0.0
    except Exception as e:
        revenue_source = "erro"
        revenue_error = str(e)[:200]
        logger.error(f"report-data: falha ao obter vendas do Vendus: {revenue_error}")
    
    # Top products
    product_counts = {}
    for o in non_cancelled:
        for item in o.get("items", []):
            name = item.get("product_name", "Desconhecido")
            qty = item.get("quantity", 1)
            if name not in product_counts:
                product_counts[name] = 0
            product_counts[name] += qty
    
    top_products = sorted(
        [{"name": k, "quantity": v} for k, v in product_counts.items()],
        key=lambda x: x["quantity"],
        reverse=True
    )[:15]
    
    # Peak hours
    hours_count = {}
    for o in non_cancelled:
        created_at = o.get("created_at", "")
        try:
            dt = datetime.fromisoformat(created_at.replace('Z', '+00:00'))
            # Convert to Lisbon time
            dt_local = dt.astimezone(lisbon_tz)
            hour = dt_local.hour
            if hour not in hours_count:
                hours_count[hour] = 0
            hours_count[hour] += 1
        except:
            pass
    
    peak_hours = [
        {"hour": h, "label": f"{h:02d}:00", "orders": hours_count.get(h, 0)}
        for h in range(8, 24)
    ]
    
    return {
        "date": target_date.strftime("%Y-%m-%d"),
        "date_formatted": target_date.strftime("%d/%m/%Y"),
        "summary": {
            "total_orders": total_orders,
            "total_revenue": round(total_revenue, 2),
            "avg_ticket": round(avg_ticket, 2),
            "invoices_count": invoices_count,
            "revenue_source": revenue_source,
            "revenue_error": revenue_error,
            "cancelled_orders": cancelled_orders,
            "delivered_orders": delivered_orders,
            "paid_orders": paid_orders,
            "unpaid_orders": unpaid_orders
        },
        "payment_methods": payment_methods,
        "top_products": top_products,
        "peak_hours": peak_hours
    }

@api_router.post("/admin/send-daily-report")
async def send_report_by_email(request: SendReportRequest, authorization: Optional[str] = Header(None)):
    """Send daily report by email for a specific date"""
    await get_current_user(authorization)
    
    if not RESEND_API_KEY:
        raise HTTPException(status_code=400, detail="API Key do Resend não configurada. Configure RESEND_API_KEY no .env")
    
    if not REPORT_EMAIL:
        raise HTTPException(status_code=400, detail="Email de destino não configurado. Configure REPORT_EMAIL no .env")
    
    from zoneinfo import ZoneInfo
    lisbon_tz = ZoneInfo('Europe/Lisbon')
    
    target_date = None
    if request.date:
        try:
            target_date = datetime.fromisoformat(request.date).replace(tzinfo=lisbon_tz)
        except:
            target_date = None
    
    logger.info(f"Envio de relatório solicitado para data: {request.date or 'hoje'}")
    
    result = await send_daily_report(db, date=target_date)
    
    if result.get("success"):
        return {
            "success": True,
            "message": f"Relatório enviado com sucesso para {REPORT_EMAIL}",
            "email_id": result.get("email_id"),
            "report_date": result.get("report_date")
        }
    else:
        raise HTTPException(
            status_code=500,
            detail=result.get("error", "Erro desconhecido ao enviar relatório")
        )

# ==================== DAILY REPORT ROUTES (Legacy) ====================

class TestReportResponse(BaseModel):
    success: bool
    message: str
    email_id: Optional[str] = None
    report_date: Optional[str] = None
    stats: Optional[dict] = None
    orders_count: Optional[int] = None
    error: Optional[str] = None

class SchedulerStatusResponse(BaseModel):
    enabled: bool
    next_run: Optional[str] = None
    timezone: str = "Europe/Lisbon"
    schedule: str = "00:00"

@api_router.post("/admin/test-daily-report", response_model=TestReportResponse)
async def test_daily_report(authorization: Optional[str] = Header(None)):
    """
    Endpoint manual para testar o envio do relatório diário.
    Gera o relatório do dia atual e envia para o REPORT_EMAIL.
    """
    await get_current_user(authorization)
    
    # Verificar configuração
    if not RESEND_API_KEY:
        return TestReportResponse(
            success=False,
            message="API Key do Resend não configurada",
            error="Configure a variável RESEND_API_KEY no ficheiro .env"
        )
    
    if not REPORT_EMAIL:
        return TestReportResponse(
            success=False,
            message="Email de destino não configurado",
            error="Configure a variável REPORT_EMAIL no ficheiro .env"
        )
    
    logger.info(f"Teste de relatório diário solicitado. Enviando para {REPORT_EMAIL}")
    
    # Executar envio do relatório
    result = await send_daily_report(db)
    
    if result.get("success"):
        return TestReportResponse(
            success=True,
            message=f"Relatório enviado com sucesso para {REPORT_EMAIL}",
            email_id=result.get("email_id"),
            report_date=result.get("report_date"),
            stats=result.get("stats"),
            orders_count=result.get("orders_count")
        )
    else:
        return TestReportResponse(
            success=False,
            message="Falha ao enviar relatório",
            error=result.get("error")
        )

@api_router.get("/admin/report-config")
async def get_report_config(authorization: Optional[str] = Header(None)):
    """Retorna a configuração atual do sistema de relatórios (ambiente ou BD)"""
    await get_current_user(authorization)
    rcfg = await resolve_resend_config(db)
    return {
        "resend_configured": bool(rcfg["api_key"]),
        "report_email": rcfg["report_email"] or "",
        "sender_email": rcfg["sender_email"],
        "source": "env" if RESEND_API_KEY else ("db" if rcfg["api_key"] else "none"),
        "scheduler_enabled": SCHEDULER_ENABLED,
        "timezone": "Europe/Lisbon",
        "schedule_time": "00:00"
    }

@api_router.post("/admin/resend-config")
async def save_resend_config(request: ResendConfigRequest, authorization: Optional[str] = Header(None)):
    """Guarda a config do Resend na BD (para configurar sem mexer no .env do
    servidor). A chave só é gravada se vier preenchida; senão mantém a atual."""
    await get_current_user(authorization)

    doc = await db.settings.find_one({"key": "resend_config"}, {"_id": 0})
    current = (doc or {}).get("value", {}) or {}

    new_key = (request.api_key or "").strip()
    value = {
        "api_key": new_key or current.get("api_key", ""),
        "report_email": (request.report_email or current.get("report_email", "")).strip(),
        "sender_email": (request.sender_email or current.get("sender_email", "")).strip(),
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    await db.settings.update_one(
        {"key": "resend_config"},
        {"$set": {"key": "resend_config", "value": value}},
        upsert=True,
    )

    rcfg = await resolve_resend_config(db)
    return {
        "message": "Configuração guardada",
        "resend_configured": bool(rcfg["api_key"]),
        "report_email": rcfg["report_email"],
        "sender_email": rcfg["sender_email"],
    }

@api_router.post("/admin/scheduler/enable")
async def enable_scheduler(authorization: Optional[str] = Header(None)):
    """Ativa o scheduler de relatórios diários"""
    global SCHEDULER_ENABLED
    await get_current_user(authorization)

    rcfg = await resolve_resend_config(db)
    if not rcfg["api_key"] or not rcfg["report_email"]:
        raise HTTPException(
            status_code=400,
            detail="Configure a chave do Resend e o email de destino antes de ativar o envio automático"
        )
    
    SCHEDULER_ENABLED = True
    
    # Adicionar job se não existir
    if not scheduler.get_job('daily_report'):
        scheduler.add_job(
            run_scheduled_report,
            CronTrigger(hour=23, minute=30, timezone='Europe/Lisbon'),
            id='daily_report',
            name='Daily Report Email',
            replace_existing=True
        )
        logger.info("Job de relatório diário adicionado ao scheduler")
    
    if not scheduler.running:
        scheduler.start()
        logger.info("Scheduler iniciado")
    
    # Guardar configuração no banco
    await db.settings.update_one(
        {"key": "scheduler_config"},
        {"$set": {
            "key": "scheduler_config",
            "value": {"enabled": True, "updated_at": datetime.now(timezone.utc).isoformat()}
        }},
        upsert=True
    )
    
    return {"message": "Scheduler ativado com sucesso", "enabled": True}

@api_router.post("/admin/scheduler/disable")
async def disable_scheduler(authorization: Optional[str] = Header(None)):
    """Desativa o scheduler de relatórios diários"""
    global SCHEDULER_ENABLED
    await get_current_user(authorization)
    
    SCHEDULER_ENABLED = False
    
    # Remover job
    if scheduler.get_job('daily_report'):
        scheduler.remove_job('daily_report')
        logger.info("Job de relatório diário removido")
    
    # Guardar configuração no banco
    await db.settings.update_one(
        {"key": "scheduler_config"},
        {"$set": {
            "key": "scheduler_config",
            "value": {"enabled": False, "updated_at": datetime.now(timezone.utc).isoformat()}
        }},
        upsert=True
    )
    
    return {"message": "Scheduler desativado", "enabled": False}

@api_router.get("/admin/scheduler/status", response_model=SchedulerStatusResponse)
async def get_scheduler_status(authorization: Optional[str] = Header(None)):
    """Retorna o estado atual do scheduler"""
    await get_current_user(authorization)
    
    next_run = None
    job = scheduler.get_job('daily_report')
    if job and job.next_run_time:
        next_run = job.next_run_time.isoformat()
    
    return SchedulerStatusResponse(
        enabled=SCHEDULER_ENABLED,
        next_run=next_run,
        timezone="Europe/Lisbon",
        schedule="00:00"
    )

@api_router.get("/admin/report-logs")
async def get_report_logs(
    limit: int = Query(default=20, le=100),
    authorization: Optional[str] = Header(None)
):
    """Retorna histórico de envios de relatórios"""
    await get_current_user(authorization)
    
    logs = await db.report_logs.find(
        {},
        {"_id": 0}
    ).sort("timestamp", -1).to_list(limit)
    
    return logs

async def run_scheduled_report():
    """Função executada pelo scheduler à 00:00 — envia o relatório do DIA QUE
    ACABOU (ontem), para o dia sair COMPLETO (à meia-noite "hoje" já é o dia
    seguinte, que estaria vazio)."""
    logger.info("Executando relatório diário agendado...")
    try:
        ontem = datetime.now(ZoneInfo('Europe/Lisbon')) - timedelta(days=1)
        result = await send_daily_report(db, date=ontem)
        if result.get("success"):
            logger.info(f"Relatório diário enviado com sucesso: {result}")
        else:
            logger.error(f"Falha no relatório diário: {result.get('error')}")
    except Exception as e:
        logger.error(f"Erro ao executar relatório agendado: {e}")

# Include router
app.include_router(api_router)

# CORS
# Origens permitidas via CORS_ORIGINS (lista separada por vírgulas).
# Sem CORS_ORIGINS definido NÃO usamos wildcard: em produção o operador deve
# configurar a origem; em dev caímos para o frontend local.
_raw_cors = os.environ.get('CORS_ORIGINS')
if _raw_cors:
    _cors_origins = [o.strip() for o in _raw_cors.split(',') if o.strip()]
else:
    logger.warning(
        "CORS_ORIGINS não definido — a usar fallback de desenvolvimento "
        "(http://localhost:3000). Defina CORS_ORIGINS em produção."
    )
    _cors_origins = ["http://localhost:3000"]
# Com wildcard "*" não é possível usar credenciais (regra dos browsers).
_allow_credentials = _cors_origins != ['*']
app.add_middleware(
    CORSMiddleware,
    allow_credentials=_allow_credentials,
    allow_origins=_cors_origins,
    allow_methods=["*"],
    allow_headers=["*"],
)


# O arranque/encerramento é tratado pelo `lifespan` definido no topo do ficheiro.


if __name__ == "__main__":
    # Execução local: python server.py
    import uvicorn
    port = int(os.environ.get("PORT", 8001))
    uvicorn.run("server:app", host="0.0.0.0", port=port, reload=False)
