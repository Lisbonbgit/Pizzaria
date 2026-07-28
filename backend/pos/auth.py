"""Helpers de autenticação do módulo POS (tokens de dispositivo).

Funções puras, sem I/O — hash/verificação bcrypt do token de dispositivo,
usadas pelos endpoints de `pos_devices` em server.py (criar/revogar) e pelo
helper `valid_device_token` (auth-duplo dos terminais POS, tarefa futura).
Mesmo mecanismo bcrypt de `hash_password`/`verify_password` em server.py,
mas em módulo próprio conforme o plano da Fase 1.
"""
import bcrypt


def hash_token(raw: str) -> str:
    """Devolve o hash bcrypt do token em claro (para guardar em `pos_devices.token_hash`)."""
    return bcrypt.hashpw(raw.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_token(raw: str, hashed: str) -> bool:
    """Compara um token em claro com o hash guardado."""
    return bcrypt.checkpw(raw.encode("utf-8"), hashed.encode("utf-8"))
