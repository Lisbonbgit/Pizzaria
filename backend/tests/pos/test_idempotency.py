"""Referência fiscal ESTÁVEL (`stable_ext_ref`) — lógica pura, sem I/O.

A `external_reference` de cada fatura passa a derivar de (mesa, sessão de caixa,
itens) por hash determinístico. Assim, um RETRY do mesmo fecho gera EXATAMENTE
a mesma referência — o que permite ao `close_table` detetar o documento já
emitido no Vendus e reutilizá-lo em vez de emitir uma 2ª FS (cobrança dupla).
"""
from pos.idempotency import stable_ext_ref


def test_ref_estavel_e_sensivel():
    items = [{"title": "Pizza", "qty": 1, "gross_price": 13.9, "tax_id": "INT"}]
    a = stable_ext_ref(5, "s1", items)
    b = stable_ext_ref(5, "s1", items)
    assert a == b                          # mesmo fecho -> mesma ref (idempotente)
    assert a.startswith("mesa-5-s1-")
    items2 = items + [{"title": "Coca", "qty": 1, "gross_price": 2.0, "tax_id": "NOR"}]
    assert stable_ext_ref(5, "s1", items2) != a   # itens diferentes -> ref diferente


def test_ref_sensivel_a_mesa_e_sessao():
    items = [{"title": "Pizza", "qty": 1, "gross_price": 13.9, "tax_id": "INT"}]
    # Mesa diferente -> ref diferente (o prefixo muda).
    assert stable_ext_ref(6, "s1", items) != stable_ext_ref(5, "s1", items)
    # Sessão de caixa diferente -> ref diferente (fecho de outro dia/turno).
    assert stable_ext_ref(5, "s2", items) != stable_ext_ref(5, "s1", items)
    # Fallback "legacy" (admin sem caixa) continua determinístico.
    assert stable_ext_ref(5, "legacy", items) == stable_ext_ref(5, "legacy", items)


def test_ordem_dos_itens_nao_altera_a_ref():
    # `sort_keys=True` ordena as CHAVES de cada item; a lista mantém a ordem, por
    # isso a mesma lista (mesma ordem) dá sempre a mesma ref — o determinismo é
    # o que importa para o retry reutilizar o documento.
    i1 = {"tax_id": "INT", "title": "Pizza", "qty": 1, "gross_price": 13.9}
    i2 = {"gross_price": 13.9, "qty": 1, "title": "Pizza", "tax_id": "INT"}
    assert stable_ext_ref(5, "s1", [i1]) == stable_ext_ref(5, "s1", [i2])


def test_ref_lida_com_acentos():
    # ensure_ascii=False: títulos com acentos (ex.: "Açaí") não rebentam o hash.
    items = [{"title": "Açaí grande", "qty": 1, "gross_price": 6.5, "tax_id": "INT"}]
    r = stable_ext_ref(5, "s1", items)
    assert r.startswith("mesa-5-s1-") and len(r) > len("mesa-5-s1-")
