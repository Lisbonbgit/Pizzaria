"""Validação do PIN dos utilizadores POS (lógica pura, sem I/O).

Reutiliza `server.valid_pin` — a mesma função usada pelos endpoints
de criação/atualização de `pos_users` — para não haver duas versões
da regra a divergir.
"""
from server import valid_pin


def test_pin_4_digitos():
    assert valid_pin("1234")
    assert not valid_pin("12a4")
    assert not valid_pin("123")
    assert not valid_pin("")
