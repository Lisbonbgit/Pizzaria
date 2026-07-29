"""Cálculo do dinheiro esperado em caixa (`expected_cash`) — sem I/O.

Fase 1 (Task 7): helper puro partilhado pelo endpoint de movimentos
(`POST /api/pos/cash/movement`, para mostrar o esperado corrente) e, mais
tarde, pelo fecho/reconciliação da caixa (Task 10).
"""
from typing import List, Dict, Any


def expected_cash(opening: float, cash_sales: float, movements: List[Dict[str, Any]]) -> float:
    """Devolve o dinheiro esperado em caixa: abertura + vendas em dinheiro +
    reforços - sangrias, arredondado a 2 casas decimais (dinheiro = 2 casas).

    `movements` é a lista `cash_sessions.movements` — cada item tem
    `type` ("sangria" ou "reforco") e `amount` (sempre positivo)."""
    reforcos = sum(m["amount"] for m in movements if m["type"] == "reforco")
    sangrias = sum(m["amount"] for m in movements if m["type"] == "sangria")
    return round(opening + cash_sales + reforcos - sangrias, 2)


def movements_breakdown(movements: List[Dict[str, Any]]) -> Dict[str, float]:
    """Soma reforços e sangrias de `cash_sessions.movements` em separado (cada
    total arredondado a 2 casas) — usado pela pré-visualização do esperado
    (`GET /pos/cash/expected`) para mostrar a composição do valor sem repetir
    a soma que `expected_cash` já faz internamente."""
    reforcos = round(sum(m["amount"] for m in movements if m["type"] == "reforco"), 2)
    sangrias = round(sum(m["amount"] for m in movements if m["type"] == "sangria"), 2)
    return {"reforcos": reforcos, "sangrias": sangrias}


def cash_sales_from_vendus(vendus: Dict[str, Any], metodos: List[Dict[str, Any]],
                            cash_method_id: Any) -> Dict[str, Any]:
    """A partir da resposta do Vendus por janela (`app_sales_summary_window`,
    com `by_method`) e da lista de métodos de pagamento
    (`list_payment_methods`), identifica as vendas em DINHEIRO pelo ID
    configurado (`cash_method_id`) — nunca pela string "Dinheiro" — e devolve:

      * `cash_sales`       — total em dinheiro na janela (2 casas decimais).
      * `warnings`         — avisos (método não configurado / não encontrado
                              no Vendus); vazio quando tudo bate.
      * `vendus_by_method` — o `by_method` do Vendus, repassado (o fecho
                              usa-o também para a reconciliação e para o Z).
      * `id_to_title`      — mapa id→título dos métodos (chaves normalizadas
                              a str), para alinhar as `pos_sales` com o Vendus.

    Função PURA: sem I/O. Partilhada pelo fecho (`POST /pos/cash/close`) e
    pela pré-visualização best-effort (`GET /pos/cash/expected`) — garante
    que os dois calculam exatamente o mesmo `cash_sales` a partir da mesma
    resposta do Vendus (DRY: nunca podem divergir)."""
    vendus_by_method = vendus.get("by_method") or {}
    # Chaves normalizadas a str — o id vem numérico do Vendus e Optional[int]
    # das definições; comparar como str evita surpresas int/str do JSON.
    id_to_title = {
        str(m.get("id")): (str(m.get("title") or "").strip() or str(m.get("id")))
        for m in (metodos or [])
    }

    warnings: List[str] = []
    cash_sales = 0.0
    if cash_method_id is None:
        warnings.append(
            "Método de pagamento 'Dinheiro' não está configurado nas definições do POS — "
            "vendas em dinheiro contadas como 0."
        )
    else:
        cash_title = id_to_title.get(str(cash_method_id))
        if not cash_title:
            warnings.append(
                "Método de 'Dinheiro' configurado não foi encontrado no Vendus — "
                "vendas em dinheiro contadas como 0."
            )
        else:
            cash_sales = round(float((vendus_by_method.get(cash_title) or {}).get("total", 0.0) or 0.0), 2)

    return {
        "cash_sales": cash_sales,
        "warnings": warnings,
        "vendus_by_method": vendus_by_method,
        "id_to_title": id_to_title,
    }


# Tolerância de comparação de dinheiro: meio cêntimo. Ambos os lados já vêm
# arredondados a 2 casas, mas usar `<` a uma tolerância evita falsos negativos
# de ruído de vírgula flutuante (ex.: 199.65 != 199.6500000001).
_MONEY_EPS = 0.005


def reconciliation_diff(vendus_by_method: Dict[str, Dict[str, Any]],
                        pos_sales_by_method: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
    """Reconcilia a repartição por método de pagamento do Vendus (verdade fiscal,
    lida por janela temporal do fecho) com a das `pos_sales` da sessão.

    Ambos os argumentos têm a forma `{metodo: {"count": int, "total": float}}`,
    onde a chave `metodo` é o MESMO eixo dos dois lados (o título do método, ou o
    seu id — o chamador é que garante que estão alinhados).

    Um método "bate" quando o total (a `_MONEY_EPS`) E a contagem coincidem.
    Devolve:
      * `ok`      — True sse TODOS os métodos batem (totais e contagens).
      * `orphans` — métodos presentes no Vendus mas sem contrapartida correta nas
                    `pos_sales` (em falta ou divergentes) — venda fiscal órfã.
      * `missing` — métodos presentes nas `pos_sales` mas ausentes do Vendus —
                    registo POS sem contrapartida fiscal (não devia acontecer).
      * `details` — por método: os dois lados + flag `match`, para o Z mostrar
                    exatamente onde diverge.

    Função PURA: não bloqueia nada nem lê I/O; o fecho usa o `ok`/listas só para
    anexar um aviso ao Z (a reconciliação NUNCA impede o fecho — §Task 10)."""
    orphans: List[str] = []   # no Vendus, mas em falta/divergente nas pos_sales
    missing: List[str] = []   # nas pos_sales, mas ausente do Vendus
    details: Dict[str, Any] = {}
    ok = True

    for metodo in sorted(set(vendus_by_method) | set(pos_sales_by_method)):
        v = vendus_by_method.get(metodo)
        p = pos_sales_by_method.get(metodo)
        v_total = round(float((v or {}).get("total", 0.0) or 0.0), 2)
        v_count = int((v or {}).get("count", 0) or 0)
        p_total = round(float((p or {}).get("total", 0.0) or 0.0), 2)
        p_count = int((p or {}).get("count", 0) or 0)

        match = abs(v_total - p_total) < _MONEY_EPS and v_count == p_count
        details[metodo] = {
            "vendus": {"total": v_total, "count": v_count},
            "pos_sales": {"total": p_total, "count": p_count},
            "match": match,
        }
        if not match:
            ok = False
            if p is None:
                # Está no Vendus e não nas pos_sales → venda fiscal órfã.
                orphans.append(metodo)
            elif v is None:
                # Está nas pos_sales e não no Vendus → registo POS sem fatura.
                missing.append(metodo)
            else:
                # Presente nos dois mas os valores divergem — o Vendus manda,
                # por isso conta como órfão (a fatura existe, o registo não bate).
                orphans.append(metodo)

    return {"ok": ok, "orphans": orphans, "missing": missing, "details": details}
