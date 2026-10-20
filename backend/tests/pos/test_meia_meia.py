"""Pizza meia-meia — regra pura (pedido do dono 2026-10-20).

Metade de um sabor, metade de outro, da MESMA categoria de pizzas, no MESMO
tamanho; paga-se a metade mais cara; extras uma vez, a preços do catálogo."""
import pytest

from pos.meia_meia import (MeiaMeiaInvalida, categoria_elegivel, incluida_no_rodizio,
                           montar_meia_meia, nome_meia_meia, preco_no_tamanho,
                           preco_unitario)

PIZZAS = {"id": "c-piz", "name": "Pizzas", "active": True}
MEDIA, GRANDE = "Média (6 Fatias)", "Grande (8 Fatias)"


def pizza(pid, nome, media, grande, inc="nao", **extra):
    p = {"id": pid, "name": nome, "category_id": "c-piz", "base_price": media,
         "variations": [{"name": MEDIA, "price": media}, {"name": GRANDE, "price": grande}],
         "extras": [{"name": "Borda de Catupiry", "price": 3.0}],
         "available": True, "rodizio_incluido": inc}
    p.update(extra)
    return p


MARG = pizza("p-marg", "Margherita", 12.9, 16.9, inc="ambos")
FRANGO = pizza("p-frango", "Frango Com Catupiry", 14.9, 18.9, inc="completo")
COCA = {"id": "p-coca", "name": "Coca-Cola", "category_id": "c-beb", "base_price": 3.0,
        "variations": [], "available": True}


def test_paga_se_a_metade_mais_cara_no_tamanho():
    m = montar_meia_meia(MARG, FRANGO, PIZZAS, GRANDE)
    assert m["base_price"] == 18.9
    assert montar_meia_meia(MARG, FRANGO, PIZZAS, MEDIA)["base_price"] == 14.9
    assert montar_meia_meia(FRANGO, MARG, PIZZAS, GRANDE)["base_price"] == 18.9
    assert m["product_name"] == "1/2 Margherita + 1/2 Frango Com Catupiry"
    assert m["halves"] == [{"product_id": "p-marg", "product_name": "Margherita"},
                           {"product_id": "p-frango", "product_name": "Frango Com Catupiry"}]


def test_extras_contam_uma_vez_e_a_preco_do_catalogo():
    # o browser pode mandar o preço do extra que quiser: conta o do catálogo
    assert preco_unitario(18.9, MARG, [{"name": "Borda de Catupiry", "price": 0}], []) == 21.9
    assert preco_unitario(18.9, MARG, [], []) == 18.9


def test_extra_que_a_pizza_nao_tem_e_recusado():
    with pytest.raises(MeiaMeiaInvalida):
        preco_unitario(18.9, MARG, [{"name": "Ouro", "price": 0}], [])


def test_complemento_conta_a_preco_do_catalogo():
    a = dict(MARG, complement_groups=[{"name": "Molho", "items": [{"name": "Picante", "price": 0.5}]}])
    assert preco_unitario(18.9, a, [], [{"group_name": "Molho", "items": [{"name": "Picante", "price": 0}]}]) == 19.4
    with pytest.raises(MeiaMeiaInvalida):
        preco_unitario(18.9, a, [], [{"group_name": "Molho", "items": [{"name": "Nada", "price": 0}]}])


@pytest.mark.parametrize("b, motivo", [
    (MARG, "dois sabores diferentes"),
    (COCA, "mesma categoria"),
    (dict(FRANGO, available=False), "esgotad"),
    (None, "já não existe"),
])
def test_combinacoes_invalidas_sao_recusadas(b, motivo):
    with pytest.raises(MeiaMeiaInvalida) as e:
        montar_meia_meia(MARG, b, PIZZAS, GRANDE)
    assert motivo in str(e.value)


def test_segundo_sabor_tem_de_existir_no_tamanho():
    so_media = dict(FRANGO, variations=[{"name": MEDIA, "price": 14.9}])
    with pytest.raises(MeiaMeiaInvalida) as e:
        montar_meia_meia(MARG, so_media, PIZZAS, GRANDE)
    assert "Grande" in str(e.value)


def test_so_categorias_de_pizza_ativas_e_nao_pos_only():
    assert categoria_elegivel({"name": "Pizzas"})
    assert categoria_elegivel({"name": "Pízzas Doces", "active": True})
    assert not categoria_elegivel({"name": "Bebidas"})
    assert not categoria_elegivel({"name": "Pizzas", "active": False})
    assert not categoria_elegivel({"name": "Pizzas App", "pos_only": True})
    assert not categoria_elegivel(None)
    with pytest.raises(MeiaMeiaInvalida):
        montar_meia_meia(MARG, FRANGO, {"name": "Bebidas"}, GRANDE)


def test_preco_no_tamanho():
    assert preco_no_tamanho(MARG, GRANDE) == 16.9
    assert preco_no_tamanho(MARG, "Gigante") is None
    assert preco_no_tamanho(COCA, None) == 3.0
    assert preco_no_tamanho(COCA, GRANDE) is None


def test_rodizio_so_com_sabores_incluidos_no_nivel():
    assert incluida_no_rodizio(MARG, "simples") and incluida_no_rodizio(MARG, "completo")
    assert not incluida_no_rodizio(FRANGO, "simples") and incluida_no_rodizio(FRANGO, "completo")
    assert not incluida_no_rodizio(MARG, "none") and not incluida_no_rodizio(MARG, None)


def test_nome():
    assert nome_meia_meia("A", "B") == "1/2 A + 1/2 B"


def test_sem_tamanho_pede_o_tamanho():
    with pytest.raises(MeiaMeiaInvalida) as e:
        montar_meia_meia(MARG, FRANGO, PIZZAS, None)
    assert "Escolhe o tamanho" in str(e.value)


def test_primeiro_sabor_tambem_tem_de_existir_no_tamanho():
    so_media = dict(MARG, variations=[{"name": MEDIA, "price": 12.9}])
    with pytest.raises(MeiaMeiaInvalida) as e:
        montar_meia_meia(so_media, FRANGO, PIZZAS, GRANDE)
    assert "Margherita" in str(e.value)
