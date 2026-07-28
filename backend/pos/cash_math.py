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
