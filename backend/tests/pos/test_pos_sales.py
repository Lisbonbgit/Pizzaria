"""Linhas de venda POS por documento (`pos_sales`) — lógica pura, sem I/O.

`build_pos_sales_rows` faz `zip(invoices, docs)` e devolve UMA linha por
documento emitido no Vendus (um fecho de mesa pode emitir N documentos:
split_count>1 → uma FS por pessoa; rodízio parcial → documento a documento).
A sessão de caixa e o operador NUNCA vêm do corpo do pedido — são resolvidos
no servidor e passados aqui já validados (ver close_table em server.py).
"""
from pos.sales import build_pos_sales_rows


def test_uma_linha_por_documento():
    # Brief: 2 faturas + 2 documentos → 2 linhas, com o id/número/valor certos.
    invoices = [{"amount": 40.0}, {"amount": 45.0}]
    docs = [{"id": 11, "number": "FS 1"}, {"id": 12, "number": "FS 2"}]
    rows = build_pos_sales_rows(invoices, docs, 316430468, "s1", "u1", "mesa", 5)
    assert len(rows) == 2
    assert rows[0]["vendus_document_id"] == 11 and rows[0]["amount"] == 40.0
    assert rows[1]["doc_number"] == "FS 2" and rows[1]["cash_session_id"] == "s1"


def test_campos_completos_da_linha():
    # Cada linha carrega toda a proveniência: operador, método, tipo, mesa,
    # id único e created_at — o que o fecho Z e a reconciliação (Task 10) usam.
    invoices = [{"amount": 12.5}]
    docs = [{"id": 99, "number": "FS 7"}]
    row = build_pos_sales_rows(invoices, docs, 316430468, "sess-x", "op-9", "rodizio", 3)[0]
    assert row["cash_session_id"] == "sess-x"
    assert row["pos_user_id"] == "op-9"
    assert row["vendus_document_id"] == 99
    assert row["doc_number"] == "FS 7"
    assert row["amount"] == 12.5
    assert row["payment_method_id"] == 316430468
    assert row["kind"] == "rodizio"
    assert row["table_number"] == 3
    assert isinstance(row["id"], str) and row["id"]
    assert "created_at" in row


def test_uma_so_fatura():
    # n==1 (fatura única itemizada) → exatamente uma linha.
    rows = build_pos_sales_rows(
        [{"amount": 30.0}], [{"id": 5, "number": "FS 5"}],
        316430468, "s2", "u2", "mesa", 8,
    )
    assert len(rows) == 1
    assert rows[0]["vendus_document_id"] == 5


def test_ids_unicos_por_linha():
    # O id de cada linha é um UUID próprio (não colide entre documentos).
    invoices = [{"amount": 10.0}, {"amount": 20.0}]
    docs = [{"id": 1, "number": "FS 1"}, {"id": 2, "number": "FS 2"}]
    rows = build_pos_sales_rows(invoices, docs, 1, "s", "u", "mesa", 1)
    assert rows[0]["id"] != rows[1]["id"]


def test_montante_arredondado_a_2_casas():
    # O valor é dinheiro → 2 casas decimais.
    rows = build_pos_sales_rows(
        [{"amount": 10.005}], [{"id": 3, "number": "FS 3"}],
        1, "s", "u", "mesa", 1,
    )
    assert rows[0]["amount"] == 10.01


def test_sem_faturas_devolve_lista_vazia():
    # Sem documentos não há linhas (nunca deve acontecer no fecho, mas é seguro).
    assert build_pos_sales_rows([], [], 1, "s", "u", "mesa", 1) == []


def test_zip_para_no_mais_curto():
    # Defensivo: se as listas tiverem tamanhos diferentes, zip para na mais
    # curta — nunca inventa uma linha sem documento correspondente.
    invoices = [{"amount": 1.0}, {"amount": 2.0}]
    docs = [{"id": 1, "number": "FS 1"}]
    rows = build_pos_sales_rows(invoices, docs, 1, "s", "u", "mesa", 1)
    assert len(rows) == 1
