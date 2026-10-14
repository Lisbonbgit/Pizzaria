"""Divisão da conta em N partes iguais — lógica pura, sem I/O.

Cada parte é uma FS própria (com o seu NIF e método de pagamento), emitida
uma de cada vez. A regra de repartição é a MESMA que o fecho de mesa já usava
inline: reparte por taxa de IVA e põe o resto do arredondamento na ÚLTIMA
parte, para as partes somarem EXATAMENTE o total (dinheiro, nunca aproximar).
"""
import math


def compute_shares(by_tax: dict, n: int, title: str) -> list:
    """N partes iguais a partir do total por IVA.

    `by_tax`: {tax_id: total_dessa_taxa}. Devolve
    `[{"items": [{"title","qty","gross_price","tax_id"}], "amount": float}]`.
    Partes que dessem 0 são descartadas (não se emite FS de valor zero), por
    isso o resultado pode ter menos de `n` partes em contas muito pequenas.
    """
    n = max(1, int(n))
    # Arredonda para BAIXO: arredondar para cima podia pôr base*(n-1) acima do
    # subtotal (um IVA de 0,05 € em 9 partes) e as FS somavam MAIS do que a venda.
    bases = {tax: math.floor(round(float(sub) * 100, 6) / n) / 100 for tax, sub in by_tax.items()}
    # Cada parte (menos a última) vale EXATAMENTE total/N — é o que o ecrã mostra
    # em "Cada pessoa paga". Os cêntimos em falta vão para o maior IVA.
    if bases:
        # Em cêntimos inteiros e meio-para-cima, igual ao Math.round do ecrã (a
        # soma em float dava 184,08999… e o round caía para o lado errado).
        total_cents = round(sum(float(v) for v in by_tax.values()) * 100)
        target = math.floor(total_cents / n + 0.5) / 100
        maior = max(by_tax, key=lambda t: float(by_tax[t]))
        ajustada = round(bases[maior] + target - sum(bases.values()), 2)
        # Contas de poucos cêntimos: se o ajuste deixasse a última parte negativa,
        # fica-se pelo arredondamento para baixo (nunca cobrar a mais).
        if ajustada * (n - 1) <= float(by_tax[maior]) + 1e-9:
            bases[maior] = ajustada
    shares_by_tax = {}
    for tax, sub in by_tax.items():
        base = bases[tax]
        # A última leva o resto: base*(n-1) + resto == sub, ao cêntimo.
        shares_by_tax[tax] = [base] * (n - 1) + [round(float(sub) - base * (n - 1), 2)]

    out = []
    for i in range(n):
        items_i, amount_i = [], 0.0
        for tax, parts in shares_by_tax.items():
            share = parts[i]
            if share and share > 0:
                items_i.append({
                    "title": f"{title} ({i + 1}/{n})",
                    "qty": 1,
                    "gross_price": share,
                    "tax_id": tax,
                })
                amount_i += share
        if items_i:
            out.append({"items": items_i, "amount": round(amount_i, 2)})
    return out


def next_unpaid_index(shares: list):
    """Índice da próxima parte por pagar, ou None se já saíram todas."""
    for i, s in enumerate(shares):
        if not s.get("paid"):
            return i
    return None


def next_amount(shares: list):
    """Valor da próxima parte a cobrar (o que o operador marca no terminal), ou
    None se já saíram todas."""
    i = next_unpaid_index(shares)
    return None if i is None else shares[i]["amount"]


def remaining_amount(shares: list) -> float:
    """Quanto falta faturar (soma das partes por pagar)."""
    return round(sum(s.get("amount", 0) or 0 for s in shares if not s.get("paid")), 2)
