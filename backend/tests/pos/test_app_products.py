"""Filtragem/extração dos produtos "App" do Vendus — lógica pura, sem I/O.

`extract_app_products` alimenta o import de "Venda Aplicações" no catálogo do
balcão (server.py: POST /admin/pos/import-app-products).
"""
from pos.app_products import extract_app_products, is_app_product


def test_filtra_so_produtos_com_app_no_titulo():
    vprods = [
        {"title": "Pizza Calabresa App", "gross_price": 18.40, "tax_id": "INT", "reference": "PZ-APP-1"},
        {"title": "Pizza Calabresa", "gross_price": 12.50, "tax_id": "INT", "reference": "PZ-1"},
        {"title": "Coca-Cola 33cl", "gross_price": 2.50, "tax_id": "NOR", "reference": "BEB-1"},
    ]
    out = extract_app_products(vprods)
    assert len(out) == 1
    assert out[0]["name"] == "Pizza Calabresa App"


def test_filtro_e_case_insensitive():
    vprods = [{"title": "Sumo APP Laranja", "gross_price": 3.0, "tax_id": "NOR", "reference": "S1"}]
    out = extract_app_products(vprods)
    assert len(out) == 1


def test_extrai_preco_iva_e_referencia_do_gross_price():
    vprods = [{"title": "Pizza Marguerita App", "gross_price": 15.9, "tax_id": "INT", "reference": "PZ-APP-2"}]
    out = extract_app_products(vprods)[0]
    assert out["base_price"] == 15.9
    assert out["vendus_tax_id"] == "INT"
    assert out["vendus_reference"] == "PZ-APP-2"


def test_produto_sem_titulo_e_ignorado():
    vprods = [{"title": "", "gross_price": 10.0, "tax_id": "NOR", "reference": "X"}, None and {}]
    out = extract_app_products([v for v in vprods if v is not None])
    assert out == []


def test_produto_sem_preco_ou_referencia_nao_rebenta():
    vprods = [{"title": "Água App"}]
    out = extract_app_products(vprods)
    assert out == [{
        "name": "Água App", "base_price": 0.0, "vendus_tax_id": None, "vendus_reference": None,
    }]


def test_lista_vazia_devolve_lista_vazia():
    assert extract_app_products([]) == []


# --- is_app_product: predicado partilhado (o import geral do menu SALTA estes,
#     para não puxar os preços de delivery de volta ao menu do cliente) ---

def test_is_app_product_reconhece_app_case_insensitive():
    assert is_app_product("Pizza Calabresa App") is True
    assert is_app_product("Sumo APP Laranja") is True
    assert is_app_product("  Água App  ") is True


def test_is_app_product_falso_para_normais_e_vazios():
    assert is_app_product("Pizza Calabresa") is False
    assert is_app_product("Coca-Cola 33cl") is False
    assert is_app_product("") is False
    assert is_app_product(None) is False


def test_is_app_product_alinhado_com_extract():
    # O que o extract inclui é exatamente o que is_app_product marca True.
    vprods = [
        {"title": "Pizza Calabresa App", "gross_price": 18.4},
        {"title": "Pizza Calabresa", "gross_price": 12.5},
    ]
    incluidos = {p["name"] for p in extract_app_products(vprods)}
    marcados = {vp["title"] for vp in vprods if is_app_product(vp["title"])}
    assert incluidos == marcados == {"Pizza Calabresa App"}
