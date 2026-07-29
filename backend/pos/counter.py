"""Lógica pura dos pedidos de balcão (POS) — sem I/O.

Um pedido de balcão não tem mesa: o operador escolhe produtos diretamente no
POS (Fase 2, Task 1) e o pedido segue para a cozinha como qualquer outro
pedido, mas com `table_number=None` e `source="balcao"`. `build_counter_items`
monta os itens (título, quantidade, preço, imposto) e o total a partir do
carrinho e do catálogo de produtos carregado por quem chama; `counter_ext_ref`
gera a referência externa estável usada pela integração fiscal (idempotência,
mesmo espírito do `external_reference` do fecho de mesa).
"""
from typing import Optional


def build_counter_items(products_by_id: dict, cart: list, default_tax: str = "NOR") -> dict:
    """Monta os itens do pedido de balcão a partir do carrinho.

    `products_by_id`: {product_id: {"name", "base_price", "vendus_tax_id"?}}.
    `cart`: [{"product_id", "quantity"}]. Entradas cujo `product_id` não existe
    no catálogo (ex: produto removido entre o carrinho e o envio) são
    ignoradas em vez de rebentar. `tax_id` usa o do produto quando definido,
    senão cai no `default_tax` (ex: produto ainda sem `vendus_tax_id`).
    """
    items = []
    total = 0.0
    for entry in cart:
        prod = products_by_id.get(entry.get("product_id"))
        if prod is None:
            continue
        qty = entry.get("quantity", 0)
        price = prod.get("base_price", 0)
        tax_id = prod.get("vendus_tax_id") or default_tax
        items.append({
            "title": prod.get("name"),
            "qty": qty,
            "gross_price": price,
            "tax_id": tax_id,
        })
        total += price * qty
    return {"items": items, "total": round(total, 2)}


def counter_ext_ref(order_id: str) -> str:
    """Referência externa estável do pedido de balcão (idempotência fiscal)."""
    return f"balcao-{order_id}"
