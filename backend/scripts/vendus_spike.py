"""
Spike de validação da API Vendus (mode:tests) — responde às perguntas que a
documentação NÃO responde, antes de comprometer a arquitetura dos fluxos:

  R3-a) Dois POST DC na mesma mesa -> somam no MESMO documento ou separam?
  R3-b) Item metido à mão no POS -> cai no MESMO documento que a app lê?
  R3-c) Faturar no POS -> liberta a mesa / é detetável por polling?

Segurança: RECUSA correr se VENDUS_MODE != "tests" (não gera documentos fiscais).
A chave é lida de backend/.env (gitignored) — nunca é impressa.

Uso (a partir de backend/):
    # 1ª vez: cria 2 DC de teste na mesma mesa e lê o estado
    python scripts/vendus_spike.py

    # Reconfirmar após um passo manual no POS (NÃO cria novos DC, só lê):
    SPIKE_READONLY=1 python scripts/vendus_spike.py

Opcional (fixar a mesa em vez de auto-escolher a 1ª):
    SPIKE_ROOM_ID=123 SPIKE_TABLE_ID=456 python scripts/vendus_spike.py
"""
import os
import sys
from datetime import date

# Permite "import vendus..." quando corrido como script a partir de backend/
_BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _BACKEND not in sys.path:
    sys.path.insert(0, _BACKEND)

from dotenv import load_dotenv  # noqa: E402
from vendus import VendusConfig, VendusClient  # noqa: E402
from vendus.errors import VendusError  # noqa: E402

load_dotenv(os.path.join(_BACKEND, ".env"))

cfg = VendusConfig.load(os.environ)
if cfg.mode != "tests":
    sys.exit("RECUSADO: corre o spike apenas com VENDUS_MODE=tests em backend/.env.")

READONLY = os.environ.get("SPIKE_READONLY") == "1"
PIN_ROOM = os.environ.get("SPIKE_ROOM_ID")
PIN_TABLE = os.environ.get("SPIKE_TABLE_ID")

client = VendusClient(cfg)


def _total(doc: dict):
    for k in ("amount_gross", "amount", "total"):
        if doc.get(k) is not None:
            return doc.get(k)
    return "?"


try:
    print("== 1) Salas e mesas ==")
    rooms = client.list_rooms()
    if not rooms:
        sys.exit("Sem salas. Ativa o módulo de restauração e configura salas/mesas no Vendus.")
    room_id = int(PIN_ROOM) if PIN_ROOM else rooms[0]["id"]
    tables = client.list_tables(room_id)
    if not tables:
        sys.exit(f"Sem mesas na sala {room_id}.")
    table_id = int(PIN_TABLE) if PIN_TABLE else tables[0]["id"]
    print(f"  sala={room_id}  mesa={table_id}  (register={cfg.register_id})")

    if not READONLY:
        print("\n== 2) APPEND: dois POST DC na mesma mesa ==")
        d1 = client.create_table_order(
            room_id=room_id, table_id=table_id, occupation=1,
            items=[{"title": "SPIKE Item A", "qty": 1, "gross_price": 1.00, "tax_id": "NOR"}],
            external_reference="spike-1",
        )
        d2 = client.create_table_order(
            room_id=room_id, table_id=table_id, occupation=1,
            items=[{"title": "SPIKE Item B", "qty": 1, "gross_price": 2.00, "tax_id": "NOR"}],
            external_reference="spike-2",
        )
        print(f"  doc1 id={d1.get('id')} number={d1.get('number')}")
        print(f"  doc2 id={d2.get('id')} number={d2.get('number')}")
        print(f"  >>> MESMO documento? {d1.get('id') == d2.get('id')}")
    else:
        print("\n== 2) (SPIKE_READONLY: não cria DC; só lê o estado atual) ==")

    print("\n== 3) Conta da mesa (DC detalhados de hoje, filtrados por rest_table) ==")
    today = date.today().isoformat()
    docs = client.list_open_table_docs(since=today)
    mine = [d for d in docs if str(d.get("rest_table")) == str(table_id)]
    print(f"  DC para a mesa {table_id}: {len(mine)} documento(s)")
    for d in mine:
        items = d.get("items") or []
        print(f"   - id={d.get('id')} itens={len(items)} total={_total(d)}")
        for it in items:
            print(f"       · {it.get('title')}  x{it.get('qty')}  {it.get('gross_price')}")

    print("\n== 4) PASSOS MANUAIS (regista no doc de resultados) ==")
    print("  a) No POS do Vendus, adiciona 1 item à MESMA mesa. Depois corre:")
    print("       SPIKE_READONLY=1 python scripts/vendus_spike.py")
    print("     -> o item aparece no MESMO documento (secção 3)?  => R3-b")
    print("  b) No POS, fatura a mesa (FT/FR). Depois corre de novo o comando acima.")
    print("     -> a mesa deixou de ter DC aberto? surge um FT/FR?  => R3-c")
    print("\nSpike terminado. Preenche docs/superpowers/specs/2026-07-19-vendus-spike-resultados.md")

except VendusError as e:
    sys.exit(f"Erro Vendus: {type(e).__name__}: {e}")
finally:
    client.close()
