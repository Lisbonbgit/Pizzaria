"""Referência fiscal ESTÁVEL (`stable_ext_ref`) — lógica pura, sem I/O.

A `external_reference` de cada fatura deriva de (mesa, sessão de caixa, CHAVE do
fecho) por hash determinístico. A CHAVE é a IDENTIDADE do que se fatura (linhas
`(order_id, idx)` à la carte; estado pago-antes + contagens no rodízio), NÃO o
conteúdo dos itens — senão dois fechos diferentes com os mesmos itens colidiam e
o 2º reutilizava a FS do 1º (SUB-FATURAÇÃO).
"""
from pos.idempotency import stable_ext_ref


def test_mesmo_conjunto_de_linhas_mesma_ref():
    # Retry do MESMO fecho (mesmas linhas por pagar) -> MESMA ref (idempotente).
    linhas = [("ord-A", 0), ("ord-A", 1)]
    a = stable_ext_ref(5, "s1", sorted(linhas))
    b = stable_ext_ref(5, "s1", sorted(linhas))
    assert a == b
    assert a.startswith("mesa-5-s1-")


def test_fechos_distintos_com_itens_iguais_dao_refs_diferentes():
    # A REGRESSÃO que isto corrige: a mesma mesa/sessão a vender o MESMO produto
    # em dois pedidos diferentes tem de dar refs DIFERENTES (senão o 2º não era
    # faturado = sub-faturação). A chave é a identidade das linhas, não os itens.
    fecho1 = stable_ext_ref(5, "s1", [("ord-A", 0)])   # 1ª Coca (pedido A)
    fecho2 = stable_ext_ref(5, "s1", [("ord-B", 0)])   # 2ª Coca (pedido B), item igual
    assert fecho1 != fecho2


def test_ref_sensivel_a_mesa_e_sessao():
    linhas = [("ord-A", 0)]
    assert stable_ext_ref(6, "s1", linhas) != stable_ext_ref(5, "s1", linhas)
    assert stable_ext_ref(5, "s2", linhas) != stable_ext_ref(5, "s1", linhas)
    # Fallback "legacy" (admin sem caixa) continua determinístico.
    assert stable_ext_ref(5, "legacy", linhas) == stable_ext_ref(5, "legacy", linhas)


def test_rodizio_tem_token_rodizio_na_ref():
    # O relatório diário rotula "Mesa N (rodízio)" quando a ref contém o token
    # `rodizio` (external_reference.split("-")). rodizio=True tem de o repor.
    chave = {"paid_before": {"adults": 0}, "adults": 2, "half": 0, "free": 0,
             "waste": 0, "extras": []}
    ref = stable_ext_ref(5, "s1", chave, rodizio=True)
    assert "rodizio" in ref.split("-")
    assert ref.startswith("mesa-5-rodizio-s1-")


def test_rodizio_pago_antes_distingue_pagamentos_sequenciais():
    # Dois pagamentos iguais de rodízio (2 adultos) em sequência têm de dar refs
    # diferentes, porque o estado pago-ANTES muda entre eles.
    p1 = stable_ext_ref(5, "s1", {"paid_before": {"adults": 0}, "adults": 2,
                                  "half": 0, "free": 0, "waste": 0, "extras": []}, rodizio=True)
    p2 = stable_ext_ref(5, "s1", {"paid_before": {"adults": 2}, "adults": 2,
                                  "half": 0, "free": 0, "waste": 0, "extras": []}, rodizio=True)
    assert p1 != p2
    # ... mas o RETRY do mesmo pagamento (pago-antes ainda 0) dá a mesma ref.
    p1_retry = stable_ext_ref(5, "s1", {"paid_before": {"adults": 0}, "adults": 2,
                                        "half": 0, "free": 0, "waste": 0, "extras": []}, rodizio=True)
    assert p1 == p1_retry
