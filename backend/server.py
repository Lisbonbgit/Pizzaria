from fastapi import FastAPI, APIRouter, HTTPException, Depends, UploadFile, File, Query, BackgroundTasks, Header
from fastapi.staticfiles import StaticFiles
from dotenv import load_dotenv
from starlette.middleware.cors import CORSMiddleware
from motor.motor_asyncio import AsyncIOMotorClient
import os
import logging
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
            if RESEND_API_KEY and REPORT_EMAIL:
                SCHEDULER_ENABLED = True
                scheduler.add_job(
                    run_scheduled_report,
                    CronTrigger(hour=23, minute=59, timezone='Europe/Lisbon'),
                    id='daily_report',
                    name='Daily Report Email',
                    replace_existing=True
                )
                scheduler.start()
                logger.info("Scheduler de relatórios diários iniciado automaticamente")
            else:
                logger.warning("Scheduler configurado mas RESEND_API_KEY ou REPORT_EMAIL não definidos")
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

# ==================== AUTH HELPERS ====================

def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')

def verify_password(password: str, hashed: str) -> bool:
    return bcrypt.checkpw(password.encode('utf-8'), hashed.encode('utf-8'))

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
        data.extend(self.DOUBLE_SIZE)
        data.extend(self._text("*** NOVO PEDIDO ***\n"))
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
        data.extend(self.DOUBLE_SIZE)
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
        data.extend(self.DOUBLE_SIZE)
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
        "order": await db.products.count_documents({"category_id": product.category_id}),
        "created_at": datetime.now(timezone.utc).isoformat()
    }
    await db.products.insert_one(prod_doc)
    return ProductResponse(**prod_doc)

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
        # Create a single pending job without printer (to be processed when agent connects)
        print_job_id = str(uuid.uuid4())
        print_job = {
            "id": print_job_id,
            "order_id": order_id,
            "printer_id": None,
            "printer_name": "Default",
            "printer_type": "kitchen",
            "status": "pending",
            "attempts": 0,
            "error": None,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "updated_at": datetime.now(timezone.utc).isoformat()
        }
        await db.print_jobs.insert_one(print_job)
        logger.warning(f"Order {order_id}: No active printers configured, created default print job")
    
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

# ==================== VENDUS: FECHO DE MESA ====================

VENDUS_DEFAULT_TAX_ID = os.environ.get("VENDUS_DEFAULT_TAX_ID", "NOR")


def _vendus_client() -> VendusClient:
    return VendusClient(VendusConfig.load(os.environ))


async def _open_orders_for_table(table_number: int) -> list:
    return await db.orders.find(
        {"table_number": table_number, "paid": False, "status": {"$ne": "cancelled"}},
        {"_id": 0},
    ).sort("created_at", 1).to_list(500)


class CloseTableRequest(BaseModel):
    payment_method_id: int
    nif: Optional[str] = None


@api_router.get("/tables/{table_number}/bill")
async def get_table_bill(table_number: int, authorization: Optional[str] = Header(None)):
    """Conta em aberto da mesa (soma dos pedidos não pagos)."""
    await get_current_user(authorization)
    orders = await _open_orders_for_table(table_number)
    lines = []
    total = 0.0
    for o in orders:
        for it in o.get("items", []):
            lines.append({
                "product_name": it.get("product_name"),
                "quantity": it.get("quantity", 1),
                "unit_price": it.get("unit_price", 0),
                "total_price": it.get("total_price", 0),
            })
        total += o.get("total", 0)
    return {"table_number": table_number, "orders": len(orders),
            "lines": lines, "total": round(total, 2)}


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
        a["total"] += o.get("total", 0) or 0
        a["count"] += 1
        ca = o.get("created_at")
        if ca and (a["last"] is None or ca > a["last"]):
            a["last"] = ca
    sessions = await db.table_sessions.find({"status": "open"}, {"_id": 0}).to_list(1000)
    sess_by = {s["table_number"]: s for s in sessions}
    out = []
    for t in tables:
        a = agg.get(t["number"], {"total": 0.0, "count": 0, "last": None})
        s = sess_by.get(t["number"])
        out.append({
            "id": t["id"], "number": t["number"], "name": t.get("name"),
            "open_total": round(a["total"], 2), "open_orders": a["count"],
            "occupied": a["count"] > 0 or s is not None,
            "people": (s or {}).get("people"),
            "last_activity": a["last"] or (s or {}).get("opened_at"),
        })
    return out


# ---- Sessões de mesa (fluxo do cliente por QR) ----

async def _open_session(table_number: int):
    return await db.table_sessions.find_one(
        {"table_number": table_number, "status": "open"}, {"_id": 0}
    )


class OpenTableRequest(BaseModel):
    people: int = 1


@api_router.post("/tables/{table_number}/open")
async def open_table_session(table_number: int, req: OpenTableRequest):
    """PÚBLICO — o cliente abre a mesa (nº de pessoas) na 1ª leitura do QR."""
    existing = await _open_session(table_number)
    if existing:
        return existing
    session = {
        "id": str(uuid.uuid4()),
        "table_number": table_number,
        "people": max(1, req.people or 1),
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
    orders = await _open_orders_for_table(table_number)
    lines = []
    total = 0.0
    for o in orders:
        src = o.get("source", "client")
        for it in o.get("items", []):
            lines.append({
                "product_name": it.get("product_name"),
                "quantity": it.get("quantity", 1),
                "total_price": it.get("total_price", 0),
                "source": src,
            })
        total += o.get("total", 0)
    return {
        "open": s is not None,
        "people": (s or {}).get("people"),
        "opened_at": (s or {}).get("opened_at"),
        "bill": {"total": round(total, 2), "lines": lines, "orders": len(orders)},
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
    """Fecha a mesa: emite a fatura-recibo (FR) no Vendus com os itens da conta e
    o pagamento escolhido, e marca os pedidos como pagos."""
    await get_current_user(authorization)
    orders = await _open_orders_for_table(table_number)
    if not orders:
        raise HTTPException(status_code=400, detail="Mesa sem conta em aberto")

    # IVA por produto (do que foi importado do Vendus); fallback ao default
    prod_ids = list({it.get("product_id") for o in orders for it in o.get("items", []) if it.get("product_id")})
    tax_by_prod = {}
    if prod_ids:
        async for p in db.products.find({"id": {"$in": prod_ids}}, {"_id": 0, "id": 1, "vendus_tax_id": 1}):
            if p.get("vendus_tax_id"):
                tax_by_prod[p["id"]] = p["vendus_tax_id"]

    vendus_items = []
    total = 0.0
    for o in orders:
        for it in o.get("items", []):
            qty = it.get("quantity", 1) or 1
            unit = round(float(it.get("unit_price", 0) or 0), 2)
            vendus_items.append({
                "title": it.get("product_name", "Item"),
                "qty": qty,
                "gross_price": unit,
                "tax_id": tax_by_prod.get(it.get("product_id"), VENDUS_DEFAULT_TAX_ID),
            })
        total += o.get("total", 0)
    total = round(total, 2)

    payments = [{"id": req.payment_method_id, "amount": total}]
    client = {"fiscal_id": req.nif} if req.nif else None
    ext_ref = f"mesa-{table_number}-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}"

    def _invoice():
        c = _vendus_client()
        try:
            return c.create_invoice(items=vendus_items, payments=payments,
                                    client=client, external_reference=ext_ref)
        finally:
            c.close()
    try:
        doc = await asyncio.to_thread(_invoice)
    except VendusError as e:
        raise HTTPException(status_code=502, detail=f"Erro ao faturar no Vendus: {e}")

    order_ids = [o["id"] for o in orders]
    await db.orders.update_many(
        {"id": {"$in": order_ids}},
        {"$set": {"paid": True, "status": "delivered",
                  "payment_method": str(req.payment_method_id),
                  "vendus_document_id": doc.get("id")}},
    )
    # fecha a sessão da mesa (nº de pessoas) — a mesa fica livre
    await db.table_sessions.update_many(
        {"table_number": table_number, "status": "open"},
        {"$set": {"status": "closed", "closed_at": datetime.now(timezone.utc).isoformat()}},
    )
    return {"table_number": table_number, "total": total,
            "orders_closed": len(order_ids),
            "vendus": {"id": doc.get("id"), "number": doc.get("number"),
                       "atcud": doc.get("atcud")}}


@api_router.post("/tables/{table_number}/print-consulta")
async def print_table_consulta(table_number: int, authorization: Optional[str] = Header(None)):
    """Imprime uma CONTA PROVISÓRIA (consulta de mesa) para mostrar ao cliente.
    NÃO é fatura — a fatura só sai no fecho (Vendus). Enfileira um print job tipo
    'cashier' com um snapshot da conta atual; o agente imprime quando ligar."""
    await get_current_user(authorization)
    orders = await _open_orders_for_table(table_number)
    if not orders:
        raise HTTPException(status_code=400, detail="Mesa sem conta em aberto")

    items = []
    total = 0.0
    for o in orders:
        for it in o.get("items", []):
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
        total += o.get("total", 0)
    total = round(total, 2)

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
            raise HTTPException(status_code=400, detail="Nenhuma impressora ativa configurada")
        
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
        
        result.append({
            "job": job,
            "printer": printer,
            "printer_type": printer_type,
            "order": order,
            "restaurant_name": restaurant_name,
            "is_test": job.get("is_test", False)
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

from scheduler import send_daily_report, RESEND_API_KEY, REPORT_EMAIL

class SendReportRequest(BaseModel):
    date: Optional[str] = None  # ISO date string e.g. "2025-07-04"

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
    
    total_revenue = sum(o.get("total", 0) for o in non_cancelled)
    avg_ticket = total_revenue / len(non_cancelled) if non_cancelled else 0
    
    paid_orders = len([o for o in non_cancelled if o.get("paid", False)])
    unpaid_orders = len(non_cancelled) - paid_orders
    
    # Payment methods breakdown
    payment_methods = {}
    for o in non_cancelled:
        if o.get("paid", False):
            method = o.get("payment_method", "não especificado")
            if method not in payment_methods:
                payment_methods[method] = {"count": 0, "total": 0}
            payment_methods[method]["count"] += 1
            payment_methods[method]["total"] += o.get("total", 0)
    
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
    schedule: str = "23:59"

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
    """Retorna a configuração atual do sistema de relatórios"""
    await get_current_user(authorization)
    
    return {
        "resend_configured": bool(RESEND_API_KEY),
        "report_email": REPORT_EMAIL or "Não configurado",
        "scheduler_enabled": SCHEDULER_ENABLED,
        "timezone": "Europe/Lisbon",
        "schedule_time": "23:59"
    }

@api_router.post("/admin/scheduler/enable")
async def enable_scheduler(authorization: Optional[str] = Header(None)):
    """Ativa o scheduler de relatórios diários"""
    global SCHEDULER_ENABLED
    await get_current_user(authorization)
    
    if not RESEND_API_KEY or not REPORT_EMAIL:
        raise HTTPException(
            status_code=400,
            detail="Configure RESEND_API_KEY e REPORT_EMAIL antes de ativar o scheduler"
        )
    
    SCHEDULER_ENABLED = True
    
    # Adicionar job se não existir
    if not scheduler.get_job('daily_report'):
        scheduler.add_job(
            run_scheduled_report,
            CronTrigger(hour=23, minute=59, timezone='Europe/Lisbon'),
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
        schedule="23:59"
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
