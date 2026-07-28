"""Auth-duplo dos terminais POS — `get_pos_or_admin` (lógica pura, sem Mongo).

`get_pos_or_admin` tenta primeiro o JWT de admin (`get_current_user`); se
falhar, cai para o device token (`valid_device_token`, aqui monkeypatchado
para não bater na base de dados). Sem nenhum dos dois, 401.

Sem pytest-asyncio no projeto (ver tests/pos/test_pin.py e vizinhos, todos
síncronos) — corremos as corotinas com `asyncio.run`.
"""
import asyncio

import pytest
from fastapi import HTTPException

import server
from server import create_token, get_pos_or_admin


def test_admin_jwt_valido_passa():
    # Token de admin (typ="admin") válido -> aceite, devolve kind="admin".
    token = create_token("admin-1", "gestor@lenhaebrasa.com")

    async def run():
        return await get_pos_or_admin(authorization=f"Bearer {token}", x_device_token=None)

    resultado = asyncio.run(run())
    assert resultado["kind"] == "admin"
    assert resultado["user"]["email"] == "gestor@lenhaebrasa.com"


def test_device_token_valido_passa(monkeypatch):
    # Sem JWT de admin, mas com um device token que `valid_device_token`
    # (monkeypatchado) reconhece como válido -> aceite, kind="pos".
    async def fake_valid_device_token(raw: str) -> bool:
        return raw == "token-valido-do-terminal"

    monkeypatch.setattr(server, "valid_device_token", fake_valid_device_token)

    async def run():
        return await get_pos_or_admin(authorization=None, x_device_token="token-valido-do-terminal")

    resultado = asyncio.run(run())
    assert resultado == {"kind": "pos"}


def test_sem_admin_e_sem_device_token_da_401(monkeypatch):
    # Nem JWT de admin nem device token válido -> 401 (nenhum acesso concedido).
    async def fake_valid_device_token(raw: str) -> bool:
        return False

    monkeypatch.setattr(server, "valid_device_token", fake_valid_device_token)

    async def run():
        await get_pos_or_admin(authorization=None, x_device_token="token-invalido")

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(run())
    assert exc_info.value.status_code == 401


def test_pos_jwt_sozinho_nao_basta_sem_device_token(monkeypatch):
    # Um JWT válido mas typ="pos" (sessão de operador) não é aceite como admin
    # (get_current_user recusa-o) e, sem device token, também não há fallback.
    from pos.auth import create_pos_token

    pos_token = create_pos_token("op-1", "Maicon")

    async def fake_valid_device_token(raw: str) -> bool:
        return False

    monkeypatch.setattr(server, "valid_device_token", fake_valid_device_token)

    async def run():
        await get_pos_or_admin(authorization=f"Bearer {pos_token}", x_device_token=None)

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(run())
    assert exc_info.value.status_code == 401
