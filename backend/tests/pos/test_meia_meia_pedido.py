"""Meia-meia de ponta a ponta no servidor: o pedido público (QR e mesa) e o balcão.

Na rota pública o SERVIDOR faz a conta (o preço do browser é ignorado) e monta o
nome e as metades; no balcão (POS autenticado) valida e mantém o preço do POS."""
import asyncio

import pytest
from fastapi import HTTPException

import server
from server import OrderCreate, OrderItemCreate, create_order
from tests.pos.test_mesa_divisao import _Coll
from tests.pos.test_meia_meia import COCA, FRANGO, GRANDE, MARG, MEDIA, PIZZAS, pizza

CALAB = pizza("p-calab", "Calabresa", 13.9, 17.9, inc="ambos")


class _Db:
    def __init__(self, sessao=None):
        self.orders = _Coll()
        self.products = _Coll([MARG, FRANGO, CALAB, COCA])
        self.categories = _Coll([PIZZAS, {"id": "c-beb", "name": "Bebidas", "active": True}])
        self.table_sessions = _Coll([sessao] if sessao else [])
        self.cash_sessions = _Coll([{"id": "cx", "status": "open"}])
        self.split_plans = _Coll()


@pytest.fixture
def db(monkeypatch):
    d = _Db()
    monkeypatch.setattr(server, "db", d)

    async def numero():
        return 7

    async def sem_impressao(order_id):
        return None
    monkeypatch.setattr(server, "get_next_order_number", numero)
    monkeypatch.setattr(server, "_enqueue_order_prints", sem_impressao)
    return d


def _item(a=MARG, b=FRANGO, tamanho=GRANDE, preco=1.0, extras=None, qtd=1):
    return OrderItemCreate(product_id=a["id"], product_name=a["name"], quantity=qtd,
                           variation={"name": tamanho, "price": 0}, extras=extras or [],
                           unit_price=preco, total_price=preco * qtd,
                           half_product_id=b["id"] if b else None)


def _pede(itens, total=1.0):
    return asyncio.run(create_order(OrderCreate(table_id="t-4", table_number=4,
                                                items=itens, total=total)))


def test_servidor_calcula_preco_nome_e_metades(db):
    _pede([_item(extras=[{"name": "Borda de Catupiry", "price": 0}], qtd=2)])
    it = db.orders.docs[0]["items"][0]
    assert it["product_name"] == "1/2 Margherita + 1/2 Frango Com Catupiry"
    assert it["halves"][1] == {"product_id": "p-frango", "product_name": "Frango Com Catupiry"}
    assert it["unit_price"] == 21.9                  # 18,90 (Frango Grande) + 3,00 borda
    assert it["total_price"] == 43.8
    assert "half_product_id" not in it
    assert db.orders.docs[0]["total"] == 43.8         # o total acompanha


def test_pedido_sem_meia_meia_fica_como_hoje(db):
    normal = OrderItemCreate(product_id="p-marg", product_name="Margherita", quantity=1,
                             variation={"name": MEDIA, "price": 12.9}, unit_price=12.9, total_price=12.9)
    _pede([normal], total=12.9)
    it = db.orders.docs[0]["items"][0]
    assert it["product_name"] == "Margherita" and "halves" not in it
    assert db.orders.docs[0]["total"] == 12.9


def test_combinacao_invalida_da_400(db):
    with pytest.raises(HTTPException) as e:
        _pede([_item(b=COCA)])
    assert e.value.status_code == 400 and "categoria" in e.value.detail
    assert db.orders.docs == []


def test_rodizio_a_zero_so_com_os_dois_incluidos(db):
    db.table_sessions.docs.append({"table_number": 4, "status": "open", "rodizio": "simples"})
    _pede([_item(b=CALAB, tamanho=MEDIA, preco=0.0)])          # os dois "ambos"
    assert db.orders.docs[0]["items"][0]["unit_price"] == 0.0
    with pytest.raises(HTTPException) as e:                     # Frango só no completo
        _pede([_item(b=FRANGO, tamanho=MEDIA, preco=0.0)])
    assert "rodízio" in e.value.detail


def test_zero_euros_fora_do_rodizio_e_recusado(db):
    with pytest.raises(HTTPException):
        _pede([_item(b=CALAB, preco=0.0)])
