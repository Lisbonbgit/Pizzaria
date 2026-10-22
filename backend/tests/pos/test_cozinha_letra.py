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


def test_meia_meia_sai_com_uma_metade_por_linha():
    out = _cozinha({"product_name": "1/2 Margherita + 1/2 Frango Com Catupiry", "quantity": 1,
                    "variation": {"name": "Grande (8 Fatias)"},
                    "halves": [{"product_id": "a", "product_name": "Margherita"},
                               {"product_id": "b", "product_name": "Frango Com Catupiry"}]})
    assert GS + b"\x11" + b"1x MEIA-MEIA" in out
    assert b"1/2 MARGHERITA" in out and b"1/2 FRANGO COM" in out and b"CATUPIRY" in out
    assert b"1x 1/2" not in out          # o nome composto não sai como linha do artigo


def test_maiusculas_acentuadas_saem_sem_acento():
    # as metades e a OBS vão em maiúsculas; Â/Ê/Ô/À iam crus (cp860) para uma
    # impressora sem página de código fixada e saíam como lixo
    out = _cozinha({"product_name": "1/2 Frango à Brás + 1/2 Pêssego", "quantity": 1,
                    "notes": "sem côco nem pão",
                    "halves": [{"product_id": "a", "product_name": "Frango à Brás"},
                               {"product_id": "b", "product_name": "Pêssego Ìmpar Ûnico"}]})
    assert b"1/2 FRANGO A BRAS" in out and b"1/2 PESSEGO IMPAR" in out and b"UNICO" in out
    assert b"OBS: SEM COCO" in out and b"NEM PAO" in out
    assert max(out) < 0x80, "byte fora do ASCII no talão"
