"""Helpers de autenticação do módulo POS.

Funções puras, sem I/O:
  * `hash_token`/`verify_token` — hash/verificação bcrypt do token de
    dispositivo (usados pelos endpoints de `pos_devices` em server.py e pelo
    helper `valid_device_token`).
  * `create_pos_token`/`decode_pos_token` — token JWT curto da sessão POS,
    emitido no login por PIN e verificado na dependência `get_pos_operator`.

O `JWT_SECRET` é lido do ambiente NO MOMENTO DA CHAMADA (não no import), para
que os testes o possam definir antes de importar o módulo e para partilhar o
mesmo segredo do JWT de admin em server.py.
"""
import os
from datetime import datetime, timezone, timedelta

import bcrypt
import jwt

# Mesmo algoritmo do JWT de admin (server.JWT_ALGORITHM).
POS_JWT_ALGORITHM = "HS256"
# Sessão POS curta: o terminal volta a pedir o PIN passadas 12h.
POS_TOKEN_TTL = timedelta(hours=12)


def hash_token(raw: str) -> str:
    """Devolve o hash bcrypt do token em claro (para guardar em `pos_devices.token_hash`)."""
    return bcrypt.hashpw(raw.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_token(raw: str, hashed: str) -> bool:
    """Compara um token em claro com o hash guardado."""
    return bcrypt.checkpw(raw.encode("utf-8"), hashed.encode("utf-8"))


def create_pos_token(pos_user_id: str, name: str) -> str:
    """Emite o JWT curto da sessão POS para um operador já autenticado por PIN.

    A identidade (`pos_user_id`) vem SEMPRE de um utilizador validado no login,
    nunca de um corpo de pedido — o token é a única fonte de identidade do POS.
    """
    secret = os.environ["JWT_SECRET"]
    payload = {
        "typ": "pos",  # marca de tipo — impede que um JWT de admin passe por token POS
        "pos_user_id": pos_user_id,
        "name": name,
        "exp": datetime.now(timezone.utc) + POS_TOKEN_TTL,
    }
    return jwt.encode(payload, secret, algorithm=POS_JWT_ALGORITHM)


def decode_pos_token(token: str) -> dict:
    """Verifica assinatura, validade e TIPO do token POS e devolve o payload.

    O token tem de trazer `typ == "pos"`; caso contrário (p.ex. um JWT de admin,
    assinado com o mesmo segredo) é recusado com `jwt.InvalidTokenError`. Propaga
    também `jwt.ExpiredSignatureError` — quem consome (a dependência
    `get_pos_operator`) traduz ambos para HTTP 401.
    """
    secret = os.environ["JWT_SECRET"]
    payload = jwt.decode(token, secret, algorithms=[POS_JWT_ALGORITHM])
    if payload.get("typ") != "pos":
        raise jwt.InvalidTokenError("Token não é do tipo POS")
    return payload
