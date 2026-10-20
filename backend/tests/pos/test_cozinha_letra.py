"""Talão da cozinha: letra MAIOR e as observações ainda maiores (pedido do dono,
2026-10-20). Com `GS !` o tamanho é (largura-1)<<4 | (altura-1): o 0x10 que se usava
era só largura ×2 — letra larga e baixa. Isto prende os tamanhos que saem."""
from server import ESCPOSFormatter

GS = b"\x1d!"
BASE = {"order_number": 7, "source": "client", "table_number": 4,
        "created_at": "2026-10-20T19:00:00+00:00"}


def _cozinha(item, **extra):
    return ESCPOSFormatter().format_kitchen({**BASE, "items": [item], **extra})


def test_artigo_sai_em_letra_dupla_nos_dois_sentidos():
    out = _cozinha({"product_name": "Margherita", "quantity": 2})
    assert GS + b"\x11" + b"2x Margherita" in out          # 2×2


def test_observacao_do_artigo_sai_maior_que_o_artigo():
    out = _cozinha({"product_name": "Margherita", "quantity": 1, "notes": "sem cebola"})
    assert GS + b"\x22" + b"OBS: SEM CEBOLA" in out        # 3×3


def test_observacao_do_pedido_sai_em_letra_grande():
    out = _cozinha({"product_name": "Margherita", "quantity": 1}, notes="alergia a frutos secos")
    assert GS + b"\x22" + b"ALERGIA A" in out


def test_observacao_comprida_parte_por_palavras():
    # 3×3 numa folha de 80 mm = 16 letras por linha: a impressora partia a meio
    # das palavras ("CEBOL" / "A"); agora parte nos espaços.
    out = _cozinha({"product_name": "Pizza", "quantity": 1,
                    "notes": "bem passada sem cebola e sem oregaos"})
    linhas = [l for l in out.split(b"\n") if b"PASSADA" in l or b"CEBOLA" in l or b"OREGAOS" in l]
    for l in linhas:
        texto = l.split(GS + b"\x22")[-1]
        assert len(texto) <= 16, texto
    assert b"OREGAOS" in out and b"CEBOLA" in out
