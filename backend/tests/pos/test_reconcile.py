"""Reconciliação da caixa (`reconciliation_diff`) — lógica pura, sem I/O.

Compara a repartição por método de pagamento do Vendus (verdade fiscal, lida
por JANELA temporal do fecho) com a das `pos_sales` da sessão (o registo em
Mongo). Bate → `ok=True`; diverge (total OU contagem, ou método em falta) →
`ok=False` e o método fica listado em `orphans`/`missing`. A reconciliação NUNCA
bloqueia o fecho — só sinaliza divergências para o operador (Task 10).
"""
from pos.cash_math import reconciliation_diff


def test_reconcile_ok_e_orfaos():
    v = {"Dinheiro": {"total": 56.25, "count": 1}, "Multibanco": {"total": 199.65, "count": 3}}
    p = {"Dinheiro": {"total": 56.25, "count": 1}, "Multibanco": {"total": 199.65, "count": 3}}
    assert reconciliation_diff(v, p)["ok"] is True

    p2 = {"Dinheiro": {"total": 56.25, "count": 1}}     # falta Multibanco em pos_sales
    r = reconciliation_diff(v, p2)
    assert r["ok"] is False and "Multibanco" in r["orphans"]


def test_reconcile_divergencia_de_total():
    # Total diferente no mesmo método → não bate (mesmo com a contagem igual).
    v = {"Dinheiro": {"total": 56.25, "count": 2}}
    p = {"Dinheiro": {"total": 50.00, "count": 2}}
    r = reconciliation_diff(v, p)
    assert r["ok"] is False and "Dinheiro" in r["orphans"]


def test_reconcile_divergencia_de_contagem():
    # Mesmo total, contagem diferente → não bate.
    v = {"Multibanco": {"total": 100.0, "count": 3}}
    p = {"Multibanco": {"total": 100.0, "count": 2}}
    r = reconciliation_diff(v, p)
    assert r["ok"] is False and "Multibanco" in r["orphans"]


def test_reconcile_metodo_so_no_pos_sales_vai_para_missing():
    # Método que existe nas pos_sales mas não no Vendus → "missing" (registo POS
    # sem contrapartida fiscal). Não deve aparecer em "orphans".
    v = {"Dinheiro": {"total": 10.0, "count": 1}}
    p = {"Dinheiro": {"total": 10.0, "count": 1}, "MBWay": {"total": 5.0, "count": 1}}
    r = reconciliation_diff(v, p)
    assert r["ok"] is False
    assert "MBWay" in r["missing"] and "MBWay" not in r["orphans"]


def test_reconcile_vazio_bate():
    # Sessão sem vendas em nenhum dos lados → bate (nada a reconciliar).
    assert reconciliation_diff({}, {})["ok"] is True
