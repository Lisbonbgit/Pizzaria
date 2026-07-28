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


def test_admin_token_rejeitado_como_pos():
    # Segurança: um JWT de admin (typ="admin"), assinado com o MESMO segredo, não
    # pode passar por token POS — decode_pos_token exige typ="pos".
    secret = os.environ["JWT_SECRET"]
    admin_like = jwt.encode(
        {"user_id": "admin-env", "typ": "admin",
         "exp": datetime.now(timezone.utc) + timedelta(hours=1)},
        secret, algorithm="HS256",
    )
    with pytest.raises(jwt.InvalidTokenError):
        decode_pos_token(admin_like)


def test_pos_token_nao_passa_por_admin():
    # O token POS traz typ="pos"; get_current_user exige typ="admin", logo recusa-o
    # (impede a escalada de privilégio de operador POS -> admin).
    t = create_pos_token("u1", "Maicon")
    payload = jwt.decode(t, os.environ["JWT_SECRET"], algorithms=["HS256"])
    assert payload["typ"] == "pos"
    assert payload["typ"] != "admin"
