"""Preferências no talão: várias escolhas chegam juntas num só campo.

Com mínimo/máximo o cliente passa a poder marcar várias preferências (ex.:
Com Gelo + Limão) — era por só dar uma que existia a opção combinada "Gelo e
Limão". As escolhas chegam juntas em `selected_preference`, e este teste prende
que o talão da cozinha as mostra (é o que a cozinha precisa de ler).
"""
from server import ESCPOSFormatter

BASE = {"order_number": 7, "source": "balcao", "table_number": None,
        "created_at": "2026-10-08T18:00:00+00:00"}


def _cozinha(item):
    return ESCPOSFormatter().format_kitchen({**BASE, "items": [item]})


def test_varias_preferencias_saem_no_talao():
    out = _cozinha({"product_name": "Coca-Cola", "quantity": 1,
                    "selected_preference": "Com Gelo, Limão"})
    assert b"COM GELO" in out and b"LIM" in out


def test_uma_so_preferencia_continua_igual():
    out = _cozinha({"product_name": "Coca-Cola", "quantity": 1,
                    "selected_preference": "Sem Gelo"})
    assert b"SEM GELO" in out


def test_sem_preferencia_nao_imprime_linha():
    assert b">>" not in _cozinha({"product_name": "Pizza", "quantity": 1})
