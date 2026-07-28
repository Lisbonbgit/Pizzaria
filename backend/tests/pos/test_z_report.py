"""Relatório Z imprimível (Task 11) — teste PURO de `build_z_escpos`.

Sem Mongo/rede: dá-se um dict de dados do Z (a forma exata devolvida por
`POST /api/pos/cash/close`, Task 10) e verifica-se que o texto do talão
(depois de descodificado de cp860) contém os rótulos e valores esperados.
"""
from pos.z_report import build_z_escpos

SAMPLE_Z = {
    "restaurant": "Pizzaria Lenha e Brasa",
    "z_footer_text": "Obrigado pela preferencia!",
    "session_id": "sess-123",
    "opened_by": "Ana",
    "opened_at": "2026-07-27T09:00:00+00:00",
    "closed_by": "Bruno",
    "closed_at": "2026-07-27T22:15:00+00:00",
    "opening_amount": 50.0,
    "movements": [
        {"type": "reforco", "amount": 20.0, "by": "op1", "at": "2026-07-27T12:00:00+00:00"},
        {"type": "sangria", "amount": 30.0, "reason": "deposito", "by": "op1",
         "at": "2026-07-27T18:00:00+00:00"},
    ],
    "cash_sales": 199.65,
    "totals_by_method": {
        "Dinheiro": {"count": 5, "total": 199.65},
        "Multibanco": {"count": 3, "total": 87.30},
    },
    "vendus_total": 286.95,
    "vendus_count": 8,
    "expected_cash": 239.65,
    "counted_amount": 235.0,
    "difference": -4.65,
    "reconciliation": {"ok": True, "orphans": [], "missing": [], "details": {}},
    "warnings": [],
}


def _decode(raw: bytes) -> str:
    return raw.decode("cp860", errors="replace")


def test_build_z_escpos_devolve_bytes():
    raw = build_z_escpos(SAMPLE_Z)
    assert isinstance(raw, bytes)
    assert len(raw) > 0


def test_build_z_escpos_cabecalho_e_rodape():
    texto = _decode(build_z_escpos(SAMPLE_Z))
    assert "Pizzaria Lenha e Brasa" in texto
    assert "FECHO DE CAIXA" in texto
    assert "Ana" in texto  # aberta por
    assert "Bruno" in texto  # fechada por
    assert "Obrigado pela preferencia" in texto  # z_footer_text (sem acento)


def test_build_z_escpos_totais_por_metodo():
    texto = _decode(build_z_escpos(SAMPLE_Z))
    assert "POR FORMA DE PAGAMENTO" in texto
    assert "Dinheiro" in texto
    assert "Multibanco" in texto
    assert "EUR 199.65" in texto
    assert "EUR 87.30" in texto


def test_build_z_escpos_movimentos():
    texto = _decode(build_z_escpos(SAMPLE_Z))
    assert "Reforco" in texto
    assert "Sangria" in texto
    assert "EUR 20.00" in texto
    assert "EUR 30.00" in texto
    assert "deposito" in texto


def test_build_z_escpos_esperado_contado_diferenca():
    texto = _decode(build_z_escpos(SAMPLE_Z))
    assert "Fundo de caixa: EUR 50.00" in texto
    assert "EUR 239.65" in texto  # esperado
    assert "EUR 235.00" in texto  # contado
    assert "EUR -4.65" in texto   # diferença negativa


def test_build_z_escpos_sem_aviso_quando_reconciliacao_ok():
    texto = _decode(build_z_escpos(SAMPLE_Z))
    assert "DIVERGENCIAS" not in texto


def test_build_z_escpos_aviso_reconciliacao_com_divergencias():
    z = dict(SAMPLE_Z)
    z["reconciliation"] = {
        "ok": False,
        "orphans": ["Dinheiro"],
        "missing": ["Multibanco"],
        "details": {},
    }
    texto = _decode(build_z_escpos(z))
    assert "DIVERGENCIAS" in texto
    assert "Dinheiro" in texto  # orphan citado
    assert "Multibanco" in texto  # missing citado


def test_build_z_escpos_sem_movimentos_nao_rebenta():
    z = dict(SAMPLE_Z)
    z["movements"] = []
    raw = build_z_escpos(z)
    assert isinstance(raw, bytes)
    texto = _decode(raw)
    assert "MOVIMENTOS" not in texto


def test_build_z_escpos_sem_totais_mostra_sem_vendas():
    z = dict(SAMPLE_Z)
    z["totals_by_method"] = {}
    texto = _decode(build_z_escpos(z))
    assert "(sem vendas)" in texto


def test_build_z_escpos_dict_minimo_nao_rebenta():
    # Um Z quase vazio (defensivo) não deve rebentar — todos os .get() têm fallback.
    raw = build_z_escpos({})
    assert isinstance(raw, bytes)
    assert len(raw) > 0
