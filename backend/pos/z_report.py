"""Relatório Z (fecho de caixa) em ESC/POS — lógica pura, sem I/O.

`build_z_escpos` recebe os DADOS do Z já calculados pelo fecho (Task 10, o
dict devolvido por `POST /api/pos/cash/close` ou reconstruído por
`GET /api/pos/cash/{id}/z`) e devolve os bytes prontos para a impressora da
caixa — o mesmo mecanismo de `db.print_jobs` + `escpos_direct_b64` +
`printer_type="cashier"` já usado para as faturas (ver `close_table` em
server.py). Não depende do `ESCPOSFormatter` de server.py (evita import
circular: server.py importa `pos.*`, nunca o contrário) — usa os mesmos
comandos ESC/POS e a mesma técnica de "despir" acentos para code page 860,
só que num módulo independente e testável sem Mongo.

PURA de propósito: nenhuma chamada de rede/BD/relógio — a mesma entrada
produz sempre a mesma saída (testável em `tests/pos/test_z_report.py`).
"""
from typing import Any, Dict

ESC = b"\x1b"
GS = b"\x1d"
INIT = ESC + b"@"
CUT = GS + b"V\x00"
BOLD_ON = ESC + b"E\x01"
BOLD_OFF = ESC + b"E\x00"
CENTER = ESC + b"a\x01"
LEFT = ESC + b"a\x00"
DOUBLE_HEIGHT = GS + b"!\x10"
NORMAL_SIZE = GS + b"!\x00"

_LINE_WIDTH = 48  # impressora de 80mm (48 colunas), igual ao ESCPOSFormatter

# Substituições para code page 860 (a impressora térmica não fala UTF-8) —
# mesmo critério do ESCPOSFormatter._text em server.py.
_ACCENT_MAP = {
    "ã": "a", "õ": "o", "á": "a", "é": "e", "í": "i", "ó": "o", "ú": "u",
    "à": "a", "è": "e", "ì": "i", "ò": "o", "ù": "u",
    "â": "a", "ê": "e", "î": "i", "ô": "o", "û": "u",
    "ç": "c", "Ç": "C", "ñ": "n", "Ñ": "N",
    "Ã": "A", "Õ": "O", "Á": "A", "É": "E", "Í": "I", "Ó": "O", "Ú": "U",
    "€": "EUR", "£": "GBP", "¥": "JPY",
}


def _text(s: str) -> bytes:
    """Codifica texto para cp860, despindo acentos/€ que a impressora não tem."""
    for old, new in _ACCENT_MAP.items():
        s = s.replace(old, new)
    try:
        return s.encode("cp860", errors="replace")
    except Exception:
        return s.encode("ascii", errors="replace")


def _line(char: str = "-") -> bytes:
    return _text(char * _LINE_WIDTH + "\n")


def _money(v: Any) -> str:
    """Formata um valor monetário com 2 casas decimais e EUR (§constraints)."""
    return f"EUR {float(v or 0):.2f}"


def _fmt_dt(iso: Any) -> str:
    """Formata um datetime ISO (UTC) em hora de Lisboa, dd/mm/aaaa hh:mm.
    Defensivo: se não conseguir interpretar, devolve a string original."""
    if not iso:
        return ""
    try:
        from datetime import datetime
        from zoneinfo import ZoneInfo
        dt = datetime.fromisoformat(str(iso).replace("Z", "+00:00"))
        return dt.astimezone(ZoneInfo("Europe/Lisbon")).strftime("%d/%m/%Y %H:%M")
    except Exception:
        return str(iso)


def build_z_escpos(z: Dict[str, Any]) -> bytes:
    """Constrói o talão do relatório Z a partir dos DADOS do Z (Task 10/11).

    `z` é o dict devolvido por `close_cash_session`/`get_cash_session_z`:
    `restaurant`, `z_footer_text`, `opened_by`, `opened_at`, `closed_by`,
    `closed_at`, `opening_amount`, `movements`, `totals_by_method`
    (`{titulo: {count, total}}`), `expected_cash`, `counted_amount`,
    `difference`, `reconciliation` (`{ok, orphans, missing, ...}`).

    Devolve bytes ESC/POS prontos a enfileirar em `print_jobs` (mesmo formato
    das faturas: init, texto, corte no fim)."""
    data = bytearray()
    data.extend(INIT)

    # --- Cabeçalho ---
    data.extend(CENTER)
    data.extend(BOLD_ON)
    data.extend(_text(f"{z.get('restaurant') or 'Pizzaria'}\n"))
    data.extend(DOUBLE_HEIGHT)
    data.extend(_text("FECHO DE CAIXA\n"))
    data.extend(NORMAL_SIZE)
    data.extend(BOLD_OFF)
    data.extend(_text(f"{_fmt_dt(z.get('closed_at'))}\n"))
    data.extend(_line("="))

    # --- Aberta/fechada por ---
    data.extend(LEFT)
    data.extend(_text(f"Aberta por: {z.get('opened_by') or '-'}\n"))
    data.extend(_text(f"  em {_fmt_dt(z.get('opened_at'))}\n"))
    data.extend(_text(f"Fechada por: {z.get('closed_by') or '-'}\n"))
    data.extend(_text(f"  em {_fmt_dt(z.get('closed_at'))}\n"))
    data.extend(_line("-"))

    # --- Fundo de caixa ---
    data.extend(_text(f"Fundo de caixa: {_money(z.get('opening_amount'))}\n"))

    # --- Movimentos (sangria/reforço) ---
    movimentos = z.get("movements") or []
    if movimentos:
        data.extend(_line("-"))
        data.extend(_text("MOVIMENTOS\n"))
        for m in movimentos:
            rotulo = "Reforco" if m.get("type") == "reforco" else "Sangria"
            sinal = "+" if m.get("type") == "reforco" else "-"
            linha = f"{rotulo}: {sinal}{_money(m.get('amount'))}"
            if m.get("reason"):
                linha += f" ({m['reason']})"
            data.extend(_text(linha + "\n"))

    # --- Por forma de pagamento ---
    data.extend(_line("-"))
    data.extend(BOLD_ON)
    data.extend(_text("POR FORMA DE PAGAMENTO\n"))
    data.extend(BOLD_OFF)
    totals = z.get("totals_by_method") or {}
    for titulo in sorted(totals):
        v = totals[titulo] or {}
        count = int(v.get("count", 0) or 0)
        total = _money(v.get("total"))
        data.extend(_text(f"{titulo:<24}{count:>3}x {total:>12}\n"))
    if not totals:
        data.extend(_text("(sem vendas)\n"))

    # --- Esperado / contado / diferença ---
    data.extend(_line("-"))
    data.extend(_text(f"Esperado (dinheiro): {_money(z.get('expected_cash'))}\n"))
    data.extend(_text(f"Contado:             {_money(z.get('counted_amount'))}\n"))
    data.extend(BOLD_ON)
    data.extend(_text(f"DIFERENCA:           {_money(z.get('difference'))}\n"))
    data.extend(BOLD_OFF)

    # --- Aviso de reconciliação ---
    reconciliacao = z.get("reconciliation") or {}
    if reconciliacao and not reconciliacao.get("ok", True):
        data.extend(_line("-"))
        data.extend(BOLD_ON)
        data.extend(_text("ATENCAO: RECONCILIACAO COM DIVERGENCIAS\n"))
        data.extend(BOLD_OFF)
        orphans = reconciliacao.get("orphans") or []
        missing = reconciliacao.get("missing") or []
        if orphans:
            data.extend(_text(f"Vendus sem par nas vendas POS: {', '.join(orphans)}\n"))
        if missing:
            data.extend(_text(f"Vendas POS sem fatura: {', '.join(missing)}\n"))

    # --- Rodapé ---
    footer = (z.get("z_footer_text") or "").strip()
    if footer:
        data.extend(_line("="))
        data.extend(CENTER)
        data.extend(_text(footer + "\n"))
        data.extend(LEFT)

    data.extend(_line("="))
    data.extend(_text("\n\n\n"))
    data.extend(CUT)

    return bytes(data)
