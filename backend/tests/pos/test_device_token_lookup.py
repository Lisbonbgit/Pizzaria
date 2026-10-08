"""Validação do token de terminal POS — tem de ser PROCURA DIRETA, não varrimento.

O varrimento antigo comparava o token com todos os dispositivos ativos por
bcrypt (~0,5s cada). Com 22 terminais registados cada pedido gastava até 11
segundos de CPU, e o POS consulta as mesas de 10 em 10 segundos sozinho — o
servidor (1 CPU) saturava e tudo ficava lento. Estes testes prendem o
comportamento novo: caminho rápido sem bcrypt, e os registos antigos a serem
convertidos na primeira utilização.
"""
import asyncio
from datetime import datetime, timezone, timedelta

import server
from pos.auth import hash_token, token_fingerprint

FUTURO = (datetime.now(timezone.utc) + timedelta(days=30)).isoformat()
PASSADO = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()


class _Coll:
    def __init__(self, docs): self.docs = docs; self.updates = []
    async def find_one(self, q, projection=None):
        for d in self.docs:
            if all(k in d and d[k] == v for k, v in q.items() if not isinstance(v, dict)):
                return d
        return None
    def find(self, q, projection=None):
        faltam = "token_fingerprint" in q and q["token_fingerprint"] == {"$exists": False}
        sel = [d for d in self.docs
               if d.get("active") == q.get("active", True)
               and (not faltam or "token_fingerprint" not in d)]
        class C:
            async def to_list(self, n): return sel
        return C()
    async def update_one(self, q, u, **k): self.updates.append((q, u))


class _Db:
    def __init__(self, docs): self.pos_devices = _Coll(docs)


def _corre(docs, raw, monkeypatch, proibir_bcrypt=False):
    db = _Db(docs)
    monkeypatch.setattr(server, "db", db)
    if proibir_bcrypt:
        def explode(*a, **k):
            raise AssertionError("bcrypt foi chamado no caminho rápido!")
        monkeypatch.setattr(server, "verify_token", explode)
    return asyncio.run(server.valid_device_token(raw)), db


def test_caminho_rapido_encontra_sem_usar_bcrypt(monkeypatch):
    raw = "token-aleatorio-do-terminal"
    docs = [{"id": "d1", "active": True, "expires_at": FUTURO,
             "token_fingerprint": token_fingerprint(raw), "token_hash": "x"}]
    # bcrypt proibido: se for chamado, o teste rebenta.
    ok, _ = _corre(docs, raw, monkeypatch, proibir_bcrypt=True)
    assert ok is True


def test_token_errado_e_recusado(monkeypatch):
    docs = [{"id": "d1", "active": True, "expires_at": FUTURO,
             "token_fingerprint": token_fingerprint("certo"), "token_hash": "x"}]
    ok, _ = _corre(docs, "errado", monkeypatch)
    assert ok is False


def test_token_expirado_e_recusado(monkeypatch):
    raw = "token-velho"
    docs = [{"id": "d1", "active": True, "expires_at": PASSADO,
             "token_fingerprint": token_fingerprint(raw), "token_hash": "x"}]
    ok, _ = _corre(docs, raw, monkeypatch, proibir_bcrypt=True)
    assert ok is False


def test_registo_antigo_ainda_funciona_e_fica_convertido(monkeypatch):
    # Sem impressão digital: usa bcrypt uma vez E grava a impressão para a
    # próxima ser direta (senão o terminal antigo continuava lento para sempre).
    raw = "token-de-registo-antigo"
    docs = [{"id": "d1", "active": True, "expires_at": FUTURO,
             "token_hash": hash_token(raw)}]
    ok, db = _corre(docs, raw, monkeypatch)
    assert ok is True
    assert db.pos_devices.updates, "devia ter gravado a impressão digital"
    q, u = db.pos_devices.updates[0]
    assert q == {"id": "d1"}
    assert u["$set"]["token_fingerprint"] == token_fingerprint(raw)


def test_impressao_digital_e_estavel_e_distingue():
    assert token_fingerprint("a") == token_fingerprint("a")
    assert token_fingerprint("a") != token_fingerprint("b")
    assert len(token_fingerprint("a")) == 64
