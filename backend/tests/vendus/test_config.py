import pytest
from vendus.config import VendusConfig


def test_load_fail_closed_sem_api_key():
    with pytest.raises(RuntimeError):
        VendusConfig.load({})


def test_load_defaults():
    cfg = VendusConfig.load({"VENDUS_API_KEY": "abc"})
    assert cfg.api_key == "abc"
    assert cfg.base_url == "https://www.vendus.pt/ws/v1.1/"
    assert cfg.mode == "tests"
    assert cfg.register_id is None


def test_load_overrides():
    cfg = VendusConfig.load({
        "VENDUS_API_KEY": "abc",
        "VENDUS_BASE_URL": "https://www.vendus.es/ws/v1.1",
        "VENDUS_MODE": "normal",
        "VENDUS_REGISTER_ID": "42",
    })
    assert cfg.base_url == "https://www.vendus.es/ws/v1.1/"  # normaliza trailing slash
    assert cfg.mode == "normal"
    assert cfg.register_id == 42
