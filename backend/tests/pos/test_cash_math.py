"""Cálculo do dinheiro esperado em caixa — lógica pura, sem I/O.

`expected_cash` soma a abertura, as vendas em dinheiro e os reforços, e
subtrai as sangrias. Usado pelo endpoint `POST /api/pos/cash/movement`
(para mostrar o esperado corrente) e, mais tarde, pelo fecho/reconciliação
(Task 10).
"""
from pos.cash_math import expected_cash


def test_expected_cash():
    movs = [{"type": "reforco", "amount": 20.0}, {"type": "sangria", "amount": 50.0}]
    # 100 abertura + 300 vendas dinheiro + 20 reforco - 50 sangria = 370
    assert expected_cash(100.0, 300.0, movs) == 370.0


def test_expected_cash_sem_movimentos():
    # Sem sangria/reforço, o esperado é só abertura + vendas em dinheiro.
    assert expected_cash(50.0, 120.0, []) == 170.0


def test_expected_cash_so_sangria():
    # Só sangrias: o esperado desce abaixo de abertura + vendas.
    movs = [{"type": "sangria", "amount": 30.0}, {"type": "sangria", "amount": 15.0}]
    assert expected_cash(100.0, 0.0, movs) == 55.0
