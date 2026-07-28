"""Idempotência fiscal — referência ESTÁVEL para a `external_reference` do Vendus.

O fecho de mesa (`close_table`) tinha refs baseadas no relógio
(`mesa-N-<timestamp>`), por isso cada RETRY do mesmo fecho gerava uma ref nova e
o Vendus emitia uma FS nova = cobrança dupla. Aqui a ref deriva SÓ de
(mesa, sessão de caixa, itens) por hash determinístico: o mesmo fecho dá sempre
a MESMA ref. Com isso, `close_table` consulta os documentos do dia, encontra o
que já tem essa ref e reutiliza-o em vez de emitir uma 2ª fatura.

PURA de propósito: sem I/O, sem relógio — só entrada → saída determinística.
"""
import hashlib
import json


def stable_ext_ref(table_number, cash_session_id, items) -> str:
    """Referência fiscal determinística para uma fatura.

    Mesma (mesa, sessão, itens) → MESMA ref (idempotente para o retry).
    Itens diferentes → ref diferente (fecho diferente, documento diferente).

    O hash é sobre o JSON canónico dos `items` (as chaves ordenadas com
    `sort_keys=True`; `ensure_ascii=False` para acentos não alterarem os bytes).
    Trunca-se a 10 hex — chega para distinguir fechos sem alongar a ref.

    Args:
        table_number: número da mesa fechada.
        cash_session_id: id da sessão de caixa aberta; "legacy" no admin sem caixa.
        items: lista dos itens dessa fatura (o mesmo `vendus_items`/`items_i`
            que segue para o Vendus).

    Returns:
        str: `mesa-{table_number}-{cash_session_id}-{hash10}`.
    """
    h = hashlib.sha1(
        json.dumps(items, sort_keys=True, ensure_ascii=False).encode()
    ).hexdigest()[:10]
    return f"mesa-{table_number}-{cash_session_id}-{h}"
