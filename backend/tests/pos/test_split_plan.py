"""Divisão da conta em N partes iguais — lógica pura, sem I/O.

Alimenta a divisão sequencial da mesa (`close_table`) e do balcão
(`checkout_counter_order`): cada parte é uma FS própria, com o seu NIF e
método de pagamento.
"""
from pos.split_plan import compute_shares, next_amount, next_unpaid_index, remaining_amount


def test_duas_partes_somam_exatamente_o_total():
    shares = compute_shares({"INT": 20.01}, 2, "Conta dividida Mesa 3")
    assert len(shares) == 2
    assert round(sum(s["amount"] for s in shares), 2) == 20.01


def test_resto_do_arredondamento_vai_para_a_ultima():
    # 10.01 / 3 = 3.336... -> 3.34, 3.34, 3.33 (a última leva o resto)
    shares = compute_shares({"INT": 10.01}, 3, "Conta dividida Mesa 1")
    assert [s["amount"] for s in shares] == [3.34, 3.34, 3.33]
    assert round(sum(s["amount"] for s in shares), 2) == 10.01


def test_agrupa_por_iva_com_uma_linha_por_taxa():
    shares = compute_shares({"INT": 10.0, "NOR": 4.0}, 2, "Conta dividida Mesa 5")
    assert len(shares) == 2
    for s in shares:
        assert s["amount"] == 7.0
        taxes = sorted(i["tax_id"] for i in s["items"])
        assert taxes == ["INT", "NOR"]
        for i in s["items"]:
            assert i["qty"] == 1
            assert i["title"].startswith("Conta dividida Mesa 5")


def test_titulo_numera_a_parte():
    shares = compute_shares({"INT": 10.0}, 2, "Conta dividida Mesa 7")
    assert shares[0]["items"][0]["title"] == "Conta dividida Mesa 7 (1/2)"
    assert shares[1]["items"][0]["title"] == "Conta dividida Mesa 7 (2/2)"


def test_n_igual_a_um_devolve_uma_parte_com_tudo():
    shares = compute_shares({"INT": 12.5}, 1, "Conta dividida Mesa 2")
    assert len(shares) == 1
    assert shares[0]["amount"] == 12.5


def test_partes_a_zero_sao_descartadas():
    # 0.01 dividido por 3: só uma parte tem valor; não se emitem FS de 0.
    shares = compute_shares({"INT": 0.01}, 3, "Conta dividida Mesa 4")
    assert all(s["amount"] > 0 for s in shares)
    assert round(sum(s["amount"] for s in shares), 2) == 0.01


def test_progressao_das_partes():
    shares = [{"amount": 5.0, "paid": False}, {"amount": 5.0, "paid": False}]
    assert next_unpaid_index(shares) == 0
    assert remaining_amount(shares) == 10.0

    shares[0]["paid"] = True
    assert next_unpaid_index(shares) == 1
    assert remaining_amount(shares) == 5.0

    shares[1]["paid"] = True
    assert next_unpaid_index(shares) is None
    assert remaining_amount(shares) == 0.0


def test_cada_parte_vale_o_que_o_ecra_mostra():
    # O ecrã mostra "Cada pessoa paga" = total/N. Com dois IVAs, arredondar cada
    # taxa à parte dava 3,66 na fatura e 3,67 no ecrã (o operador cobrava um no
    # terminal e a FS dizia outro). As N−1 primeiras partes valem EXATAMENTE
    # total/N; a última leva o resto.
    shares = compute_shares({"INT": 10.0, "NOR": 1.0}, 3, "Mesa 1")
    assert [s["amount"] for s in shares[:-1]] == [3.67, 3.67]
    assert round(sum(s["amount"] for s in shares), 2) == 11.0
    # 184,09 / 2 = 92,045 → o ecrã (Math.round) mostra 92,05. Somar os IVAs em
    # float dava 184,08999… e a FS saía com 92,04.
    shares = compute_shares({"INT": 183.95, "NOR": 0.14}, 2, "Mesa 1")
    assert shares[0]["amount"] == 92.05


def test_nunca_cobra_a_mais_com_um_iva_pequeno():
    # 0,05 € a 23% dividido por 9: arredondar para cima dava partes de 0,01 que
    # somavam 0,08 — as FS somavam MAIS do que a venda.
    for sub in (0.05, 0.14, 0.15, 0.23):
        shares = compute_shares({"INT": 40.0, "NOR": sub}, 9, "Mesa 1")
        assert round(sum(s["amount"] for s in shares), 2) == round(40.0 + sub, 2)
        for s in shares:
            assert all(i["gross_price"] > 0 for i in s["items"])


def test_proxima_parte_e_o_valor_a_cobrar():
    shares = compute_shares({"INT": 27.0}, 7, "Mesa 1")
    assert next_amount(shares) == shares[0]["amount"]
    for s in shares[:-1]:
        s["paid"] = True
    assert next_amount(shares) == shares[-1]["amount"]
    shares[-1]["paid"] = True
    assert next_amount(shares) is None
