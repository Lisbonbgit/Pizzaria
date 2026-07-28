"""Linhas de venda POS (`pos_sales`) — lógica pura, sem I/O.

Uma venda POS é UMA linha por documento fiscal emitido no Vendus. Um único
fecho de mesa (`close_table`) pode emitir N documentos:
  * `split_count > 1` → uma Fatura Simplificada (FS) por pessoa;
  * rodízio parcial → documento a documento à medida que se vai pagando.

`build_pos_sales_rows` faz o `zip(invoices, docs)` e produz essas linhas. É
PURA de propósito: recebe a sessão de caixa e o operador já resolvidos no
servidor (a sessão de `cash_sessions`, o operador do token POS) — NUNCA do
corpo do pedido, para a proveniência da venda não ser falsificável (§2.6).

As linhas alimentam o fecho Z e a reconciliação da Task 10. O índice único em
`vendus_document_id` (criado no arranque, ver server.lifespan) torna a inserção
idempotente: um retry de um fecho já gravado não duplica linhas.
"""
import uuid
from datetime import datetime, timezone


def build_pos_sales_rows(invoices, docs, payment_method_id, cash_session_id,
                         pos_user_id, kind, table_number):
    """Constrói uma linha de `pos_sales` por documento emitido.

    `invoices` e `docs` andam a par (um documento por fatura, pela mesma ordem
    em que foram emitidos em `close_table._emit_all`). Faz `zip`, por isso para
    na lista mais curta — defensivo, nunca inventa uma linha sem documento.

    Args:
        invoices: lista de `{"amount": float, ...}` (as faturas construídas no fecho).
        docs: lista de respostas do Vendus (`{"id", "number", ...}`), a par de `invoices`.
        payment_method_id: id do método de pagamento Vendus usado no fecho.
        cash_session_id: id da sessão de caixa aberta (resolvido no servidor).
        pos_user_id: id do operador (do token POS); pode ser `None` no legado.
        kind: tipo da venda ("mesa" à la carte / "rodizio").
        table_number: número da mesa fechada.

    Returns:
        list[dict]: uma linha por documento, pronta para `insert_many`.
    """
    rows = []
    for inv, doc in zip(invoices, docs):
        rows.append({
            "id": str(uuid.uuid4()),
            "cash_session_id": cash_session_id,
            "pos_user_id": pos_user_id,
            "vendus_document_id": doc.get("id"),
            "doc_number": doc.get("number"),
            "amount": round(float(inv.get("amount", 0) or 0), 2),
            "payment_method_id": payment_method_id,
            "kind": kind,
            "table_number": table_number,
            "created_at": datetime.now(timezone.utc).isoformat(),
        })
    return rows
