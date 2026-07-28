"""Abertura de caixa (`cash_sessions`) — unicidade atómica, lógica pura.

`pick_open_session` simula, sem I/O, o resultado do find-or-create atómico
usado por `POST /api/pos/cash/open`: índice único parcial em
`{status:"open"}` + `insert_one`; se o Mongo devolver `DuplicateKeyError`
(já existe uma sessão aberta), o endpoint procura-a (`existing`) e devolve-a
em vez de criar uma segunda — a abertura é idempotente.
"""
from pos.cash import pick_open_session


def test_existing_open_session_e_devolvida_sem_criar_segunda():
    # Já há uma sessão aberta -> abrir de novo devolve a MESMA sessão.
    existing = {"id": "sessao-1", "status": "open", "opening_amount": 50.0}
    new = {"id": "sessao-2", "status": "open", "opening_amount": 100.0}
    assert pick_open_session(existing, new) is existing


def test_sem_sessao_aberta_cria_a_nova():
    # Sem nenhuma sessão aberta -> a sessão recém-criada é a que fica válida.
    new = {"id": "sessao-1", "status": "open", "opening_amount": 0.0}
    assert pick_open_session(None, new) is new
