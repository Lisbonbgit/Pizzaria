"""Divisão da conta em N partes iguais — lógica pura, sem I/O.

Alimenta a divisão sequencial da mesa (`close_table`) e do balcão
(`checkout_counter_order`): cada parte é uma FS própria, com o seu NIF e
método de pagamento.
"""
from pos.split_plan import compute_shares, next_unpaid_index, remaining_amount


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
