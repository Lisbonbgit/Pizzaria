"""Helper puro: agrega os produtos vendidos (quantidade + valor €) a partir dos
nossos pedidos, para o relatório do backoffice. O valor € por linha usa a MESMA
via da faturação (`line_vendus` + `combine_global` sem desconto global), pelo
que itens de rodízio incluídos (unit_price=0) entram a €0 e os descontos de
linha são respeitados. Ignora itens anulados (soft-void, `removed`). Sem I/O."""
from pos.pricing import line_vendus, combine_global


def summarize_products(orders, default_tax_id, top=15):
    """`orders`: pedidos NÃO cancelados. Devolve top-N produtos por quantidade,
    cada um com `quantity` e `revenue` (€ líquido, 2 casas)."""
    qty_by = {}
    rev_by = {}
    for o in orders:
        for item in o.get("items", []):
            if item.get("removed"):
                continue
            name = item.get("product_name", "Desconhecido")
            qty = item.get("quantity", 1) or 1
            _, net = combine_global(line_vendus(item, None, default_tax_id), 0)
            qty_by[name] = qty_by.get(name, 0) + qty
            rev_by[name] = round(rev_by.get(name, 0.0) + net, 2)
    rows = [
        {"name": k, "quantity": v, "revenue": rev_by.get(k, 0.0)}
        for k, v in qty_by.items()
    ]
    rows.sort(key=lambda x: x["quantity"], reverse=True)
    return rows[:top]
