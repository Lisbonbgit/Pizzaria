"""Abrir Gaveta (`POST /pos/cash/drawer`, menu Caixa) — enfileira o comando
ESC/POS de pulso ("kick") na impressora da CAIXA, pelo mesmo mecanismo
`print_jobs` + `escpos_direct_b64` + `printer_type="cashier"` usado pelas
faturas (`close_table`) e pelo talão Z (`close_cash_session`).

Sem pytest-asyncio no projeto (ver tests/pos/test_pin.py e vizinhos, todos
síncronos) — corremos a corotina com `asyncio.run`. `server.db` é substituído
por um fake em memória: sem isto, `db.print_jobs.insert_one` tentaria mesmo
ligar a um Mongo (não há um a correr nestes testes unitários).
"""
import asyncio
import base64

import pytest
from fastapi import HTTPException

import server
from server import create_token, open_cash_drawer

KICK_BYTES = b"\x1b\x70\x00\x19\xfa"  # ESC p 0 25 250 — pulso padrão da gaveta


class _FakePrintJobs:
    def __init__(self):
        self.inserted = []

    async def insert_one(self, doc):
        self.inserted.append(doc)


class _FakeDb:
    def __init__(self):
        self.print_jobs = _FakePrintJobs()


def test_sem_auth_da_401_e_nao_enfileira_nada(monkeypatch):
    fake_db = _FakeDb()
    monkeypatch.setattr(server, "db", fake_db)

    async def fake_valid_device_token(raw: str) -> bool:
        return False

    monkeypatch.setattr(server, "valid_device_token", fake_valid_device_token)

    async def run():
        await open_cash_drawer(authorization=None, x_device_token="invalido")

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(run())
    assert exc_info.value.status_code == 401
    assert fake_db.print_jobs.inserted == []


def test_device_token_valido_enfileira_kick_na_caixa(monkeypatch):
    fake_db = _FakeDb()
    monkeypatch.setattr(server, "db", fake_db)

    async def fake_valid_device_token(raw: str) -> bool:
        return raw == "token-valido-do-terminal"

    monkeypatch.setattr(server, "valid_device_token", fake_valid_device_token)

    async def run():
        return await open_cash_drawer(authorization=None, x_device_token="token-valido-do-terminal")

    resultado = asyncio.run(run())
    assert resultado == {"ok": True}

    assert len(fake_db.print_jobs.inserted) == 1
    job = fake_db.print_jobs.inserted[0]
    assert job["printer_type"] == "cashier"
    assert job["printer_name"] == "Caixa"
    assert job["status"] == "pending"
    assert base64.b64decode(job["escpos_direct_b64"]) == KICK_BYTES


def test_admin_jwt_valido_tambem_abre_a_gaveta(monkeypatch):
    # Auth-duplo (get_pos_or_admin): o JWT de admin também é aceite, sem
    # device token nenhum.
    fake_db = _FakeDb()
    monkeypatch.setattr(server, "db", fake_db)
    token = create_token("admin-1", "gestor@lenhaebrasa.com")

    async def run():
        return await open_cash_drawer(authorization=f"Bearer {token}", x_device_token=None)

    resultado = asyncio.run(run())
    assert resultado == {"ok": True}
    assert len(fake_db.print_jobs.inserted) == 1
