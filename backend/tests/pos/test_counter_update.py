"""Atualizar um pedido de balcão já impresso (Fase 3): substitui itens +
reimprime só na cozinha; recusa pedido pago/cancelado."""
import asyncio

import pytest
from fastapi import HTTPException

import server
from server import create_token, create_pos_token, update_counter_order, CounterOrderRequest, CounterOrderItem


class _Cursor:
    def __init__(self, docs):
        self._docs = docs
    async def to_list(self, n):
        return list(self._docs)


class _Orders:
    def __init__(self, order):
        self.order = order
        self.updated = None
    async def find_one(self, query, projection=None):
        if query.get("id") == self.order.get("id") and self.order.get("source") == "balcao":
            return dict(self.order)
        return None
    async def update_one(self, query, update):
        # aplica só se o pedido bate o filtro (paid:false, status != cancelled)
        ok = (self.order.get("paid") in (False, None)) and self.order.get("status") != "cancelled"
        if query.get("paid") is False and not ok:
            class R: matched_count = 0
            return R()
        self.order.update(update["$set"])
        self.updated = update["$set"]
        class R: matched_count = 1
        return R()


class _PrintJobs:
    def __init__(self):
        self.inserted = []
    async def insert_one(self, doc):
        self.inserted.append(doc)


class _Simple:
    def __init__(self, one=None, many=None):
        self._one = one
        self._many = many or []
    async def find_one(self, query, projection=None):
        return self._one
    def find(self, query, projection=None):
        return _Cursor(self._many)


class _FakeDb:
    def __init__(self, order, products, open_session=None, printers=None):
        self.orders = _Orders(order)
        self.products = _Simple(many=products)
        self.cash_sessions = _Simple(one=open_session)
        self.printers = _Simple(many=printers or [])
        self.print_jobs = _PrintJobs()


def _req():
    return CounterOrderRequest(items=[CounterOrderItem(product_id="p1", quantity=2)])


def test_update_substitui_itens_e_reimprime_so_cozinha(monkeypatch):
    order = {"id": "o1", "source": "balcao", "order_number": 7, "paid": False,
             "status": "received", "items": [], "total": 0.0}
    products = [{"id": "p1", "name": "Pizza", "base_price": 10.0, "vendus_tax_id": "INT"}]
    fake = _FakeDb(order, products)
    monkeypatch.setattr(server, "db", fake)

    admin = create_token("admin-1", "gestor@lenhaebrasa.com")   # kind=admin -> salta require_open_cash
    pos_token = create_pos_token("op-1", "Ana")

    async def run():
        return await update_counter_order("o1", _req(), authorization=f"Bearer {admin}",
                                          x_device_token=None, x_pos_token=pos_token)
    res = asyncio.run(run())

    assert res["order_number"] == 7
    assert res["total"] == 20.0
    assert order["total"] == 20.0 and len(order["items"]) == 1   # substituiu na "BD"
    # reimprimiu SÓ cozinha, com is_update, e nunca um talão de caixa
    jobs = fake.print_jobs.inserted
    assert len(jobs) == 1
    assert jobs[0]["printer_type"] == "kitchen"
    assert jobs[0]["order_snapshot"]["is_update"] is True
    assert all(j["printer_type"] != "cashier" for j in jobs)


def test_update_recusa_pedido_pago(monkeypatch):
    order = {"id": "o1", "source": "balcao", "order_number": 7, "paid": True,
             "status": "delivered", "items": [{"product_name": "X", "quantity": 1}], "total": 5.0}
    fake = _FakeDb(order, [{"id": "p1", "name": "Pizza", "base_price": 10.0}])
    monkeypatch.setattr(server, "db", fake)
    admin = create_token("admin-1", "gestor@lenhaebrasa.com")
    pos_token = create_pos_token("op-1", "Ana")

    async def run():
        return await update_counter_order("o1", _req(), authorization=f"Bearer {admin}",
                                          x_device_token=None, x_pos_token=pos_token)
    with pytest.raises(HTTPException) as exc:
        asyncio.run(run())
    assert exc.value.status_code == 400
    assert fake.print_jobs.inserted == []   # não reimprimiu nada
