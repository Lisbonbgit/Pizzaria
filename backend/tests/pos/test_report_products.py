"""Agregação de produtos vendidos (quantidade + valor €) para o backoffice."""
from pos.report import summarize_products


def test_agrega_quantidade_e_valor_a_la_carte_e_desconto():
    orders = [
        {"items": [
            {"product_name": "Pizza", "quantity": 2, "unit_price": 10.0},
            {"product_name": "Água", "quantity": 1, "unit_price": 1.5},
        ]},
        {"items": [
            {"product_name": "Pizza", "quantity": 1, "unit_price": 10.0, "discount_pct": 50},
        ]},
    ]
    out = summarize_products(orders, "NOR")
    by = {r["name"]: r for r in out}
    assert by["Pizza"]["quantity"] == 3
    assert by["Pizza"]["revenue"] == 25.0   # 2*10 + 1*10*0.5
    assert by["Água"]["revenue"] == 1.5


def test_rodizio_incluido_conta_quantidade_mas_valor_zero():
    orders = [{"items": [
        {"product_name": "Costela (rodízio)", "quantity": 3, "unit_price": 0.0},
    ]}]
    out = summarize_products(orders, "NOR")
    assert out[0]["quantity"] == 3
    assert out[0]["revenue"] == 0.0


def test_ignora_itens_anulados():
    orders = [{"items": [
        {"product_name": "X", "quantity": 1, "unit_price": 5.0, "removed": True},
        {"product_name": "Y", "quantity": 1, "unit_price": 3.0},
    ]}]
    out = summarize_products(orders, "NOR")
    assert {r["name"] for r in out} == {"Y"}


def test_meia_meia_conta_meia_pizza_a_cada_sabor():
    from pos.report import summarize_products
    pedidos = [{"items": [
        {"product_name": "Margherita", "quantity": 2, "unit_price": 12.9, "total_price": 25.8},
        {"product_name": "1/2 Margherita + 1/2 Frango", "quantity": 1, "unit_price": 18.9,
         "total_price": 18.9,
         "halves": [{"product_id": "a", "product_name": "Margherita"},
                    {"product_id": "b", "product_name": "Frango"}]},
    ]}]
    rows = {r["name"]: r for r in summarize_products(pedidos, "INT")}
    assert rows["Margherita"]["quantity"] == 2.5
    assert rows["Frango"]["quantity"] == 0.5
    assert rows["Margherita"]["revenue"] == 35.25     # 25,80 + 9,45
    assert rows["Frango"]["revenue"] == 9.45
    assert "1/2 Margherita + 1/2 Frango" not in rows


def test_meia_meia_com_centimo_impar_reparte_sem_perder_o_centimo():
    pedidos = [{"items": [
        {"product_name": "1/2 A + 1/2 B", "quantity": 1, "unit_price": 17.95,
         "halves": [{"product_id": "a", "product_name": "A"},
                    {"product_id": "b", "product_name": "B"}]},
    ]}]
    rows = {r["name"]: r["revenue"] for r in summarize_products(pedidos, "INT")}
    assert rows == {"A": 8.97, "B": 8.98}
    assert round(rows["A"] + rows["B"], 2) == 17.95
