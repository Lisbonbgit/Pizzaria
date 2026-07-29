"""Lógica pura dos pedidos de balcão (POS) — sem I/O.

Um pedido de balcão não tem mesa: o operador escolhe produtos diretamente no
POS (Fase 2, Task 1) e o pedido segue para a cozinha como qualquer outro
pedido, mas com `table_number=None` e `source="balcao"`. `build_counter_items`
monta os itens no MESMO formato `OrderItem` usado pelo resto do sistema
(`product_id`, `product_name`, `quantity`, `unit_price`, `total_price`,
`vendus_tax_id`) — é o formato que os formatadores ESC/POS da cozinha/caixa e
o dashboard já sabem ler — a partir do carrinho e do catálogo de produtos
carregado por quem chama; `counter_ext_ref` gera a referência externa estável
usada pela integração fiscal (idempotência, mesmo espírito do
`external_reference` do fecho de mesa).
"""


def build_counter_items(products_by_id: dict, cart: list, default_tax: str = "NOR") -> dict:
    """Monta os itens do pedido de balcão a partir do carrinho.

    `products_by_id`: {product_id: {"name", "base_price", "vendus_tax_id"?}}.
    `cart`: [{"product_id", "quantity"}]. Entradas cujo `product_id` não existe
    no catálogo (ex: produto removido entre o carrinho e o envio) são
    ignoradas em vez de rebentar.

    Os itens saem no formato `OrderItem` (`product_id`, `product_name`,
    `quantity`, `unit_price`, `total_price`) para que os talões ESC/POS
    (cozinha/caixa) e o dashboard os leiam sem tratamento especial. O
    `vendus_tax_id` é guardado tal como vem do produto (pode ser `None`,
    quando o produto ainda não tem imposto Vendus definido) — a resolução
    para o `default_tax` fica para a Task 2 da Fase 2, no momento da
    faturação, não aqui. `default_tax` é mantido na assinatura por
    compatibilidade (quem chama já o passa) mas não é usado nesta função.
    """
    items = []
    total = 0.0
    for entry in cart:
        prod = products_by_id.get(entry.get("product_id"))
        if prod is None:
            continue
        qty = entry.get("quantity", 0)
        unit_price = prod.get("base_price", 0)
        item_total = round(unit_price * qty, 2)
        items.append({
            "product_id": entry.get("product_id"),
            "product_name": prod.get("name"),
            "quantity": qty,
            "unit_price": unit_price,
            "total_price": item_total,
            "vendus_tax_id": prod.get("vendus_tax_id"),
        })
        total += item_total
    return {"items": items, "total": round(total, 2)}


def counter_ext_ref(order_id: str) -> str:
    """Referência externa estável do pedido de balcão (idempotência fiscal)."""
    return f"balcao-{order_id}"
