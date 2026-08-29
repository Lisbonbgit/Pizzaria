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
from pos.pricing import line_vendus, combine_global


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
        # Overrides do staff (diálogo do produto), com fallback ao produto:
        #   - preço unitário: `unit_price` do carrinho, senão `base_price`;
        #   - IVA: `vendus_tax_id` do carrinho, senão o do produto (pode ser None,
        #     resolvido para o default na faturação, não aqui — mesma regra de antes).
        up = entry.get("unit_price")
        unit_price = round(float(up if up is not None else prod.get("base_price", 0) or 0), 2)
        tax = entry.get("vendus_tax_id") or prod.get("vendus_tax_id")
        gross = round(unit_price * qty, 2)
        # Desconto por linha: € tem precedência sobre % (mutuamente exclusivos),
        # tal como na mesa (`line_vendus`/`set_item_discount`). `total_price`
        # continua a ser o BRUTO (unit×qty) — a resolução do líquido para a FS
        # fica em `line_vendus`/`combine_global`, e o `total` do pedido é o líquido.
        dpct = float(entry.get("discount_pct") or 0)
        damt = float(entry.get("discount_amount") or 0)
        item = {
            "product_id": entry.get("product_id"),
            "product_name": prod.get("name"),
            "quantity": qty,
            "unit_price": unit_price,
            "total_price": gross,
            "vendus_tax_id": tax,
        }
        # € tem PRECEDÊNCIA sobre % (mutuamente exclusivos) — só uma chave é
        # guardada no item, igual a `line_vendus`/`set_item_discount`.
        if damt:
            item["discount_amount"] = round(damt, 2)
        elif dpct:
            item["discount_pct"] = dpct
        # Tamanho/variação (ex.: pizza Grande no balcão) — mesma convenção
        # `variation:{name}` da mesa: o talão da cozinha, o da caixa e a FS
        # (line_vendus) já a leem e mostram "(Grande)".
        vname = entry.get("variation_name")
        if vname:
            item["variation"] = {"name": vname}
        items.append(item)
        # Líquido do item pela MESMA via da faturação (`line_vendus` +
        # `combine_global`, sem desconto global) → o `total` do pedido bate ao
        # cêntimo com o pagamento/FS do `checkout_counter_order` (fonte única de
        # verdade; evita divergência de arredondamento no total em cache).
        _, liquido = combine_global(line_vendus(item, None, default_tax), 0)
        total += liquido
    return {"items": items, "total": round(total, 2)}


def counter_ext_ref(order_id: str) -> str:
    """Referência externa estável do pedido de balcão (idempotência fiscal)."""
    return f"balcao-{order_id}"
