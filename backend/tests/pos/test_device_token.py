"""Hash/verificação do token de dispositivo POS (lógica pura, sem I/O).

`hash_token`/`verify_token` vivem em `pos/auth.py` (bcrypt) e são consumidos
tanto pelos endpoints de criação/revogação em server.py como pelo helper
`valid_device_token` (auth-duplo dos terminais, tarefa futura).
"""
from pos.auth import hash_token, verify_token


def test_token_hash_roundtrip():
    h = hash_token("abc123")
    assert verify_token("abc123", h)
    assert not verify_token("errado", h)
