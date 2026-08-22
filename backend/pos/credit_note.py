"""Reconstrói as linhas de uma Nota de Crédito a partir das linhas da fatura
de origem (documento Vendus). Cada linha da NC leva o id do artigo, a
quantidade, o título e o PREÇO/IVA originais (o Vendus, sem o preço, re-derivava
pelo preço de catálogo do artigo — errado quando tamanhos partilham um id).
`amounts.gross_unit` é o preço unitário com IVA; `tax.id` é a classe de IVA.
Sem I/O."""


def nc_items_from_fs(fs_items):
    """Devolve as linhas da NC a partir das `fs_items` (linhas da FS do Vendus).
    Levanta ValueError se alguma linha não tiver `id` (a NC credita por id)."""
    out = []
    for it in fs_items:
        if it.get("id") is None:
            raise ValueError("linha da fatura sem id — não creditável")
        amounts = it.get("amounts") or {}
        line = {"id": it.get("id"), "qty": it.get("qty"), "title": it.get("title")}
        gu = amounts.get("gross_unit")
        if gu is not None:
            line["gross_price"] = round(float(gu), 2)
        tax = (it.get("tax") or {}).get("id")
        if tax:
            line["tax_id"] = tax
        out.append(line)
    return out
