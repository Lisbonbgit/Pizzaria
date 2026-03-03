#!/usr/bin/env python3
"""
Pizzaria Print Agent - Windows Local Printer Bridge
====================================================

Este agente funciona como ponte entre o backend na cloud e as impressoras 
térmicas ESC/POS na rede local da pizzaria.

Suporta múltiplas impressoras com formatos diferentes:
- COZINHA: Foco nos detalhes de preparação
- CAIXA: Foco nos preços e valores

Instalação no Windows:
1. Instalar Python 3.8+ (https://python.org)
2. Executar: pip install requests
3. Configurar API_KEY e BACKEND_URL abaixo
4. Executar: python print_agent.py
"""

import socket
import time
import logging
import os
import sys
import json
from datetime import datetime
from pathlib import Path

try:
    import requests
except ImportError:
    print("Erro: Biblioteca 'requests' não encontrada.")
    print("Execute: pip install requests")
    sys.exit(1)

# ==================== CONFIGURAÇÃO ====================

# URL do backend (altere para a URL do seu sistema)
BACKEND_URL = "https://daily-order-summary.preview.emergentagent.com"

# API Key do Print Agent (obtenha no Admin > Impressoras > Print Agent)
API_KEY = "SUA_API_KEY_AQUI"

# Intervalo de polling em segundos
POLL_INTERVAL = 3

# Número máximo de tentativas de impressão
MAX_RETRIES = 3

# Timeout de conexão com a impressora (segundos)
PRINTER_TIMEOUT = 5

# Diretório de logs
LOG_DIR = Path(__file__).parent / "logs"

# ==================== CONFIGURAÇÃO DE LOGS ====================

LOG_DIR.mkdir(exist_ok=True)
log_file = LOG_DIR / f"print_agent_{datetime.now().strftime('%Y%m%d')}.log"

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(log_file, encoding='utf-8'),
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger("PrintAgent")

# ==================== ESC/POS PRINTER ====================

class ESCPOSPrinter:
    """Classe para comunicação com impressoras térmicas ESC/POS via TCP"""
    
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
    
    def __init__(self, ip: str, port: int = 9100, width: int = 80, timeout: int = PRINTER_TIMEOUT):
        self.ip = ip
        self.port = port
        self.width = width
        self.timeout = timeout
        self.chars_per_line = 48 if width == 80 else 32
    
    def _line(self, char: str = '-') -> bytes:
        return (char * self.chars_per_line + '\n').encode('cp860', errors='replace')
    
    def _text(self, text: str) -> bytes:
        replacements = {
            'ã': 'a', 'õ': 'o', 'á': 'a', 'é': 'e', 'í': 'i', 'ó': 'o', 'ú': 'u',
            'à': 'a', 'è': 'e', 'ì': 'i', 'ò': 'o', 'ù': 'u',
            'â': 'a', 'ê': 'e', 'î': 'i', 'ô': 'o', 'û': 'u',
            'ç': 'c', 'Ç': 'C', 'ñ': 'n', 'Ñ': 'N',
            'Ã': 'A', 'Õ': 'O', 'Á': 'A', 'É': 'E', 'Í': 'I', 'Ó': 'O', 'Ú': 'U',
            '€': 'EUR', '£': 'GBP'
        }
        for old, new in replacements.items():
            text = text.replace(old, new)
        try:
            return text.encode('cp860', errors='replace')
        except:
            return text.encode('ascii', errors='replace')
    
    def _get_datetime(self, order: dict) -> datetime:
        created_at = order.get('created_at', datetime.now().isoformat())
        if isinstance(created_at, str):
            try:
                return datetime.fromisoformat(created_at.replace('Z', '+00:00'))
            except:
                return datetime.now()
        return created_at
    
    def format_kitchen(self, order: dict, printer_name: str = "COZINHA") -> bytes:
        """Formato para impressora da COZINHA - foco na preparação"""
        data = bytearray()
        data.extend(self.INIT)
        
        # Cabeçalho - NOVO PEDIDO
        data.extend(self.CENTER)
        data.extend(self.BOLD_ON)
        data.extend(self.DOUBLE_SIZE)
        data.extend(self._text("*** NOVO PEDIDO ***\n"))
        data.extend(self.NORMAL_SIZE)
        data.extend(self.BOLD_OFF)
        
        data.extend(self._line('='))
        
        # Número do pedido - GRANDE
        data.extend(self.CENTER)
        data.extend(self.DOUBLE_SIZE)
        data.extend(self.BOLD_ON)
        data.extend(self._text(f"PEDIDO #{order['order_number']}\n"))
        data.extend(self.NORMAL_SIZE)
        data.extend(self.BOLD_OFF)
        
        # Mesa - GRANDE
        data.extend(self.DOUBLE_SIZE)
        data.extend(self._text(f"MESA: {order['table_number']}\n"))
        data.extend(self.NORMAL_SIZE)
        
        # Data/hora
        dt = self._get_datetime(order)
        data.extend(self._text(f"{dt.strftime('%d/%m/%Y %H:%M')}\n"))
        
        data.extend(self._line('='))
        
        # Itens - detalhados para preparação
        data.extend(self.LEFT)
        
        for item in order.get('items', []):
            qty = item.get('quantity', 1)
            name = item.get('product_name', 'Item')
            variation = item.get('variation', {})
            
            # Nome do item com quantidade - NEGRITO
            data.extend(self.BOLD_ON)
            data.extend(self.DOUBLE_HEIGHT)
            data.extend(self._text(f"{qty}x {name}\n"))
            data.extend(self.NORMAL_SIZE)
            data.extend(self.BOLD_OFF)
            
            # Tamanho
            if variation and variation.get('name'):
                data.extend(self._text(f"   Tamanho: {variation['name']}\n"))
            
            # Extras
            for extra in item.get('extras', []):
                data.extend(self._text(f"   + {extra.get('name', '')}\n"))
            
            # Notas do item - EM DESTAQUE
            if item.get('notes'):
                data.extend(self.BOLD_ON)
                data.extend(self._text(f"   >>> {item['notes'].upper()} <<<\n"))
                data.extend(self.BOLD_OFF)
            
            data.extend(self._text("\n"))
        
        data.extend(self._line('-'))
        
        # Observações do pedido - MUITO DESTACADAS
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
        """Formato para impressora do CAIXA - foco nos preços"""
        data = bytearray()
        data.extend(self.INIT)
        
        # Cabeçalho
        data.extend(self.CENTER)
        data.extend(self.BOLD_ON)
        data.extend(self._text(f"[{printer_name}]\n"))
        data.extend(self.BOLD_OFF)
        
        data.extend(self._line('='))
        
        # Número do pedido
        data.extend(self.DOUBLE_SIZE)
        data.extend(self.BOLD_ON)
        data.extend(self._text(f"PEDIDO #{order['order_number']}\n"))
        data.extend(self.NORMAL_SIZE)
        data.extend(self.BOLD_OFF)
        
        # Mesa
        data.extend(self.BOLD_ON)
        data.extend(self._text(f"MESA: {order['table_number']}\n"))
        data.extend(self.BOLD_OFF)
        
        data.extend(self._line('-'))
        
        # Itens com preços
        data.extend(self.LEFT)
        
        for item in order.get('items', []):
            qty = item.get('quantity', 1)
            name = item.get('product_name', 'Item')
            variation = item.get('variation', {})
            total_price = item.get('total_price', 0)
            
            # Linha do item
            item_desc = f"{qty}x {name}"
            if variation and variation.get('name'):
                item_desc += f" ({variation['name']})"
            
            data.extend(self._text(f"{item_desc}\n"))
            
            # Extras com preço
            for extra in item.get('extras', []):
                data.extend(self._text(f"   + {extra.get('name', '')} (+{extra.get('price', 0):.2f})\n"))
            
            # Preço
            data.extend(self.RIGHT)
            data.extend(self._text(f"EUR {total_price:.2f}\n"))
            data.extend(self.LEFT)
            
            data.extend(self._text("\n"))
        
        data.extend(self._line('-'))
        
        # Total - GRANDE
        data.extend(self.CENTER)
        data.extend(self.DOUBLE_SIZE)
        data.extend(self.BOLD_ON)
        data.extend(self._text(f"TOTAL: EUR {order.get('total', 0):.2f}\n"))
        data.extend(self.NORMAL_SIZE)
        data.extend(self.BOLD_OFF)
        
        data.extend(self._line('-'))
        
        # Informações finais
        data.extend(self.LEFT)
        dt = self._get_datetime(order)
        data.extend(self._text(f"Data: {dt.strftime('%d/%m/%Y %H:%M')}\n"))
        data.extend(self._text(f"ID: {order.get('id', '')[:8]}\n"))
        
        data.extend(self._line('='))
        data.extend(self._text("\n\n\n"))
        
        return bytes(data)
    
    def format_order(self, order: dict, printer_name: str = "", printer_type: str = "kitchen") -> bytes:
        """Formata pedido baseado no tipo de impressora"""
        if printer_type == "cashier":
            return self.format_cashier(order, printer_name)
        else:
            return self.format_kitchen(order, printer_name)
    
    def format_test(self, printer_name: str = "", restaurant_name: str = "Pizzaria") -> bytes:
        """Formata um teste de impressão"""
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
        data.extend(self._text("Print Agent activo.\n"))
        data.extend(self._line('='))
        data.extend(self._text("\n\n\n"))
        data.extend(self.BOLD_OFF)
        return bytes(data)
    
    def send(self, data: bytes, cut: bool = True) -> tuple:
        """Envia dados para a impressora via TCP"""
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(self.timeout)
            sock.connect((self.ip, self.port))
            sock.sendall(data)
            
            if cut:
                sock.sendall(self.CUT)
            
            sock.close()
            return True, "Impressão enviada com sucesso"
        except socket.timeout:
            return False, f"Timeout ao conectar com {self.ip}:{self.port}"
        except ConnectionRefusedError:
            return False, f"Conexão recusada por {self.ip}:{self.port}"
        except Exception as e:
            return False, f"Erro: {str(e)}"

# ==================== PRINT AGENT ====================

class PrintAgent:
    """Agente de impressão que comunica com o backend"""
    
    def __init__(self, backend_url: str, api_key: str):
        self.backend_url = backend_url.rstrip('/')
        self.api_key = api_key
        self.headers = {
            "X-API-Key": api_key,
            "Content-Type": "application/json"
        }
        self.running = True
    
    def get_pending_jobs(self) -> list:
        """Busca jobs pendentes no backend"""
        try:
            response = requests.get(
                f"{self.backend_url}/api/agent/pending-jobs",
                headers=self.headers,
                timeout=30
            )
            if response.status_code == 200:
                return response.json()
            elif response.status_code == 401:
                logger.error("API Key inválida! Verifique a configuração.")
                return []
            else:
                logger.warning(f"Erro ao buscar jobs: {response.status_code}")
                return []
        except requests.exceptions.ConnectionError:
            logger.warning("Sem conexão com o servidor")
            return []
        except Exception as e:
            logger.error(f"Erro ao buscar jobs: {e}")
            return []
    
    def update_job_status(self, job_id: str, status: str, error: str = None) -> bool:
        """Atualiza o status de um job no backend"""
        try:
            data = {"status": status}
            if error:
                data["error"] = error
            
            response = requests.put(
                f"{self.backend_url}/api/agent/jobs/{job_id}/status",
                headers=self.headers,
                json=data,
                timeout=30
            )
            return response.status_code == 200
        except Exception as e:
            logger.error(f"Erro ao atualizar status: {e}")
            return False
    
    def process_job(self, job_data: dict) -> bool:
        """Processa um job de impressão"""
        job = job_data.get("job", {})
        printer_config = job_data.get("printer", {})
        order = job_data.get("order")
        restaurant_name = job_data.get("restaurant_name", "Pizzaria")
        is_test = job_data.get("is_test", False)
        printer_type = job_data.get("printer_type", "kitchen")
        
        job_id = job.get("id")
        printer_name = job.get("printer_name", "Default")
        
        if not printer_config:
            logger.warning(f"Job {job_id}: Sem configuração de impressora")
            self.update_job_status(job_id, "failed", "Impressora não configurada")
            return False
        
        # Configurar impressora
        printer = ESCPOSPrinter(
            ip=printer_config.get("ip", ""),
            port=printer_config.get("port", 9100),
            width=printer_config.get("width", 80)
        )
        
        # Preparar dados para impressão baseado no tipo
        if is_test:
            logger.info(f"Processando teste de impressão para {printer_name}")
            print_data = printer.format_test(printer_name, restaurant_name)
        elif order:
            logger.info(f"Processando pedido #{order.get('order_number')} para {printer_name} (tipo: {printer_type})")
            print_data = printer.format_order(order, printer_name, printer_type)
        else:
            logger.warning(f"Job {job_id}: Sem dados para imprimir")
            self.update_job_status(job_id, "failed", "Sem dados para imprimir")
            return False
        
        # Marcar como "printing"
        self.update_job_status(job_id, "printing")
        
        # Enviar para impressora
        cut_paper = printer_config.get("cut_paper", True)
        success, message = printer.send(print_data, cut_paper)
        
        if success:
            logger.info(f"Job {job_id}: Impresso com sucesso em {printer_name} ({printer_type})")
            self.update_job_status(job_id, "printed")
            return True
        else:
            logger.error(f"Job {job_id}: Falha - {message}")
            self.update_job_status(job_id, "failed", message)
            return False
    
    def run(self):
        """Loop principal do agente"""
        logger.info("=" * 50)
        logger.info("Print Agent Iniciado")
        logger.info(f"Backend: {self.backend_url}")
        logger.info(f"Intervalo: {POLL_INTERVAL}s")
        logger.info("Suporte a múltiplas impressoras: COZINHA / CAIXA")
        logger.info("=" * 50)
        
        while self.running:
            try:
                # Buscar jobs pendentes
                jobs = self.get_pending_jobs()
                
                if jobs:
                    logger.info(f"Encontrados {len(jobs)} jobs pendentes")
                    
                    for job_data in jobs:
                        self.process_job(job_data)
                        time.sleep(0.5)  # Pequeno delay entre jobs
                
                # Aguardar próximo ciclo
                time.sleep(POLL_INTERVAL)
                
            except KeyboardInterrupt:
                logger.info("Interrupção recebida, encerrando...")
                self.running = False
            except Exception as e:
                logger.error(f"Erro no loop principal: {e}")
                time.sleep(POLL_INTERVAL)
        
        logger.info("Print Agent Encerrado")

# ==================== MAIN ====================

def test_printer_connection(ip: str, port: int = 9100):
    """Testa conexão com uma impressora"""
    print(f"\nTestando conexão com {ip}:{port}...")
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(5)
        sock.connect((ip, port))
        sock.close()
        print(f"✓ Conexão bem sucedida com {ip}:{port}")
        return True
    except socket.timeout:
        print(f"✗ Timeout ao conectar com {ip}:{port}")
        return False
    except ConnectionRefusedError:
        print(f"✗ Conexão recusada por {ip}:{port}")
        return False
    except Exception as e:
        print(f"✗ Erro: {e}")
        return False

def main():
    """Função principal"""
    print("""
╔══════════════════════════════════════════════════════════════╗
║           PIZZARIA PRINT AGENT - Windows Edition             ║
║                                                              ║
║  Este agente conecta o sistema de pedidos às impressoras     ║
║  térmicas da sua rede local.                                 ║
║                                                              ║
║  Suporta múltiplas impressoras:                              ║
║    - COZINHA: Formato de preparação                          ║
║    - CAIXA: Formato com preços                               ║
╚══════════════════════════════════════════════════════════════╝
    """)
    
    # Verificar configuração
    if API_KEY == "SUA_API_KEY_AQUI":
        print("ERRO: API_KEY não configurada!")
        print("\nPara configurar:")
        print("1. Abra o Admin do sistema")
        print("2. Vá em Impressoras > Print Agent")
        print("3. Copie a API Key")
        print("4. Cole no campo API_KEY neste ficheiro")
        print(f"\nFicheiro: {__file__}")
        input("\nPressione Enter para sair...")
        return
    
    # Menu de opções
    print("\nOpções:")
    print("1. Iniciar Print Agent")
    print("2. Testar conexão com impressora")
    print("3. Sair")
    
    try:
        choice = input("\nEscolha (1/2/3): ").strip()
    except:
        choice = "1"
    
    if choice == "2":
        ip = input("IP da impressora: ").strip()
        port = input("Porta (default 9100): ").strip()
        port = int(port) if port else 9100
        test_printer_connection(ip, port)
        input("\nPressione Enter para continuar...")
        main()
    elif choice == "3":
        print("A sair...")
        return
    else:
        # Iniciar agent
        agent = PrintAgent(BACKEND_URL, API_KEY)
        agent.run()

if __name__ == "__main__":
    main()
