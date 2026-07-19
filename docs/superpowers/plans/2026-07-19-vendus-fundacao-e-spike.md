# Plano A — Fundação Vendus + Spike de validação

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Construir e testar a biblioteca-cliente do Vendus no backend (config + cliente HTTP tipado) e correr o **spike** que valida as semânticas não documentadas do Vendus (append de mesa, POS↔API, fecho), decidindo o desenho dos fluxos.

**Architecture:** Um pacote novo e isolado `backend/vendus/` com uma classe `VendusClient` sobre `httpx`, testável com `httpx.MockTransport` (sem Vendus vivo). Autenticação HTTP Basic (API key como username, password vazia). Consciente do rate-limit. Config **fail-closed** (sem `VENDUS_API_KEY` os métodos recusam, à imagem do `JWT_SECRET`). O spike é um script à parte que usa esta biblioteca contra a conta real em `mode:"tests"`.

**Tech Stack:** Python 3.11+, FastAPI 0.110, Pydantic 2.x, `httpx` (novo), `pytest` (novo, dev), MongoDB (motor).

## Global Constraints

- **Base de código:** trabalhar na branch `feat/vendus-integracao` (a partir de `migracao-hostinger`). **Não** tocar em `main` (é a versão Emergent viva na pizzaria).
- **Vendus API:** base URL default `https://www.vendus.pt/ws/v1.1/`; **HTTP Basic**, API key como *username*, password vazia; **JSON** apenas; rate-limit ~**100 créditos / 20s** (headers `Rate-Limit-Limit`/`Remaining`/`Reset`); campo `mode` = `"tests"` | `"normal"`.
- **Segredos:** `VENDUS_API_KEY` vive **só** no backend (`backend/.env`), nunca no frontend. Adicionar ao `backend/.env.example` (com valor de exemplo vazio).
- **Fail-closed:** sem `VENDUS_API_KEY`, `VendusConfig.load()` levanta `RuntimeError` (padrão igual ao `JWT_SECRET`, server.py:39-44).
- **Documentos de mesa:** tipo `DC` (Consulta de Mesa). Fatura final: `FT`/`FR`/`FS` (a app **não** fatura).
- **Estilo:** módulos pequenos e focados; nomes e comentários em PT-PT como o resto do `server.py`.

---

## Roadmap (família de planos)

| Plano | Âmbito | Depende de |
|-------|--------|-----------|
| **A (este)** | Spike + biblioteca-cliente Vendus (config, client, testes) | — |
| B | Modelo de dados (campos de mapeamento) + UI de mapeamento (AdminMenu/AdminTables) + endpoints proxy | A |
| C | Fluxos: pedido→DC, "ver conta" on-demand, fecho por polling, kill-switch, remover relatórios | **resultado do spike (A)** |
| D | APK Android de impressão (backend formata / APK relé, routing por categoria) | B |

Este plano entrega **A**. No fim, o resultado do spike decide/afinar o Plano C.

---

## Ficheiros criados/modificados neste plano

- **Criar:** `backend/vendus/__init__.py` — exporta `VendusClient`, `VendusConfig` e as exceções.
- **Criar:** `backend/vendus/config.py` — `VendusConfig` (carrega env, fail-closed).
- **Criar:** `backend/vendus/errors.py` — exceções tipadas.
- **Criar:** `backend/vendus/client.py` — `VendusClient` (transporte, auth, rate-limit, métodos de recurso).
- **Criar:** `backend/tests/vendus/__init__.py` e `backend/tests/vendus/test_config.py`, `test_client.py`.
- **Criar:** `backend/scripts/vendus_spike.py` — script do spike (descartável, mas fica versionado como evidência).
- **Criar:** `docs/superpowers/specs/2026-07-19-vendus-spike-resultados.md` — resultados do spike (preenchido ao correr).
- **Modificar:** `backend/requirements.txt` — adicionar `httpx` (runtime) e `pytest` (dev).
- **Modificar:** `backend/.env.example` — adicionar as variáveis Vendus.

---

## Fase 0 — Spike de validação (investigação, com gate de decisão)

> **Natureza:** isto **não** é TDD — é uma investigação empírica contra a conta real em `mode:"tests"`. Requer a `VENDUS_API_KEY` e o módulo de restauração ativo. O "teste" é o **registo dos resultados** e a **decisão** que ele desbloqueia.

### Task 0: Correr o spike e registar resultados

**Files:**
- Create: `backend/scripts/vendus_spike.py`
- Create: `docs/superpowers/specs/2026-07-19-vendus-spike-resultados.md`

> ⚠️ **Pré-requisito de execução:** exige `VENDUS_API_KEY` (Configuração > Utilizadores > Opções > API no backoffice Vendus) e que existam salas/mesas configuradas. Corre sempre com `VENDUS_MODE=tests`.

- [ ] **Step 1: Escrever o script do spike**

```python
# backend/scripts/vendus_spike.py
"""
Spike de validação da API Vendus (mode:tests) — responde às perguntas que a
documentação NÃO responde, antes de comprometer a arquitetura dos fluxos.

Uso:
    VENDUS_API_KEY=xxx VENDUS_MODE=tests \
    VENDUS_REGISTER_ID=123 python backend/scripts/vendus_spike.py

NÃO gera documentos fiscais (mode=tests). NÃO fatura automaticamente
(o passo de fecho é manual, para evitar efeitos colaterais).
"""
import os
import sys
import json
import base64
import httpx

BASE = os.environ.get("VENDUS_BASE_URL", "https://www.vendus.pt/ws/v1.1/").rstrip("/") + "/"
KEY = os.environ.get("VENDUS_API_KEY")
MODE = os.environ.get("VENDUS_MODE", "tests")
REGISTER_ID = os.environ.get("VENDUS_REGISTER_ID")

if not KEY:
    sys.exit("VENDUS_API_KEY em falta.")
if MODE != "tests":
    sys.exit("Recusado: corre este spike apenas com VENDUS_MODE=tests.")

auth = (KEY, "")  # Basic: key como username, password vazia


def _get(path, **params):
    r = httpx.get(BASE + path, auth=auth, params=params, timeout=30)
    r.raise_for_status()
    return r.json()


def _post(path, body):
    body = {**body, "mode": MODE}
    r = httpx.post(BASE + path, auth=auth, json=body, timeout=30)
    print(f"  POST {path} -> {r.status_code}")
    if r.status_code >= 400:
        print("  ERRO:", r.text[:500])
    r.raise_for_status()
    return r.json()


print("== 1) Salas e mesas disponíveis ==")
rooms = _get("rooms/")
print(json.dumps(rooms, ensure_ascii=False, indent=2)[:1000])
if not rooms:
    sys.exit("Sem salas — ativa o módulo de restauração e configura salas/mesas.")
room_id = rooms[0]["id"]
tables = _get("tables/", parent=room_id)
print(json.dumps(tables, ensure_ascii=False, indent=2)[:1000])
if not tables:
    sys.exit("Sem mesas na primeira sala.")
table_id = tables[0]["id"]
print(f"  -> a usar sala {room_id}, mesa {table_id}")

base_doc = {
    "type": "DC",
    "rest_room": room_id,
    "rest_table": table_id,
    "occupation": 1,
}
if REGISTER_ID:
    base_doc["register_id"] = int(REGISTER_ID)

print("\n== 2) APPEND: dois POST DC na mesma mesa ==")
d1 = _post("documents/", {**base_doc, "external_reference": "spike-1",
           "items": [{"title": "SPIKE Item A", "qty": 1, "gross_price": 1.00, "tax_id": "NOR"}]})
print("  doc1 id:", d1.get("id"), "number:", d1.get("number"))
d2 = _post("documents/", {**base_doc, "external_reference": "spike-2",
           "items": [{"title": "SPIKE Item B", "qty": 1, "gross_price": 2.00, "tax_id": "NOR"}]})
print("  doc2 id:", d2.get("id"), "number:", d2.get("number"))
print(f"  >>> MESMO documento? {d1.get('id') == d2.get('id')}  (id1={d1.get('id')} id2={d2.get('id')})")

print("\n== 3) LER a conta da mesa (documentos DC detalhados de hoje) ==")
open_docs = _get("documents/", type="DC", view="detailed")
mine = [d for d in open_docs if str(d.get("rest_table")) == str(table_id)]
print(f"  DC para a mesa {table_id}: {len(mine)} documento(s)")
for d in mine:
    print("   -", d.get("id"), "itens:", len(d.get("items", []) or []),
          "total:", d.get("amount_gross") or d.get("amount"))

print("\n== 4) PASSOS MANUAIS (registar à mão no doc de resultados) ==")
print("  a) No POS do Vendus, adiciona 1 item à MESMA mesa. Re-corre este spike e")
print("     confirma se o item aparece no MESMO documento DC (secção 3).")
print("  b) No POS, fatura a mesa (FT/FR). Depois corre:")
print(f"     GET documents/?type=DC&view=detailed  -> a mesa {table_id} ainda tem DC aberto?")
print("     E confirma se surge um FT/FR para a mesa (deteção de fecho por polling).")
print("\nSpike terminado. Preenche docs/superpowers/specs/2026-07-19-vendus-spike-resultados.md")
```

- [ ] **Step 2: Criar o documento de resultados (a preencher ao correr)**

```markdown
# Resultados do Spike Vendus — 2026-07-19

> Preenchido ao correr `backend/scripts/vendus_spike.py` com VENDUS_MODE=tests.

## 1. Salas/mesas usadas
- Sala: `<id>` · Mesa: `<id>` · Register: `<id/none>`

## 2. Append (R3-a) — dois POST DC na mesma mesa
- doc1 id: `<...>` · doc2 id: `<...>`
- **MESMO documento?** `SIM | NÃO`
- Conclusão: as linhas **[somam no mesmo DC] / [criam DCs separados]**.

## 3. POS ↔ API (R3-b) — item metido à mão no POS
- Apareceu no MESMO documento que a app criou? `SIM | NÃO`
- Conclusão: adições manuais **[são lidas pela app] / [ficam noutro documento]**.

## 4. Fecho (R3-c) — faturar no POS
- Após FT/FR, a mesa deixou de ter DC aberto? `SIM | NÃO`
- O FT/FR é visível por `GET /documents?since=hoje`? `SIM | NÃO`
- Conclusão: fecho **[detetável por polling] / [não detetável]**.

## 5. Campos úteis observados
- `tables` reflete estado ocupada/livre? `SIM(campo=...) | NÃO`
- Campo do total do DC: `amount_gross | amount | outro=...`
- `tax_id` esperado para os itens: `<...>`

## DECISÃO
- [ ] **Cenário "SOMAM"** (2-a SIM e 3 SIM) → Plano C segue o **caminho principal** (a app abre/segue 1 DC por mesa; conta = ler esse DC).
- [ ] **Cenário "SEPARAM"** → Plano C usa **reconciliação** (listar DC do dia por `rest_table`, agregar; usar `external_reference` para reconhecer os da app).
```

- [ ] **Step 3: Correr o spike**

Run: `cd backend && VENDUS_API_KEY=<key> VENDUS_MODE=tests VENDUS_REGISTER_ID=<id> python scripts/vendus_spike.py`
Expected: imprime salas/mesas, os dois POST (status 200/201), e a leitura dos DC. Sem erros HTTP.

- [ ] **Step 4: Registar resultados e decidir**

Preencher `2026-07-19-vendus-spike-resultados.md` e marcar a **DECISÃO** (Somam vs Separam). Este resultado é a entrada do Plano C.

- [ ] **Step 5: Commit**

```bash
git add backend/scripts/vendus_spike.py docs/superpowers/specs/2026-07-19-vendus-spike-resultados.md
git commit -m "spike(vendus): valida semanticas de mesa (append/POS/fecho) em mode:tests"
```

---

## Fase 1 — Biblioteca-cliente Vendus (backend, TDD)

### Task 1: Dependências + config fail-closed

**Files:**
- Modify: `backend/requirements.txt`
- Modify: `backend/.env.example`
- Create: `backend/vendus/__init__.py`
- Create: `backend/vendus/errors.py`
- Create: `backend/vendus/config.py`
- Create: `backend/tests/vendus/__init__.py`
- Create: `backend/tests/vendus/test_config.py`

**Interfaces:**
- Produces:
  - `VendusConfig` (dataclass) com campos `api_key: str`, `base_url: str`, `mode: str`, `register_id: Optional[int]`.
  - `VendusConfig.load(env: Mapping[str, str]) -> VendusConfig` — **fail-closed**: sem `VENDUS_API_KEY` levanta `RuntimeError`. `base_url` default `https://www.vendus.pt/ws/v1.1/`, `mode` default `"tests"`.
  - Exceções: `VendusError`, `VendusRateLimited(VendusError)`, `VendusUnavailable(VendusError)`, `VendusHTTPError(VendusError)`.

- [ ] **Step 1: Escrever o teste que falha**

```python
# backend/tests/vendus/test_config.py
import pytest
from vendus.config import VendusConfig

def test_load_fail_closed_sem_api_key():
    with pytest.raises(RuntimeError):
        VendusConfig.load({})

def test_load_defaults():
    cfg = VendusConfig.load({"VENDUS_API_KEY": "abc"})
    assert cfg.api_key == "abc"
    assert cfg.base_url == "https://www.vendus.pt/ws/v1.1/"
    assert cfg.mode == "tests"
    assert cfg.register_id is None

def test_load_overrides():
    cfg = VendusConfig.load({
        "VENDUS_API_KEY": "abc",
        "VENDUS_BASE_URL": "https://www.vendus.es/ws/v1.1",
        "VENDUS_MODE": "normal",
        "VENDUS_REGISTER_ID": "42",
    })
    assert cfg.base_url == "https://www.vendus.es/ws/v1.1/"  # normaliza trailing slash
    assert cfg.mode == "normal"
    assert cfg.register_id == 42
```

- [ ] **Step 2: Correr e verificar que falha**

Run: `cd backend && python -m pytest tests/vendus/test_config.py -v`
Expected: FAIL com `ModuleNotFoundError: No module named 'vendus.config'`.

- [ ] **Step 3: Implementar o mínimo**

```python
# backend/vendus/errors.py
class VendusError(Exception):
    """Erro base da integração Vendus."""

class VendusRateLimited(VendusError):
    """429 / créditos de rate-limit esgotados."""

class VendusUnavailable(VendusError):
    """Vendus inacessível (timeout/conexão/5xx)."""

class VendusHTTPError(VendusError):
    """Resposta HTTP de erro (4xx não-429)."""
    def __init__(self, status_code: int, body: str):
        self.status_code = status_code
        self.body = body
        super().__init__(f"Vendus HTTP {status_code}: {body[:300]}")
```

```python
# backend/vendus/config.py
from __future__ import annotations
from dataclasses import dataclass
from typing import Mapping, Optional

_DEFAULT_BASE = "https://www.vendus.pt/ws/v1.1/"

@dataclass(frozen=True)
class VendusConfig:
    api_key: str
    base_url: str
    mode: str
    register_id: Optional[int]

    @staticmethod
    def load(env: Mapping[str, str]) -> "VendusConfig":
        api_key = env.get("VENDUS_API_KEY", "").strip()
        if not api_key:
            raise RuntimeError(
                "VENDUS_API_KEY em falta. Defina-a em backend/.env "
                "(Vendus: Configuracao > Utilizadores > Opcoes > API)."
            )
        base = (env.get("VENDUS_BASE_URL") or _DEFAULT_BASE).rstrip("/") + "/"
        mode = env.get("VENDUS_MODE") or "tests"
        reg = env.get("VENDUS_REGISTER_ID")
        return VendusConfig(
            api_key=api_key,
            base_url=base,
            mode=mode,
            register_id=int(reg) if reg else None,
        )
```

```python
# backend/vendus/__init__.py
from .config import VendusConfig
from .errors import (
    VendusError, VendusRateLimited, VendusUnavailable, VendusHTTPError,
)
__all__ = [
    "VendusConfig", "VendusError", "VendusRateLimited",
    "VendusUnavailable", "VendusHTTPError",
]
```

```python
# backend/tests/vendus/__init__.py
# (vazio — marca o pacote de testes)
```

Em `backend/requirements.txt`, na secção de HTTP, acrescentar:
```
# Cliente HTTP (integração Vendus)
httpx>=0.27,<0.28
```
E numa nova secção de dev/testes:
```
# Testes
pytest>=8.0,<9
```

Em `backend/.env.example`, acrescentar:
```
# ---- Integração Vendus ----
VENDUS_API_KEY=
VENDUS_BASE_URL=https://www.vendus.pt/ws/v1.1/
VENDUS_MODE=tests
VENDUS_REGISTER_ID=
```

- [ ] **Step 4: Instalar deps e correr o teste**

Run: `cd backend && pip install "httpx>=0.27,<0.28" "pytest>=8.0,<9" && python -m pytest tests/vendus/test_config.py -v`
Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add backend/vendus backend/tests/vendus backend/requirements.txt backend/.env.example
git commit -m "feat(vendus): config fail-closed + erros tipados + deps (httpx/pytest)"
```

---

### Task 2: `VendusClient` — transporte, auth, rate-limit

**Files:**
- Create: `backend/vendus/client.py`
- Modify: `backend/vendus/__init__.py` (exportar `VendusClient`)
- Create: `backend/tests/vendus/test_client.py`

**Interfaces:**
- Consumes: `VendusConfig`, exceções de `errors.py`.
- Produces:
  - `class VendusClient` construído com `VendusClient(config: VendusConfig, transport: httpx.BaseTransport | None = None)` (o `transport` injetável permite testes com `httpx.MockTransport`).
  - Método privado `_request(method: str, path: str, *, params=None, json=None) -> Any` que:
    - usa Basic auth `(api_key, "")`;
    - injeta `mode` no corpo dos POST;
    - mapeia `429` → `VendusRateLimited`, timeouts/conexão/5xx → `VendusUnavailable`, outros 4xx → `VendusHTTPError`;
    - devolve JSON decodificado.

- [ ] **Step 1: Escrever o teste que falha**

```python
# backend/tests/vendus/test_client.py
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
    def handler(request): return httpx.Response(429, json={"errors": ["rate"]})
    with pytest.raises(VendusRateLimited):
        _client(handler)._request("GET", "documents/")

def test_5xx_levanta_unavailable():
    def handler(request): return httpx.Response(503, text="down")
    with pytest.raises(VendusUnavailable):
        _client(handler)._request("GET", "documents/")

def test_4xx_levanta_http_error():
    def handler(request): return httpx.Response(400, text="bad")
    with pytest.raises(VendusHTTPError):
        _client(handler)._request("GET", "documents/")
```

- [ ] **Step 2: Correr e verificar que falha**

Run: `cd backend && python -m pytest tests/vendus/test_client.py -v`
Expected: FAIL com `ModuleNotFoundError: No module named 'vendus.client'`.

- [ ] **Step 3: Implementar o mínimo**

```python
# backend/vendus/client.py
from __future__ import annotations
from typing import Any, Optional
import httpx
from .config import VendusConfig
from .errors import VendusRateLimited, VendusUnavailable, VendusHTTPError

class VendusClient:
    """Cliente HTTP para a API Vendus (v1.1). Basic auth com a API key
    como username. `transport` injetável para testes."""

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

    def _request(self, method: str, path: str, *, params: dict | None = None,
                 json: dict | None = None) -> Any:
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
```

Atualizar `backend/vendus/__init__.py`:
```python
from .config import VendusConfig
from .client import VendusClient
from .errors import (
    VendusError, VendusRateLimited, VendusUnavailable, VendusHTTPError,
)
__all__ = [
    "VendusConfig", "VendusClient", "VendusError", "VendusRateLimited",
    "VendusUnavailable", "VendusHTTPError",
]
```

- [ ] **Step 4: Correr e verificar que passa**

Run: `cd backend && python -m pytest tests/vendus/test_client.py -v`
Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add backend/vendus/client.py backend/vendus/__init__.py backend/tests/vendus/test_client.py
git commit -m "feat(vendus): VendusClient com Basic auth, mode e mapeamento de erros/rate-limit"
```

---

### Task 3: Métodos de recurso (produtos, salas, mesas, documentos)

**Files:**
- Modify: `backend/vendus/client.py`
- Modify: `backend/tests/vendus/test_client.py`

**Interfaces:**
- Consumes: `VendusClient._request`.
- Produces (métodos de `VendusClient`):
  - `list_products(**filters) -> list[dict]` → `GET products/`
  - `list_categories() -> list[dict]` → `GET products/categories/`
  - `list_rooms() -> list[dict]` → `GET rooms/`
  - `list_tables(room_id: int) -> list[dict]` → `GET tables/?parent=<room_id>`
  - `create_table_order(*, room_id, table_id, occupation, items, external_reference) -> dict` → `POST documents/` (`type:"DC"`, mais `register_id` se existir na config)
  - `get_document(doc_id: int) -> dict` → `GET documents/{id}/?view=detailed`
  - `list_open_table_docs(since: str) -> list[dict]` → `GET documents/?type=DC&view=detailed&since=<since>`

- [ ] **Step 1: Escrever o teste que falha**

```python
# acrescentar a backend/tests/vendus/test_client.py
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
    _client(handler)  # noqa
    client = VendusClient(CFG, transport=httpx.MockTransport(handler))
    rows = client.list_tables(room_id=5)
    assert rows[0]["id"] == 2
    assert "parent=5" in seen["url"]
```

- [ ] **Step 2: Correr e verificar que falha**

Run: `cd backend && python -m pytest tests/vendus/test_client.py -k "table_order or list_tables" -v`
Expected: FAIL com `AttributeError: 'VendusClient' object has no attribute 'create_table_order'`.

- [ ] **Step 3: Implementar o mínimo**

```python
# acrescentar dentro de class VendusClient (backend/vendus/client.py)

    # ---- Produtos / catálogo ----
    def list_products(self, **filters) -> list[dict]:
        return self._request("GET", "products/", params=filters) or []

    def list_categories(self) -> list[dict]:
        return self._request("GET", "products/categories/") or []

    # ---- Salas / mesas ----
    def list_rooms(self) -> list[dict]:
        return self._request("GET", "rooms/") or []

    def list_tables(self, room_id: int) -> list[dict]:
        return self._request("GET", "tables/", params={"parent": room_id}) or []

    # ---- Documentos (conta de mesa) ----
    def create_table_order(self, *, room_id: int, table_id: int, occupation: int,
                           items: list[dict], external_reference: str) -> dict:
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

    def list_open_table_docs(self, since: str) -> list[dict]:
        return self._request(
            "GET", "documents/",
            params={"type": "DC", "view": "detailed", "since": since},
        ) or []
```

- [ ] **Step 4: Correr e verificar que passa**

Run: `cd backend && python -m pytest tests/vendus/test_client.py -v`
Expected: todos passam (6+).

- [ ] **Step 5: Commit**

```bash
git add backend/vendus/client.py backend/tests/vendus/test_client.py
git commit -m "feat(vendus): metodos de recurso (produtos, salas, mesas, documentos DC)"
```

---

## Self-Review (feito ao escrever)

**Spec coverage:** Este plano cobre a §5.1 (camada de serviço Vendus: config, client, métodos `create_table_order`/`get_document`/`list_open_table_docs`/`list_products`/`list_categories`/`list_rooms`/`list_tables`) e a **§4 (Fase 0 — spike)** por inteiro. As §5.2–5.7 (modelo de dados, fluxos, kill-switch, remoção de relatórios) e a Frente B ficam para os Planos B/C/D do roadmap — decisão consciente: os fluxos dependem do resultado do spike (§4/§8), pelo que não se escreve código especulativo antes dele.

**Placeholder scan:** sem "TODO/TBD". O único conteúdo "a preencher" é o **documento de resultados do spike**, que é o *output* esperado da investigação, não um passo de código por definir.

**Type consistency:** `VendusConfig.load`, `VendusClient(config, transport=...)`, `_request(method, path, *, params, json)` e os métodos de recurso são usados com as mesmas assinaturas nos testes e na implementação. As exceções (`VendusRateLimited/Unavailable/HTTPError`) são as mesmas em `errors.py`, `client.py` e testes.

---

## Notas de execução

- Correr os testes: `cd backend && python -m pytest tests/vendus/ -v` (não precisa de Vendus vivo — tudo mockado).
- O **spike (Task 0)** é o único passo que precisa da `VENDUS_API_KEY` real e do módulo de restauração ativo; corre sempre em `mode:tests`.
- Não fazer deploy nada disto ainda — é fundação. O `main` (Emergent vivo) não é tocado.
