"""Produtos "App" do Vendus (preços de entrega/delivery, ex.: "Pizza Calabresa
App") — filtragem + extração pura, sem I/O, para o import de "Venda
Aplicações" no catálogo do balcão.

A extração de preço/IVA/referência é a MESMA que `import_menu_from_vendus`
(server.py) usa para o import geral do menu — reutilizada aqui em vez de
duplicada, para os dois imports lerem o Vendus da mesma forma.
"""
import re

# `reference` auto-gerada pelo Vendus (ex.: "VPIZ247-2608014") — a cópia-lixo
# criada quando uma FS saiu SEM ligar ao artigo. As versões limpas têm o nome
# legível na `reference` ("Pizza Calabresa App"), que nunca casa isto.
_AUTO_REF = re.compile(r"^V[A-Z]{3}\d")


def is_app_product(title) -> bool:
    """True se o `title` é de um produto "App" (preço de delivery). Único ponto
    de verdade para o filtro, partilhado por `extract_app_products` (import de
    "Venda Aplicações") e pelo import geral do menu (`import_menu_from_vendus`),
    que os SALTA — senão o import geral puxava-os da categoria pos_only de volta
    para a categoria nativa e re-expunha os preços de delivery no menu do cliente.
    """
    t = (title or "").strip().lower()
    return bool(t) and "app" in t


def is_garbage_ref(ref) -> bool:
    """True se `ref` é uma reference auto-gerada pelo Vendus (cópia-lixo)."""
    return bool(ref) and bool(_AUTO_REF.match(str(ref).strip()))


def _prefer(a: dict, b: dict) -> dict:
    """De dois artigos App com o MESMO título, qual fica: o de `reference` limpa
    ganha ao lixo; em empate, o `vendus_id` mais baixo (o artigo mais antigo).
    ponytail: heurística simples; reimportar corrige se o dono trocar o preço."""
    ga, gb = is_garbage_ref(a["vendus_reference"]), is_garbage_ref(b["vendus_reference"])
    if ga != gb:
        return b if ga else a
    ida = a["vendus_id"] if a["vendus_id"] is not None else float("inf")
    idb = b["vendus_id"] if b["vendus_id"] is not None else float("inf")
    return a if ida <= idb else b


def extract_app_products(vendus_products: list) -> list:
    """Filtra os produtos cujo `title` contém "app" (case-insensitive) e devolve
    `[{"name","base_price","vendus_tax_id","vendus_reference","vendus_id"}]`.

    `vendus_id` (id numérico do artigo) é ESSENCIAL: a FS reaproveita o artigo
    por `vendus_id` (`line_vendus`) — sem ele, cada venda App criava um artigo
    novo ("lixo"). Dedup por título: mantém só UM artigo por produto, preferindo
    a versão limpa e descartando as cópias-lixo (`is_garbage_ref`).

    Produtos sem título são ignorados. `base_price` vem de `gross_price` (preço
    final já com IVA); `vendus_tax_id`/`vendus_reference` tal como no Vendus
    (podem ser None).
    """
    best: dict = {}
    for vp in vendus_products:
        title = (vp.get("title") or "").strip()
        if not is_app_product(title):
            continue
        cand = {
            "name": title,
            "base_price": float(vp.get("gross_price") or 0),
            "vendus_tax_id": vp.get("tax_id"),
            "vendus_reference": vp.get("reference"),
            "vendus_id": vp.get("id"),
        }
        key = title.lower()
        best[key] = cand if key not in best else _prefer(cand, best[key])
    return list(best.values())
