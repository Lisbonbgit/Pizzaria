"""Idempotência fiscal — referência ESTÁVEL para a `external_reference` do Vendus.

O fecho de mesa (`close_table`) tinha refs baseadas no relógio
(`mesa-N-<timestamp>`), por isso cada RETRY do mesmo fecho gerava uma ref nova e
o Vendus emitia uma FS nova = cobrança dupla. Aqui a ref deriva de
(mesa, sessão de caixa, CHAVE do fecho) por hash determinístico.

⚠️ A CHAVE tem de ser: (a) ESTÁVEL entre retries do MESMO fecho, mas
(b) DISTINTA entre fechos diferentes — senão dois fechos genuinamente diferentes
com os mesmos itens (ex.: a mesma mesa a vender outra Coca na mesma sessão)
colidiam e o 2º reutilizava a FS do 1º = SUB-FATURAÇÃO. Por isso a chave NÃO é o
conteúdo dos itens; é a IDENTIDADE do que está a ser faturado:
  - à la carte / dividir: o conjunto de linhas `(order_id, idx)` faturadas (que
    ficam por pagar até ao fecho, logo estáveis no retry e distintas por pedido);
  - rodízio: o estado pago-ANTES + as pessoas/contagens pagas AGORA + os extras.

PURA de propósito: sem I/O, sem relógio — só entrada → saída determinística.
"""
import hashlib
import json


def stable_ext_ref(table_number, cash_session_id, key_obj, rodizio: bool = False) -> str:
    """Referência fiscal determinística para uma fatura.

    Args:
        table_number: número da mesa fechada.
        cash_session_id: id da sessão de caixa aberta; "legacy" no admin sem caixa.
        key_obj: a CHAVE do fecho (identidade), NÃO o conteúdo dos itens — ver o
            docstring do módulo. Qualquer objeto JSON-serializável determinístico.
        rodizio: se True, insere o token `rodizio` na ref (para o relatório diário
            continuar a rotular "Mesa N (rodízio)").

    Returns:
        str: `mesa-{table}-[rodizio-]{cash_session_id}-{hash10}`.
        Mesma chave → MESMA ref (idempotente no retry). Chave diferente → ref
        diferente (fecho diferente → documento diferente).
    """
    h = hashlib.sha1(
        json.dumps(key_obj, sort_keys=True, ensure_ascii=False, default=str).encode()
    ).hexdigest()[:10]
    meio = "rodizio-" if rodizio else ""
    return f"mesa-{table_number}-{meio}{cash_session_id}-{h}"
