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
from server import (CloseTableRequest, CounterCheckoutRequest, SetRodizioRequest,
                    cancel_counter_order, cancel_table_split, checkout_counter_order,
                    close_table, counter_open_split, create_pos_token, create_token,
                    free_table, set_table_rodizio)


# ---- Mongo de bolso: o suficiente para o close_table correr de ponta a ponta ----

def _get(doc, path):
    for p in path.split("."):
        doc = doc.get(p) if isinstance(doc, dict) else None
    return doc


def _match(doc, q):
    for k, v in q.items():
        cur = _get(doc, k)
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
    async def find_one(self, q, projection=None, **k):
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
    def list_app_invoices(self, date=None):
        return [{"id": f"d{i + 1}", "number": f"FS 1/{i + 1}", "external_reference": e["ext_ref"]}
                for i, e in enumerate(_FakeVendus.emitidas)]
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


def _fecha(split_count=1, metodo=1, nif=None, **extra):
    req = CloseTableRequest(payment_method_id=metodo, split_count=split_count, nif=nif, **extra)
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


def _status(fn):
    with pytest.raises(HTTPException) as e:
        fn()
    return e.value.status_code


def test_o_ecra_sabe_quanto_cobrar_em_cada_parte(db):
    # 27,00 em 7: seis partes de 3,86 e a última de 3,84. O operador marca o valor
    # no terminal à mão — tem de ver o da PARTE, não o da conta inteira.
    r1 = _fecha(split_count=7)
    assert r1["amount"] == 3.86 and r1["next_amount"] == 3.86
    assert _conta()["split"]["next_amount"] == 3.86
    for _ in range(5):
        r = _fecha(split_count=7)
    assert r["part"] == 6 and r["next_amount"] == 3.84
    assert _conta()["split"]["next_amount"] == 3.84
    r7 = _fecha(split_count=7)
    assert r7["amount"] == 3.84 and r7["next_amount"] is None and r7["table_free"] is True


def test_a_meio_da_divisao_so_se_continua_a_divisao(db):
    _fecha(split_count=3)
    linhas = [{"order_id": "o1", "idx": 0}, {"order_id": "o1", "idx": 1}]
    # Separar Conta com TODOS os itens emitia em silêncio a parte seguinte, sem NIF.
    assert _status(lambda: _fecha(split_count=3, items=linhas)) == 409
    # Fechar como rodízio cobrava de novo o que já estava faturado.
    assert _status(lambda: _fecha(split_count=3, rodizio_tier="simples", adults=1)) == 409
    assert _status(lambda: asyncio.run(set_table_rodizio(
        4, SetRodizioRequest(tier="simples", adults=1), authorization=_ADMIN,
        x_device_token=None))) == 409
    # Outro N (o ecrã dessincronizado depois de um erro do Vendus) emitia uma
    # parte da divisão antiga com o valor errado.
    assert _status(lambda: _fecha(split_count=1)) == 409
    assert _status(lambda: _fecha(split_count=9)) == 409
    assert len(_FakeVendus.emitidas) == 1
    assert _fecha(split_count=3)["part"] == 2


def test_cliente_nao_liga_o_rodizio_pelo_qr_a_meio_da_divisao(db):
    # A porta pública do QR também passava a mesa a rodízio.
    db.table_sessions.docs[0].update({"id": "s1", "rodizio": "none"})
    _fecha(split_count=3)
    asyncio.run(server.open_table_session(4, server.OpenTableRequest(rodizio="simples", adults=2)))
    assert db.table_sessions.docs[0]["rodizio"] == "none"


def test_ultima_parte_que_morreu_a_meio_acaba_sem_nova_fatura(db):
    # Crash entre marcar a última parte e marcar as linhas: o plano ficava com
    # todas as partes pagas e a mesa travada para sempre ("Divisão já concluída").
    _fecha(split_count=2)
    _fecha(split_count=2)                                  # 2 FS, mesa fechada
    db.orders.docs[0]["paid"] = False                      # repõe o estado do crash
    for it in db.orders.docs[0]["items"]:
        it["paid"] = False
    db.table_sessions.docs[0]["status"] = "open"
    db.split_plans.docs.append({"target": {"kind": "table", "id": 4}, "n": 2, "total": 27.0,
                                "finalize": {"line_ids": [["o1", 0], ["o1", 1]]},
                                "shares": [{"amount": 13.5, "paid": True, "doc_number": "FS 1/1", "ext_ref": "a"},
                                           {"amount": 13.5, "paid": True, "doc_number": "FS 1/2", "ext_ref": "b"}]})
    r = _fecha(split_count=2)
    assert r["table_free"] is True
    assert len(_FakeVendus.emitidas) == 2                  # nenhuma FS nova
    assert db.orders.docs[0]["paid"] is True
    assert db.split_plans.docs == []
    assert db.table_sessions.docs[0]["status"] == "closed"


def test_nao_cancela_a_divisao_se_o_vendus_ja_tem_a_fatura(db):
    # O Vendus pode criar a FS e responder 503: a parte fica por marcar. Cancelar
    # aí e fechar por inteiro faturava duas vezes o mesmo.
    _fecha(split_count=3)
    plano = db.split_plans.docs[0]
    plano["shares"][0]["paid"] = False                     # como se a resposta se perdesse
    assert _status(lambda: asyncio.run(cancel_table_split(
        4, authorization=_ADMIN, x_device_token=None))) == 409
    assert db.split_plans.docs != []
    # Sem FS no Vendus, cancela.
    _FakeVendus.emitidas = []
    assert asyncio.run(cancel_table_split(4, authorization=_ADMIN, x_device_token=None))["cancelled"]
    assert db.split_plans.docs == []


def test_pedido_com_item_anulado_fica_pago(db):
    db.orders.docs[0]["items"].append({"product_id": "p3", "product_name": "Erro", "quantity": 1,
                                       "unit_price": 5.0, "total_price": 5.0, "removed": True})
    _fecha()
    assert db.orders.docs[0]["paid"] is True


# ---- Balcão ----

_POS = create_pos_token("op-1", "Ana")


def _balcao(db):
    db.orders.docs = [{"id": "b1", "order_number": 42, "source": "balcao", "paid": False,
                       "status": "received", "total": 27.0, "items": _mesa()[0]["items"]}]


def _cobra(split_count=1, metodo=1):
    body = CounterCheckoutRequest(order_id="b1", payment_method_id=metodo, split_count=split_count)
    return asyncio.run(checkout_counter_order(body, authorization=_ADMIN, x_device_token=None,
                                              x_pos_token=_POS))


def test_balcao_nao_cancela_a_venda_a_meio_da_divisao(db):
    _balcao(db)
    r = _cobra(split_count=3)
    assert r["order_paid"] is False and r["next_amount"] == 9.0
    assert _status(lambda: asyncio.run(cancel_counter_order(
        "b1", authorization=_ADMIN, x_device_token=None))) == 409
    assert db.orders.docs[0]["status"] != "cancelled"
    assert _status(lambda: _cobra(split_count=1)) == 409   # outro N
    assert _cobra(split_count=3)["part"] == 2


def test_balcao_retoma_a_divisao_depois_de_recarregar(db):
    _balcao(db)
    assert asyncio.run(counter_open_split(authorization=_ADMIN, x_device_token=None)) == []
    _cobra(split_count=3)
    [v] = asyncio.run(counter_open_split(authorization=_ADMIN, x_device_token=None))
    assert v["order_id"] == "b1" and v["order_number"] == 42 and len(v["items"]) == 2
    assert v["split"] == {"part": 1, "of": 3, "remaining": 18.0, "next_amount": 9.0}
    _cobra(split_count=3)
    r = _cobra(split_count=3)
    assert r["order_paid"] is True and r["next_amount"] is None
    assert db.orders.docs[0]["paid"] is True
    assert asyncio.run(counter_open_split(authorization=_ADMIN, x_device_token=None)) == []


def test_balcao_nao_retoma_venda_ja_paga_ou_cancelada(db):
    # Um plano esquecido (código antigo) não pode ressuscitar uma venda fechada.
    _balcao(db)
    _cobra(split_count=3)
    for estado in ({"paid": True}, {"status": "cancelled"}):
        db.orders.docs[0].update(estado)
        assert asyncio.run(counter_open_split(authorization=_ADMIN, x_device_token=None)) == []
        db.orders.docs[0].update({"paid": False, "status": "received"})


def test_balcao_ultima_parte_que_morreu_a_meio_acaba_sem_nova_fatura(db):
    _balcao(db)
    db.split_plans.docs.append({"target": {"kind": "counter", "id": "b1"}, "n": 2, "total": 27.0,
                                "finalize": {"order_id": "b1"},
                                "shares": [{"amount": 13.5, "paid": True, "doc_number": "FS 1/1", "ext_ref": "a"},
                                           {"amount": 13.5, "paid": True, "doc_number": "FS 1/2", "ext_ref": "b"}]})
    r = _cobra(split_count=2)
    assert r["order_paid"] is True and r["doc_number"] == "FS 1/2"
    assert _FakeVendus.emitidas == []
    assert db.orders.docs[0]["paid"] is True and db.split_plans.docs == []


def _plano_todo_pago(kind, ident, finalize):
    return {"target": {"kind": kind, "id": ident}, "n": 2, "total": 27.0, "finalize": finalize,
            "shares": [{"amount": 13.5, "paid": True, "doc_number": "FS 1/1", "ext_ref": "a"},
                       {"amount": 13.5, "paid": True, "doc_number": "FS 1/2", "ext_ref": "b"}]}


def test_abrir_a_conta_acaba_divisao_que_morreu_na_ultima_parte(db):
    # Sem isto o ecrã mostrava "Parte 3 de 2" com um valor para cobrar a alguém.
    db.split_plans.docs.append(_plano_todo_pago("table", 4, {"line_ids": [["o1", 0], ["o1", 1]]}))
    conta = _conta()
    assert conta["split"] is None and conta["lines"] == []
    assert db.orders.docs[0]["paid"] is True and db.split_plans.docs == []
    assert db.table_sessions.docs[0]["status"] == "closed"
    assert _FakeVendus.emitidas == []


def test_balcao_lista_de_retoma_acaba_divisao_que_morreu_na_ultima_parte(db):
    _balcao(db)
    db.split_plans.docs.append(_plano_todo_pago("counter", "b1", {"order_id": "b1"}))
    assert asyncio.run(counter_open_split(authorization=_ADMIN, x_device_token=None)) == []
    assert db.orders.docs[0]["paid"] is True and db.split_plans.docs == []


def test_balcao_regista_a_venda_mesmo_que_morra_ao_marcar_a_parte(db, monkeypatch):
    # O registo da venda (fecho Z) vinha DEPOIS de marcar a parte: um crash aí
    # deixava uma FS real sem linha em pos_sales.
    _balcao(db)
    db.cash_sessions.docs.append({"id": "cx", "status": "open", "opened_at": "2026-10-14T08:00:00+00:00"})

    async def morre(*a, **k):
        raise RuntimeError("crash")
    monkeypatch.setattr(server, "_mark_share_paid", morre)
    with pytest.raises(RuntimeError):
        _cobra(split_count=3)
    assert len(_FakeVendus.emitidas) == 1
    assert len(db.pos_sales.docs) == 1
