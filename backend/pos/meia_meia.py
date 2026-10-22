"""Pizza meia-meia — regra pura, sem I/O (pedido do dono, 2026-10-20).

Uma meia-meia é UMA linha do pedido: o 1.º sabor (A) com o 2.º (B) em `halves`.
Só entre pizzas da MESMA categoria (nome com "pizza", ativa, não pos_only), no
MESMO tamanho; paga-se a metade mais cara; extras e complementos são da pizza
inteira (os de A) e contam uma vez, a preços do CATÁLOGO (nunca os do browser).
"""
import unicodedata


class MeiaMeiaInvalida(ValueError):
    """Combinação inválida. A mensagem vai tal e qual para o ecrã (português)."""


def _sem_acentos(texto: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", texto or "")
                   if unicodedata.category(c) != "Mn")


def categoria_elegivel(cat) -> bool:
    if not cat:
        return False
    return ("pizza" in _sem_acentos(cat.get("name", "")).lower()
            and cat.get("active", True) is not False
            and not cat.get("pos_only", False))


def preco_no_tamanho(prod: dict, nome_tamanho):
    """Preço do produto no tamanho, ou None se não existir nesse tamanho. Sem
    variações, só serve "sem tamanho" (preço base)."""
    variacoes = prod.get("variations") or []
    if not variacoes:
        return None if nome_tamanho else round(float(prod.get("base_price", 0) or 0), 2)
    for v in variacoes:
        if v.get("name") == nome_tamanho:
            return round(float(v.get("price", 0) or 0), 2)
    return None


def nome_meia_meia(nome_a: str, nome_b: str) -> str:
    return f"1/2 {nome_a} + 1/2 {nome_b}"


def montar_meia_meia(prod_a: dict, prod_b, cat_a, nome_tamanho, rodizio: bool = False) -> dict:
    """`rodizio`: só o caminho a 0 € do rodízio (já validado por quem chama) aceita
    metades `rodizio_only`; fora dele duas dessas a 0 € davam uma pizza de borla."""
    if not categoria_elegivel(cat_a):
        raise MeiaMeiaInvalida(f"{prod_a.get('name')} não pode ser meia-meia")
    if prod_b is None:
        raise MeiaMeiaInvalida("O 2.º sabor já não existe no menu")
    if prod_b.get("id") == prod_a.get("id"):
        raise MeiaMeiaInvalida("Escolhe dois sabores diferentes")
    if prod_b.get("category_id") != prod_a.get("category_id"):
        raise MeiaMeiaInvalida("Os dois sabores têm de ser da mesma categoria")
    for prod in (prod_a, prod_b):
        if prod.get("available") is False:
            raise MeiaMeiaInvalida(f"{prod.get('name')} está esgotada")
        if prod.get("rodizio_only") and not rodizio:
            raise MeiaMeiaInvalida(f"{prod.get('name')} só existe no rodízio")
    if not nome_tamanho and prod_a.get("variations"):
        raise MeiaMeiaInvalida("Escolhe o tamanho")
    preco_a = preco_no_tamanho(prod_a, nome_tamanho)
    preco_b = preco_no_tamanho(prod_b, nome_tamanho)
    for prod, preco in ((prod_a, preco_a), (prod_b, preco_b)):
        if preco is None:
            raise MeiaMeiaInvalida(f"{prod.get('name')} não existe no tamanho {nome_tamanho}")
    return {
        "product_name": nome_meia_meia(prod_a["name"], prod_b["name"]),
        "halves": [{"product_id": prod_a["id"], "product_name": prod_a["name"]},
                   {"product_id": prod_b["id"], "product_name": prod_b["name"]}],
        "base_price": max(preco_a, preco_b),
    }


def extras_do_catalogo(prod_a: dict, extras, complementos) -> tuple:
    """Os extras e complementos escolhidos, com os preços do CATÁLOGO de A (os do
    browser não contam nem ficam gravados). Um que A não tenha → MeiaMeiaInvalida;
    mal formado (não é um dicionário, sem nome) → idem, nunca um 500."""
    precos_extra = {e.get("name"): float(e.get("price", 0) or 0) for e in prod_a.get("extras") or []}
    precos_comp = {(g.get("name"), i.get("name")): float(i.get("price", 0) or 0)
                   for g in prod_a.get("complement_groups") or [] for i in g.get("items") or []}
    try:
        novos_extras = []
        for e in extras or []:
            if e["name"] not in precos_extra:
                raise MeiaMeiaInvalida(f"O extra \"{e['name']}\" não existe em {prod_a.get('name')}")
            novos_extras.append({**e, "price": precos_extra[e["name"]]})
        novos_comp = []
        for g in complementos or []:
            itens = []
            for i in g.get("items") or []:
                chave = (g.get("group_name"), i["name"])
                if chave not in precos_comp:
                    raise MeiaMeiaInvalida(f"\"{i['name']}\" não existe em {prod_a.get('name')}")
                itens.append({**i, "price": precos_comp[chave]})
            novos_comp.append({**g, "items": itens})
    except (TypeError, AttributeError, KeyError):
        raise MeiaMeiaInvalida("Extras ou complementos inválidos")
    return novos_extras, novos_comp


def preco_unitario(base: float, prod_a: dict, extras, complementos) -> float:
    """Preço base + extras e complementos de A, a preços do catálogo."""
    novos_extras, novos_comp = extras_do_catalogo(prod_a, extras, complementos)
    total = float(base)
    for e in novos_extras:
        total += e["price"]
    for g in novos_comp:
        for i in g["items"]:
            total += i["price"]
    return round(total, 2)


def incluida_no_rodizio(prod: dict, nivel) -> bool:
    """Mesma regra do menu do cliente (`isIncluded` no MenuPage)."""
    inc = prod.get("rodizio_incluido") or "nao"
    if nivel == "simples":
        return inc == "ambos"
    if nivel == "completo":
        return inc in ("ambos", "completo")
    return False
