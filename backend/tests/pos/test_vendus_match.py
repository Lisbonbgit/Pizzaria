"""Casamento produto da app -> artigo oficial do Vendus (por nome normalizado)."""
from pos.vendus_match import is_official, norm, match_products


def test_is_official_exclui_lixo_auto_gerado():
    assert is_official("Pizza Calabresa") is True
    assert is_official("V5-Q231-26073157") is False
    assert is_official("VAGU143-26072239") is False


def test_norm_remove_pizza_acentos_tamanho():
    assert norm("Calabresa") == norm("Pizza Calabresa")
    assert norm("Compal Maracujá") == norm("Compal de Maracuja")


def test_match_casa_por_nome_e_prefere_nao_app():
    app = [{"id": "p1", "name": "Calabresa", "base_price": 13.9}]
    vendus = [
        {"id": 1, "title": "Pizza Calabresa App", "reference": "Pizza Calabresa App", "gross_price": 18.4},
        {"id": 2, "title": "Pizza Calabresa", "reference": "Pizza Calabresa", "gross_price": 13.9},
        {"id": 3, "title": "V5-Q231-26073157", "reference": "V5-Q231-26073157", "gross_price": 0},
    ]
    out = match_products(app, vendus)
    assert len(out) == 1
    assert out[0]["status"] == "matched"
    assert out[0]["match"]["id"] == 2            # preferiu o SEM "App"
    assert out[0]["app_price"] == 13.9
    assert out[0]["match"]["price"] == 13.9


def test_match_sem_correspondencia():
    app = [{"id": "p9", "name": "Produto Inexistente", "base_price": 5}]
    vendus = [{"id": 1, "title": "Pizza Calabresa", "reference": "Pizza Calabresa", "gross_price": 13.9}]
    out = match_products(app, vendus)
    assert out[0]["status"] == "none"
    assert out[0]["match"] is None
