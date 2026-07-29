import json
import httpx
import pytest
from vendus.config import VendusConfig
from vendus.client import VendusClient
from vendus.errors import VendusRateLimited, VendusUnavailable, VendusHTTPError

CFG = VendusConfig.load({"VENDUS_API_KEY": "testkey", "VENDUS_MODE": "tests"})


def _client(handler):
    return VendusClient(CFG, transport=httpx.MockTransport(handler))


def test_timeout_default_e_configuravel():
    # Sem `timeout` explícito mantém o default atual (30s) — usado na emissão
    # de FS. Passar `timeout` (ex.: as chamadas espelho da caixa) fica com um
    # bound curto e não com o default.
    padrao = VendusClient(CFG, transport=httpx.MockTransport(lambda r: httpx.Response(200)))
    assert padrao._http.timeout == httpx.Timeout(30.0)

    curto = VendusClient(
        CFG, transport=httpx.MockTransport(lambda r: httpx.Response(200)), timeout=6.0
    )
    assert curto._http.timeout == httpx.Timeout(6.0)


def test_basic_auth_e_mode_no_post():
    captured = {}

    def handler(request: httpx.Request):
        captured["auth"] = request.headers.get("authorization")
        captured["body"] = json.loads(request.content.decode())
        return httpx.Response(200, json={"id": 1})

    _client(handler)._request("POST", "documents/", json={"type": "DC"})
    # Basic base64("testkey:")
    assert captured["auth"] == "Basic dGVzdGtleTo="
    assert captured["body"]["mode"] == "tests"      # mode injetado
    assert captured["body"]["type"] == "DC"


def test_429_levanta_rate_limited():
    def handler(request):
        return httpx.Response(429, json={"errors": ["rate"]})

    with pytest.raises(VendusRateLimited):
        _client(handler)._request("GET", "documents/")


def test_5xx_levanta_unavailable():
    def handler(request):
        return httpx.Response(503, text="down")

    with pytest.raises(VendusUnavailable):
        _client(handler)._request("GET", "documents/")


def test_4xx_levanta_http_error():
    def handler(request):
        return httpx.Response(400, text="bad")

    with pytest.raises(VendusHTTPError):
        _client(handler)._request("GET", "documents/")


def test_create_table_order_monta_payload():
    seen = {}

    def handler(request: httpx.Request):
        seen["url"] = str(request.url)
        seen["body"] = json.loads(request.content.decode())
        return httpx.Response(200, json={"id": 999, "type": "DC"})

    cfg = VendusConfig.load({"VENDUS_API_KEY": "k", "VENDUS_REGISTER_ID": "7", "VENDUS_MODE": "tests"})
    client = VendusClient(cfg, transport=httpx.MockTransport(handler))
    out = client.create_table_order(
        room_id=1, table_id=2, occupation=3,
        items=[{"reference": "P1", "title": "Pizza", "qty": 1, "gross_price": 9.5, "tax_id": "NOR"}],
        external_reference="order-abc",
    )
    assert out["id"] == 999
    b = seen["body"]
    assert b["type"] == "DC" and b["rest_room"] == 1 and b["rest_table"] == 2
    assert b["occupation"] == 3 and b["register_id"] == 7
    assert b["external_reference"] == "order-abc"
    assert b["items"][0]["reference"] == "P1"
    assert b["mode"] == "tests"


def test_list_tables_usa_parent():
    seen = {}

    def handler(request: httpx.Request):
        seen["url"] = str(request.url)
        return httpx.Response(200, json=[{"id": 2, "title": "Mesa 2"}])

    client = VendusClient(CFG, transport=httpx.MockTransport(handler))
    rows = client.list_tables(room_id=5)
    assert rows[0]["id"] == 2
    assert "parent=5" in seen["url"]


def test_get_document_usa_view_detailed():
    seen = {}

    def handler(request: httpx.Request):
        seen["url"] = str(request.url)
        return httpx.Response(200, json={"id": 10, "items": []})

    client = VendusClient(CFG, transport=httpx.MockTransport(handler))
    doc = client.get_document(10)
    assert doc["id"] == 10
    assert "documents/10/" in seen["url"]
    assert "view=detailed" in seen["url"]


def test_create_invoice_monta_fr_com_pagamento_e_cliente():
    seen = {}

    def handler(request: httpx.Request):
        seen["body"] = json.loads(request.content.decode())
        return httpx.Response(200, json={"id": 1, "number": "FR 1/1", "atcud": "X-1"})

    cfg = VendusConfig.load({"VENDUS_API_KEY": "k", "VENDUS_REGISTER_ID": "9", "VENDUS_MODE": "tests"})
    client = VendusClient(cfg, transport=httpx.MockTransport(handler))
    out = client.create_invoice(
        items=[{"title": "Pizza", "qty": 1, "gross_price": 9.5, "tax_id": "NOR"}],
        payments=[{"id": 316430468, "amount": 9.5}],
        client={"fiscal_id": "500000000"},
        external_reference="mesa-1-close",
    )
    assert out["number"] == "FR 1/1"
    b = seen["body"]
    assert b["type"] == "FR" and b["register_id"] == 9
    assert b["payments"][0]["id"] == 316430468
    assert b["client"]["fiscal_id"] == "500000000"
    assert b["external_reference"] == "mesa-1-close"
    assert b["mode"] == "tests"


def test_list_open_table_docs_filtra_dc_e_since():
    seen = {}

    def handler(request: httpx.Request):
        seen["url"] = str(request.url)
        return httpx.Response(200, json=[{"id": 1, "type": "DC"}])

    client = VendusClient(CFG, transport=httpx.MockTransport(handler))
    rows = client.list_open_table_docs(since="2026-07-19")
    assert rows[0]["id"] == 1
    assert "type=DC" in seen["url"]
    assert "view=detailed" in seen["url"]
    assert "since=2026-07-19" in seen["url"]


def test_app_sales_summary_window_atravessa_meia_noite():
    # Sessão aberta 27/07 22:30 Lisboa (=21:30 UTC) e fechada 28/07 01:30 Lisboa.
    # A janela tem de: (a) percorrer os DOIS dias do calendário Lisboa; (b) manter
    # a FS de depois da meia-noite (00:30); (c) excluir a FS de ANTES da abertura
    # (20:00) e a de DEPOIS do fecho (02:00) — tudo por `local_time`, não por data.
    por_data = {
        "2026-07-27": [
            {"id": 1, "number": "FS 1", "type": "FS", "date": "2026-07-27",
             "local_time": "2026-07-27 22:45:00", "amount_gross": 10.0,
             "external_reference": "mesa-1-x",
             "payments": [{"id": 100, "title": "Dinheiro", "amount": 10.0}]},
            {"id": 2, "number": "FS 2", "type": "FS", "date": "2026-07-27",
             "local_time": "2026-07-27 20:00:00", "amount_gross": 99.0,   # ANTES da abertura
             "external_reference": "mesa-2-x",
             "payments": [{"id": 200, "title": "Multibanco", "amount": 99.0}]},
        ],
        "2026-07-28": [
            {"id": 3, "number": "FS 3", "type": "FS", "date": "2026-07-28",
             "local_time": "2026-07-28 00:30:00", "amount_gross": 25.0,   # depois da meia-noite
             "external_reference": "mesa-3-x",
             "payments": [{"id": 200, "title": "Multibanco", "amount": 25.0}]},
            {"id": 4, "number": "FS 4", "type": "FS", "date": "2026-07-28",
             "local_time": "2026-07-28 02:00:00", "amount_gross": 50.0,   # DEPOIS do fecho
             "external_reference": "mesa-4-x",
             "payments": [{"id": 100, "title": "Dinheiro", "amount": 50.0}]},
        ],
    }
    datas_pedidas = []
    registers = []

    def handler(request: httpx.Request):
        since = request.url.params.get("since")
        datas_pedidas.append(since)
        registers.append(request.url.params.get("register_id"))
        return httpx.Response(200, json=por_data.get(since, []))

    cfg = VendusConfig.load({"VENDUS_API_KEY": "k", "VENDUS_REGISTER_ID": "7", "VENDUS_MODE": "tests"})
    client = VendusClient(cfg, transport=httpx.MockTransport(handler))
    out = client.app_sales_summary_window("2026-07-27T21:30:00+00:00", "2026-07-28T01:30:00+01:00")

    assert set(datas_pedidas) == {"2026-07-27", "2026-07-28"}   # percorreu os 2 dias
    assert registers == ["7", "7"]                              # register preservado
    assert out["count"] == 2                                    # só FS 1 e FS 3 na janela
    assert out["total"] == 35.0
    assert set(out["documents"]) == {"FS 1", "FS 3"}
    assert out["by_method"]["Dinheiro"] == {"count": 1, "total": 10.0}
    assert out["by_method"]["Multibanco"] == {"count": 1, "total": 25.0}
    assert "Multibanco" not in [i["label"] for i in out["invoices"]]  # sanity


def test_app_sales_summary_window_janela_no_mesmo_dia():
    # Sessão inteiramente no mesmo dia: um único fetch, filtra pela hora.
    docs = [
        {"id": 1, "number": "FS 1", "type": "FS", "date": "2026-07-28",
         "local_time": "2026-07-28 12:00:00", "amount_gross": 8.0,
         "external_reference": "mesa-1-x",
         "payments": [{"id": 100, "title": "Dinheiro", "amount": 8.0}]},
        {"id": 2, "number": "FS 2", "type": "FS", "date": "2026-07-28",
         "local_time": "2026-07-28 09:00:00", "amount_gross": 5.0,   # antes da abertura
         "external_reference": "mesa-2-x",
         "payments": [{"id": 100, "title": "Dinheiro", "amount": 5.0}]},
    ]
    fetches = []

    def handler(request: httpx.Request):
        fetches.append(request.url.params.get("since"))
        return httpx.Response(200, json=docs)

    client = VendusClient(CFG, transport=httpx.MockTransport(handler))
    out = client.app_sales_summary_window("2026-07-28T10:00:00+01:00", "2026-07-28T15:00:00+01:00")
    assert fetches == ["2026-07-28"]          # um só dia → um só fetch
    assert out["count"] == 1 and out["total"] == 8.0


def test_list_app_invoices_404_no_data_devolve_vazio():
    # O Vendus 404 "No data" (A001) num dia/caixa sem vendas NÃO é erro: []
    def handler(request):
        return httpx.Response(404, json={"errors": [{"code": "A001", "message": "No data"}]})

    assert _client(handler).list_app_invoices(date="2026-07-29") == []


def test_window_com_dia_sem_dados_nao_rebenta():
    # Uma sessão cujo dia não tem vendas: o fecho tem de reconciliar com 0, não 502.
    def handler(request):
        return httpx.Response(404, json={"errors": [{"code": "A001", "message": "No data"}]})

    out = _client(handler).app_sales_summary_window(
        "2026-07-29T10:00:00+01:00", "2026-07-29T23:00:00+01:00")
    assert out["count"] == 0 and out["total"] == 0.0


def test_list_app_invoices_outro_404_propaga():
    # Um 404 que NÃO seja "No data" continua a ser erro (não engolir tudo).
    def handler(request):
        return httpx.Response(404, json={"errors": [{"code": "X999", "message": "Nope"}]})

    with pytest.raises(VendusHTTPError):
        _client(handler).list_app_invoices(date="2026-07-29")


def _client_com_register(handler):
    cfg = VendusConfig.load({"VENDUS_API_KEY": "k", "VENDUS_REGISTER_ID": "7", "VENDUS_MODE": "tests"})
    return VendusClient(cfg, transport=httpx.MockTransport(handler))


def test_register_movement_monta_body_sem_mode_e_faz_chamada_crua():
    # O endpoint de movimentos REJEITA `mode` (403) — `register_movement` tem
    # de ir por fora do `_request` (que injeta `mode` sempre).
    seen = {}

    def handler(request: httpx.Request):
        seen["url"] = str(request.url)
        seen["method"] = request.method
        seen["body"] = json.loads(request.content.decode())
        return httpx.Response(201, json={"id": 1, "status": "open"})

    out = _client_com_register(handler).register_movement("open", "NU", 50.0)
    assert seen["method"] == "POST"
    assert "registers/7/movements/" in seen["url"]
    assert seen["body"] == {"operation": "open", "type": "NU", "amount": 50.0}
    assert "mode" not in seen["body"]
    assert out == {"id": 1, "status": "open"}


def test_register_movement_com_obs_e_output_no_body():
    seen = {}

    def handler(request: httpx.Request):
        seen["body"] = json.loads(request.content.decode())
        return httpx.Response(201, json={"id": 2})

    _client_com_register(handler).register_movement(
        "out", "NU", 10.5, obs="sangria depósito", output="escpos"
    )
    assert seen["body"]["operation"] == "out"
    assert seen["body"]["obs"] == "sangria depósito"
    assert seen["body"]["output"] == "escpos"
    assert "mode" not in seen["body"]


def test_register_movement_close_com_output_devolve_escpos_base64():
    # 201 no fecho, com `output` (base64 do talão Z do Vendus) na resposta.
    def handler(request: httpx.Request):
        body = json.loads(request.content.decode())
        assert body["operation"] == "close"
        assert body["output"] == "escpos"
        return httpx.Response(201, json={"id": 3, "status": "close", "output": "Gxeb...base64..."})

    out = _client_com_register(handler).register_movement("close", "NU", 235.0, output="escpos")
    assert out["status"] == "close"
    assert out["output"] == "Gxeb...base64..."


def test_register_movement_erro_http_levanta():
    def handler(request):
        return httpx.Response(403, text="mode not allowed")

    with pytest.raises(VendusHTTPError):
        _client_com_register(handler).register_movement("open", "NU", 50.0)


def test_register_movement_sem_register_id_levanta_vendus_error():
    from vendus.errors import VendusError
    with pytest.raises(VendusError):
        _client(handler=lambda request: httpx.Response(200)).register_movement("open", "NU", 0)


def test_register_status_le_status_do_registador():
    def handler(request: httpx.Request):
        assert request.method == "GET"
        assert "registers/7/" in str(request.url)
        return httpx.Response(200, json={"id": 7, "status": "close"})

    assert _client_com_register(handler).register_status() == "close"
