"""O talão de cozinha marca as reimpressões de balcão como ATUALIZADO."""
from server import ESCPOSFormatter

BASE = {
    "order_number": 7,
    "source": "balcao",
    "table_number": None,
    "items": [{"product_name": "Pizza", "quantity": 1}],
    "created_at": "2026-08-09T18:00:00+00:00",
}


def test_pedido_novo_diz_novo_pedido():
    out = ESCPOSFormatter().format_kitchen(dict(BASE))
    assert b"NOVO PEDIDO" in out
    assert b"ATUALIZADO" not in out


def test_pedido_atualizado_diz_atualizado_e_substitui():
    out = ESCPOSFormatter().format_kitchen({**BASE, "is_update": True})
    assert b"PEDIDO ATUALIZADO" in out
    assert b"substitui" in out
    assert b"NOVO PEDIDO" not in out
