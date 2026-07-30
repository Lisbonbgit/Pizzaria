"""Pedido de balcão (POS) — montagem de itens e total, lógica pura.

`build_counter_items` monta os itens no formato `OrderItem`
({product_id,product_name,quantity,unit_price,total_price,vendus_tax_id}) e o
total a partir do carrinho ([{product_id,quantity}]) e do catálogo de
produtos ({product_id: {name,base_price,vendus_tax_id}}) — o mesmo formato
que os formatadores ESC/POS (cozinha/caixa) e o dashboard já esperam, tal
como corrigido no review da Task 1 (Fase 2): os itens de balcão tinham um
formato próprio ({title,qty,gross_price,tax_id}) que os talões não sabiam
ler. `counter_ext_ref` é a referência externa estável usada pela integração
fiscal (idempotência, à semelhança de `external_reference` no fecho de
mesa).
"""
from pos.counter import build_counter_items, counter_ext_ref


def test_build_items_e_total():
    prods = {"p1": {"name": "Imperial", "base_price": 2.0, "vendus_tax_id": "NOR"},
             "p2": {"name": "Pizza", "base_price": 13.9, "vendus_tax_id": "INT"}}
    cart = [{"product_id": "p1", "quantity": 2}, {"product_id": "p2", "quantity": 1}]
    r = build_counter_items(prods, cart, default_tax="NOR")
    assert r["total"] == 17.9
    assert r["items"][0] == {
        "product_id": "p1",
        "product_name": "Imperial",
        "quantity": 2,
        "unit_price": 2.0,
        "total_price": 4.0,
        "vendus_tax_id": "NOR",
    }


# --- Overrides do staff (diálogo do produto no balcão): preço/IVA/desconto ---

def test_override_preco_e_iva():
    prods = {"p1": {"name": "Pizza", "base_price": 13.9, "vendus_tax_id": "INT"}}
    cart = [{"product_id": "p1", "quantity": 2, "unit_price": 10.0, "vendus_tax_id": "NOR"}]
    r = build_counter_items(prods, cart)
    it = r["items"][0]
    assert it["unit_price"] == 10.0            # override do preço ganha ao base_price
    assert it["vendus_tax_id"] == "NOR"        # override do IVA ganha ao do produto
    assert it["total_price"] == 20.0           # bruto = 10×2
    assert r["total"] == 20.0                  # sem desconto: líquido = bruto


def test_override_desconto_percentagem():
    prods = {"p1": {"name": "Pizza", "base_price": 20.0, "vendus_tax_id": "INT"}}
    cart = [{"product_id": "p1", "quantity": 1, "discount_pct": 10}]
    r = build_counter_items(prods, cart)
    it = r["items"][0]
    assert it["total_price"] == 20.0           # bruto mantém-se
    assert it["discount_pct"] == 10
    assert "discount_amount" not in it
    assert r["total"] == 18.0                  # líquido = 20 − 10%


def test_override_desconto_euros_tem_precedencia():
    prods = {"p1": {"name": "Pizza", "base_price": 20.0, "vendus_tax_id": "INT"}}
    cart = [{"product_id": "p1", "quantity": 1, "discount_amount": 5.0, "discount_pct": 10}]
    r = build_counter_items(prods, cart)
    it = r["items"][0]
    assert it["discount_amount"] == 5.0        # € ganha ao %
    assert "discount_pct" not in it
    assert r["total"] == 15.0                  # líquido = 20 − 5€


def test_sem_overrides_usa_produto():
    prods = {"p1": {"name": "Imperial", "base_price": 2.0, "vendus_tax_id": "NOR"}}
    cart = [{"product_id": "p1", "quantity": 3}]
    r = build_counter_items(prods, cart)
    it = r["items"][0]
    assert it["unit_price"] == 2.0 and it["vendus_tax_id"] == "NOR"
    assert "discount_pct" not in it and "discount_amount" not in it
    assert r["total"] == 6.0


def test_ext_ref_estavel():
    assert counter_ext_ref("abc") == "balcao-abc"


def test_ext_ref_idempotente_entre_pedido_e_faturacao():
    # A referência externa é a CHAVE de idempotência fiscal do balcão: a mesma
    # que o pedido usa (Task 1) tem de ser a mesma que a faturação recalcula
    # (Task 2), senão o dedup no Vendus não encontrava a FS de um retry e
    # emitia uma 2ª = cobrança dupla. Deriva SÓ do order_id (estável, único),
    # sem relógio nem sessão — mesmo pedido → mesma ref, sempre.
    order_id = "5f1c9b2a-0000-4a11-9c33-abcdef012345"
    ref_no_pedido = counter_ext_ref(order_id)          # calculada ao criar o pedido
    ref_na_faturacao = counter_ext_ref(order_id)        # recalculada no checkout
    assert ref_no_pedido == ref_na_faturacao
    # Pedidos DISTINTOS → refs distintas (nunca reutilizar a FS de outro pedido).
    assert counter_ext_ref("pedido-a") != counter_ext_ref("pedido-b")


def test_ignora_product_id_inexistente():
    # Entrada do carrinho cujo produto já não existe no catálogo é ignorada,
    # em vez de rebentar (ex: produto removido entre o carrinho e o envio).
    prods = {"p1": {"name": "Imperial", "base_price": 2.0, "vendus_tax_id": "NOR"}}
    cart = [{"product_id": "p1", "quantity": 1}, {"product_id": "fantasma", "quantity": 5}]
    r = build_counter_items(prods, cart, default_tax="NOR")
    assert r["items"] == [{
        "product_id": "p1",
        "product_name": "Imperial",
        "quantity": 1,
        "unit_price": 2.0,
        "total_price": 2.0,
        "vendus_tax_id": "NOR",
    }]
    assert r["total"] == 2.0


def test_mantem_vendus_tax_id_none_quando_produto_sem_imposto():
    # Produto sem vendus_tax_id (ainda não migrado) mantém None aqui — a
    # resolução do imposto por defeito é feita na faturação (Task 2), não
    # na montagem dos itens.
    prods = {"p1": {"name": "Água", "base_price": 1.5, "vendus_tax_id": None}}
    cart = [{"product_id": "p1", "quantity": 3}]
    r = build_counter_items(prods, cart, default_tax="NOR")
    assert r["items"][0]["vendus_tax_id"] is None
    assert r["total"] == 4.5
