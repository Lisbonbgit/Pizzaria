"""Faturação do balcão — o DESCONTO GLOBAL tem de chegar à FS.

O desconto global (%) do balcão combina-se com o desconto próprio de cada
linha (`pos.pricing.combine_global`) e vai ao Vendus linha a linha — nunca um
abatimento por fora. Este teste prende o valor que sai para o Vendus: é o
caminho do dinheiro, e um `0` esquecido na ligação passava despercebido.
"""
import asyncio

import server
from server import create_token, create_pos_token, checkout_counter_order, CounterCheckoutRequest


class _Cursor:
    def __init__(self, docs): self._docs = list(docs)
    def __aiter__(self):
        async def gen():
            for d in self._docs:
                yield d
        return gen()


class _Coll:
    def __init__(self, one=None, many=None):
        self._one, self._many = one, many or []
        self.updated = None
        self.inserted = []
    async def find_one(self, q, projection=None): return self._one
    def find(self, q, projection=None): return _Cursor(self._many)
    async def update_one(self, q, u, **k): self.updated = u.get("$set")
    async def insert_one(self, d): self.inserted.append(d)
    async def insert_many(self, d, **k): self.inserted.extend(d)


class _Db:
    def __init__(self, order):
        self.orders = _Coll(one=order)
        self.products = _Coll(many=[])
        self.cash_sessions = _Coll(one=None)      # sem caixa: admin passa à mesma
        self.split_plans = _Coll(one=None)        # sem divisão a meio
        self.pos_sales = _Coll()
        self.print_jobs = _Coll()


class _FakeVendus:
    """Guarda o que lhe mandaram emitir, para o teste inspecionar."""
    ultima = {}
    def list_app_invoices(self, date=None): return []
    def create_invoice(self, items, payments, client, external_reference, doc_type, output):
        _FakeVendus.ultima = {"items": items, "payments": payments}
        return {"id": "d1", "number": "FS 1/1", "output": None}
    def close(self): pass


def _corre(order, pct, monkeypatch, euros=0):
    db = _Db(order)
    monkeypatch.setattr(server, "db", db)
    monkeypatch.setattr(server, "_vendus_client", lambda *a, **k: _FakeVendus())
    admin = create_token("a1", "gestor@lenhaebrasa.com")
    pos_token = create_pos_token("op-1", "Ana")
    body = CounterCheckoutRequest(order_id="o1", payment_method_id=1,
                                  global_discount_pct=pct,
                                  global_discount_amount=euros)
    return asyncio.run(checkout_counter_order(
        body, authorization=f"Bearer {admin}", x_device_token=None,
        x_pos_token=pos_token))


def _order():
    return {"id": "o1", "source": "balcao", "paid": False, "status": "received",
            "items": [{"product_id": "p1", "product_name": "Pizza", "quantity": 1,
                       "unit_price": 20.0, "total_price": 20.0, "vendus_tax_id": "INT"}]}


def test_sem_desconto_global_cobra_o_total(monkeypatch):
    res = _corre(_order(), 0, monkeypatch)
    assert res["total"] == 20.0
    assert _FakeVendus.ultima["payments"][0]["amount"] == 20.0


def test_desconto_global_chega_a_fatura(monkeypatch):
    res = _corre(_order(), 10, monkeypatch)
    # 20,00 − 10% = 18,00, tanto no que se cobra como no que vai para o Vendus.
    assert res["total"] == 18.0
    assert _FakeVendus.ultima["payments"][0]["amount"] == 18.0
    # E o desconto vai NA LINHA (o Vendus recebe-o), não por fora.
    assert _FakeVendus.ultima["items"][0].get("discount_percentage") == 10


def test_desconto_em_euros_chega_a_fatura(monkeypatch):
    # 20,00 com 5,00 de desconto = 15,00, tanto no que se cobra como no Vendus.
    res = _corre(_order(), 0, monkeypatch, euros=5.0)
    assert res["total"] == 15.0
    assert _FakeVendus.ultima["payments"][0]["amount"] == 15.0


def test_euros_tem_precedencia_sobre_percentagem(monkeypatch):
    # Se vierem os dois, manda o valor em euros (é o mais explícito).
    res = _corre(_order(), 50, monkeypatch, euros=2.0)
    assert res["total"] == 18.0
