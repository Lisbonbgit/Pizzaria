"""Meia-meia de ponta a ponta no servidor: o pedido público (QR e mesa) e o balcão.

Na rota pública o SERVIDOR faz a conta (o preço do browser é ignorado) e monta o
nome e as metades; no balcão (POS autenticado) valida e mantém o preço do POS."""
import asyncio

import pytest
from fastapi import HTTPException

import server
from pos.counter import build_counter_items
from server import (CounterOrderItem, CounterOrderRequest, OrderCreate, OrderItemCreate,
                    create_counter_order, create_order, create_pos_token, create_token)
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


def test_pedido_misto_o_total_soma_todas_as_linhas(db):
    # meia-meia + pizza normal no mesmo pedido: o total é a soma das DUAS linhas
    normal = OrderItemCreate(product_id="p-marg", product_name="Margherita", quantity=1,
                             variation={"name": MEDIA, "price": 12.9}, unit_price=12.9, total_price=12.9)
    _pede([_item(), normal], total=1.0)
    itens = db.orders.docs[0]["items"]
    assert itens[0]["unit_price"] == 18.9 and itens[1]["total_price"] == 12.9
    assert db.orders.docs[0]["total"] == round(sum(i["total_price"] for i in itens), 2) == 31.8


# --- Balcão (POS autenticado): valida as metades, o preço é o do POS -------------

def test_build_counter_items_monta_nome_e_guarda_metades():
    metades = [{"product_id": "p-marg", "product_name": "Margherita"},
               {"product_id": "p-frango", "product_name": "Frango Com Catupiry"}]
    out = build_counter_items({"p-marg": MARG}, [{"product_id": "p-marg", "quantity": 1,
                                                  "unit_price": 21.9, "variation_name": GRANDE,
                                                  "halves": metades}])
    it = out["items"][0]
    assert it["product_name"] == "1/2 Margherita + 1/2 Frango Com Catupiry"
    assert it["halves"] == metades and it["unit_price"] == 21.9


def _balcao(db, item):
    admin = create_token("a1", "gestor@lenhaebrasa.com")
    return asyncio.run(create_counter_order(
        CounterOrderRequest(items=[item]), authorization=f"Bearer {admin}",
        x_device_token=None, x_pos_token=create_pos_token("op-1", "Ana")))


def test_balcao_valida_e_mantem_o_preco_do_pos(db):
    _balcao(db, CounterOrderItem(product_id="p-marg", quantity=1, variation_name=GRANDE,
                                 unit_price=20.0, half_product_id="p-frango"))
    it = db.orders.docs[0]["items"][0]
    assert it["product_name"] == "1/2 Margherita + 1/2 Frango Com Catupiry"
    assert it["unit_price"] == 20.0                 # o staff pode ter mudado o preço
    assert len(it["halves"]) == 2


def test_balcao_recusa_meia_meia_invalida(db):
    with pytest.raises(HTTPException) as e:
        _balcao(db, CounterOrderItem(product_id="p-marg", quantity=1, variation_name=GRANDE,
                                     unit_price=20.0, half_product_id="p-coca"))
    assert e.value.status_code == 400


def test_balcao_update_tambem_valida(db):
    from server import update_counter_order
    db.orders.docs.append({"id": "b1", "source": "balcao", "paid": False,
                           "status": "received", "items": []})
    admin = create_token("a1", "gestor@lenhaebrasa.com")
    with pytest.raises(HTTPException) as e:
        asyncio.run(update_counter_order(
            "b1", CounterOrderRequest(items=[CounterOrderItem(
                product_id="p-marg", quantity=1, variation_name=GRANDE, unit_price=20.0,
                half_product_id="p-coca")]),
            authorization=f"Bearer {admin}", x_device_token=None,
            x_pos_token=create_pos_token("op-1", "Ana")))
    assert e.value.status_code == 400


def test_balcao_update_guarda_as_metades_e_o_preco_do_pos(db, monkeypatch):
    from types import SimpleNamespace
    from server import update_counter_order
    db.printers, db.print_jobs = _Coll(), _Coll()
    db.orders.docs.append({"id": "b1", "source": "balcao", "paid": False,
                           "status": "received", "order_number": 7, "items": []})
    escrita = db.orders.update_one

    async def com_match(q, u, **k):                 # o duplo devolve None; o código lê matched_count
        await escrita(q, u, **k)
        return SimpleNamespace(matched_count=1)
    monkeypatch.setattr(db.orders, "update_one", com_match)
    admin = create_token("a1", "gestor@lenhaebrasa.com")
    out = asyncio.run(update_counter_order(
        "b1", CounterOrderRequest(items=[CounterOrderItem(
            product_id="p-marg", quantity=1, variation_name=GRANDE, unit_price=20.0,
            half_product_id="p-frango")]),
        authorization=f"Bearer {admin}", x_device_token=None,
        x_pos_token=create_pos_token("op-1", "Ana")))
    it = db.orders.docs[0]["items"][0]
    assert it["product_name"] == "1/2 Margherita + 1/2 Frango Com Catupiry"
    assert len(it["halves"]) == 2 and it["unit_price"] == 20.0
    assert out["items"][0]["halves"] == it["halves"]
