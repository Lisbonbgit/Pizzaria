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

    # ---- Produtos / catálogo ----
    def list_products(self, **filters) -> list:
        return self._request("GET", "products/", params=filters) or []

    def list_categories(self) -> list:
        return self._request("GET", "products/categories/") or []

    # ---- Salas / mesas ----
    def list_rooms(self) -> list:
        return self._request("GET", "rooms/") or []

    def list_tables(self, room_id: int) -> list:
        return self._request("GET", "tables/", params={"parent": room_id}) or []

    # ---- Documentos (conta de mesa) ----
    def create_table_order(self, *, room_id: int, table_id: int, occupation: int,
                           items: list, external_reference: str) -> dict:
        body = {
            "type": "DC",
            "rest_room": room_id,
            "rest_table": table_id,
            "occupation": occupation,
            "items": items,
            "external_reference": external_reference,
        }
        if self._cfg.register_id is not None:
            body["register_id"] = self._cfg.register_id
        return self._request("POST", "documents/", json=body)

    def get_document(self, doc_id: int) -> dict:
        return self._request("GET", f"documents/{doc_id}/", params={"view": "detailed"})

    def list_open_table_docs(self, since: str) -> list:
        return self._request(
            "GET", "documents/",
            params={"type": "DC", "view": "detailed", "since": since},
        ) or []

    def list_payment_methods(self) -> list:
        return self._request("GET", "documents/paymentmethods/") or []

    def create_invoice(self, *, items: list, payments: list, doc_type: str = "FR",
                       client: Optional[dict] = None,
                       external_reference: Optional[str] = None,
                       output: Optional[str] = None) -> dict:
        """Emite um documento fiscal (ex.: FS = fatura simplificada) com os itens e
        os pagamentos. `client` opcional para NIF/empresa. `output` (ex.: 'escpos'
        ou 'pdf') pede ao Vendus o documento já imprimível, devolvido no campo
        'output' (base64)."""
        body: dict = {"type": doc_type, "items": items, "payments": payments}
        if self._cfg.register_id is not None:
            body["register_id"] = self._cfg.register_id
        if client:
            body["client"] = client
        if external_reference:
            body["external_reference"] = external_reference
        if output:
            body["output"] = output
        return self._request("POST", "documents/", json=body)
