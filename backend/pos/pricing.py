"""Preço/IVA/desconto por linha (Fase 3, Task 1) — helper puro, sem I/O.

`line_vendus` resolve a linha Vendus (`{title, qty, gross_price, tax_id,
discount_percentage?, discount_amount?}`) de UM item da conta, isolado da BD
para ser testável e reutilizável nos endpoints de edição de linha (Task 1) e,
mais tarde, no fecho de mesa (Task 2, que hoje tem esta lógica duplicada
inline em `close_table`/`server.py` — NÃO tocado nesta tarefa).
"""
from typing import Optional


def line_vendus(item: dict, product_tax_id: Optional[str], default_tax_id: str) -> dict:
    """Resolve a linha Vendus de um item da conta.

    - `title`: nome do produto, com a variação entre parêntesis se existir
      (espelha `close_table`: `f"{title} ({var['name']})"`).
    - `qty`: quantidade do item (default 1 se ausente/zero/None).
    - `gross_price`: preço unitário, arredondado a 2 casas (dinheiro).
    - `tax_id`: IVA do item (override) > IVA do produto > default — por esta
      ordem, o primeiro valor "verdadeiro" ganha.
    - desconto: `discount_amount` (€) tem precedência sobre `discount_pct`
      (%) — são mutuamente exclusivos, só uma das chaves é devolvida.
    """
    title = item.get("product_name", "Item")
    var = item.get("variation") or {}
    if isinstance(var, dict) and var.get("name"):
        title = f"{title} ({var['name']})"

    line = {
        "title": title,
        "qty": item.get("quantity", 1) or 1,
        "gross_price": round(float(item.get("unit_price", 0) or 0), 2),
        "tax_id": item.get("vendus_tax_id") or product_tax_id or default_tax_id,
    }

    damount = item.get("discount_amount")
    dpct = item.get("discount_pct")
    if damount:
        line["discount_amount"] = round(float(damount), 2)
    elif dpct:
        line["discount_percentage"] = float(dpct)

    return line


def combine_global(li: dict, global_pct: float) -> tuple:
    """Combina o desconto PRÓPRIO de uma linha Vendus (o `discount_percentage`
    OU `discount_amount` que `line_vendus` resolveu) com o desconto GLOBAL (%)
    da fatura, num ÚNICO `discount_percentage` — o Vendus só aceita um dos dois
    por linha. Devolve `(linha_final, liquido)`.

    Regras (fixadas por testes):
    - O desconto global aplica-se SEMPRE por cima do desconto da linha.
    - Só percentagem (linha e/ou global): composição multiplicativa
      `1-(1-p)(1-g)` — idêntico ao histórico do `close_table` (`_eff_disc`),
      por isso uma linha sem desconto nenhum sai byte-a-byte igual a hoje.
    - Desconto em € na linha: líquido `= (bruto - €)·(1 - global)`, e converte-se
      esse líquido numa percentagem equivalente (o Vendus recebe SÓ
      `discount_percentage`). Nunca se envia `discount_amount` — a sua semântica
      (por unidade vs por linha) não é fiável, ao passo que o cálculo por
      percentagem `bruto·(1-pct/100)` é o caminho já provado em produção.
    - O `liquido` devolvido é EXATAMENTE o que o Vendus calcula da linha final
      (`bruto·(1-pct/100)`, arredondado a 2), garantindo que o pagamento bate
      com a soma das linhas sem desvio de cêntimos.
    """
    g = max(0.0, min(100.0, float(global_pct or 0)))
    qty = li.get("qty", 1) or 1
    unit = float(li.get("gross_price", 0) or 0)
    gross = round(unit * qty, 2)

    out = {k: li[k] for k in ("title", "qty", "gross_price", "tax_id") if k in li}

    damount = li.get("discount_amount")
    dpct = li.get("discount_percentage")
    if damount:
        net_after_amount = max(0.0, gross - float(damount))
        net_target = round(net_after_amount * (1 - g / 100.0), 2)
        eff = round(100.0 * (1 - net_target / gross), 4) if gross > 0 else 0.0
    else:
        eff = round(100.0 * (1 - (1 - float(dpct or 0) / 100.0) * (1 - g / 100.0)), 4)

    if eff > 0:
        out["discount_percentage"] = eff
    liquido = round(unit * qty * (1 - eff / 100.0), 2)
    return out, liquido
