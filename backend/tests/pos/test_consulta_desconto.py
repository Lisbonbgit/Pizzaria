"""Consulta de mesa impressa TEM de trazer o desconto da linha.

Defeito relatado pelo dono: dava desconto na mesa, pedia a consulta, e o
desconto não saía. A causa era a conta ser calculada em DOIS sítios — o
`_open_bill_lines` descontava, a consulta não — e a consulta imprimia o valor
cheio. Agora os dois usam `item_net_total`.
"""
import asyncio

import server
from pos.pricing import item_net_total
from server import ESCPOSFormatter, create_token


# ---- a regra, isolada ----

def test_desconto_em_percentagem():
    assert item_net_total({"total_price": 20.0, "discount_pct": 10}) == (20.0, 18.0)


def test_desconto_em_euros():
    assert item_net_total({"total_price": 20.0, "discount_amount": 5}) == (20.0, 15.0)


def test_sem_desconto_fica_igual():
    assert item_net_total({"total_price": 13.9}) == (13.9, 13.9)


def test_nunca_fica_negativo():
    assert item_net_total({"total_price": 10.0, "discount_amount": 999})[1] == 0.0


# ---- o defeito: a consulta impressa ----

class _Coll:
    def __init__(self, many=None): self._many = many or []; self.inserted = []
    def find(self, q, p=None):
        docs = self._many
        class C:
            async def to_list(self, n): return docs
        return C()
    async def insert_one(self, d): self.inserted.append(d)


class _Db:
    def __init__(self): self.printers = _Coll(); self.print_jobs = _Coll()


def test_consulta_impressa_traz_o_desconto(monkeypatch):
    # Pizza de 20,00 com 25% de desconto -> a consulta tem de dizer 15,00.
    orders = [{"id": "o1", "source": "client", "items": [
        {"product_name": "Pizza", "quantity": 1, "unit_price": 20.0,
         "total_price": 20.0, "discount_pct": 25},
    ]}]
    db = _Db()
    monkeypatch.setattr(server, "db", db)
    async def _orders(n): return orders
    async def _sess(n): return None
    monkeypatch.setattr(server, "_open_orders_for_table", _orders)
    monkeypatch.setattr(server, "_open_session", _sess)

    admin = create_token("a1", "gestor@lenhaebrasa.com")
    res = asyncio.run(server.print_table_consulta(
        1, authorization=f"Bearer {admin}", x_device_token=None))

    assert res["total"] == 15.0, "a consulta mostrava o valor cheio"
    snap = db.print_jobs.inserted[0]["order_snapshot"]
    assert snap["items"][0]["total_price"] == 15.0
    assert snap["total"] == 15.0


def test_talao_da_consulta_mostra_o_abatimento():
    out = ESCPOSFormatter().format_cashier({
        "order_number": "CONSULTA", "table_number": 1, "total": 15.0,
        "created_at": "2026-10-08T18:00:00+00:00",
        "items": [{"product_name": "Pizza", "quantity": 1, "unit_price": 20.0,
                   "total_price": 15.0, "gross_total": 20.0, "discount_pct": 25}],
    })
    assert b"desconto" in out and b"25%" in out
