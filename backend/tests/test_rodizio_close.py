"""Cálculo do fecho de rodízio (puro, sem I/O).

Espelha a matemática de `close_table` quando `rodizio_tier` está definido:
total = adultos*preço + crianças_meia*(preço/2) + extras à la carte + taxas de desperdício.
"""


def rodizio_total(price, adults, children_half, extras=0.0, waste_boxes=0, waste_fee=5.0):
    half = round(price / 2, 2)
    total = 0.0
    if adults > 0:
        total += round(price * adults, 2)
    if children_half > 0:
        total += round(half * children_half, 2)
    total += round(extras, 2)
    if waste_boxes > 0:
        total += round(waste_fee * waste_boxes, 2)
    return round(total, 2)


def test_rodizio_charge_completo():
    # 3 adultos + 1 criança-meia @ 22,90 = 3*22,90 + 11,45 = 80,15
    assert rodizio_total(22.90, adults=3, children_half=1) == 80.15


def test_rodizio_com_extras_e_taxa():
    # 2 adultos @ 22,90 + Coca-Cola 2,00 + 1 taxa desperdício 5,00 = 52,80
    assert rodizio_total(22.90, adults=2, children_half=0, extras=2.00,
                         waste_boxes=1, waste_fee=5.0) == 52.80


def test_rodizio_simples_so_adultos():
    # 4 adultos @ 18,90 = 75,60
    assert rodizio_total(18.90, adults=4, children_half=0) == 75.60
