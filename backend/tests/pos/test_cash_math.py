"""Cálculo do dinheiro esperado em caixa — lógica pura, sem I/O.

`expected_cash` soma a abertura, as vendas em dinheiro e os reforços, e
subtrai as sangrias. Usado pelo endpoint `POST /api/pos/cash/movement`
(para mostrar o esperado corrente) e, mais tarde, pelo fecho/reconciliação
(Task 10).
"""
from pos.cash_math import cash_sales_from_vendus, expected_cash, movements_breakdown


def test_expected_cash():
    movs = [{"type": "reforco", "amount": 20.0}, {"type": "sangria", "amount": 50.0}]
    # 100 abertura + 300 vendas dinheiro + 20 reforco - 50 sangria = 370
    assert expected_cash(100.0, 300.0, movs) == 370.0


def test_expected_cash_sem_movimentos():
    # Sem sangria/reforço, o esperado é só abertura + vendas em dinheiro.
    assert expected_cash(50.0, 120.0, []) == 170.0


def test_expected_cash_so_sangria():
    # Só sangrias: o esperado desce abaixo de abertura + vendas.
    movs = [{"type": "sangria", "amount": 30.0}, {"type": "sangria", "amount": 15.0}]
    assert expected_cash(100.0, 0.0, movs) == 55.0


def test_movements_breakdown_soma_reforcos_e_sangrias_em_separado():
    movs = [
        {"type": "reforco", "amount": 20.0},
        {"type": "reforco", "amount": 5.5},
        {"type": "sangria", "amount": 50.0},
    ]
    assert movements_breakdown(movs) == {"reforcos": 25.5, "sangrias": 50.0}


def test_movements_breakdown_vazio():
    assert movements_breakdown([]) == {"reforcos": 0.0, "sangrias": 0.0}


# ---- cash_sales_from_vendus (Fase 4b: partilhada pelo fecho e pela
# pré-visualização `GET /pos/cash/expected`) ----

def test_cash_sales_from_vendus_identifica_pelo_id_configurado():
    vendus = {"by_method": {"Dinheiro": {"total": 56.25, "count": 1}, "Multibanco": {"total": 10.0, "count": 1}}}
    metodos = [{"id": 1, "title": "Dinheiro"}, {"id": 2, "title": "Multibanco"}]
    r = cash_sales_from_vendus(vendus, metodos, 1)
    assert r["cash_sales"] == 56.25
    assert r["warnings"] == []
    assert r["vendus_by_method"] == vendus["by_method"]
    assert r["id_to_title"] == {"1": "Dinheiro", "2": "Multibanco"}


def test_cash_sales_from_vendus_sem_metodo_configurado_da_aviso_e_zero():
    vendus = {"by_method": {"Dinheiro": {"total": 56.25, "count": 1}}}
    metodos = [{"id": 1, "title": "Dinheiro"}]
    r = cash_sales_from_vendus(vendus, metodos, None)
    assert r["cash_sales"] == 0.0
    assert len(r["warnings"]) == 1
    assert "não está configurado" in r["warnings"][0]


def test_cash_sales_from_vendus_metodo_configurado_nao_existe_no_vendus():
    vendus = {"by_method": {"Dinheiro": {"total": 56.25, "count": 1}}}
    metodos = [{"id": 1, "title": "Dinheiro"}]
    r = cash_sales_from_vendus(vendus, metodos, 999)
    assert r["cash_sales"] == 0.0
    assert len(r["warnings"]) == 1
    assert "não foi encontrado no Vendus" in r["warnings"][0]


def test_cash_sales_from_vendus_metodo_id_como_string_bate_com_int():
    # `cash_method_id` guardado nas definições pode chegar como int; os ids
    # do Vendus/JSON também podem vir numéricos — a comparação é sempre str.
    vendus = {"by_method": {"Dinheiro": {"total": 100.0, "count": 2}}}
    metodos = [{"id": "1", "title": "Dinheiro"}]
    r = cash_sales_from_vendus(vendus, metodos, 1)
    assert r["cash_sales"] == 100.0
