import json
import httpx
import pytest
from vendus.config import VendusConfig
from vendus.client import VendusClient
from vendus.errors import VendusRateLimited, VendusUnavailable, VendusHTTPError

CFG = VendusConfig.load({"VENDUS_API_KEY": "testkey", "VENDUS_MODE": "tests"})


def _client(handler):
    return VendusClient(CFG, transport=httpx.MockTransport(handler))


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
