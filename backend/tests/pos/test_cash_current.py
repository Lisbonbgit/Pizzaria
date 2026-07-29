"""`GET /pos/cash/current` (Fase 4b) — passou a devolver também `last_close`,
o fecho mais recente, tanto com sessão aberta como sem nenhuma (ecrã "Caixa
Fechada" mostra "Último fecho: ..."). Só a app-fonte deste endpoint sabe se
há sessão aberta pelo campo `status` — nunca pela verdade do payload inteiro
(o payload deixou de poder ser `null`; ver PosApp.js/PosHome.js, que passaram
a checar `status === "open"` explicitamente em vez de `!!res.data`).

Sem pytest-asyncio no projeto (ver tests/pos/test_pin.py e vizinhos, todos
síncronos) — corremos a corotina com `asyncio.run`. `server.db` é substituído
por um fake em memória: sem isto, `db.cash_sessions.find_one`/`find` tentaria
mesmo ligar a um Mongo (não há um a correr nestes testes unitários).
"""
import asyncio

import server
from server import get_current_cash_session


class _FakeCursor:
    def __init__(self, docs):
        self._docs = list(docs)

    def sort(self, field, direction):
        self._docs.sort(key=lambda d: d.get(field) or "", reverse=(direction == -1))
        return self

    async def to_list(self, n):
        return self._docs[:n]


class _FakeCashSessions:
    def __init__(self, docs):
        self._docs = docs

    async def find_one(self, filt, proj=None):
        for d in self._docs:
            if all(d.get(k) == v for k, v in filt.items()):
                return dict(d)
        return None

    def find(self, filt, proj=None):
        matches = [d for d in self._docs if all(d.get(k) == v for k, v in filt.items())]
        return _FakeCursor(matches)


class _FakeDb:
    def __init__(self, docs):
        self.cash_sessions = _FakeCashSessions(docs)


def test_nunca_houve_nenhum_fecho_last_close_e_none(monkeypatch):
    monkeypatch.setattr(server, "db", _FakeDb([]))

    resultado = asyncio.run(get_current_cash_session(operador={"id": "op1", "name": "Ana"}))

    assert resultado == {"last_close": None}


def test_sem_sessao_aberta_devolve_o_fecho_mais_recente(monkeypatch):
    fechado_antigo = {
        "id": "s1", "status": "closed", "closed_by_name": "Ana",
        "closed_at": "2026-07-27T20:00:00+00:00", "counted_amount": 100.0,
    }
    fechado_recente = {
        "id": "s2", "status": "closed", "closed_by_name": "Bruno",
        "closed_at": "2026-07-28T21:30:00+00:00", "counted_amount": 235.5,
    }
    # Ordem de inserção propositadamente "errada" — o `sort("closed_at", -1)`
    # é que tem de escolher o mais recente, não a ordem da lista.
    monkeypatch.setattr(server, "db", _FakeDb([fechado_antigo, fechado_recente]))

    resultado = asyncio.run(get_current_cash_session(operador={"id": "op1", "name": "Ana"}))

    assert "status" not in resultado  # sem sessão aberta -> sem campo status
    assert resultado["last_close"] == {
        "closed_by_name": "Bruno",
        "closed_at": "2026-07-28T21:30:00+00:00",
        "counted_amount": 235.5,
    }


def test_com_sessao_aberta_devolve_a_sessao_e_tambem_o_last_close(monkeypatch):
    aberta = {"id": "s3", "status": "open", "opened_by_name": "Carla", "opening_amount": 50.0}
    fechado = {
        "id": "s1", "status": "closed", "closed_by_name": "Ana",
        "closed_at": "2026-07-27T20:00:00+00:00", "counted_amount": 100.0,
    }
    monkeypatch.setattr(server, "db", _FakeDb([aberta, fechado]))

    resultado = asyncio.run(get_current_cash_session(operador={"id": "op1", "name": "Ana"}))

    assert resultado["status"] == "open"
    assert resultado["opened_by_name"] == "Carla"
    assert resultado["last_close"]["closed_by_name"] == "Ana"
