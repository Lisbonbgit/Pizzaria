"""Talões do BALCÃO (impressora da Caixa) com letra maior — pedido do dono
2026-10-20. A cópia do pedido e a consulta são montadas por nós; as faturas vêm
prontas do Vendus e só ganham altura dupla (mesmas colunas, conteúdo intacto)."""
import re

from server import ESCPOSFormatter, _escpos_mais_alto

GS = b"\x1d!"
PEDIDO = {"order_number": 42, "source": "balcao", "table_number": None, "total": 27.0,
          "id": "abcdef123456", "created_at": "2026-10-20T19:00:00+00:00",
          "items": [{"product_name": "Margherita", "quantity": 2, "unit_price": 9.0,
                     "total_price": 18.0, "extras": [{"name": "Borda", "price": 3.0}]}]}


def _caixa():
    return ESCPOSFormatter().format_cashier(dict(PEDIDO))


def test_copia_do_pedido_tem_tudo_maior():
    out = _caixa()
    assert GS + b"\x11" + b"PEDIDO #42" in out           # 2×2
    assert GS + b"\x11" + b"BALCAO" in out
    assert GS + b"\x11" + b"2x Margherita" in out
    assert GS + b"\x01" + b"   + Borda" in out            # altura dupla
    assert GS + b"\x11" + b"EUR 18.00" in out


def test_total_e_o_maior_do_talao():
    assert GS + b"\x12" + b"TOTAL: EUR 27.00" in _caixa()   # 2 de largura × 3 de altura


def _sem_tamanhos(raw):
    return re.sub(rb"[\x1b\x1d]!.", b"", raw, flags=re.S)


def test_fatura_verdadeira_do_vendus_usa_esc_e_tambem_fica_alta():
    # Estrutura de uma FS real (19/10): o Vendus muda o tamanho com ESC ! (00 e
    # 20), não com GS !. Sem isto o 1.º "ESC ! 00" anulava a altura e a FS saía igual.
    fs = (b"\x1b@\n\x1ba1\x1b!\x00Lenha e Brasa\n\x1ba0\x1b!\x00NIF: 503109479\n"
          b"Fatura Simplificada       FS 01P2026/264\n"
          b"\x1b!\x20Total      Eur 53,35\n\x1b!\x00Multibanco    Eur 53,35\n\x1bJ\xfe\x1dV\x00")
    novo = _escpos_mais_alto(fs)
    assert b"\x1b!\x00" not in novo                     # nenhum "normal" sobra
    assert novo.count(b"\x1b!\x10") == 3                 # normal → alto
    assert b"\x1b!\x30Total" in novo                    # largo → largo E alto
    assert _sem_tamanhos(novo) == _sem_tamanhos(fs)    # o texto da fatura não muda


def test_fatura_do_vendus_fica_com_altura_dupla_sem_mexer_no_texto():
    fs = (b"\x1b@\x1ba\x01\x1bE\x01Lenha e Brasa\n\x1bE\x00\x1d!\x10FS 01P2026/230\x1d!\x00\n"
          b"Margherita          18,00\nTOTAL               18,00\n\x1dV\x00")
    novo = _escpos_mais_alto(fs)
    assert novo.startswith(b"\x1b@\x1d!\x01")           # tudo alto desde o início
    assert b"\x1d!\x11FS 01P2026/230" in novo           # o que era largo fica largo E alto
    assert b"\x1d!\x01\n" in novo                       # o "normal" passa a alto
    assert _sem_tamanhos(novo) == _sem_tamanhos(fs)     # o texto da fatura não muda


def test_a_ponte_recebe_a_fatura_ja_com_altura_dupla(monkeypatch):
    # A transformação só vale se estiver LIGADA: é o pending-jobs que a ponte lê.
    import asyncio
    import base64
    import server
    from tests.pos.test_mesa_divisao import _Coll

    fs = b"\x1b@FS 01P2026/230\n\x1d!\x00TOTAL 18,00\n\x1dV\x00"
    cozinha = {"order_number": 9, "source": "balcao", "table_number": None,
               "created_at": "2026-10-20T19:00:00+00:00",
               "items": [{"product_name": "Pizza", "quantity": 1}]}

    class _Db:
        settings = _Coll([{"key": "print_agent", "value": {"api_key": "k"}}])
        printers = _Coll()
        orders = _Coll()
        print_jobs = _Coll([
            {"id": "j1", "status": "pending", "printer_type": "cashier", "printer_name": "Caixa",
             "created_at": "1", "escpos_direct_b64": base64.b64encode(fs).decode()},
            {"id": "j2", "status": "pending", "printer_type": "kitchen", "printer_name": "Cozinha",
             "created_at": "2", "order_snapshot": cozinha},
        ])
    monkeypatch.setattr(server, "db", _Db())
    jobs = asyncio.run(server.get_pending_jobs_for_agent(x_api_key="k"))
    por_id = {j["job"]["id"]: base64.b64decode(j["escpos_base64"]) for j in jobs}
    assert por_id["j1"] == _escpos_mais_alto(fs)
    assert b"\x1d!\x22PEDIDO #9" in por_id["j2"]          # a cozinha não leva a transformação
