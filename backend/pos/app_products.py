"""Produtos "App" do Vendus (preços de entrega/delivery, ex.: "Pizza Calabresa
App") — filtragem + extração pura, sem I/O, para o import de "Venda
Aplicações" no catálogo do balcão.

A extração de preço/IVA/referência é a MESMA que `import_menu_from_vendus`
(server.py) usa para o import geral do menu — reutilizada aqui em vez de
duplicada, para os dois imports lerem o Vendus da mesma forma.
"""


def is_app_product(title) -> bool:
    """True se o `title` é de um produto "App" (preço de delivery). Único ponto
    de verdade para o filtro, partilhado por `extract_app_products` (import de
    "Venda Aplicações") e pelo import geral do menu (`import_menu_from_vendus`),
    que os SALTA — senão o import geral puxava-os da categoria pos_only de volta
    para a categoria nativa e re-expunha os preços de delivery no menu do cliente.
    """
    t = (title or "").strip().lower()
    return bool(t) and "app" in t


def extract_app_products(vendus_products: list) -> list:
    """Filtra os produtos cujo `title` contém "app" (case-insensitive) e
    devolve `[{"name", "base_price", "vendus_tax_id", "vendus_reference"}]`.

    Produtos sem título são ignorados (nada a importar). `base_price` vem de
    `gross_price` (preço final já com IVA, tal como o resto do catálogo);
    `vendus_tax_id` vem de `tax_id` tal como está no Vendus (pode ser None).
    """
    out = []
    for vp in vendus_products:
        title = (vp.get("title") or "").strip()
        if not is_app_product(title):
            continue
        out.append({
            "name": title,
            "base_price": float(vp.get("gross_price") or 0),
            "vendus_tax_id": vp.get("tax_id"),
            "vendus_reference": vp.get("reference"),
        })
    return out
