"""`GET /pos/cash/expected` (Fase 4b) — pré-visualização do dinheiro esperado
em caixa para a sessão ABERTA, ANTES do fecho (ecrã "Contagem de Caixa"
mostra "Valor esperado no caixa: ..." para o operador comparar).

Usa o MESMO cálculo do fecho (`cash_sales_from_vendus` + `expected_cash`,
partilhados via pos/cash_math.py — ver test_cash_math.py), mas é
BEST-EFFORT: uma falha do Vendus nunca dá 500 aqui (ao contrário do fecho,
que dá 502) — devolve o esperado só com abertura+movimentos e
`vendus_ok: false`.

Sem pytest-asyncio no projeto (ver tests/pos/test_pin.py e vizinhos, todos
síncronos) — corremos as corotinas com `asyncio.run`. `server.db` é
substituído por um fake em memória e as chamadas de I/O
(`_cash_expected_vendus_read`, `_pos_settings_config`, `valid_device_token`)
são monkeypatchadas — sem rede/Mongo real.
"""
import asyncio

import pytest
from fastapi import HTTPException

import server
from server import get_cash_expected

OPEN_SESSION = {
    "id": "sess-1",
    "status": "open",
    "opened_at": "2026-07-27T09:00:00+00:00",
    "opening_amount": 50.0,
    "movements": [
        {"type": "reforco", "amount": 20.0},
        {"type": "sangria", "amount": 5.0},
    ],
}


class _FakeCashSessions:
    def __init__(self, open_session):
        self._open = open_session

    async def find_one(self, filt, proj=None):
        if filt.get("status") == "open" and self._open:
            return dict(self._open)
        return None


class _FakeDb:
    def __init__(self, open_session):
        self.cash_sessions = _FakeCashSessions(open_session)


def _patch_common(monkeypatch, open_session=OPEN_SESSION, cash_method_id=1):
    monkeypatch.setattr(server, "db", _FakeDb(open_session))

    async def fake_valid_device_token(raw):
        return raw == "token-valido"

    monkeypatch.setattr(server, "valid_device_token", fake_valid_device_token)

    async def fake_pos_settings_config():
        return {"require_open_cash": True, "cash_payment_method_id": cash_method_id, "z_footer_text": ""}

    monkeypatch.setattr(server, "_pos_settings_config", fake_pos_settings_config)


def test_sem_caixa_aberta_da_409(monkeypatch):
    _patch_common(monkeypatch, open_session=None)

    async def run():
        await get_cash_expected(authorization=None, x_device_token="token-valido")

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(run())
    assert exc_info.value.status_code == 409


def test_sem_auth_da_401(monkeypatch):
    _patch_common(monkeypatch)

    async def run():
        await get_cash_expected(authorization=None, x_device_token="invalido")

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(run())
    assert exc_info.value.status_code == 401


def test_vendus_ok_calcula_esperado_com_vendas_em_dinheiro(monkeypatch):
    _patch_common(monkeypatch)

    def fake_leitura(inicio_iso, fim_iso, cash_method_id):
        # A pré-visualização tem de passar o MESMO cash_method_id lido das
        # definições — nunca um valor hardcoded/errado.
        assert cash_method_id == 1
        return 300.0

    monkeypatch.setattr(server, "_cash_expected_vendus_read", fake_leitura)

    resultado = asyncio.run(get_cash_expected(authorization=None, x_device_token="token-valido"))

    # 50 abertura + 300 vendas dinheiro + 20 reforco - 5 sangria = 365
    assert resultado["expected_cash"] == 365.0
    assert resultado["opening_amount"] == 50.0
    assert resultado["cash_sales"] == 300.0
    assert resultado["reforcos"] == 20.0
    assert resultado["sangrias"] == 5.0
    assert resultado["vendus_ok"] is True


def test_vendus_falha_devolve_estimativa_sem_500(monkeypatch):
    _patch_common(monkeypatch)

    def fake_leitura_falha(inicio_iso, fim_iso, cash_method_id):
        raise RuntimeError("Vendus indisponivel")

    monkeypatch.setattr(server, "_cash_expected_vendus_read", fake_leitura_falha)

    resultado = asyncio.run(get_cash_expected(authorization=None, x_device_token="token-valido"))

    # Sem Vendus: só abertura + movimentos = 50 + 20 - 5 = 65
    assert resultado["expected_cash"] == 65.0
    assert resultado["cash_sales"] == 0.0
    assert resultado["vendus_ok"] is False


def test_admin_jwt_valido_tambem_ve_o_esperado(monkeypatch):
    # Auth-duplo (get_pos_or_admin): o JWT de admin também é aceite, sem
    # device token nenhum — mesmo padrão de tests/pos/test_cash_drawer.py.
    from server import create_token

    _patch_common(monkeypatch)

    def fake_leitura(inicio_iso, fim_iso, cash_method_id):
        return 0.0

    monkeypatch.setattr(server, "_cash_expected_vendus_read", fake_leitura)
    token = create_token("admin-1", "gestor@lenhaebrasa.com")

    resultado = asyncio.run(get_cash_expected(authorization=f"Bearer {token}", x_device_token=None))

    assert resultado["vendus_ok"] is True
