"""Cálculo do dinheiro esperado em caixa (`expected_cash`) — sem I/O.

Fase 1 (Task 7): helper puro partilhado pelo endpoint de movimentos
(`POST /api/pos/cash/movement`, para mostrar o esperado corrente) e, mais
tarde, pelo fecho/reconciliação da caixa (Task 10).
"""
from typing import List, Dict, Any


def expected_cash(opening: float, cash_sales: float, movements: List[Dict[str, Any]]) -> float:
    """Devolve o dinheiro esperado em caixa: abertura + vendas em dinheiro +
    reforços - sangrias, arredondado a 2 casas decimais (dinheiro = 2 casas).

    `movements` é a lista `cash_sessions.movements` — cada item tem
    `type` ("sangria" ou "reforco") e `amount` (sempre positivo)."""
    reforcos = sum(m["amount"] for m in movements if m["type"] == "reforco")
    sangrias = sum(m["amount"] for m in movements if m["type"] == "sangria")
    return round(opening + cash_sales + reforcos - sangrias, 2)
