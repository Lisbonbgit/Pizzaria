"""Pedido de balcão (POS) — montagem de itens e total, lógica pura.

`build_counter_items` monta os itens {title,qty,gross_price,tax_id} e o total
a partir do carrinho ([{product_id,quantity}]) e do catálogo de produtos
({product_id: {name,base_price,vendus_tax_id}}), tal como especificado no
Passo 1 do brief da Task 1 (Fase 2). `counter_ext_ref` é a referência externa
estável usada pela integração fiscal (idempotência, à semelhança de
`external_reference` no fecho de mesa).
"""
from pos.counter import build_counter_items, counter_ext_ref


def test_build_items_e_total():
    prods = {"p1": {"name": "Imperial", "base_price": 2.0, "vendus_tax_id": "NOR"},
             "p2": {"name": "Pizza", "base_price": 13.9, "vendus_tax_id": "INT"}}
    cart = [{"product_id": "p1", "quantity": 2}, {"product_id": "p2", "quantity": 1}]
    r = build_counter_items(prods, cart, default_tax="NOR")
    assert r["total"] == 17.9
    assert r["items"][0] == {"title": "Imperial", "qty": 2, "gross_price": 2.0, "tax_id": "NOR"}


def test_ext_ref_estavel():
    assert counter_ext_ref("abc") == "balcao-abc"


def test_ignora_product_id_inexistente():
    # Entrada do carrinho cujo produto já não existe no catálogo é ignorada,
    # em vez de rebentar (ex: produto removido entre o carrinho e o envio).
    prods = {"p1": {"name": "Imperial", "base_price": 2.0, "vendus_tax_id": "NOR"}}
    cart = [{"product_id": "p1", "quantity": 1}, {"product_id": "fantasma", "quantity": 5}]
    r = build_counter_items(prods, cart, default_tax="NOR")
    assert r["items"] == [{"title": "Imperial", "qty": 1, "gross_price": 2.0, "tax_id": "NOR"}]
    assert r["total"] == 2.0


def test_usa_default_tax_quando_produto_sem_vendus_tax_id():
    # Produto sem vendus_tax_id (ainda não migrado) cai no imposto por defeito.
    prods = {"p1": {"name": "Água", "base_price": 1.5, "vendus_tax_id": None}}
    cart = [{"product_id": "p1", "quantity": 3}]
    r = build_counter_items(prods, cart, default_tax="NOR")
    assert r["items"][0]["tax_id"] == "NOR"
    assert r["total"] == 4.5
