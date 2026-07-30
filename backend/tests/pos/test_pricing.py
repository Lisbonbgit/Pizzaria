"""Preço/IVA/desconto por linha (Fase 3, Task 1) — helper puro, sem I/O.

`line_vendus` resolve a linha Vendus de UM item da conta: título (com
variação, se houver), quantidade, preço bruto, IVA (override do item > IVA
do produto > default) e desconto (percentagem OU montante — mutuamente
exclusivos, o montante ganha). Espelha a lógica de `close_table`
(server.py) mas isolada e sem depender da BD, para poder ser testada aqui e
reutilizada nos endpoints de edição de linha (Task 1) e no fecho (Task 2).
"""
from pos.pricing import line_vendus, combine_global


def test_override_iva_e_preco():
    it = {"product_name": "Pizza", "quantity": 2, "unit_price": 15.0, "vendus_tax_id": "NOR"}
    r = line_vendus(it, product_tax_id="INT", default_tax_id="INT")
    assert r["tax_id"] == "NOR"          # override do item ganha ao IVA do produto
    assert r["gross_price"] == 15.0 and r["qty"] == 2


def test_fallback_iva_produto():
    it = {"product_name": "Água", "quantity": 1, "unit_price": 1.0}
    assert line_vendus(it, product_tax_id="INT", default_tax_id="NOR")["tax_id"] == "INT"


def test_fallback_iva_default():
    # Sem override do item nem IVA do produto -> cai no default.
    it = {"product_name": "Item", "quantity": 1, "unit_price": 1.0}
    assert line_vendus(it, product_tax_id=None, default_tax_id="NOR")["tax_id"] == "NOR"


def test_desconto_pct_vs_amount():
    a = line_vendus({"product_name": "X", "quantity": 1, "unit_price": 10.0, "discount_pct": 10}, "INT", "INT")
    assert a["discount_percentage"] == 10 and "discount_amount" not in a
    b = line_vendus({"product_name": "X", "quantity": 1, "unit_price": 10.0, "discount_amount": 2.5}, "INT", "INT")
    assert b["discount_amount"] == 2.5 and "discount_percentage" not in b


def test_sem_desconto():
    # Sem discount_pct nem discount_amount -> nenhuma das duas chaves aparece.
    r = line_vendus({"product_name": "X", "quantity": 1, "unit_price": 10.0}, "INT", "INT")
    assert "discount_percentage" not in r and "discount_amount" not in r


def test_titulo_com_variacao():
    it = {"product_name": "Pizza", "quantity": 1, "unit_price": 8.5, "variation": {"name": "Familiar"}}
    r = line_vendus(it, "INT", "INT")
    assert r["title"] == "Pizza (Familiar)"


def test_titulo_sem_variacao():
    it = {"product_name": "Pizza", "quantity": 1, "unit_price": 8.5}
    assert line_vendus(it, "INT", "INT")["title"] == "Pizza"


def test_amount_ganha_a_pct():
    # Se ambos estiverem presentes (não devia acontecer, mas a função é pura e
    # tem de decidir): discount_amount tem precedência sobre discount_pct.
    it = {"product_name": "X", "quantity": 1, "unit_price": 10.0, "discount_pct": 10, "discount_amount": 2.5}
    r = line_vendus(it, "INT", "INT")
    assert r["discount_amount"] == 2.5 and "discount_percentage" not in r


def test_gross_price_arredondado():
    it = {"product_name": "X", "quantity": 1, "unit_price": 1.005}
    assert line_vendus(it, "INT", "INT")["gross_price"] == 1.0


def test_quantity_default_um():
    it = {"product_name": "X", "unit_price": 5.0}
    assert line_vendus(it, "INT", "INT")["qty"] == 1


# ---- combine_global: desconto GLOBAL (%) por cima do desconto da linha ----
# O fecho de mesa (close_table) tem um desconto global (%) sobre TODA a fatura
# que se combina com o desconto próprio de cada linha. Como o Vendus só aceita
# UM de discount_percentage/discount_amount por linha, `combine_global` funde os
# dois num único discount_percentage e devolve o líquido EXATO que o Vendus vai
# calcular da linha — para o pagamento bater com a soma sem desvio de cêntimos.


def test_combine_linha_simples_identica():
    # Sem desconto de linha e sem global: item Vendus fica IGUAL e líquido = bruto
    # (retrocompatível com o comportamento histórico do close_table).
    li = {"title": "Pizza", "qty": 2, "gross_price": 10.0, "tax_id": "INT"}
    out, net = combine_global(li, 0)
    assert out == {"title": "Pizza", "qty": 2, "gross_price": 10.0, "tax_id": "INT"}
    assert "discount_percentage" not in out and "discount_amount" not in out
    assert net == 20.0


def test_combine_item_pct_sem_global():
    li = {"title": "X", "qty": 1, "gross_price": 10.0, "tax_id": "INT", "discount_percentage": 10.0}
    out, net = combine_global(li, 0)
    assert out["discount_percentage"] == 10.0
    assert net == 9.0


def test_combine_item_pct_mais_global():
    # 10% de linha + 20% global compõem-se (multiplicativo), não somam: 1-0.9*0.8=0.28.
    li = {"title": "X", "qty": 2, "gross_price": 10.0, "tax_id": "INT", "discount_percentage": 10.0}
    out, net = combine_global(li, 20)
    assert out["discount_percentage"] == 28.0
    assert net == 14.4


def test_combine_item_euro_mais_global():
    # €2 de desconto na linha + 10% global: líquido=(10-2)*0.9=7.20; expresso como
    # UMA só linha com discount_percentage (nunca discount_amount).
    li = {"title": "X", "qty": 1, "gross_price": 10.0, "tax_id": "INT", "discount_amount": 2.0}
    out, net = combine_global(li, 10)
    assert net == 7.2
    assert out["discount_percentage"] == 28.0
    assert "discount_amount" not in out


def test_combine_item_euro_sem_global():
    li = {"title": "X", "qty": 1, "gross_price": 10.0, "tax_id": "INT", "discount_amount": 2.5}
    out, net = combine_global(li, 0)
    assert net == 7.5
    assert out["discount_percentage"] == 25.0


def test_combine_so_global():
    # Linha sem desconto próprio, só global -> discount_percentage = global.
    li = {"title": "Adulto", "qty": 3, "gross_price": 12.0, "tax_id": "INT"}
    out, net = combine_global(li, 10)
    assert out["discount_percentage"] == 10.0
    assert net == 32.4


def test_combine_euro_maior_que_bruto():
    # Desconto € superior ao bruto -> líquido 0 e 100% (nunca líquido negativo).
    li = {"title": "X", "qty": 1, "gross_price": 5.0, "tax_id": "INT", "discount_amount": 9.0}
    out, net = combine_global(li, 0)
    assert net == 0.0
    assert out["discount_percentage"] == 100.0


def test_combine_pagamento_bate_soma_das_linhas():
    # O líquido devolvido é EXATAMENTE o que o Vendus calcula da linha final
    # (bruto*(1-pct/100)), logo a soma dos líquidos == pagamento, sem desvio.
    linhas = [
        {"title": "A", "qty": 1, "gross_price": 7.0, "tax_id": "INT", "discount_amount": 1.0},
        {"title": "B", "qty": 2, "gross_price": 3.33, "tax_id": "NOR", "discount_percentage": 5.0},
    ]
    total = 0.0
    for li in linhas:
        out, net = combine_global(li, 15)
        pct = out.get("discount_percentage", 0.0)
        vendus_net = round(out["gross_price"] * out["qty"] * (1 - pct / 100.0), 2)
        assert net == vendus_net          # o líquido == cálculo do Vendus
        total += net
    assert total == round(total, 2)


def test_combine_mapeamento_open_bill_line():
    # Uma linha no formato de _open_bill_lines (com override de IVA e desconto €)
    # -> line_vendus lê os nomes de campo certos e combine_global reflete tudo.
    bill_line = {
        "order_id": "o1", "idx": 0, "product_id": "p1",
        "product_name": "Pizza", "quantity": 1, "unit_price": 10.0,
        "total_price": 10.0, "gross_total": 10.0, "discount_pct": 0.0,
        "discount_amount": 2.0, "vendus_tax_id": "NOR", "variation": None,
        "source": "client",
    }
    li = line_vendus(bill_line, product_tax_id="INT", default_tax_id="INT")
    assert li["tax_id"] == "NOR"          # override do item ganha ao IVA do produto
    assert li["discount_amount"] == 2.0
    out, net = combine_global(li, 0)
    assert out["tax_id"] == "NOR"
    assert net == 8.0
    assert out["discount_percentage"] == 20.0
