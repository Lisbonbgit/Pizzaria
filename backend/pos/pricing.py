"""Preço/IVA/desconto por linha (Fase 3, Task 1) — helper puro, sem I/O.

`line_vendus` resolve a linha Vendus (`{title, qty, gross_price, tax_id,
discount_percentage?, discount_amount?}`) de UM item da conta, isolado da BD
para ser testável e reutilizável nos endpoints de edição de linha (Task 1) e,
mais tarde, no fecho de mesa (Task 2, que hoje tem esta lógica duplicada
inline em `close_table`/`server.py` — NÃO tocado nesta tarefa).
"""
from typing import Optional


def line_vendus(item: dict, product_tax_id: Optional[str], default_tax_id: str,
                vendus_id: Optional[int] = None) -> dict:
    """Resolve a linha Vendus de um item da conta.

    - `title`: nome do produto, com a variação entre parêntesis se existir
      (espelha `close_table`: `f"{title} ({var['name']})"`).
    - `qty`: quantidade do item (default 1 se ausente/zero/None).
    - `gross_price`: preço unitário, arredondado a 2 casas (dinheiro).
    - `tax_id`: IVA do item (override) > IVA do produto > default — por esta
      ordem, o primeiro valor "verdadeiro" ganha.
    - desconto: `discount_amount` (€) tem precedência sobre `discount_pct`
      (%) — são mutuamente exclusivos, só uma das chaves é devolvida.
    """
    title = item.get("product_name", "Item")
    var = item.get("variation") or {}
    if isinstance(var, dict) and var.get("name"):
        title = f"{title} ({var['name']})"

    line = {
        "title": title,
        "qty": item.get("quantity", 1) or 1,
        "gross_price": round(float(item.get("unit_price", 0) or 0), 2),
        "tax_id": item.get("vendus_tax_id") or product_tax_id or default_tax_id,
    }

    if vendus_id is not None:
        line["id"] = vendus_id

    damount = item.get("discount_amount")
    dpct = item.get("discount_pct")
    if damount:
        line["discount_amount"] = round(float(damount), 2)
    elif dpct:
        line["discount_percentage"] = float(dpct)

    return line


def combine_global(li: dict, global_pct: float) -> tuple:
    """Combina o desconto PRÓPRIO de uma linha Vendus (o `discount_percentage`
    OU `discount_amount` que `line_vendus` resolveu) com o desconto GLOBAL (%)
    da fatura, num ÚNICO `discount_percentage` — o Vendus só aceita um dos dois
    por linha. Devolve `(linha_final, liquido)`.

    Regras (fixadas por testes):
    - O desconto global aplica-se SEMPRE por cima do desconto da linha.
    - Só percentagem (linha e/ou global): composição multiplicativa
      `1-(1-p)(1-g)` — idêntico ao histórico do `close_table` (`_eff_disc`),
      por isso uma linha sem desconto nenhum sai byte-a-byte igual a hoje.
    - Desconto em € na linha: líquido `= (bruto - €)·(1 - global)`, e converte-se
      esse líquido numa percentagem equivalente (o Vendus recebe SÓ
      `discount_percentage`). Nunca se envia `discount_amount` — a sua semântica
      (por unidade vs por linha) não é fiável, ao passo que o cálculo por
      percentagem `bruto·(1-pct/100)` é o caminho já provado em produção.
    - O `liquido` devolvido é EXATAMENTE o que o Vendus calcula da linha final
      (`bruto·(1-pct/100)`, arredondado a 2), garantindo que o pagamento bate
      com a soma das linhas sem desvio de cêntimos.
    """
    g = max(0.0, min(100.0, float(global_pct or 0)))
    qty = li.get("qty", 1) or 1
    unit = float(li.get("gross_price", 0) or 0)
    gross = round(unit * qty, 2)

    out = {k: li[k] for k in ("id", "title", "qty", "gross_price", "tax_id") if k in li}

    damount = li.get("discount_amount")
    dpct = li.get("discount_percentage")
    if damount:
        net_after_amount = max(0.0, gross - float(damount))
        net_target = round(net_after_amount * (1 - g / 100.0), 2)
        eff = round(100.0 * (1 - net_target / gross), 4) if gross > 0 else 0.0
    else:
        eff = round(100.0 * (1 - (1 - float(dpct or 0) / 100.0) * (1 - g / 100.0)), 4)

    if eff > 0:
        out["discount_percentage"] = eff
    liquido = round(unit * qty * (1 - eff / 100.0), 2)
    return out, liquido


def apply_global_amount(lines: list, amount: float) -> tuple:
    """Desconto GLOBAL em EUROS sobre um conjunto de linhas Vendus.

    O Vendus só aceita percentagem por linha, por isso o valor em € converte-se
    na percentagem equivalente e passa pelo MESMO `combine_global` (que compõe
    com o desconto próprio de cada linha). Essa conversão sozinha não fecha a
    conta: medido em 4000 ensaios, só 70% davam certo ao cêntimo e o desvio ia
    até 2 cêntimos. Por isso o resto do arredondamento é absorvido na ÚLTIMA
    linha com valor — a mesma regra da divisão da conta — e o que se cobra passa
    a ser EXATAMENTE `bruto - desconto`.

    Devolve `(linhas_vendus, liquidos)`, um líquido por linha, na mesma ordem.
    """
    def _bruto(l):
        return round(float(l.get("gross_price", 0) or 0) * (l.get("qty", 1) or 1), 2)

    bruto_total = round(sum(_bruto(l) for l in lines), 2)
    amount = max(0.0, min(float(amount or 0), bruto_total))
    if bruto_total <= 0:
        return [combine_global(l, 0)[0] for l in lines], [0.0 for _ in lines]

    pct = round(100.0 * amount / bruto_total, 4)
    saidas, liquidos = [], []
    for l in lines:
        out, liq = combine_global(l, pct)
        saidas.append(out)
        liquidos.append(liq)

    # Resto do arredondamento na ÚLTIMA linha com valor.
    alvo = round(bruto_total - amount, 2)
    resto = round(alvo - round(sum(liquidos), 2), 2)
    if resto:
        for i in range(len(lines) - 1, -1, -1):
            g = _bruto(lines[i])
            novo = round(liquidos[i] + resto, 2)
            if g <= 0 or novo < 0 or novo > g:
                continue
            eff = round(100.0 * (1 - novo / g), 4)
            if eff > 0:
                saidas[i]["discount_percentage"] = eff
            else:
                saidas[i].pop("discount_percentage", None)
            liquidos[i] = novo
            break
    return saidas, liquidos


def item_net_total(item: dict) -> tuple:
    """`(bruto, líquido)` de uma linha da conta, com o desconto do ITEM aplicado.

    Existe porque a conta era calculada em DOIS sítios — `_open_bill_lines`
    (que descontava) e a consulta de mesa (que não descontava) — e a consulta
    saía impressa com o valor cheio. Agora os dois chamam isto.

    `discount_pct` e `discount_amount` são mutuamente exclusivos (só um fica
    gravado), mas subtraem-se os dois por segurança. Nunca devolve negativo.
    """
    dpct = float(item.get("discount_pct", 0) or 0)
    damt = float(item.get("discount_amount", 0) or 0)
    gross = round(float(item.get("total_price", 0) or 0), 2)
    net = round(max(0.0, gross * (1 - dpct / 100.0) - damt), 2)
    return gross, net
