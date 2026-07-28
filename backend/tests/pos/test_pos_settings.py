"""Definições do POS (`PosSettingsConfig`) — validação pura, sem Mongo.

Testa só o modelo Pydantic (o mesmo usado pelo PUT /admin/pos/settings) e os
defaults: não precisa de base de dados, à semelhança dos outros testes
síncronos em tests/pos/ (ver test_pin.py).
"""
import pytest
from pydantic import ValidationError

from server import POS_SETTINGS_DEFAULT, PosSettingsConfig


def test_defaults():
    cfg = PosSettingsConfig()
    assert cfg.model_dump() == POS_SETTINGS_DEFAULT


def test_aceita_valores_validos():
    cfg = PosSettingsConfig(
        require_open_cash=False,
        cash_payment_method_id=3,
        z_footer_text="Obrigado pela preferência!",
    )
    assert cfg.model_dump() == {
        "require_open_cash": False,
        "cash_payment_method_id": 3,
        "z_footer_text": "Obrigado pela preferência!",
    }


def test_cash_payment_method_id_aceita_null():
    cfg = PosSettingsConfig(cash_payment_method_id=None)
    assert cfg.cash_payment_method_id is None


def test_rejeita_tipos_invalidos():
    with pytest.raises(ValidationError):
        PosSettingsConfig(cash_payment_method_id="dinheiro")

    with pytest.raises(ValidationError):
        PosSettingsConfig(require_open_cash="nao-e-bool-string-qualquer")
