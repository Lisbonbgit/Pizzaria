"""Desconto GLOBAL em EUROS na fatura (mesa e balcão).

O Vendus só aceita percentagem por linha, por isso o valor em € converte-se
numa percentagem equivalente. Essa conversão sozinha deixava até 2 cêntimos de
diferença (medido: só 70% dos casos davam certo ao cêntimo), por isso o resto
do arredondamento é absorvido na ÚLTIMA linha — tal como na divisão da conta.
O que se cobra tem de ser EXATAMENTE bruto − desconto.
"""
import random

from pos.pricing import apply_global_amount


def _linhas(*pares):
    return [{"title": f"i{i}", "qty": q, "gross_price": p, "tax_id": "INT"}
            for i, (q, p) in enumerate(pares)]


def test_desconto_em_euros_bate_ao_centimo():
    linhas = _linhas((1, 13.90), (1, 18.90), (2, 2.50))   # bruto = 37.80
    outs, liqs = apply_global_amount(linhas, 5.00)
    assert round(sum(liqs), 2) == 32.80


def test_caso_que_a_conversao_simples_falhava():
    # 10,01 de bruto com 3,33 de desconto: a percentagem pura deixava resto.
    linhas = _linhas((1, 3.33), (1, 3.34), (1, 3.34))
    outs, liqs = apply_global_amount(linhas, 3.33)
    assert round(sum(liqs), 2) == 6.68


def test_desconto_maior_que_a_conta_nao_fica_negativo():
    linhas = _linhas((1, 10.00))
    outs, liqs = apply_global_amount(linhas, 999.0)
    assert round(sum(liqs), 2) == 0.0
    assert all(l >= 0 for l in liqs)


def test_sem_desconto_nao_mexe_nas_linhas():
    linhas = _linhas((1, 10.00), (1, 5.00))
    outs, liqs = apply_global_amount(linhas, 0)
    assert round(sum(liqs), 2) == 15.00
    assert all("discount_percentage" not in o for o in outs)


def test_o_desconto_vai_na_LINHA_para_o_vendus():
    # Nunca um abatimento por fora: o Vendus recebe percentagem por linha.
    linhas = _linhas((1, 20.00))
    outs, _ = apply_global_amount(linhas, 2.00)
    assert outs[0]["discount_percentage"] == 10.0


def test_bate_sempre_ao_centimo_em_muitos_casos():
    random.seed(11)
    for _ in range(2000):
        linhas = _linhas(*[(random.randint(1, 3), round(random.uniform(1.5, 25.0), 2))
                           for _ in range(random.randint(1, 8))])
        bruto = round(sum(round(l["gross_price"] * l["qty"], 2) for l in linhas), 2)
        desc = round(random.uniform(0.5, bruto), 2)
        _, liqs = apply_global_amount(linhas, desc)
        assert round(sum(liqs), 2) == round(bruto - desc, 2), (bruto, desc)


def test_desconto_em_euros_nao_desfaz_o_desconto_das_linhas():
    # Defeito (no ar desde 08/10): o alvo era BRUTO − €, e o "resto" ia parar à
    # última linha, a desfazer os descontos dos itens. Pizza 20 € a −50% + 10 €
    # com 2 € de desconto na conta: o ecrã dizia 18,00 e a FS saía com 28,00.
    linhas = _linhas((1, 20.0), (1, 10.0))
    linhas[0]["discount_percentage"] = 50
    _, liq = apply_global_amount(linhas, 2.0)
    assert round(sum(liq), 2) == 18.0
    # Desconto da linha em euros: 20 − 5 = 15, + 10 = 25, − 3 na conta = 22.
    linhas = _linhas((1, 20.0), (1, 10.0))
    linhas[0]["discount_amount"] = 5.0
    _, liq = apply_global_amount(linhas, 3.0)
    assert round(sum(liq), 2) == 22.0


def test_com_descontos_de_linha_bate_sempre_ao_centimo():
    from pos.pricing import combine_global
    random.seed(11)
    for _ in range(3000):
        linhas = _linhas(*[(random.randint(1, 4), random.randint(100, 2500) / 100)
                           for _ in range(random.randint(1, 6))])
        for l in linhas:
            r = random.random()
            if r < 0.3:
                l["discount_percentage"] = random.choice([10, 15, 25, 50])
            elif r < 0.45:
                l["discount_amount"] = round(random.uniform(0.5, l["gross_price"]), 2)
        liquido = round(sum(combine_global(l, 0)[1] for l in linhas), 2)
        desconto = round(random.uniform(0, liquido), 2)
        _, liq = apply_global_amount(linhas, desconto)
        assert round(sum(liq), 2) == round(liquido - desconto, 2), (linhas, desconto)
        assert all(x >= 0 for x in liq)
