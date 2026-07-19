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
