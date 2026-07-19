from __future__ import annotations
from typing import Any, Optional
import httpx
from .config import VendusConfig
from .errors import VendusRateLimited, VendusUnavailable, VendusHTTPError


class VendusClient:
    """Cliente HTTP para a API Vendus (v1.1). Basic auth com a API key
    como username (password vazia). `transport` injetável para testes."""

    def __init__(self, config: VendusConfig, transport: Optional[httpx.BaseTransport] = None):
        self._cfg = config
        self._http = httpx.Client(
            base_url=config.base_url,
            auth=(config.api_key, ""),
            timeout=30.0,
            transport=transport,
        )

    def close(self) -> None:
        self._http.close()

    def _request(self, method: str, path: str, *, params: Optional[dict] = None,
                 json: Optional[dict] = None) -> Any:
        body = None
        if json is not None:
            body = {**json, "mode": self._cfg.mode}
        try:
            resp = self._http.request(method, path, params=params, json=body)
        except (httpx.TimeoutException, httpx.TransportError) as e:
            raise VendusUnavailable(str(e)) from e

        if resp.status_code == 429:
            reset = resp.headers.get("Rate-Limit-Reset")
            raise VendusRateLimited(f"rate-limit; reset em {reset}s")
        if 500 <= resp.status_code < 600:
            raise VendusUnavailable(f"Vendus {resp.status_code}")
        if resp.status_code >= 400:
            raise VendusHTTPError(resp.status_code, resp.text)
        if not resp.content:
            return None
        return resp.json()
