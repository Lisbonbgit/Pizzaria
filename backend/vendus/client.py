from __future__ import annotations
from typing import Any, Optional
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
import httpx
from .config import VendusConfig
from .errors import VendusError, VendusRateLimited, VendusUnavailable, VendusHTTPError

# Fuso do restaurante (Portugal continental). O Vendus grava `local_time` na
# hora local; a caixa é lida/reconciliada por JANELA temporal neste fuso.
_LISBON = ZoneInfo("Europe/Lisbon")


class VendusClient:
    """Cliente HTTP para a API Vendus (v1.1). Basic auth com a API key
    como username (password vazia). `transport` injetável para testes."""

    def __init__(self, config: VendusConfig, transport: Optional[httpx.BaseTransport] = None,
                 timeout: float = 30.0):
        self._cfg = config
        self._http = httpx.Client(
            base_url=config.base_url,
            auth=(config.api_key, ""),
            timeout=timeout,
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
        try:
            docs = self._request("GET", "documents/", params=params) or []
        except VendusHTTPError as e:
            # O Vendus devolve 404 "No data" (código A001) quando NÃO há documentos
            # para o filtro (um dia/caixa sem vendas). Isso é ZERO vendas, não um
            # erro — não pode rebentar o fecho de caixa nem o relatório diário.
            if e.status_code == 404 and ("A001" in e.body or "No data" in e.body):
                return []
            raise
        return [
            d for d in docs
            if str(d.get("date", "")).startswith(date) and d.get("type") != "RG"
        ]

    def app_sales_summary(self, date: str) -> dict:
        """Resumo das vendas faturadas pela app num dia: total e repartição por
        forma de pagamento (Dinheiro, Multibanco, ...), lido das faturas reais do
        Vendus. Fonte de verdade da receita — inclui rodízio e descontos, que não
        ficam no `total` dos pedidos."""
        return self._summarize_docs(self.list_app_invoices(date=date))

    def app_sales_summary_window(self, start_lisbon_iso: str, end_lisbon_iso: str) -> dict:
        """Como `app_sales_summary`, mas seleciona as FS da caixa da app por
        JANELA temporal `[start, end]` (Europe/Lisbon), NÃO por string de data.
        É o que o fecho da caixa precisa: uma sessão pode atravessar a meia-noite,
        e filtrar por `date.startswith("YYYY-MM-DD")` deixaria de fora as vendas do
        outro dia do calendário.

        `start_lisbon_iso`/`end_lisbon_iso` são ISO 8601 (o fecho passa o
        `opened_at` — em UTC — já convertido para Lisboa, e o "agora" em Lisboa).
        Estratégia: percorre cada data do calendário Lisboa de `start.date()` a
        `end.date()`, reutiliza o fetch por-dia existente (mesmo `register_id`) e
        depois mantém só as FS cujo `local_time` (interpretado como Lisboa) cai
        dentro da janela. Devolve a mesma forma de `app_sales_summary`."""
        start = self._as_lisbon(start_lisbon_iso)
        end = self._as_lisbon(end_lisbon_iso)

        # União das FS de cada dia abrangido (dedup por id/número do documento —
        # cada fetch por-dia já filtra ao seu dia, mas o dedup é defensivo).
        docs_by_key: dict = {}
        dia = start.date()
        ultimo = end.date()
        while dia <= ultimo:
            for doc in self.list_app_invoices(date=dia.isoformat()):
                key = doc.get("id") or doc.get("number") or id(doc)
                docs_by_key[key] = doc
            dia += timedelta(days=1)

        na_janela = []
        for doc in docs_by_key.values():
            lt = self._parse_local_time(doc.get("local_time"))
            if lt is not None and start <= lt <= end:
                na_janela.append(doc)
        return self._summarize_docs(na_janela)

    @staticmethod
    def _as_lisbon(iso: str) -> datetime:
        """ISO 8601 → datetime aware no fuso de Lisboa. Sem tz no texto assume-se
        já em hora de Lisboa; com tz (ex.: o `opened_at` em UTC) converte-se."""
        dt = datetime.fromisoformat(iso)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=_LISBON)
        return dt.astimezone(_LISBON)

    @staticmethod
    def _parse_local_time(local_time: Any) -> Optional[datetime]:
        """`local_time` do Vendus ("YYYY-MM-DD HH:MM:SS", hora de Lisboa) → datetime
        aware em Lisboa. Devolve None se estiver ausente/malformado (a FS é então
        ignorada na janela — nunca rebenta o fecho)."""
        s = str(local_time or "").strip()
        if len(s) < 19:
            return None
        try:
            naive = datetime.strptime(s[:19], "%Y-%m-%d %H:%M:%S")
        except ValueError:
            return None
        return naive.replace(tzinfo=_LISBON)

    def _summarize_docs(self, docs: list) -> dict:
        """Resume uma lista de FS já filtradas: total, repartição por forma de
        pagamento e detalhe por fatura. Partilhado por `app_sales_summary` (por
        dia) e `app_sales_summary_window` (por janela) — a MESMA forma de saída."""
        by_method: dict = {}
        total = 0.0
        invoices = []
        for d in docs:
            gross = float(d.get("amount_gross") or 0)
            total = round(total + gross, 2)
            pays = d.get("payments") or []
            method = "Sem pagamento"
            if pays:
                for p in pays:
                    title = (p.get("title") or "Outro").strip() or "Outro"
                    amt = float(p.get("amount") or 0)
                    cur = by_method.setdefault(title, {"count": 0, "total": 0.0})
                    cur["total"] = round(cur["total"] + amt, 2)
                # 1 fatura = 1 forma de pagamento (contamos o documento uma vez)
                method = (pays[0].get("title") or "Outro").strip() or "Outro"
                by_method[method]["count"] += 1
            else:
                cur = by_method.setdefault("Sem pagamento", {"count": 0, "total": 0.0})
                cur["total"] = round(cur["total"] + gross, 2)
                cur["count"] += 1

            # Rótulo da conta a partir do external_reference: "mesa-N[-rodizio]-ts"
            ref = str(d.get("external_reference") or "")
            parts = ref.split("-")
            if len(parts) >= 2 and parts[0] == "mesa" and parts[1].isdigit():
                label = f"Mesa {parts[1]}" + (" (rodízio)" if "rodizio" in parts else "")
            else:
                label = d.get("number") or "Conta"
            lt = str(d.get("local_time") or "")
            hhmm = lt[11:16] if len(lt) >= 16 else ""
            invoices.append({
                "label": label,
                "time": hhmm,
                "amount": round(gross, 2),
                "method": method,
                "number": d.get("number"),
            })

        invoices.sort(key=lambda x: x["time"])
        return {
            "total": round(total, 2),
            "by_method": by_method,
            "count": len(docs),
            "invoices": invoices,
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

    # ---- Registador: movimentos de caixa (abrir/fechar/entrada/saída) ----
    def register_movement(self, operation: str, mtype: str = "NU", amount: float = 0,
                          obs: Optional[str] = None, output: Optional[str] = None) -> dict:
        """Movimento de caixa no registador Vendus: `operation` é
        'open'/'close'/'in'/'out', `mtype` a forma ('NU' = numerário). NÃO usa
        `_request` — este endpoint REJEITA o campo `mode` (403) que `_request`
        injeta sempre em todos os POSTs. Chamada crua via `self._http` (mesmo
        cliente httpx, já com base_url + auth). `output='escpos'` em 'close'
        devolve o talão Z já em ESC/POS (base64) no campo 'output' da resposta."""
        if self._cfg.register_id is None:
            raise VendusError("register_id não configurado")
        body: dict = {"operation": operation, "type": mtype, "amount": round(float(amount), 2)}
        if obs:
            body["obs"] = obs
        if output:
            body["output"] = output
        resp = self._http.request("POST", f"registers/{self._cfg.register_id}/movements/", json=body)
        if resp.status_code >= 400:
            raise VendusHTTPError(resp.status_code, resp.text)
        return resp.json() if resp.content else {}

    def register_status(self) -> Optional[str]:
        """Estado atual do registador Vendus ('open'/'close'). Usado antes de
        abrir a caixa da app para não tentar reabrir um registador já aberto
        (ex.: reaberto manualmente na app do Vendus)."""
        if self._cfg.register_id is None:
            raise VendusError("register_id não configurado")
        resp = self._http.request("GET", f"registers/{self._cfg.register_id}/")
        if resp.status_code >= 400:
            raise VendusHTTPError(resp.status_code, resp.text)
        data = resp.json() if resp.content else {}
        return (data or {}).get("status")
