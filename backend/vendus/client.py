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

    # ---- Relatório de vendas (receita real faturada pela app) ----
    def list_app_invoices(self, *, date: str, per_page: int = 200) -> list:
        """Documentos faturados na caixa da app (register_id configurado) a partir
        de `date` (formato YYYY-MM-DD, inclusive). `view=detailed` traz os
        `payments` e `amount_gross`. Devolve só os documentos DESSE dia e exclui
        recibos (RG), que são apenas o comprovativo da mesma venda."""
        params: dict = {"since": date, "view": "detailed", "per_page": per_page}
        if self._cfg.register_id is not None:
            params["register_id"] = self._cfg.register_id
        docs = self._request("GET", "documents/", params=params) or []
        return [
            d for d in docs
            if str(d.get("date", "")).startswith(date) and d.get("type") != "RG"
        ]

    def app_sales_summary(self, date: str) -> dict:
        """Resumo das vendas faturadas pela app num dia: total e repartição por
        forma de pagamento (Dinheiro, Multibanco, ...), lido das faturas reais do
        Vendus. Fonte de verdade da receita — inclui rodízio e descontos, que não
        ficam no `total` dos pedidos."""
        docs = self.list_app_invoices(date=date)
        by_method: dict = {}
        total = 0.0
        for d in docs:
            gross = float(d.get("amount_gross") or 0)
            total = round(total + gross, 2)
            pays = d.get("payments") or []
            if pays:
                for p in pays:
                    title = (p.get("title") or "Outro").strip() or "Outro"
                    amt = float(p.get("amount") or 0)
                    cur = by_method.setdefault(title, {"count": 0, "total": 0.0})
                    cur["total"] = round(cur["total"] + amt, 2)
                # 1 fatura = 1 forma de pagamento (contamos o documento uma vez)
                title0 = (pays[0].get("title") or "Outro").strip() or "Outro"
                by_method[title0]["count"] += 1
            else:
                cur = by_method.setdefault("Sem pagamento", {"count": 0, "total": 0.0})
                cur["total"] = round(cur["total"] + gross, 2)
                cur["count"] += 1
        return {
            "total": round(total, 2),
            "by_method": by_method,
            "count": len(docs),
            "documents": [d.get("number") for d in docs],
        }

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
