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
