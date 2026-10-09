"""Divisão da conta da MESA — tem de deixar emitir TODAS as partes.

Defeito do dono (2026-10-09): dividiu por 9, saiu a 1.ª fatura e o ecrã não
deixou avançar. O fecho marcava TODAS as linhas pagas logo na 1.ª parte (o ciclo
genérico de "marcar pagos" corria também na divisão), a conta ficava vazia e a
parte 2 dava "Mesa sem conta em aberto". As linhas só podem ficar pagas na
ÚLTIMA parte — e aí o pedido fica pago e a mesa fecha.
"""
import asyncio
import copy

import pytest
from fastapi import HTTPException

import server
from server import CloseTableRequest, close_table, create_token, free_table


# ---- Mongo de bolso: o suficiente para o close_table correr de ponta a ponta ----

def _match(doc, q):
    for k, v in q.items():
        cur = doc.get(k)
        if isinstance(v, dict) and any(str(x).startswith("$") for x in v):
            if "$ne" in v and cur == v["$ne"]:
                return False
            if "$in" in v and cur not in v["$in"]:
                return False
        elif cur != v:
            return False
    return True


def _set(doc, path, value):
    *head, last = path.split(".")
    for p in head:
        doc = doc[int(p)] if isinstance(doc, list) else doc.setdefault(p, {})
    if isinstance(doc, list):
        doc[int(last)] = value
    else:
        doc[last] = value


class _Cursor:
    def __init__(self, docs): self._docs = docs
    def sort(self, *a, **k): return self
    async def to_list(self, n): return self._docs
    def __aiter__(self):
        async def gen():
            for d in self._docs:
                yield d
        return gen()


class _Res:
    modified_count = 0


class _Coll:
    def __init__(self, docs=None): self.docs = [copy.deepcopy(d) for d in docs or []]
    async def find_one(self, q, projection=None):
        for d in self.docs:
            if _match(d, q):
                return copy.deepcopy(d)
        return None
    def find(self, q, projection=None):
        return _Cursor([copy.deepcopy(d) for d in self.docs if _match(d, q)])
    async def update_one(self, q, u, **k):
        for d in self.docs:
            if _match(d, q):
                for p, v in u.get("$set", {}).items():
                    _set(d, p, v)
                break
    async def update_many(self, q, u, **k):
        r = _Res()
        for d in self.docs:
            if _match(d, q):
                for p, v in u.get("$set", {}).items():
                    _set(d, p, v)
                r.modified_count += 1
        return r
    async def insert_one(self, d): self.docs.append(copy.deepcopy(d))
    async def insert_many(self, ds, **k): self.docs.extend(copy.deepcopy(ds))
    async def delete_one(self, q):
        for d in self.docs:
            if _match(d, q):
                self.docs.remove(d)
                break


class _Db:
    def __init__(self, orders):
        self.orders = _Coll(orders)
        self.products = _Coll()
        self.cash_sessions = _Coll()             # sem caixa: o admin passa à mesma
        self.split_plans = _Coll()
        self.table_sessions = _Coll([{"table_number": 4, "status": "open"}])
        self.pos_sales = _Coll()
        self.print_jobs = _Coll()


class _FakeVendus:
    emitidas = []
    def list_app_invoices(self, date=None): return []
    def create_invoice(self, items, payments, client, external_reference, doc_type, output):
        _FakeVendus.emitidas.append({"amount": payments[0]["amount"],
                                     "ext_ref": external_reference, "client": client})
        n = len(_FakeVendus.emitidas)
        return {"id": f"d{n}", "number": f"FS 1/{n}", "output": None}
    def close(self): pass


def _mesa():
    return [{"id": "o1", "table_number": 4, "paid": False, "status": "delivered",
             "source": "client", "created_at": "2026-10-09T20:00:00",
             "items": [
                 {"product_id": "p1", "product_name": "Pizza", "quantity": 1,
                  "unit_price": 18.0, "total_price": 18.0, "vendus_tax_id": "INT"},
                 {"product_id": "p2", "product_name": "Coca-Cola", "quantity": 3,
                  "unit_price": 3.0, "total_price": 9.0, "vendus_tax_id": "NOR"},
             ]}]


@pytest.fixture
def db(monkeypatch):
    d = _Db(_mesa())
    _FakeVendus.emitidas = []
    monkeypatch.setattr(server, "db", d)
    monkeypatch.setattr(server, "_vendus_client", lambda *a, **k: _FakeVendus())
    return d


_ADMIN = f"Bearer {create_token('a1', 'gestor@lenhaebrasa.com')}"


def _fecha(split_count=1, metodo=1, nif=None):
    req = CloseTableRequest(payment_method_id=metodo, split_count=split_count, nif=nif)
    return asyncio.run(close_table(4, req, authorization=_ADMIN,
                                   x_device_token=None, x_pos_token=None))


def _conta():
    return asyncio.run(server.get_table_bill(4, authorization=_ADMIN, x_device_token=None))


def test_divisao_deixa_emitir_todas_as_partes(db):
    r1 = _fecha(split_count=3, metodo=1, nif="123456789")
    assert (r1["part"], r1["of"], r1["table_free"]) == (1, 3, False)

    # Ao voltar ao ecrã a conta tem de continuar lá (senão o botão desliga-se).
    conta = _conta()
    assert len(conta["lines"]) == 2
    assert conta["split"]["part"] == 1 and conta["split"]["of"] == 3

    r2 = _fecha(split_count=3, metodo=2)
    assert (r2["part"], r2["of"], r2["table_free"]) == (2, 3, False)
    r3 = _fecha(split_count=3, metodo=1)
    assert (r3["part"], r3["of"], r3["table_free"]) == (3, 3, True)

    # 3 faturas, cada uma com a SUA ext_ref, a somar EXATAMENTE a conta (27,00).
    assert len(_FakeVendus.emitidas) == 3
    assert len({e["ext_ref"] for e in _FakeVendus.emitidas}) == 3
    assert round(sum(e["amount"] for e in _FakeVendus.emitidas), 2) == 27.0
    # Cada parte leva o SEU NIF.
    assert [e["client"] for e in _FakeVendus.emitidas] == [{"fiscal_id": "123456789"}, None, None]

    # Só na última: linhas pagas, PEDIDO pago, plano apagado, mesa fechada.
    o = db.orders.docs[0]
    assert all(it.get("paid") for it in o["items"])
    assert o["paid"] is True
    assert db.split_plans.docs == []
    assert db.table_sessions.docs[0]["status"] == "closed"


def test_a_meio_da_divisao_nada_fica_pago(db):
    _fecha(split_count=9)
    o = db.orders.docs[0]
    assert not any(it.get("paid") for it in o["items"])
    assert o["paid"] is False
    assert db.table_sessions.docs[0]["status"] == "open"


def test_sem_divisao_continua_a_pagar_e_fechar(db):
    r = _fecha()
    assert r["table_free"] is True and r["of"] is None
    assert db.orders.docs[0]["paid"] is True
    assert db.table_sessions.docs[0]["status"] == "closed"


def test_nao_se_liberta_a_mesa_a_meio_da_divisao(db):
    # Libertar a meio cancelava os pedidos (com FS já emitida) e deixava o plano
    # pendurado na mesa — os clientes seguintes pagariam a parte 2 da conta antiga.
    _fecha(split_count=3)
    with pytest.raises(HTTPException) as e:
        asyncio.run(free_table(4, authorization=_ADMIN, x_device_token=None))
    assert e.value.status_code == 409
    assert db.orders.docs[0]["status"] != "cancelled"
    assert db.split_plans.docs != []
