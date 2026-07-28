from fastapi import FastAPI, APIRouter, HTTPException, Depends, UploadFile, File, Query, BackgroundTasks, Header
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
from datetime import datetime, timezone
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
from vendus import VendusConfig, VendusClient, VendusError

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
                    CronTrigger(hour=23, minute=30, timezone='Europe/Lisbon'),
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

class CategoryUpdate(BaseModel):
    name: Optional[str] = None
    order: Optional[int] = None
    active: Optional[bool] = None
    available_days: Optional[List[int]] = None

class CategoryResponse(BaseModel):
    id: str
    name: str
    order: int
    active: bool
    available_days: List[int] = []
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
    table_id: str
    table_number: int
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
        
        # Table number - BIG
        data.extend(self.DOUBLE_SIZE)
        data.extend(self._text(f"MESA: {order['table_number']}\n"))
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
        
        # Table
        data.extend(self.BOLD_ON)
        data.extend(self._text(f"MESA: {order['table_number']}\n"))
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
async def void_order_item(order_id: str, idx: int, authorization: Optional[str] = Header(None)):
    """Remove um item da conta da mesa SEM faturar (adicionado por engano pelo
    staff ou pelo cliente). Soft-void: marca items.{idx}.removed=True (mantém
    rasto). Um item já faturado não pode ser removido. Devolve um dict simples
    (não o OrderResponse, que era frágil com orders antigas sem todos os campos)."""
    await get_current_user(authorization)
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


class ItemDiscount(BaseModel):
    pct: float = 0  # 0..100


@api_router.post("/orders/{order_id}/items/{idx}/discount")
async def set_item_discount(order_id: str, idx: int, body: ItemDiscount,
                            authorization: Optional[str] = Header(None)):
    """Define um desconto (%) num item da mesa. Fica gravado no item e reflete-se
    na conta, na consulta e na fatura (enviado ao Vendus como discount_percentage)."""
    await get_current_user(authorization)
    pct = max(0.0, min(100.0, float(body.pct or 0)))
    order = await db.orders.find_one({"id": order_id}, {"_id": 0, "items": 1})
    if not order:
        raise HTTPException(status_code=404, detail="Pedido não encontrado")
    items = order.get("items", [])
    if idx < 0 or idx >= len(items):
        raise HTTPException(status_code=404, detail="Item não encontrado")
    if items[idx].get("paid"):
        raise HTTPException(status_code=400, detail="Item já faturado")
    await db.orders.update_one({"id": order_id}, {"$set": {f"items.{idx}.discount_pct": pct}})
    return {"ok": True, "order_id": order_id, "idx": idx, "discount_pct": pct}

# ==================== VENDUS: FECHO DE MESA ====================

VENDUS_DEFAULT_TAX_ID = os.environ.get("VENDUS_DEFAULT_TAX_ID", "NOR")


def _vendus_client() -> VendusClient:
    return VendusClient(VendusConfig.load(os.environ))


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
            gross = round(float(it.get("total_price", 0) or 0), 2)
            net = round(gross * (1 - dpct / 100.0), 2)
            lines.append({
                "order_id": o["id"], "idx": idx,
                "product_id": it.get("product_id"),
                "product_name": it.get("product_name"),
                "quantity": it.get("quantity", 1),
                "unit_price": it.get("unit_price", 0),
                "total_price": net,          # já com o desconto do item aplicado
                "gross_total": gross,        # antes do desconto
                "discount_pct": dpct,
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
async def get_table_bill(table_number: int, authorization: Optional[str] = Header(None)):
    """Conta em aberto da mesa (linhas por faturar, item a item)."""
    await get_current_user(authorization)
    lines = await _open_bill_lines(table_number)
    total = round(sum((l.get("total_price", 0) or 0) for l in lines), 2)
    n_orders = len({l["order_id"] for l in lines})
    return {"table_number": table_number, "orders": n_orders,
            "lines": lines, "total": total}


@api_router.get("/tables-overview")
async def tables_overview(authorization: Optional[str] = Header(None)):
    """Resumo de TODAS as mesas com a respetiva conta em aberto — para a grelha
    de mesas (uma só chamada)."""
    await get_current_user(authorization)
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
async def vendus_payment_methods(authorization: Optional[str] = Header(None)):
    """Métodos de pagamento do Vendus (para o ecrã de fecho)."""
    await get_current_user(authorization)

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
                      authorization: Optional[str] = Header(None)):
    """Fecha a mesa: emite a Fatura Simplificada (FS) no Vendus com os itens da
    conta e o pagamento, imprime-a na caixa (ESC/POS do Vendus) e marca os
    pedidos como pagos."""
    await get_current_user(authorization)
    all_lines = await _open_bill_lines(table_number)
    if not all_lines and not req.rodizio_tier:
        raise HTTPException(status_code=400, detail="Mesa sem conta em aberto")

    ts = datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')
    rodizio_pay = None  # {adults, children, waste} faturado agora (rodízio parcial)

    # Desconto GLOBAL (%) sobre toda a fatura; combina com o desconto por item.
    g_disc = max(0.0, min(100.0, float(req.global_discount_pct or 0)))
    def _eff_disc(item_pct):
        return round(100.0 * (1 - (1 - (float(item_pct or 0)) / 100.0) * (1 - g_disc / 100.0)), 4)

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

        def _add(title, qty, gross, tax, item_pct=0):
            eff = _eff_disc(item_pct)
            li = {"title": title, "qty": qty, "gross_price": gross, "tax_id": tax}
            if eff > 0:
                li["discount_percentage"] = eff
            vendus_items.append(li)
            return round(gross * qty * (1 - eff / 100.0), 2)

        if pay_adults > 0:
            total += _add(f"{tier['name']} (adulto)", pay_adults, price, rtax)
        if pay_half > 0:
            total += _add(f"{tier['name']} (criança)", pay_half, half, rtax)
        for l in extra_lines:
            qty = l.get("quantity", 1) or 1
            unit = round(float(l.get("unit_price", 0) or 0), 2)
            tax = tax_by_prod.get(l.get("product_id"), VENDUS_DEFAULT_TAX_ID)
            title = l.get("product_name", "Item")
            var = l.get("variation") or {}
            if isinstance(var, dict) and var.get("name"):
                title = f"{title} ({var['name']})"
            total += _add(title, qty, unit, tax, l.get("discount_pct", 0))
        if req.waste_boxes and req.waste_boxes > 0:
            wfee = round(float(cfg.get("waste_fee", 5.0)), 2)
            total += _add("Taxa de desperdício", req.waste_boxes, wfee, cfg.get("waste_fee_tax_id", "INT"))
        total = round(total, 2)
        if not vendus_items or total <= 0:
            raise HTTPException(status_code=400, detail="Nada selecionado para faturar")

        lines = extra_lines     # só os extras selecionados ficam pagos como itens
        partial = False
        n = 1
        invoices = [{"items": vendus_items, "amount": total,
                     "ext_ref": f"mesa-{table_number}-rodizio-{ts}"}]
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
            qty = l.get("quantity", 1) or 1
            unit = round(float(l.get("unit_price", 0) or 0), 2)
            tax = tax_by_prod.get(l.get("product_id"), VENDUS_DEFAULT_TAX_ID)
            title = l.get("product_name", "Item")
            var = l.get("variation") or {}
            if isinstance(var, dict) and var.get("name"):
                title = f"{title} ({var['name']})"
            eff = _eff_disc(l.get("discount_pct", 0))          # desconto do item + global
            li = {"title": title, "qty": qty, "gross_price": unit, "tax_id": tax}
            if eff > 0:
                li["discount_percentage"] = eff
            vendus_items.append(li)
            amt = round(unit * qty * (1 - eff / 100.0), 2)     # valor líquido da linha
            by_tax[tax] = round(by_tax.get(tax, 0.0) + amt, 2)
            total += amt
        total = round(total, 2)

        # A divisão igual só se aplica à conta TODA (não a uma separação por itens).
        n = 1 if partial else max(1, min(int(req.split_count or 1), 50))

        # Constrói as faturas a emitir. n==1: uma fatura itemizada. n>1: uma fatura por
        # pessoa com a sua parte, agrupada por IVA (o resto do arredondamento vai para a
        # última, para as n faturas somarem EXATAMENTE o total).
        invoices = []  # {"items": [...], "amount": float, "ext_ref": str}
        if n == 1:
            invoices.append({"items": vendus_items, "amount": total,
                             "ext_ref": f"mesa-{table_number}-{ts}"})
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
                    invoices.append({"items": items_i, "amount": round(amount_i, 2),
                                     "ext_ref": f"mesa-{table_number}-{ts}-{i+1}de{n}"})

        client = {"fiscal_id": req.nif} if (req.nif and n == 1) else None

    def _emit_all():
        c = _vendus_client()
        docs = []
        try:
            for inv in invoices:
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
async def free_table(table_number: int, authorization: Optional[str] = Header(None)):
    """Liberta a mesa SEM faturar: cancela os pedidos em aberto e fecha a sessão.
    Para quando alguém lê o QR mas não pede, ou o cliente sai sem consumir."""
    await get_current_user(authorization)
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
async def print_table_consulta(table_number: int, authorization: Optional[str] = Header(None)):
    """Imprime uma CONTA PROVISÓRIA (consulta de mesa) para mostrar ao cliente.
    NÃO é fatura — a fatura só sai no fecho (Vendus). Enfileira um print job tipo
    'cashier' com um snapshot da conta atual; o agente imprime quando ligar."""
    await get_current_user(authorization)
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
    for vp in vprods:
        name = (vp.get("title") or "").strip()
        if not name:
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
            "products_created": prods_created, "products_updated": prods_updated}


class ReprintRequest(BaseModel):
    printer_ids: List[str] = []

@api_router.post("/orders/{order_id}/reprint")
async def reprint_order(order_id: str, request: Optional[ReprintRequest] = None, authorization: Optional[str] = Header(None)):
    """Reprint order to specific printers or all active printers"""
    await get_current_user(authorization)
    
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
    schedule: str = "23:30"

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
        "schedule_time": "23:30"
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
        schedule="23:30"
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
    """Função executada pelo scheduler para enviar o relatório diário"""
    logger.info("Executando relatório diário agendado...")
    try:
        result = await send_daily_report(db)
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
