# Ligar produtos ao Vendus — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A fatura passa a identificar cada linha pelo artigo oficial do Vendus (via `id`), para o Vendus reutilizar o artigo em vez de criar um duplicado a cada fatura.

**Architecture:** Cada produto da app ganha um `vendus_id` (id do artigo oficial). Um ecrã no admin casa produtos↔artigos por nome (o dono confirma) e grava o `vendus_id`. Na emissão, `line_vendus` passa a incluir `{"id": vendus_id}` na linha (resolvido por `product_id`, como já se faz com o IVA). O tamanho/preço continuam na linha.

**Tech Stack:** FastAPI + Motor (Mongo), React (CRA/craco), pytest (síncrono, sem pytest-asyncio).

## Global Constraints

- Textos visíveis ao utilizador em **PT-PT**.
- Helpers puros vivem em `backend/pos/`; testes síncronos, correr com `cd backend && .venv/bin/python -m pytest <caminho> -v`.
- **Chave de ligação = `id` do artigo Vendus** (confirmado no spike, Task 1). Guardar em `Product.vendus_id`.
- **Emissão da FS não muda de comportamento** (idempotência, 1-só-FS, totais, `external_reference`): só se acrescenta `{"id": ...}` à linha quando o produto está ligado.
- Artigo oficial = referência que **NÃO** termina no padrão auto-gerado `-<6+ dígitos>`.
- Frontend: node fora do PATH — `export PATH="$HOME/.local/node/bin:$HOME/Library/pnpm:$PATH"` antes de `cd frontend && npx craco build`.
- Fora de âmbito: itens sintéticos do rodízio (adulto/criança/taxa) — continuam texto livre; apagar o lixo antigo; criar artigos em falta.
- Fluxo git: ramo `matheus-vendus-ligar-produtos` (já criado) → merge no `main` → deploy.

---

### Task 1: Spike de validação (GATE) — o Vendus reutiliza por `id`?

**Feito pelo CONTROLADOR (não subagente):** corre contra o Vendus real, em modo `tests`, e exige julgamento. As tasks 2-5 só avançam depois deste gate passar.

**Objetivo:** confirmar que, ao emitir um documento cujo item traz o `id` de um artigo oficial (com preço/título próprios), o Vendus **reutiliza** esse artigo e **não cria** um novo.

- [ ] **Step 1: Contar artigos e escolher um oficial**

No servidor, contar o total de artigos e escolher um oficial (ex.: "Pizza Calabresa") e o seu `id`:
```bash
ssh root@185.158.107.3 'docker exec pizzaria-backend-1 python -c "
from server import _vendus_client
c=_vendus_client()
try:
    todos=[]; page=1
    while page<=80:
        p=c.list_products(page=page, per_page=100)
        if not p: break
        todos+=p
        if len(p)<100: break
        page+=1
    print(\"total antes:\", len(todos))
    alvo=[x for x in todos if x.get(\"title\")==\"Pizza Calabresa\"][:1]
    print(\"alvo:\", alvo)
finally: c.close()
"'
```

- [ ] **Step 2: Emitir um documento de teste com o `id` do artigo**

Emitir um documento **em modo `tests`** (não fiscal) com um item `{"id": <id do alvo>, "qty": 1, "gross_price": 13.90, "title": "Calabresa (Média)", "tax_id": "INT"}` e um pagamento. Usar o cliente Vendus com `mode=tests` explícito (o registador da app). Guardar a resposta.

- [ ] **Step 3: Contar artigos outra vez e decidir**

Repetir a contagem do Step 1.
- Se **total_depois == total_antes** e a resposta do documento mostra o item ligado ao `id` do alvo → **`id` reutiliza. GATE PASSA.** Prosseguir.
- Se aumentou → testar o mesmo com `reference` em vez de `id`. Se `reference` reutilizar, o plano passa a guardar/enviar `reference` (trocar `vendus_id`→`vendus_reference` nas tasks seguintes).
- Se nenhum reutilizar → **PARAR** e reportar ao dono (o design precisa de ser repensado).

- [ ] **Step 4: Registar o resultado**

Anotar no relatório: chave que funciona (`id`/`reference`), se o override de preço/título é aceite, e a contagem antes/depois. Nenhum commit (spike não altera o repo).

---

### Task 2: Helper puro de casamento produto↔artigo

**Files:**
- Create: `backend/pos/vendus_match.py`
- Test: `backend/tests/pos/test_vendus_match.py`

**Interfaces:**
- Produces: `is_official(reference) -> bool`; `norm(name) -> str`; `match_products(app_products, vendus_articles) -> list[dict]` onde cada dict é `{"product_id", "product_name", "app_price", "match": {"id","title","reference","price"}|None, "status": "matched"|"none"}`.

- [ ] **Step 1: Escrever o teste que falha**

Criar `backend/tests/pos/test_vendus_match.py`:
```python
"""Casamento produto da app -> artigo oficial do Vendus (por nome normalizado)."""
from pos.vendus_match import is_official, norm, match_products


def test_is_official_exclui_lixo_auto_gerado():
    assert is_official("Pizza Calabresa") is True
    assert is_official("V5-Q231-26073157") is False
    assert is_official("VAGU143-26072239") is False


def test_norm_remove_pizza_acentos_tamanho():
    assert norm("Calabresa") == norm("Pizza Calabresa")
    assert norm("Compal Maracujá") == norm("Compal de Maracuja")


def test_match_casa_por_nome_e_prefere_nao_app():
    app = [{"id": "p1", "name": "Calabresa", "base_price": 13.9}]
    vendus = [
        {"id": 1, "title": "Pizza Calabresa App", "reference": "Pizza Calabresa App", "gross_price": 18.4},
        {"id": 2, "title": "Pizza Calabresa", "reference": "Pizza Calabresa", "gross_price": 13.9},
        {"id": 3, "title": "V5-Q231-26073157", "reference": "V5-Q231-26073157", "gross_price": 0},
    ]
    out = match_products(app, vendus)
    assert len(out) == 1
    assert out[0]["status"] == "matched"
    assert out[0]["match"]["id"] == 2            # preferiu o SEM "App"
    assert out[0]["app_price"] == 13.9
    assert out[0]["match"]["price"] == 13.9


def test_match_sem_correspondencia():
    app = [{"id": "p9", "name": "Produto Inexistente", "base_price": 5}]
    vendus = [{"id": 1, "title": "Pizza Calabresa", "reference": "Pizza Calabresa", "gross_price": 13.9}]
    out = match_products(app, vendus)
    assert out[0]["status"] == "none"
    assert out[0]["match"] is None
```

- [ ] **Step 2: Correr para confirmar que falha**

Run: `cd backend && .venv/bin/python -m pytest tests/pos/test_vendus_match.py -v`
Expected: FAIL (`ModuleNotFoundError: No module named 'pos.vendus_match'`).

- [ ] **Step 3: Implementar o helper**

Criar `backend/pos/vendus_match.py`:
```python
"""Casamento puro produto-da-app -> artigo oficial do Vendus, por nome.

Um artigo oficial é o que o dono criou (referência limpa); o lixo auto-gerado
pelo Vendus tem uma referência que termina em `-<6+ dígitos>` (timestamp). O
nome normaliza-se para casar "Calabresa" com "Pizza Calabresa": minúsculas, sem
acentos, sem o prefixo "pizza", sem "de/da", sem pontuação, espaços colapsados.
Entre artigos com o mesmo nome, prefere-se o que NÃO é versão "App" (delivery).
Sem I/O."""
import re
import unicodedata

_AUTO_REF = re.compile(r"-\d{6,}$")


def is_official(reference) -> bool:
    ref = str(reference or "")
    return bool(ref) and not _AUTO_REF.search(ref)


def norm(name) -> str:
    s = unicodedata.normalize("NFKD", str(name or "")).encode("ascii", "ignore").decode()
    s = s.lower()
    s = s.replace(" app", " ")            # ignora o sufixo/infixo "App"
    s = re.sub(r"\bpizza\b", " ", s)      # "Pizza Calabresa" ~ "Calabresa"
    s = re.sub(r"\b(de|da|do|das|dos)\b", " ", s)
    s = re.sub(r"[^a-z0-9]+", " ", s)     # tira pontuação/acentos residuais
    return re.sub(r"\s+", " ", s).strip()


def match_products(app_products, vendus_articles) -> list:
    # Índice dos oficiais por nome normalizado; guarda ambos (App e não-App).
    by_norm = {}
    for a in vendus_articles:
        if not is_official(a.get("reference")):
            continue
        by_norm.setdefault(norm(a.get("title")), []).append(a)

    out = []
    for p in app_products:
        cands = by_norm.get(norm(p.get("name")), [])
        # Prefere o que NÃO tem "app" no título original.
        cands = sorted(cands, key=lambda a: 1 if "app" in str(a.get("title", "")).lower() else 0)
        chosen = cands[0] if cands else None
        out.append({
            "product_id": p.get("id"),
            "product_name": p.get("name"),
            "app_price": p.get("base_price"),
            "match": None if not chosen else {
                "id": chosen.get("id"),
                "title": chosen.get("title"),
                "reference": chosen.get("reference"),
                "price": chosen.get("gross_price"),
            },
            "status": "matched" if chosen else "none",
        })
    return out
```

- [ ] **Step 4: Correr para confirmar que passa**

Run: `cd backend && .venv/bin/python -m pytest tests/pos/test_vendus_match.py -v`
Expected: PASS (4 testes).

- [ ] **Step 5: Commit**

```bash
cd ~/dev/pizzaria && git add backend/pos/vendus_match.py backend/tests/pos/test_vendus_match.py
git commit -m "Vendus: helper puro de casamento produto<->artigo oficial (por nome)"
```

---

### Task 3: Modelo `vendus_id` + endpoints de sugestão e gravação

**Files:**
- Modify: `backend/server.py` (Product Create/Update/Response ~288-332; novos endpoints perto dos outros `/admin/...`)
- Test: `backend/tests/pos/test_vendus_link_endpoints.py`

**Interfaces:**
- Consumes: `match_products` (Task 2), `_vendus_client().list_products()`.
- Produces: `Product.vendus_id: Optional[int]`; `GET /admin/vendus/link-suggestions` → `{"suggestions": [ {product_id, product_name, app_price, current_vendus_id, match, status} ], "official_count": int}`; `POST /admin/vendus/link` body `{"links": [{"product_id": str, "vendus_id": int|null}]}` → `{"updated": int}`.

- [ ] **Step 1: Adicionar `vendus_id` ao modelo do produto**

Em `backend/server.py`, acrescentar em `ProductCreate` (após linha 299), `ProductUpdate` (após 315) e `ProductResponse` (após 332), respetivamente:
```python
    vendus_id: Optional[int] = None  # id do artigo oficial no Vendus (ligação da FS)
```

- [ ] **Step 2: Escrever os testes que falham**

Criar `backend/tests/pos/test_vendus_link_endpoints.py`:
```python
"""Endpoints de ligação produtos<->Vendus: sugestões e gravação."""
import asyncio
import pytest
from fastapi import HTTPException

import server
from server import create_token, save_vendus_links, VendusLinkRequest, VendusLink


class _Products:
    def __init__(self, docs):
        self.docs = {d["id"]: d for d in docs}
        self.updates = []
    async def update_one(self, query, update):
        pid = query.get("id")
        if pid in self.docs:
            self.docs[pid].update(update["$set"]); self.updates.append((pid, update["$set"]))
            class R: matched_count = 1
            return R()
        class R: matched_count = 0
        return R()


class _FakeDb:
    def __init__(self, prods):
        self.products = _Products(prods)


def test_save_links_grava_vendus_id(monkeypatch):
    fake = _FakeDb([{"id": "p1", "name": "Calabresa"}])
    monkeypatch.setattr(server, "db", fake)
    admin = create_token("admin-1", "gestor@lenhaebrasa.com")
    body = VendusLinkRequest(links=[VendusLink(product_id="p1", vendus_id=2)])

    async def run():
        return await save_vendus_links(body, authorization=f"Bearer {admin}")
    res = asyncio.run(run())
    assert res["updated"] == 1
    assert fake.products.docs["p1"]["vendus_id"] == 2


def test_save_links_none_desliga(monkeypatch):
    fake = _FakeDb([{"id": "p1", "name": "Calabresa", "vendus_id": 2}])
    monkeypatch.setattr(server, "db", fake)
    admin = create_token("admin-1", "gestor@lenhaebrasa.com")
    body = VendusLinkRequest(links=[VendusLink(product_id="p1", vendus_id=None)])

    async def run():
        return await save_vendus_links(body, authorization=f"Bearer {admin}")
    asyncio.run(run())
    assert fake.products.docs["p1"]["vendus_id"] is None
```

- [ ] **Step 3: Correr para confirmar que falha**

Run: `cd backend && .venv/bin/python -m pytest tests/pos/test_vendus_link_endpoints.py -v`
Expected: FAIL (`ImportError: cannot import name 'save_vendus_links'`).

- [ ] **Step 4: Implementar os modelos e endpoints**

Em `backend/server.py`, junto dos outros `/admin` (a seguir a um endpoint admin existente), acrescentar o import no topo (junto dos `from pos...`):
```python
from pos.vendus_match import match_products
```
e os modelos + endpoints:
```python
class VendusLink(BaseModel):
    product_id: str
    vendus_id: Optional[int] = None

class VendusLinkRequest(BaseModel):
    links: List[VendusLink]


@api_router.get("/admin/vendus/link-suggestions")
async def vendus_link_suggestions(authorization: Optional[str] = Header(None)):
    """Casa cada produto da app com um artigo OFICIAL do Vendus (por nome) e
    devolve as sugestões + preços dos dois lados, para o dono confirmar. Só lê."""
    await get_current_user(authorization)
    app_products = await db.products.find({}, {"_id": 0}).sort("name", 1).to_list(1000)
    c = _vendus_client()
    try:
        arts, page = [], 1
        while page <= 80:
            batch = c.list_products(page=page, per_page=100)
            if not batch:
                break
            arts.extend(batch)
            if len(batch) < 100:
                break
            page += 1
    finally:
        c.close()
    official = [a for a in arts if str(a.get("reference") or "") and not __import__("re").search(r"-\d{6,}$", str(a.get("reference")))]
    sugg = match_products(app_products, arts)
    by_pid = {p["id"]: p for p in app_products}
    for s in sugg:
        s["current_vendus_id"] = by_pid.get(s["product_id"], {}).get("vendus_id")
    return {"suggestions": sugg, "official_count": len(official)}


@api_router.post("/admin/vendus/link")
async def save_vendus_links(body: VendusLinkRequest, authorization: Optional[str] = Header(None)):
    """Grava o `vendus_id` escolhido por produto (None desliga a ligação)."""
    await get_current_user(authorization)
    updated = 0
    for link in body.links:
        res = await db.products.update_one(
            {"id": link.product_id}, {"$set": {"vendus_id": link.vendus_id}}
        )
        updated += res.matched_count
    return {"updated": updated}
```

- [ ] **Step 5: Correr os testes + import + suite pos**

Run: `cd backend && .venv/bin/python -m pytest tests/pos/test_vendus_link_endpoints.py -v`
Expected: PASS (2 testes).

Run: `cd backend && .venv/bin/python -c "import server; print('import ok')" && cd backend && .venv/bin/python -m pytest tests/pos/ -q`
Expected: `import ok` + suite pos verde.

- [ ] **Step 6: Commit**

```bash
cd ~/dev/pizzaria && git add backend/server.py backend/tests/pos/test_vendus_link_endpoints.py
git commit -m "Vendus: campo vendus_id + endpoints de sugestao e gravacao da ligacao"
```

---

### Task 4: A fatura inclui o `id` do artigo ligado

**Files:**
- Modify: `backend/pos/pricing.py` (`line_vendus`, `combine_global`)
- Modify: `backend/server.py` (`close_table` resolução de produtos; `checkout_counter_order`)
- Test: `backend/tests/pos/test_pricing.py` (acrescentar)

**Interfaces:**
- Consumes: nada novo.
- Produces: `line_vendus(item, product_tax_id, default_tax_id, vendus_id=None)` inclui `"id"` na linha quando `vendus_id` é dado; `combine_global` preserva `"id"`.

- [ ] **Step 1: Escrever o teste que falha**

Acrescentar a `backend/tests/pos/test_pricing.py`:
```python
def test_line_vendus_inclui_id_do_artigo():
    from pos.pricing import line_vendus, combine_global
    item = {"product_name": "Calabresa", "quantity": 1, "unit_price": 13.9}
    li = line_vendus(item, "INT", "NOR", vendus_id=2)
    assert li["id"] == 2
    out, _ = combine_global(li, 0)
    assert out["id"] == 2                 # combine_global preserva o id

def test_line_vendus_sem_id_nao_poe_chave():
    from pos.pricing import line_vendus
    li = line_vendus({"product_name": "X", "quantity": 1, "unit_price": 5}, "INT", "NOR")
    assert "id" not in li
```

- [ ] **Step 2: Correr para confirmar que falha**

Run: `cd backend && .venv/bin/python -m pytest tests/pos/test_pricing.py -k id -v`
Expected: FAIL (`line_vendus() got an unexpected keyword argument 'vendus_id'`).

- [ ] **Step 3: Implementar em `pricing.py`**

Em `backend/pos/pricing.py`, na assinatura de `line_vendus` acrescentar o parâmetro e, dentro, incluir o id:
```python
def line_vendus(item: dict, product_tax_id: Optional[str], default_tax_id: str,
                vendus_id: Optional[int] = None) -> dict:
```
Logo depois de construir `line = {...}` (o dict com title/qty/gross_price/tax_id), antes do bloco do desconto, acrescentar:
```python
    if vendus_id is not None:
        line["id"] = vendus_id
```
Em `combine_global`, na linha que copia os campos preservados, acrescentar `"id"`:
```python
    out = {k: li[k] for k in ("id", "title", "qty", "gross_price", "tax_id") if k in li}
```

- [ ] **Step 4: Resolver `vendus_id` por produto no `close_table`**

Em `backend/server.py`, `close_table`, nos DOIS blocos que constroem `tax_by_prod` (~1943-1947 e ~2007-2011), trazer também o `vendus_id`. Substituir cada bloco por (mesma query, mais um campo e um segundo mapa):
```python
        tax_by_prod = {}
        vid_by_prod = {}
        if prod_ids:
            async for p in db.products.find({"id": {"$in": prod_ids}}, {"_id": 0, "id": 1, "vendus_tax_id": 1, "vendus_id": 1}):
                if p.get("vendus_tax_id"):
                    tax_by_prod[p["id"]] = p["vendus_tax_id"]
                if p.get("vendus_id") is not None:
                    vid_by_prod[p["id"]] = p["vendus_id"]
```
E nas chamadas a `line_vendus` dentro do `close_table` (o ramo do rodízio ~1969 e o ramo à-la-carte ~2018-2020), passar o `vendus_id`:
```python
            li, net = combine_global(
                line_vendus(l, tax_by_prod.get(l.get("product_id")), VENDUS_DEFAULT_TAX_ID,
                            vendus_id=vid_by_prod.get(l.get("product_id"))), g_disc)
```
(Os itens sintéticos do rodízio via `_add` NÃO mudam — não têm `product_id`.)

- [ ] **Step 5: Resolver `vendus_id` no `checkout_counter_order` (balcão)**

Em `backend/server.py`, `checkout_counter_order`, antes do loop `for l in order.get("items", [])` que chama `line_vendus`, buscar o `vendus_id` dos produtos do pedido:
```python
    _pids = list({l.get("product_id") for l in order.get("items", []) if l.get("product_id")})
    vid_by_prod = {}
    if _pids:
        async for p in db.products.find({"id": {"$in": _pids}}, {"_id": 0, "id": 1, "vendus_id": 1}):
            if p.get("vendus_id") is not None:
                vid_by_prod[p["id"]] = p["vendus_id"]
```
E na chamada `line_vendus(l, None, VENDUS_DEFAULT_TAX_ID)` desse loop, passar o id:
```python
        li = line_vendus(l, None, VENDUS_DEFAULT_TAX_ID, vendus_id=vid_by_prod.get(l.get("product_id")))
```

- [ ] **Step 6: Correr os testes + import + suite pos**

Run: `cd backend && .venv/bin/python -m pytest tests/pos/test_pricing.py -v`
Expected: PASS (incl. os 2 novos).

Run: `cd backend && .venv/bin/python -c "import server; print('import ok')" && cd backend && .venv/bin/python -m pytest tests/pos/ -q`
Expected: `import ok` + suite pos verde.

- [ ] **Step 7: Commit**

```bash
cd ~/dev/pizzaria && git add backend/pos/pricing.py backend/server.py backend/tests/pos/test_pricing.py
git commit -m "Vendus: fatura inclui o id do artigo ligado (line_vendus + close_table + balcao)"
```

---

### Task 5: Frontend — ecrã "Ligar ao Vendus"

**Files:**
- Modify: `frontend/src/lib/api.js` (nova `vendusLinkAPI`)
- Create: `frontend/src/pages/admin/AdminVendusLink.js`
- Modify: `frontend/src/App.js` (rota) e `frontend/src/components/AdminLayout.js` (item de menu)

**Interfaces:**
- Consumes: `GET /admin/vendus/link-suggestions`, `POST /admin/vendus/link` (Task 3).

- [ ] **Step 1: API no `api.js`**

Em `frontend/src/lib/api.js`, acrescentar:
```javascript
// Ligação de produtos aos artigos do Vendus
export const vendusLinkAPI = {
  suggestions: () => api.get('/admin/vendus/link-suggestions'),
  save: (links) => api.post('/admin/vendus/link', { links }),
};
```

- [ ] **Step 2: Ecrã de ligação**

Criar `frontend/src/pages/admin/AdminVendusLink.js`: carrega `suggestions()`; mostra uma tabela com **Produto (app) · Preço app · Artigo Vendus (seletor) · Preço Vendus · Estado**; o seletor lista os artigos oficiais (obtidos das próprias sugestões — junta todos os `match` distintos e permite escolher/limpar); pré-selecciona o `match.id` sugerido; realça a vermelho os `status: "none"` e quando o preço app ≠ preço Vendus; botão "Guardar ligações" chama `save(links)` com `{product_id, vendus_id}` de cada linha. Segue o estilo dos outros ecrãs admin (AdminLayout, Card, Button, toast). Estado de loading e erro. Usa `vendusLinkAPI`.

- [ ] **Step 3: Rota + menu**

Em `frontend/src/App.js`, acrescentar a rota protegida `/admin/vendus-link` a apontar para `AdminVendusLink` (mesmo padrão das outras rotas admin). Em `frontend/src/components/AdminLayout.js`, acrescentar um item de menu "Ligar Vendus" a apontar para `/admin/vendus-link`.

- [ ] **Step 4: Verificar que compila**

Run: `export PATH="$HOME/.local/node/bin:$HOME/Library/pnpm:$PATH" && cd frontend && npx craco build 2>&1 | tail -15`
Expected: "Compiled successfully".

- [ ] **Step 5: Commit**

```bash
cd ~/dev/pizzaria && git add frontend/src/lib/api.js frontend/src/pages/admin/AdminVendusLink.js frontend/src/App.js frontend/src/components/AdminLayout.js
git commit -m "Backoffice: ecra Ligar ao Vendus (casamento + confirmacao + gravar vendus_id)"
```

---

## Deploy + ligação em produção (fim)

Depois das tasks revistas e verdes + revisão final:
1. Merge no `main` + deploy (rsync + rebuild) + health.
2. **Modo `tests` primeiro:** com `VENDUS_MODE=tests`, o dono usa o ecrã "Ligar ao Vendus", confirma o mapeamento, e emite-se **uma FS de teste** com produtos ligados; contar os artigos do Vendus antes/depois confirma que **não é criado nenhum artigo novo**.
3. Confirmado, ligar em produção (modo normal) e verificar a 1ª FS real.

## Self-review (feito)

- **Cobertura do spec:** spike gate (Task 1) ✓; guardar ligação `vendus_id` (Task 3) ✓; casamento por nome + confirmação (Tasks 2+5, preços lado a lado) ✓; FS usa a ligação (Task 4) ✓; produtos sem correspondência assinalados (`status:"none"`, Tasks 2+5) ✓; lixo não se apaga (fora de âmbito) ✓; verificação em modo tests (Deploy) ✓.
- **Sem placeholders:** código completo (o ecrã da Task 5 é descrito por comportamento — segue os ecrãs admin existentes — por ser UI; a lógica testável está nos helpers/endpoints).
- **Consistência de tipos:** `vendus_id: Optional[int]` (modelo, endpoint, line_vendus, resolvido por product_id no close_table/checkout); `combine_global` preserva `"id"`; `match_products` devolve `match.id` que o ecrã grava via `save([{product_id, vendus_id}])`.
