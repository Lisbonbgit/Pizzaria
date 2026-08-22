"""NC (Nota de Crédito) tem de creditar pelo PREÇO/IVA originais da linha da
fatura, não pelo preço de catálogo do artigo. Antes desta correção, a NC
levava só `{id, qty}` e o Vendus re-derivava o valor pelo preço de catálogo
do artigo — errado quando duas linhas (ex.: Média e Grande da mesma pizza)
partilham o mesmo `id` de artigo mas têm preços diferentes na fatura.
"""
from pos.credit_note import nc_items_from_fs


def test_linhas_com_mesmo_id_preservam_precos_diferentes():
    # Média e Grande da mesma pizza partilham o id do artigo (204) mas a
    # fatura cobrou preços diferentes por tamanho.
    fs_items = [
        {
            "id": 204, "qty": 1, "title": "Pizza Calabresa (Média)",
            "reference": "PZ-CAL",
            "amounts": {"net_unit": "12.75", "net_total": "12.75",
                        "gross_unit": "13.90", "gross_total": "13.90"},
            "tax": {"id": "INT", "rate": 13},
        },
        {
            "id": 204, "qty": 1, "title": "Pizza Calabresa (Grande)",
            "reference": "PZ-CAL",
            "amounts": {"net_unit": "17.34", "net_total": "17.34",
                        "gross_unit": "18.90", "gross_total": "18.90"},
            "tax": {"id": "INT", "rate": 13},
        },
    ]
    out = nc_items_from_fs(fs_items)
    assert len(out) == 2
    assert out[0]["id"] == 204 and out[1]["id"] == 204
    assert out[0]["gross_price"] == 13.90
    assert out[1]["gross_price"] == 18.90
    assert out[0]["tax_id"] == "INT" and out[1]["tax_id"] == "INT"
    assert out[0]["title"] == "Pizza Calabresa (Média)"
    assert out[0]["qty"] == 1 and out[1]["qty"] == 1


def test_linha_sem_id_levanta_value_error():
    fs_items = [{"id": None, "qty": 1, "title": "X",
                 "amounts": {"gross_unit": "5.00"}, "tax": {"id": "NOR"}}]
    try:
        nc_items_from_fs(fs_items)
        assert False, "devia ter levantado ValueError"
    except ValueError:
        pass
