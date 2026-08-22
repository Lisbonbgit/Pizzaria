"""Casamento puro produto-da-app -> artigo oficial do Vendus, por nome.

Um artigo oficial é o que o dono criou (referência limpa); o lixo auto-gerado
pelo Vendus tem uma referência que termina em `-<6+ dígitos>` (timestamp). O
nome normaliza-se para casar "Calabresa" com "Pizza Calabresa": minúsculas, sem
acentos, sem o prefixo "pizza", sem "de/da", sem pontuação, espaços colapsados.
Entre artigos com o mesmo nome, prefere-se o que NÃO é versão "App" (delivery).
Sem I/O."""
import re
import unicodedata

_AUTO_REF = re.compile(r"-\d{6,}$")


def is_official(reference) -> bool:
    ref = str(reference or "")
    return bool(ref) and not _AUTO_REF.search(ref)


def norm(name) -> str:
    s = unicodedata.normalize("NFKD", str(name or "")).encode("ascii", "ignore").decode()
    s = s.lower()
    s = s.replace(" app", " ")            # ignora o sufixo/infixo "App"
    s = re.sub(r"\bpizza\b", " ", s)      # "Pizza Calabresa" ~ "Calabresa"
    s = re.sub(r"\b(de|da|do|das|dos)\b", " ", s)
    s = re.sub(r"[^a-z0-9]+", " ", s)     # tira pontuação/acentos residuais
    return re.sub(r"\s+", " ", s).strip()


def match_products(app_products, vendus_articles) -> list:
    # Índice dos oficiais por nome normalizado; guarda ambos (App e não-App).
    by_norm = {}
    for a in vendus_articles:
        if not is_official(a.get("reference")):
            continue
        by_norm.setdefault(norm(a.get("title")), []).append(a)

    out = []
    for p in app_products:
        cands = by_norm.get(norm(p.get("name")), [])
        # Prefere o que NÃO tem "app" no título original.
        cands = sorted(cands, key=lambda a: 1 if "app" in str(a.get("title", "")).lower() else 0)
        chosen = cands[0] if cands else None
        out.append({
            "product_id": p.get("id"),
            "product_name": p.get("name"),
            "app_price": p.get("base_price"),
            "match": None if not chosen else {
                "id": chosen.get("id"),
                "title": chosen.get("title"),
                "reference": chosen.get("reference"),
                "price": chosen.get("gross_price"),
            },
            "status": "matched" if chosen else "none",
        })
    return out
