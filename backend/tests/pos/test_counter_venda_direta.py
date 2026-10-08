"""Venda direta no balcão: faturar sem mandar talão para a cozinha.

Há vendas que não passam pela cozinha (uma bebida, um produto já feito). Com
`print_kitchen=False` o pedido é criado na mesma — é preciso para emitir a
fatura — mas NÃO se gera talão de cozinha.
"""
import asyncio

import server
from server import (create_token, create_pos_token, create_counter_order,
                    CounterOrderRequest, CounterOrderItem)


class _Coll:
    def __init__(self, one=None, many=None):
        self._one, self._many = one, many or []
        self.inserted = []
    async def find_one(self, q, p=None): return self._one
    def find(self, q, p=None):
        docs = self._many
        class C:
            async def to_list(self, n): return docs
        return C()
    async def insert_one(self, d): self.inserted.append(d)
    async def count_documents(self, q): return 0


class _Db:
    def __init__(self, produtos):
        self.orders = _Coll()
        self.products = _Coll(many=produtos)
        self.cash_sessions = _Coll(one={"id": "s1"})
        self.printers = _Coll(many=[])
        self.print_jobs = _Coll()


def _vende(print_kitchen, monkeypatch):
    db = _Db([{"id": "p1", "name": "Imperial", "base_price": 2.0, "vendus_tax_id": "NOR"}])
    monkeypatch.setattr(server, "db", db)
    chamadas = []
    async def espia(order_id): chamadas.append(order_id)
    monkeypatch.setattr(server, "_enqueue_order_prints", espia)

    admin = create_token("a1", "gestor@lenhaebrasa.com")
    body = CounterOrderRequest(
        items=[CounterOrderItem(product_id="p1", quantity=1)],
        print_kitchen=print_kitchen)

    async def run():
        return await create_counter_order(
            body, authorization=f"Bearer {admin}", x_device_token=None,
            x_pos_token=create_pos_token("op-1", "Ana"))
    res = asyncio.run(run())
    return res, chamadas, db


def test_venda_direta_nao_imprime_na_cozinha(monkeypatch):
    res, chamadas, db = _vende(False, monkeypatch)
    assert chamadas == [], "não devia ter mandado nada para a cozinha"
    assert db.orders.inserted, "mas o pedido TEM de existir (é preciso para faturar)"
    assert res["total"] == 2.0


def test_pedido_normal_continua_a_imprimir(monkeypatch):
    res, chamadas, _ = _vende(True, monkeypatch)
    assert len(chamadas) == 1, "o fluxo normal tem de continuar a imprimir"
