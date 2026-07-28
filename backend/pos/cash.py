"""Lógica pura da sessão de caixa (`cash_sessions`) — sem I/O.

Fase 1 (Task 6): só os campos de ABERTURA do modelo (spec §4.1 do design
POS+Caixa). Os campos de fecho (`closed_by`, `counted_amount`,
`expected_cash`, `difference`, `reconciliation`, `totals_by_method`) chegam
na Task 10.
"""
from typing import Optional


def pick_open_session(existing: Optional[dict], new: dict) -> dict:
    """Devolve a sessão de caixa a expor ao chamador (idempotência da abertura).

    Simula, em lógica pura, o resultado do find-or-create atómico usado por
    `POST /api/pos/cash/open`: o endpoint tenta sempre `insert_one(new)`; se o
    Mongo recusar com `DuplicateKeyError` (índice único parcial em
    `{status:"open"}` — já existe uma sessão aberta), o endpoint procura-a e
    chama esta função com `existing=<sessão encontrada>`. Se não houver
    conflito, `existing` é `None` e `new` (a sessão que acabou de ser
    inserida) é a válida.

    Devolve sempre `existing` quando não é `None` — NUNCA cria uma segunda
    sessão aberta.
    """
    if existing is not None:
        return existing
    return new
