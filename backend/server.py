from fastapi import FastAPI, APIRouter, HTTPException, Depends, UploadFile, File, Query, BackgroundTasks
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
import bcrypt
import jwt
import socket
import struct
import asyncio
import qrcode
import io
import base64

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
JWT_SECRET = os.environ.get('JWT_SECRET', 'pizzaria-secret-key-2024')
JWT_ALGORITHM = "HS256"

# Create the main app
app = FastAPI(title="Pizzaria API")

# Create router with /api prefix
api_router = APIRouter(prefix="/api")

# Mount static files for uploads
app.mount("/uploads", StaticFiles(directory=str(UPLOADS_DIR)), name="uploads")

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

class CategoryUpdate(BaseModel):
    name: Optional[str] = None
    order: Optional[int] = None
    active: Optional[bool] = None

class CategoryResponse(BaseModel):
    id: str
    name: str
    order: int
    active: bool
    created_at: str

class VariationCreate(BaseModel):
    name: str
    price: float

class ExtraCreate(BaseModel):
    name: str
    price: float

class ProductCreate(BaseModel):
    name: str
    description: str
    category_id: str
    base_price: float
    image_url: Optional[str] = None
    variations: List[VariationCreate] = []
    extras: List[ExtraCreate] = []
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
    available: bool
    featured: bool
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
    notes: Optional[str] = None
    unit_price: float
    total_price: float

class OrderCreate(BaseModel):
    table_id: str
    table_number: int
    items: List[OrderItemCreate]
    notes: Optional[str] = None
    total: float

class OrderStatusUpdate(BaseModel):
    status: str

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
    print_status: str
    created_at: str

class PrinterConfig(BaseModel):
    ip: str
    port: int = 9100
    width: int = 80  # 58 or 80mm
    cut_paper: bool = True
    copies: int = 1
    restaurant_name: Optional[str] = "Pizzaria"

class PrinterConfigUpdate(BaseModel):
    ip: Optional[str] = None
    port: Optional[int] = None
    width: Optional[int] = None
    cut_paper: Optional[bool] = None
    copies: Optional[int] = None
    restaurant_name: Optional[str] = None

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

async def get_current_user(authorization: str = None) -> dict:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Token não fornecido")
    
    token = authorization.replace("Bearer ", "")
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
        user = await db.admin_users.find_one({"id": payload["user_id"]}, {"_id": 0, "password": 0})
        if not user:
            raise HTTPException(status_code=401, detail="Utilizador não encontrado")
        return user
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token expirado")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Token inválido")

# ==================== ESC/POS PRINTING ====================

class ESCPOSPrinter:
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
    DOUBLE_HEIGHT = GS + b'!\x10'
    DOUBLE_WIDTH = GS + b'!\x20'
    DOUBLE_SIZE = GS + b'!\x30'
    NORMAL_SIZE = GS + b'!\x00'
    
    def __init__(self, ip: str, port: int = 9100, width: int = 80):
        self.ip = ip
        self.port = port
        self.width = width
        self.chars_per_line = 48 if width == 80 else 32
    
    def _line(self, char: str = '-') -> bytes:
        return (char * self.chars_per_line + '\n').encode('cp860')
    
    def _text(self, text: str) -> bytes:
        try:
            return text.encode('cp860')
        except:
            return text.encode('utf-8', errors='replace')
    
    def format_order(self, order: dict, restaurant_name: str = "Pizzaria") -> bytes:
        data = bytearray()
        data.extend(self.INIT)
        
        # Restaurant name
        data.extend(self.CENTER)
        data.extend(self.BOLD_ON)
        data.extend(self.DOUBLE_SIZE)
        data.extend(self._text(f"{restaurant_name}\n"))
        data.extend(self.NORMAL_SIZE)
        data.extend(self.BOLD_OFF)
        
        # Order number
        data.extend(self.DOUBLE_SIZE)
        data.extend(self._text(f"PEDIDO #{order['order_number']}\n"))
        data.extend(self.NORMAL_SIZE)
        
        data.extend(self._line('='))
        
        # Table - highlighted
        data.extend(self.DOUBLE_SIZE)
        data.extend(self._text(f"MESA: {order['table_number']}\n"))
        data.extend(self.NORMAL_SIZE)
        
        # Date/time
        data.extend(self.LEFT)
        created_at = order.get('created_at', datetime.now(timezone.utc).isoformat())
        if isinstance(created_at, str):
            dt = datetime.fromisoformat(created_at.replace('Z', '+00:00'))
        else:
            dt = created_at
        data.extend(self._text(f"Data: {dt.strftime('%d/%m/%Y %H:%M')}\n"))
        
        data.extend(self._line('-'))
        
        # Items
        data.extend(self.BOLD_ON)
        data.extend(self._text("ITENS:\n"))
        data.extend(self.BOLD_OFF)
        
        for item in order.get('items', []):
            # Item name with quantity
            qty = item.get('quantity', 1)
            name = item.get('product_name', 'Item')
            variation = item.get('variation', {})
            
            item_line = f"{qty}x {name}"
            if variation and variation.get('name'):
                item_line += f" ({variation['name']})"
            data.extend(self.BOLD_ON)
            data.extend(self._text(f"{item_line}\n"))
            data.extend(self.BOLD_OFF)
            
            # Extras
            for extra in item.get('extras', []):
                data.extend(self._text(f"   + {extra.get('name', '')}\n"))
            
            # Item notes
            if item.get('notes'):
                data.extend(self._text(f"   OBS: {item['notes']}\n"))
            
            # Price
            data.extend(self._text(f"   EUR {item.get('total_price', 0):.2f}\n"))
        
        data.extend(self._line('-'))
        
        # Order notes
        if order.get('notes'):
            data.extend(self.BOLD_ON)
            data.extend(self._text("OBSERVACOES:\n"))
            data.extend(self.BOLD_OFF)
            data.extend(self._text(f"{order['notes']}\n"))
            data.extend(self._line('-'))
        
        # Total
        data.extend(self.CENTER)
        data.extend(self.DOUBLE_SIZE)
        data.extend(self.BOLD_ON)
        data.extend(self._text(f"TOTAL: EUR {order.get('total', 0):.2f}\n"))
        data.extend(self.NORMAL_SIZE)
        data.extend(self.BOLD_OFF)
        
        data.extend(self._line('='))
        data.extend(self._text("\n\n\n"))
        
        return bytes(data)
    
    def format_test(self, restaurant_name: str = "Pizzaria") -> bytes:
        data = bytearray()
        data.extend(self.INIT)
        data.extend(self.CENTER)
        data.extend(self.BOLD_ON)
        data.extend(self.DOUBLE_SIZE)
        data.extend(self._text(f"{restaurant_name}\n"))
        data.extend(self.NORMAL_SIZE)
        data.extend(self._line('='))
        data.extend(self._text("TESTE DE IMPRESSAO\n"))
        data.extend(self._text(f"Data: {datetime.now().strftime('%d/%m/%Y %H:%M')}\n"))
        data.extend(self._line('='))
        data.extend(self._text("Impressora configurada com sucesso!\n"))
        data.extend(self._line('='))
        data.extend(self._text("\n\n\n"))
        data.extend(self.BOLD_OFF)
        return bytes(data)
    
    async def print(self, data: bytes, cut: bool = True) -> tuple[bool, str]:
        try:
            loop = asyncio.get_event_loop()
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(10)
            
            await loop.run_in_executor(None, sock.connect, (self.ip, self.port))
            await loop.run_in_executor(None, sock.sendall, data)
            
            if cut:
                await loop.run_in_executor(None, sock.sendall, self.CUT)
            
            sock.close()
            return True, "Impressão enviada com sucesso"
        except socket.timeout:
            return False, "Timeout ao conectar com a impressora"
        except ConnectionRefusedError:
            return False, "Conexão recusada pela impressora"
        except Exception as e:
            return False, f"Erro de impressão: {str(e)}"

# ==================== PRINT JOB QUEUE ====================

async def process_print_job(job_id: str):
    """Process a print job from the queue"""
    job = await db.print_jobs.find_one({"id": job_id}, {"_id": 0})
    if not job:
        return
    
    # Get printer config
    config = await db.settings.find_one({"key": "printer"}, {"_id": 0})
    if not config or not config.get("value", {}).get("ip"):
        await db.print_jobs.update_one(
            {"id": job_id},
            {"$set": {"status": "failed", "error": "Impressora não configurada", "updated_at": datetime.now(timezone.utc).isoformat()}}
        )
        return
    
    printer_settings = config["value"]
    printer = ESCPOSPrinter(
        ip=printer_settings["ip"],
        port=printer_settings.get("port", 9100),
        width=printer_settings.get("width", 80)
    )
    
    # Update status to printing
    await db.print_jobs.update_one(
        {"id": job_id},
        {"$set": {"status": "printing", "updated_at": datetime.now(timezone.utc).isoformat()}}
    )
    
    # Get order data
    order = await db.orders.find_one({"id": job["order_id"]}, {"_id": 0})
    if not order:
        await db.print_jobs.update_one(
            {"id": job_id},
            {"$set": {"status": "failed", "error": "Pedido não encontrado", "updated_at": datetime.now(timezone.utc).isoformat()}}
        )
        return
    
    # Format and print
    data = printer.format_order(order, printer_settings.get("restaurant_name", "Pizzaria"))
    copies = printer_settings.get("copies", 1)
    
    for i in range(copies):
        success, message = await printer.print(data, printer_settings.get("cut_paper", True))
        if not success:
            attempts = job.get("attempts", 0) + 1
            if attempts < 3:
                # Retry later
                await db.print_jobs.update_one(
                    {"id": job_id},
                    {"$set": {
                        "status": "pending",
                        "attempts": attempts,
                        "error": message,
                        "updated_at": datetime.now(timezone.utc).isoformat()
                    }}
                )
            else:
                # Mark as failed
                await db.print_jobs.update_one(
                    {"id": job_id},
                    {"$set": {
                        "status": "failed",
                        "attempts": attempts,
                        "error": message,
                        "updated_at": datetime.now(timezone.utc).isoformat()
                    }}
                )
                # Update order print status
                await db.orders.update_one(
                    {"id": job["order_id"]},
                    {"$set": {"print_status": "failed"}}
                )
            return
    
    # Success
    await db.print_jobs.update_one(
        {"id": job_id},
        {"$set": {"status": "printed", "updated_at": datetime.now(timezone.utc).isoformat()}}
    )
    await db.orders.update_one(
        {"id": job["order_id"]},
        {"$set": {"print_status": "printed"}}
    )

# ==================== AUTH ROUTES ====================

@api_router.post("/auth/register", response_model=TokenResponse)
async def register_admin(user: AdminUserCreate):
    # Check if user exists
    existing = await db.admin_users.find_one({"email": user.email})
    if existing:
        raise HTTPException(status_code=400, detail="Email já registado")
    
    user_id = str(uuid.uuid4())
    user_doc = {
        "id": user_id,
        "email": user.email,
        "password": hash_password(user.password),
        "name": user.name,
        "created_at": datetime.now(timezone.utc).isoformat()
    }
    await db.admin_users.insert_one(user_doc)
    
    token = create_token(user_id, user.email)
    return TokenResponse(
        access_token=token,
        user=AdminUserResponse(id=user_id, email=user.email, name=user.name)
    )

@api_router.post("/auth/login", response_model=TokenResponse)
async def login_admin(credentials: AdminUserLogin):
    user = await db.admin_users.find_one({"email": credentials.email}, {"_id": 0})
    if not user or not verify_password(credentials.password, user["password"]):
        raise HTTPException(status_code=401, detail="Credenciais inválidas")
    
    token = create_token(user["id"], user["email"])
    return TokenResponse(
        access_token=token,
        user=AdminUserResponse(id=user["id"], email=user["email"], name=user["name"])
    )

@api_router.get("/auth/me", response_model=AdminUserResponse)
async def get_me(authorization: str = None):
    user = await get_current_user(authorization)
    return AdminUserResponse(id=user["id"], email=user["email"], name=user["name"])

# ==================== CATEGORY ROUTES ====================

@api_router.post("/categories", response_model=CategoryResponse)
async def create_category(category: CategoryCreate, authorization: str = None):
    await get_current_user(authorization)
    
    cat_id = str(uuid.uuid4())
    cat_doc = {
        "id": cat_id,
        "name": category.name,
        "order": category.order,
        "active": category.active,
        "created_at": datetime.now(timezone.utc).isoformat()
    }
    await db.categories.insert_one(cat_doc)
    return CategoryResponse(**cat_doc)

@api_router.get("/categories", response_model=List[CategoryResponse])
async def list_categories(active_only: bool = False):
    query = {"active": True} if active_only else {}
    categories = await db.categories.find(query, {"_id": 0}).sort("order", 1).to_list(100)
    return [CategoryResponse(**cat) for cat in categories]

@api_router.put("/categories/{category_id}", response_model=CategoryResponse)
async def update_category(category_id: str, update: CategoryUpdate, authorization: str = None):
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
async def delete_category(category_id: str, authorization: str = None):
    await get_current_user(authorization)
    
    result = await db.categories.delete_one({"id": category_id})
    if result.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Categoria não encontrada")
    return {"message": "Categoria eliminada"}

# ==================== PRODUCT ROUTES ====================

@api_router.post("/products", response_model=ProductResponse)
async def create_product(product: ProductCreate, authorization: str = None):
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
        "available": product.available,
        "featured": product.featured,
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
    
    products = await db.products.find(query, {"_id": 0}).to_list(500)
    return [ProductResponse(**prod) for prod in products]

@api_router.get("/products/{product_id}", response_model=ProductResponse)
async def get_product(product_id: str):
    product = await db.products.find_one({"id": product_id}, {"_id": 0})
    if not product:
        raise HTTPException(status_code=404, detail="Produto não encontrado")
    return ProductResponse(**product)

@api_router.put("/products/{product_id}", response_model=ProductResponse)
async def update_product(product_id: str, update: ProductUpdate, authorization: str = None):
    await get_current_user(authorization)
    
    update_data = {}
    for k, v in update.model_dump().items():
        if v is not None:
            if k == "variations":
                update_data[k] = [var for var in v]
            elif k == "extras":
                update_data[k] = [ext for ext in v]
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
async def delete_product(product_id: str, authorization: str = None):
    await get_current_user(authorization)
    
    result = await db.products.delete_one({"id": product_id})
    if result.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Produto não encontrado")
    return {"message": "Produto eliminado"}

@api_router.post("/products/upload-image")
async def upload_product_image(file: UploadFile = File(...), authorization: str = None):
    await get_current_user(authorization)
    
    if not file.content_type.startswith("image/"):
        raise HTTPException(status_code=400, detail="Ficheiro deve ser uma imagem")
    
    # Generate unique filename
    ext = file.filename.split(".")[-1] if "." in file.filename else "jpg"
    filename = f"{uuid.uuid4()}.{ext}"
    filepath = UPLOADS_DIR / filename
    
    # Save file
    content = await file.read()
    with open(filepath, "wb") as f:
        f.write(content)
    
    return {"url": f"/uploads/{filename}"}

# ==================== TABLE ROUTES ====================

@api_router.post("/tables", response_model=TableResponse)
async def create_table(table: TableCreate, authorization: str = None):
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
async def update_table(table_id: str, update: TableUpdate, authorization: str = None):
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
async def delete_table(table_id: str, authorization: str = None):
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
async def create_order(order: OrderCreate, background_tasks: BackgroundTasks):
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
        "created_at": datetime.now(timezone.utc).isoformat()
    }
    await db.orders.insert_one(order_doc)
    
    # Create print job
    print_job_id = str(uuid.uuid4())
    print_job = {
        "id": print_job_id,
        "order_id": order_id,
        "status": "pending",
        "attempts": 0,
        "error": None,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "updated_at": datetime.now(timezone.utc).isoformat()
    }
    await db.print_jobs.insert_one(print_job)
    
    # Process print job in background
    background_tasks.add_task(process_print_job, print_job_id)
    
    return OrderResponse(**order_doc)

@api_router.get("/orders", response_model=List[OrderResponse])
async def list_orders(
    status: Optional[str] = None,
    table_number: Optional[int] = None,
    date: Optional[str] = None,
    authorization: str = None
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
async def update_order_status(order_id: str, update: OrderStatusUpdate, authorization: str = None):
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
async def mark_order_paid(order_id: str, authorization: str = None):
    await get_current_user(authorization)
    
    result = await db.orders.update_one(
        {"id": order_id},
        {"$set": {"paid": True}}
    )
    if result.matched_count == 0:
        raise HTTPException(status_code=404, detail="Pedido não encontrado")
    
    order = await db.orders.find_one({"id": order_id}, {"_id": 0})
    return OrderResponse(**order)

@api_router.post("/orders/{order_id}/reprint")
async def reprint_order(order_id: str, background_tasks: BackgroundTasks, authorization: str = None):
    await get_current_user(authorization)
    
    order = await db.orders.find_one({"id": order_id}, {"_id": 0})
    if not order:
        raise HTTPException(status_code=404, detail="Pedido não encontrado")
    
    # Create new print job
    print_job_id = str(uuid.uuid4())
    print_job = {
        "id": print_job_id,
        "order_id": order_id,
        "status": "pending",
        "attempts": 0,
        "error": None,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "updated_at": datetime.now(timezone.utc).isoformat()
    }
    await db.print_jobs.insert_one(print_job)
    
    # Update order print status
    await db.orders.update_one({"id": order_id}, {"$set": {"print_status": "pending"}})
    
    # Process in background
    background_tasks.add_task(process_print_job, print_job_id)
    
    return {"message": "Impressão agendada", "print_job_id": print_job_id}

# ==================== PRINT JOB ROUTES ====================

@api_router.get("/print-jobs")
async def list_print_jobs(status: Optional[str] = None, authorization: str = None):
    await get_current_user(authorization)
    
    query = {}
    if status:
        query["status"] = status
    
    jobs = await db.print_jobs.find(query, {"_id": 0}).sort("created_at", -1).to_list(100)
    return jobs

# ==================== SETTINGS ROUTES ====================

@api_router.get("/settings/printer")
async def get_printer_settings(authorization: str = None):
    await get_current_user(authorization)
    
    settings = await db.settings.find_one({"key": "printer"}, {"_id": 0})
    if not settings:
        return {
            "ip": "",
            "port": 9100,
            "width": 80,
            "cut_paper": True,
            "copies": 1,
            "restaurant_name": "Pizzaria"
        }
    return settings.get("value", {})

@api_router.put("/settings/printer")
async def update_printer_settings(config: PrinterConfigUpdate, authorization: str = None):
    await get_current_user(authorization)
    
    current = await db.settings.find_one({"key": "printer"}, {"_id": 0})
    current_value = current.get("value", {}) if current else {}
    
    update_data = {k: v for k, v in config.model_dump().items() if v is not None}
    new_value = {**current_value, **update_data}
    
    await db.settings.update_one(
        {"key": "printer"},
        {"$set": {"key": "printer", "value": new_value}},
        upsert=True
    )
    
    return new_value

@api_router.post("/settings/printer/test")
async def test_printer(authorization: str = None):
    await get_current_user(authorization)
    
    settings = await db.settings.find_one({"key": "printer"}, {"_id": 0})
    if not settings or not settings.get("value", {}).get("ip"):
        raise HTTPException(status_code=400, detail="Impressora não configurada")
    
    config = settings["value"]
    printer = ESCPOSPrinter(
        ip=config["ip"],
        port=config.get("port", 9100),
        width=config.get("width", 80)
    )
    
    data = printer.format_test(config.get("restaurant_name", "Pizzaria"))
    success, message = await printer.print(data, config.get("cut_paper", True))
    
    if not success:
        raise HTTPException(status_code=500, detail=message)
    
    return {"message": "Teste de impressão enviado com sucesso"}

# ==================== DASHBOARD ROUTES ====================

@api_router.get("/dashboard/stats", response_model=DashboardStats)
async def get_dashboard_stats(authorization: str = None):
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
async def seed_database():
    """Seed database with sample data"""
    
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
        # Pizzas
        {
            "id": str(uuid.uuid4()),
            "name": "Margherita",
            "description": "Molho de tomate, mozzarella fresca, manjericão e azeite virgem extra",
            "category_id": pizza_cat_id,
            "base_price": 9.50,
            "image_url": "https://images.unsplash.com/photo-1574071318508-1cdbab80d002?w=800",
            "variations": [
                {"name": "Pequena", "price": 7.50},
                {"name": "Média", "price": 9.50},
                {"name": "Grande", "price": 12.50}
            ],
            "extras": [
                {"name": "Borda recheada", "price": 2.00},
                {"name": "Extra queijo", "price": 1.50}
            ],
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
            "variations": [
                {"name": "Pequena", "price": 9.00},
                {"name": "Média", "price": 11.00},
                {"name": "Grande", "price": 14.00}
            ],
            "extras": [
                {"name": "Borda recheada", "price": 2.00},
                {"name": "Extra pepperoni", "price": 2.00}
            ],
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
            "variations": [
                {"name": "Pequena", "price": 10.50},
                {"name": "Média", "price": 12.50},
                {"name": "Grande", "price": 15.50}
            ],
            "extras": [
                {"name": "Borda recheada", "price": 2.00},
                {"name": "Mel", "price": 1.00}
            ],
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
            "variations": [
                {"name": "Pequena", "price": 8.50},
                {"name": "Média", "price": 10.50},
                {"name": "Grande", "price": 13.50}
            ],
            "extras": [
                {"name": "Borda recheada", "price": 2.00},
                {"name": "Extra cogumelos", "price": 1.50}
            ],
            "available": True,
            "featured": False,
            "created_at": datetime.now(timezone.utc).isoformat()
        },
        # Drinks
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
            "variations": [
                {"name": "Com gás", "price": 1.50},
                {"name": "Sem gás", "price": 1.50}
            ],
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
            "variations": [
                {"name": "Tinto", "price": 4.50},
                {"name": "Branco", "price": 4.50}
            ],
            "extras": [],
            "available": True,
            "featured": False,
            "created_at": datetime.now(timezone.utc).isoformat()
        },
        # Starters
        {
            "id": str(uuid.uuid4()),
            "name": "Bruschetta",
            "description": "Pão italiano torrado com tomate, alho e manjericão fresco",
            "category_id": starters_cat_id,
            "base_price": 5.50,
            "image_url": "https://images.unsplash.com/photo-1626634896715-88334e9da24f?w=800",
            "variations": [],
            "extras": [
                {"name": "Extra queijo parmesão", "price": 1.00}
            ],
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
            "extras": [
                {"name": "Com queijo", "price": 1.50}
            ],
            "available": True,
            "featured": False,
            "created_at": datetime.now(timezone.utc).isoformat()
        },
        # Desserts
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
    
    # Set default printer settings
    await db.settings.update_one(
        {"key": "printer"},
        {"$set": {"key": "printer", "value": {
            "ip": "",
            "port": 9100,
            "width": 80,
            "cut_paper": True,
            "copies": 1,
            "restaurant_name": "Pizzaria"
        }}},
        upsert=True
    )
    
    return {
        "message": "Base de dados inicializada com sucesso",
        "data": {
            "categories": len(categories),
            "products": len(products),
            "tables": len(tables),
            "admin": {"email": "admin@pizzaria.pt", "password": "admin123"}
        }
    }

# Include router
app.include_router(api_router)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_credentials=True,
    allow_origins=os.environ.get('CORS_ORIGINS', '*').split(','),
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.on_event("shutdown")
async def shutdown_db_client():
    client.close()
