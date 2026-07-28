"""Token de sessão POS curto (JWT HS256) — lógica pura, sem I/O.

`create_pos_token`/`decode_pos_token` vivem em `pos/auth.py` e são a base do
login POS por PIN (server.py). O segredo é lido de `JWT_SECRET` no momento da
chamada, por isso basta pô-lo no ambiente antes de importar o módulo.
"""
import os

os.environ.setdefault("JWT_SECRET", "x" * 40)

from datetime import datetime, timezone, timedelta

import jwt
import pytest

from pos.auth import create_pos_token, decode_pos_token


def test_pos_token_roundtrip():
    # Passo 1 do brief: criar → descodificar devolve o mesmo operador.
    t = create_pos_token("u1", "Maicon")
    d = decode_pos_token(t)
    assert d["pos_user_id"] == "u1" and d["name"] == "Maicon"


def test_pos_token_expirado_rejeitado():
    # Um token com `exp` no passado tem de ser recusado (segurança da sessão).
    secret = os.environ["JWT_SECRET"]
    expirado = jwt.encode(
        {
            "pos_user_id": "u1",
            "name": "Maicon",
            "exp": datetime.now(timezone.utc) - timedelta(hours=1),
        },
        secret,
        algorithm="HS256",
    )
    with pytest.raises(jwt.ExpiredSignatureError):
        decode_pos_token(expirado)
