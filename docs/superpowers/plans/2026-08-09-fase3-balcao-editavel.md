# Fase 3 — Balcão editável depois de imprimir — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Depois de imprimir um pedido de balcão, o operador pode acrescentar/editar/anular linhas e **reimprimir** o pedido completo só para a cozinha (marcado «ATUALIZADO»); a fatura no fim continua a ser **uma só**, com tudo.

**Architecture:** O documento `orders` do balcão já é mutável até ao checkout, e `checkout_counter_order` lê os itens **frescos** — por isso basta um endpoint que substitua os itens e reimprima só a cozinha. A reimpressão usa o padrão `order_snapshot` (não `_enqueue_order_prints`, que imprimiria também um talão de caixa) com uma flag `is_update` que o `format_kitchen` mostra como «PEDIDO ATUALIZADO». No frontend, o balcão deixa de bloquear a edição após imprimir e ganha um botão «Reimprimir pedido»; «Emitir» exige o pedido sincronizado (sem alterações por reimprimir).

**Tech Stack:** FastAPI + Motor (Mongo), React (CRA/craco), pytest (síncrono, fakes de db + `asyncio.run`).

## Global Constraints

- Textos visíveis ao utilizador em **PT-PT**.
- Identidade do operador vem **sempre** do token POS (`get_pos_operator(x_pos_token)`), nunca do corpo.
- **Uma só FS por venda:** o `checkout_counter_order` (inalterado) lê `order.items` frescos com `ext_ref` estável `balcao-{order_id}` + paid-guard + dedup — a atualização de itens NÃO altera isso.
- A reimpressão da atualização é **só cozinha**, via `order_snapshot` (nunca `_enqueue_order_prints`).
- Guards do `/update`: pedido de balcão existe, **não** pago, **não** cancelado, e (como o `create`) caixa aberta; substituição **atómica** (filtro `paid:false`) para fechar a corrida com o checkout.
- Testes POS síncronos; correr com `cd backend && .venv/bin/python -m pytest <caminho> -v`.
- Frontend: node fora do PATH — `export PATH="$HOME/.local/node/bin:$HOME/Library/pnpm:$PATH"` antes de `cd frontend && npx craco build`.
- Fluxo git do grupo: ramo `matheus-pos-fase3` (já criado) → merge no `main` → deploy.

---

### Task 1: Backend — `format_kitchen` mostra "PEDIDO ATUALIZADO"

**Files:**
- Modify: `backend/server.py` (`ESCPOSFormatter.format_kitchen`, ~611)
- Test: `backend/tests/pos/test_kitchen_banner.py`

**Interfaces:**
- Produces: quando o dict do pedido tem `is_update: True`, o talão de cozinha imprime «PEDIDO ATUALIZADO» + «(substitui o pedido anterior)» em vez de «NOVO PEDIDO».

- [ ] **Step 1: Escrever o teste que falha**

Criar `backend/tests/pos/test_kitchen_banner.py`:

```python
"""O talão de cozinha marca as reimpressões de balcão como ATUALIZADO."""
from server import ESCPOSFormatter

BASE = {
    "order_number": 7,
    "source": "balcao",
    "table_number": None,
    "items": [{"product_name": "Pizza", "quantity": 1}],
    "created_at": "2026-08-09T18:00:00+00:00",
}


def test_pedido_novo_diz_novo_pedido():
    out = ESCPOSFormatter().format_kitchen(dict(BASE))
    assert b"NOVO PEDIDO" in out
    assert b"ATUALIZADO" not in out


def test_pedido_atualizado_diz_atualizado_e_substitui():
    out = ESCPOSFormatter().format_kitchen({**BASE, "is_update": True})
    assert b"PEDIDO ATUALIZADO" in out
    assert b"substitui" in out
    assert b"NOVO PEDIDO" not in out
```

- [ ] **Step 2: Correr para confirmar que falha**

Run: `cd backend && .venv/bin/python -m pytest tests/pos/test_kitchen_banner.py -v`
Expected: FAIL (`test_pedido_atualizado_...` — o talão diz sempre "NOVO PEDIDO").

- [ ] **Step 3: Implementar o banner condicional**

Em `backend/server.py`, dentro de `format_kitchen`, o bloco do cabeçalho (~608-613) que hoje é:

```python
        # Header - NEW ORDER alert
        data.extend(self.CENTER)
        data.extend(self.BOLD_ON)
        data.extend(self.DOUBLE_HEIGHT)
        data.extend(self._text("NOVO PEDIDO\n"))
        data.extend(self.NORMAL_SIZE)
        data.extend(self.BOLD_OFF)
```

passa a:

```python
        # Header — NOVO PEDIDO, ou PEDIDO ATUALIZADO nas reimpressões de balcão
        # (Fase 3): o operador acrescentou/editou linhas e reimprimiu; a cozinha
        # deve descartar o talão anterior deste pedido.
        data.extend(self.CENTER)
        data.extend(self.BOLD_ON)
        data.extend(self.DOUBLE_HEIGHT)
        if order.get("is_update"):
            data.extend(self._text("PEDIDO ATUALIZADO\n"))
            data.extend(self.NORMAL_SIZE)
            data.extend(self.BOLD_OFF)
            data.extend(self._text("(substitui o pedido anterior)\n"))
        else:
            data.extend(self._text("NOVO PEDIDO\n"))
            data.extend(self.NORMAL_SIZE)
            data.extend(self.BOLD_OFF)
```

- [ ] **Step 4: Correr para confirmar que passa**

Run: `cd backend && .venv/bin/python -m pytest tests/pos/test_kitchen_banner.py -v`
Expected: PASS (2 testes).

- [ ] **Step 5: Commit**

```bash
cd ~/dev/pizzaria && git add backend/server.py backend/tests/pos/test_kitchen_banner.py
git commit -m "POS balcao: talao de cozinha marca reimpressoes como PEDIDO ATUALIZADO"
```

---

### Task 2: Backend — endpoint `POST /pos/counter/{order_id}/update`

**Files:**
- Modify: `backend/server.py` (novo endpoint a seguir a `cancel_counter_order`, ~3908)
- Test: `backend/tests/pos/test_counter_update.py`

**Interfaces:**
- Consumes: `CounterOrderRequest` (já existe), `build_counter_items`, `get_pos_or_admin`, `get_pos_operator`, `_pos_settings_config`, `VENDUS_DEFAULT_TAX_ID`.
- Produces: `POST /pos/counter/{order_id}/update` — substitui `orders.items`/`total` de um pedido de balcão não pago/não cancelado, reimprime só a cozinha (snapshot `is_update`), devolve `{order_number, total, items}`.

- [ ] **Step 1: Escrever os testes que falham**

Criar `backend/tests/pos/test_counter_update.py`:

```python
"""Atualizar um pedido de balcão já impresso (Fase 3): substitui itens +
reimprime só na cozinha; recusa pedido pago/cancelado."""
import asyncio

import pytest
from fastapi import HTTPException

import server
from server import create_token, create_pos_token, update_counter_order, CounterOrderRequest, CounterOrderItem


class _Cursor:
    def __init__(self, docs):
        self._docs = docs
    async def to_list(self, n):
        return list(self._docs)


class _Orders:
    def __init__(self, order):
        self.order = order
        self.updated = None
    async def find_one(self, query, projection=None):
        if query.get("id") == self.order.get("id") and self.order.get("source") == "balcao":
            return dict(self.order)
        return None
    async def update_one(self, query, update):
        # aplica só se o pedido bate o filtro (paid:false, status != cancelled)
        ok = (self.order.get("paid") in (False, None)) and self.order.get("status") != "cancelled"
        if query.get("paid") is False and not ok:
            class R: matched_count = 0
            return R()
        self.order.update(update["$set"])
        self.updated = update["$set"]
        class R: matched_count = 1
        return R()


class _PrintJobs:
    def __init__(self):
        self.inserted = []
    async def insert_one(self, doc):
        self.inserted.append(doc)


class _Simple:
    def __init__(self, one=None, many=None):
        self._one = one
        self._many = many or []
    async def find_one(self, query, projection=None):
        return self._one
    def find(self, query, projection=None):
        return _Cursor(self._many)


class _FakeDb:
    def __init__(self, order, products, open_session=None, printers=None):
        self.orders = _Orders(order)
        self.products = _Simple(many=products)
        self.cash_sessions = _Simple(one=open_session)
        self.printers = _Simple(many=printers or [])
        self.print_jobs = _PrintJobs()


def _req():
    return CounterOrderRequest(items=[CounterOrderItem(product_id="p1", quantity=2)])


def test_update_substitui_itens_e_reimprime_so_cozinha(monkeypatch):
    order = {"id": "o1", "source": "balcao", "order_number": 7, "paid": False,
             "status": "received", "items": [], "total": 0.0}
    products = [{"id": "p1", "name": "Pizza", "base_price": 10.0, "vendus_tax_id": "INT"}]
    fake = _FakeDb(order, products)
    monkeypatch.setattr(server, "db", fake)

    admin = create_token("admin-1", "gestor@lenhaebrasa.com")   # kind=admin -> salta require_open_cash
    pos_token = create_pos_token("op-1", "Ana")

    async def run():
        return await update_counter_order("o1", _req(), authorization=f"Bearer {admin}",
                                          x_device_token=None, x_pos_token=pos_token)
    res = asyncio.run(run())

    assert res["order_number"] == 7
    assert res["total"] == 20.0
    assert order["total"] == 20.0 and len(order["items"]) == 1   # substituiu na "BD"
    # reimprimiu SÓ cozinha, com is_update, e nunca um talão de caixa
    jobs = fake.print_jobs.inserted
    assert len(jobs) == 1
    assert jobs[0]["printer_type"] == "kitchen"
    assert jobs[0]["order_snapshot"]["is_update"] is True
    assert all(j["printer_type"] != "cashier" for j in jobs)


def test_update_recusa_pedido_pago(monkeypatch):
    order = {"id": "o1", "source": "balcao", "order_number": 7, "paid": True,
             "status": "delivered", "items": [{"product_name": "X", "quantity": 1}], "total": 5.0}
    fake = _FakeDb(order, [{"id": "p1", "name": "Pizza", "base_price": 10.0}])
    monkeypatch.setattr(server, "db", fake)
    admin = create_token("admin-1", "gestor@lenhaebrasa.com")
    pos_token = create_pos_token("op-1", "Ana")

    async def run():
        return await update_counter_order("o1", _req(), authorization=f"Bearer {admin}",
                                          x_device_token=None, x_pos_token=pos_token)
    with pytest.raises(HTTPException) as exc:
        asyncio.run(run())
    assert exc.value.status_code == 400
    assert fake.print_jobs.inserted == []   # não reimprimiu nada
```

- [ ] **Step 2: Correr para confirmar que falham**

Run: `cd backend && .venv/bin/python -m pytest tests/pos/test_counter_update.py -v`
Expected: FAIL (`ImportError: cannot import name 'update_counter_order'`).

- [ ] **Step 3: Implementar o endpoint**

Em `backend/server.py`, a seguir a `cancel_counter_order` (termina ~3908, antes de `class CounterCheckoutRequest`), acrescentar:

```python
@api_router.post("/pos/counter/{order_id}/update")
async def update_counter_order(
    order_id: str,
    body: CounterOrderRequest,
    authorization: Optional[str] = Header(None),
    x_device_token: Optional[str] = Header(None),
    x_pos_token: Optional[str] = Header(None),
):
    """Atualiza os itens de um pedido de balcão JÁ impresso mas ainda não
    faturado (o operador acrescentou/editou/anulou linhas) e reimprime o pedido
    COMPLETO só na COZINHA, marcado como ATUALIZADO. Substitui os itens e
    recalcula o total; o `checkout_counter_order` lê os itens frescos, por isso
    continua a sair UMA só FS com tudo. Guards: pedido de balcão existe, NÃO
    pago, NÃO cancelado e (como o `create`) caixa aberta. Auth-duplo; o operador
    vem sempre do token POS."""
    auth = await get_pos_or_admin(authorization, x_device_token)
    await get_pos_operator(x_pos_token)  # operador identificado (não-falsificável)

    sess = await db.cash_sessions.find_one({"status": "open"})
    if auth.get("kind") == "pos":
        pos_cfg = await _pos_settings_config()
        if pos_cfg.get("require_open_cash", True) and not sess:
            raise HTTPException(status_code=409, detail="Abra a caixa primeiro")

    order = await db.orders.find_one({"id": order_id, "source": "balcao"}, {"_id": 0})
    if not order:
        raise HTTPException(status_code=404, detail="Pedido de balcão não encontrado")
    if order.get("paid"):
        raise HTTPException(status_code=400, detail="Pedido já faturado — não pode ser alterado")
    if order.get("status") == "cancelled":
        raise HTTPException(status_code=400, detail="Pedido cancelado — não pode ser alterado")

    # Valida os overrides do staff (mesma validação do create).
    for i in body.items:
        if i.unit_price is not None and i.unit_price < 0:
            raise HTTPException(status_code=400, detail="Preço inválido")
        if i.vendus_tax_id is not None and i.vendus_tax_id not in ("INT", "NOR"):
            raise HTTPException(status_code=400, detail="IVA inválido")
        if i.discount_pct is not None and not (0 <= i.discount_pct <= 100):
            raise HTTPException(status_code=400, detail="Desconto % inválido")
        if i.discount_amount is not None and i.discount_amount < 0:
            raise HTTPException(status_code=400, detail="Desconto € inválido")

    product_ids = [i.product_id for i in body.items]
    prods = await db.products.find({"id": {"$in": product_ids}}, {"_id": 0}).to_list(1000)
    products_by_id = {
        p["id"]: p for p in prods
        if not p.get("rodizio_only", False) and p.get("available", True)
    }
    cart = [{
        "product_id": i.product_id, "quantity": i.quantity,
        "unit_price": i.unit_price, "vendus_tax_id": i.vendus_tax_id,
        "discount_pct": i.discount_pct, "discount_amount": i.discount_amount,
    } for i in body.items]
    built = build_counter_items(products_by_id, cart, default_tax=VENDUS_DEFAULT_TAX_ID)
    if not built["items"]:
        raise HTTPException(status_code=400, detail="Nada para faturar")

    # Substituição ATÓMICA — só se o pedido ainda estiver por faturar. Fecha a
    # corrida com o checkout: um update que chegue depois do pagamento é
    # recusado (409) em vez de crescer um pedido já faturado (que a FS não
    # cobriria).
    res = await db.orders.update_one(
        {"id": order_id, "source": "balcao", "paid": False, "status": {"$ne": "cancelled"}},
        {"$set": {"items": built["items"], "total": built["total"]}},
    )
    if res.matched_count == 0:
        raise HTTPException(status_code=409, detail="Pedido já faturado ou cancelado")

    # Reimprime o pedido COMPLETO só na COZINHA, marcado ATUALIZADO, via
    # order_snapshot (nunca `_enqueue_order_prints`, que imprimiria também um
    # talão de CAIXA e como "NOVO PEDIDO").
    snapshot = {
        "id": f"balcao-update-{order_id}",
        "order_number": order["order_number"],
        "table_number": None,
        "source": "balcao",
        "items": built["items"],
        "total": built["total"],
        "is_update": True,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    printers = await db.printers.find({"active": True}, {"_id": 0}).to_list(100)
    kitchen = [p for p in printers if p.get("printer_type") == "kitchen"]
    targets = kitchen or [None]
    for printer in targets:
        await db.print_jobs.insert_one({
            "id": str(uuid.uuid4()),
            "order_id": None,
            "order_snapshot": snapshot,
            "printer_id": printer["id"] if printer else None,
            "printer_name": printer["name"] if printer else "Cozinha",
            "printer_type": "kitchen",
            "status": "pending",
            "attempts": 0,
            "error": None,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "updated_at": datetime.now(timezone.utc).isoformat(),
        })

    return {"order_number": order["order_number"], "total": built["total"], "items": built["items"]}
```

- [ ] **Step 4: Correr os testes + suite POS**

Run: `cd backend && .venv/bin/python -m pytest tests/pos/test_counter_update.py -v`
Expected: PASS (2 testes).

Run: `cd backend && .venv/bin/python -c "import server; print('import ok')" && cd backend && .venv/bin/python -m pytest tests/pos/ -q`
Expected: `import ok` + toda a suite pos verde.

- [ ] **Step 5: Commit**

```bash
cd ~/dev/pizzaria && git add backend/server.py backend/tests/pos/test_counter_update.py
git commit -m "POS balcao: endpoint /pos/counter/{id}/update (substitui itens + reimprime so cozinha)"
```

---

### Task 3: Frontend — balcão editável depois de imprimir + "Reimprimir pedido"

**Files:**
- Modify: `frontend/src/lib/api.js` (`posCounter.updateOrder`)
- Modify: `frontend/src/pages/pos/PosBalcao.js`

**Interfaces:**
- Consumes: `POST /pos/counter/{order_id}/update` (Task 2).

- [ ] **Step 1: `posCounter.updateOrder` no api.js**

Em `frontend/src/lib/api.js`, no objeto `posCounter`, a seguir a `createOrder`, acrescentar:

```javascript
  updateOrder: (orderId, items) =>
    posApi.post(`/pos/counter/${orderId}/update`, { items }),
```

- [ ] **Step 2: `PosBalcao` — carrinho editável após imprimir + estado `dirty`**

Em `frontend/src/pages/pos/PosBalcao.js`:

(a) Acrescentar o estado `dirty` (junto dos outros `useState`, perto do topo do componente):

```javascript
  const [dirty, setDirty] = useState(false); // há alterações por reimprimir?
```

(b) `addToCart` e `changeQty` deixam de bloquear com `printed` e passam a marcar `dirty` quando já está impresso. Substituir os dois handlers (linhas ~99-122) por:

```javascript
  const addToCart = useCallback((p) => {
    setCart((prev) => {
      const idx = prev.findIndex((c) => c.id === p.id);
      if (idx >= 0) {
        const next = [...prev];
        next[idx] = { ...next[idx], qty: next[idx].qty + 1 };
        return next;
      }
      return [...prev, {
        id: p.id, name: p.name, qty: 1,
        unitPrice: Number(p.base_price) || 0,
        tax: p.vendus_tax_id === 'INT' ? 'INT' : 'NOR',
        taxTouched: false, discKind: 'pct', discVal: '',
      }];
    });
    if (printed) setDirty(true);
  }, [printed]);

  const changeQty = useCallback((id, delta) => {
    setCart((prev) => prev
      .map((c) => (c.id === id ? { ...c, qty: c.qty + delta } : c))
      .filter((c) => c.qty > 0));
    if (printed) setDirty(true);
  }, [printed]);
```

(c) `openEdit` deixa de bloquear com `printed`; `saveEdit` marca `dirty` quando impresso. Alterar `openEdit` (linha ~128-130) removendo o `|| printed`:

```javascript
  const openEdit = (idx) => {
    const c = cart[idx];
    if (!c) return;
```

e no fim de `saveEdit` (a seguir ao `setEditIdx(null);`, ~148) acrescentar:

```javascript
    if (printed) setDirty(true);
```

(d) O total mostrado passa a ser sempre o do carrinho. Substituir a linha `const total = printed ? (orderTotal ?? cartTotal) : cartTotal;` (~125) por:

```javascript
  const total = cartTotal;
```

- [ ] **Step 3: `reimprimirPedido` + botões**

(a) A seguir a `imprimirPedido` (~187), acrescentar o handler de reimpressão (mesmo mapeamento de itens):

```javascript
  const reimprimirPedido = async () => {
    if (!orderId || !cart.length) return;
    setPrinting(true);
    try {
      const items = cart.map((c) => {
        const it = { product_id: c.id, quantity: c.qty, unit_price: c.unitPrice };
        if (c.taxTouched) it.vendus_tax_id = c.tax;
        const dv = Number(String(c.discVal).replace(',', '.')) || 0;
        if (dv > 0) {
          if (c.discKind === 'eur') it.discount_amount = dv;
          else it.discount_pct = dv;
        }
        return it;
      });
      const r = await posCounter.updateOrder(orderId, items);
      setOrderNumber(r.data.order_number);
      setOrderTotal(r.data.total);
      setDirty(false);
      toast.success('Pedido atualizado e reenviado para a cozinha');
    } catch (err) {
      console.error('Erro ao atualizar o pedido de balcão:', err);
      toast.error(err.response?.data?.detail || 'Erro ao atualizar o pedido');
    } finally {
      setPrinting(false);
    }
  };
```

(b) O picker e os +/- deixam de estar desativados. Remover `disabled={printed}` do botão do produto (~353) e a classe condicional `printed ? 'cursor-not-allowed...' : ...` (~354-359) passa a só a variante ativa:

```jsx
                      onClick={() => addToCart(p)}
                      className="flex min-h-[76px] flex-col items-start justify-between rounded-lg border border-border bg-white p-3 text-left transition-all touch-manipulation active:scale-[0.97] cursor-pointer hover:border-primary/40 hover:shadow-sm"
```

Remover `disabled={printed}` dos dois botões `changeQty` (~412 e ~421). Na linha do carrinho, remover a dependência de `printed` no `title`/`className`/`Pencil` (~386-392) para o item ser sempre editável:

```jsx
                    onClick={() => openEdit(i)}
                    title="Tocar para editar (qtd/preço/IVA/desconto)"
                    className="grid grid-cols-[1fr_5.5rem_5rem] items-center gap-2 border-b border-white/5 px-4 py-3 cursor-pointer hover:bg-white/5"
```
```jsx
                        <span className="truncate">{c.name}</span>
                        <Pencil className="h-3 w-3 shrink-0 text-white/30" />
```

(c) O banner de "carrinho bloqueado" (~313-317) passa a informar que se pode editar/reimprimir:

```jsx
          {printed && (
            <div className="mb-4 rounded-lg border border-amber-500/40 bg-amber-50 px-3 py-2 text-sm text-amber-800">
              Pedido nº {orderNumber} na cozinha. Podes acrescentar/editar linhas e <strong>Reimprimir pedido</strong>; no fim, <strong>Emitir Documento</strong>.
            </div>
          )}
```

(d) No rodapé, quando impresso e ainda não faturado, mostrar o botão «Reimprimir pedido» ANTES do bloco de faturação. Dentro do `{printed && docNumber == null && (` (~452), como primeiro filho do fragmento `<>`, acrescentar:

```jsx
                <Button
                  onClick={reimprimirPedido}
                  disabled={!cart.length || printing}
                  variant={dirty ? 'default' : 'outline'}
                  className={dirty
                    ? 'h-12 w-full bg-amber-400 text-base font-semibold text-[#3a1414] hover:bg-amber-300'
                    : 'h-12 w-full border-white/25 bg-transparent text-base font-semibold text-white hover:bg-white/10'}
                >
                  {printing ? <Loader2 className="h-5 w-5 animate-spin" /> : <Printer className="h-5 w-5" />}
                  {dirty ? 'Reimprimir pedido (atualizado)' : 'Reimprimir pedido'}
                </Button>
```

(e) «Emitir Documento» exige o pedido sincronizado — desativar quando `dirty`. Alterar o `disabled` do botão (~499):

```jsx
                  disabled={checkingOut || cancelling || !paymentId || dirty}
```

e, logo acima desse botão, um aviso quando há alterações por reimprimir:

```jsx
                {dirty && (
                  <p className="text-center text-xs text-amber-200">
                    Tens alterações por reimprimir — carrega em «Reimprimir pedido» antes de faturar.
                  </p>
                )}
```

- [ ] **Step 4: Verificar que compila**

Run: `export PATH="$HOME/.local/node/bin:$HOME/Library/pnpm:$PATH" && cd frontend && npx craco build 2>&1 | tail -15`
Expected: "Compiled successfully" (sem "Failed to compile").

- [ ] **Step 5: Commit**

```bash
cd ~/dev/pizzaria && git add frontend/src/lib/api.js frontend/src/pages/pos/PosBalcao.js
git commit -m "POS balcao: carrinho editavel apos imprimir + botao Reimprimir pedido"
```

---

## Deploy (fim da fase)

Depois das 3 tasks revistas e verdes + revisão final whole-branch:
1. Push do ramo `matheus-pos-fase3` → merge no `main` → push.
2. Deploy rsync (dry-run primeiro) + `docker compose up -d --build`.
3. Confirmar `health` + smoke: no balcão, criar um pedido → imprimir → acrescentar um item → «Reimprimir pedido» (confirmar talão «PEDIDO ATUALIZADO» só na cozinha, sem 2º talão de caixa) → «Emitir Documento» → confirmar UMA FS com todos os itens.

## Self-review (feito)

- **Cobertura do spec (Fluxo 2):** editar após imprimir (T3 remove os bloqueios) ✓; reimprimir o pedido completo só cozinha marcado ATUALIZADO (T1 banner + T2 snapshot só-kitchen) ✓; fatura única no fim (checkout inalterado lê itens frescos; T2 não mexe no checkout) ✓; sem pré-conta na reimpressão (só kitchen) ✓.
- **Fiscal:** o `/update` recusa pedido pago/cancelado e substitui atomicamente (filtro `paid:false`) → fecha a corrida update-vs-checkout; `ext_ref`/paid-guard/dedup do checkout intactos → uma só FS.
- **Sem placeholders:** código completo em cada passo.
- **Consistência de tipos:** T2 devolve `{order_number, total, items}`; T3 lê `r.data.order_number`/`r.data.total`. Snapshot com `is_update:true` (T2) ↔ `order.get("is_update")` (T1). `updateOrder(orderId, items)` (T3 api) ↔ `body.items` (T2).
