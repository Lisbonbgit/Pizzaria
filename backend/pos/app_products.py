"""Produtos "App" do Vendus (preços de entrega/delivery, ex.: "Pizza Calabresa
App") — filtragem + extração pura, sem I/O, para o import de "Venda
Aplicações" no catálogo do balcão.

A extração de preço/IVA/referência é a MESMA que `import_menu_from_vendus`
(server.py) usa para o import geral do menu — reutilizada aqui em vez de
duplicada, para os dois imports lerem o Vendus da mesma forma.
"""


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
        if not title or "app" not in title.lower():
            continue
        out.append({
            "name": title,
            "base_price": float(vp.get("gross_price") or 0),
            "vendus_tax_id": vp.get("tax_id"),
            "vendus_reference": vp.get("reference"),
        })
    return out
