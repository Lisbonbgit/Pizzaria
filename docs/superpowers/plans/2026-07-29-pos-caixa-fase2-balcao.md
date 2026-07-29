# POS + Caixa — Fase 2 (Balcão) — Plano de Implementação

> **Para quem executa (agente):** SUB-SKILL: `superpowers:subagent-driven-development`. Backend = pytest (helpers puros); frontend = `craco build` + browser. Passos com checkbox.

**Goal:** Venda ao **balcão** (rápida, paga logo) dentro do `/pos`: escolher produtos → **imprimir pedido** (cozinha) → **faturar** (FS na Caixa API) → paga logo. A venda liga-se à **sessão de caixa** (`pos_sales` kind="balcao") para o Z bater a 100%. O cartão "Balcão" deixa de dizer "Brevemente".

**Architecture:** Backend reutiliza a criação de pedido + impressão (`create_order`/print jobs) e os helpers da Fase 1 (`pos/idempotency.py`, `pos/sales.py`, `pos/cash.py` — resolução da sessão). Frontend reutiliza a lista de produtos e o padrão de picker. Balcão **não é mesa** (não usa `table_sessions` nem a grelha de mesas).

**Tech Stack:** FastAPI + Motor, React CRA/craco, shadcn/ui. Base: Fase 1 (ramo já em main+deploy).

## Global Constraints
- **Fiscal:** a FS do balcão é real (Caixa API 358144579). **Idempotente**: `external_reference = f"balcao-{order_id}"` (o `order_id` é criado uma vez e reutilizado no checkout → chave estável) + dedup no Vendus antes de emitir (reutilizar o padrão do `close_table`). `pos_sales` por documento com índice único em `vendus_document_id`.
- **Exige caixa aberta:** o checkout do balcão resolve a única `cash_session` `open` **no servidor** (409 se não houver); grava `pos_sales` kind="balcao", `table_number=null`, operador do token POS. Nunca aceitar `cash_session_id`/`pos_user_id` do body.
- **Auth:** endpoints do balcão usam `get_pos_or_admin` + operador via `get_pos_operator`. Frontend usa `posApi` (nunca admin `api`).
- Produtos: usar `base_price` + `vendus_tax_id` (fallback `VENDUS_DEFAULT_TAX_ID`); excluir `rodizio_only` e indisponíveis do picker. Dinheiro/troco como no checkout de mesa. Sem diálogo de desconto por item (isso é Fase 3). PT-PT. Money 2 casas.
- Não partir mesas/QR/admin. Deploy só depois de smoke.

## Estrutura de ficheiros
- **Modificar** `backend/server.py` — helper `_enqueue_order_prints`, `POST /pos/counter/order`, `POST /pos/counter/checkout`.
- **Criar** `backend/pos/counter.py` — helper puro `build_counter_items(products, cart)` (product+qty → linhas Vendus + total) e `counter_ext_ref(order_id)`.
- **Criar** `backend/tests/pos/test_counter.py`.
- **Modificar** `frontend/src/lib/api.js` — `posCounter` (order, checkout) + lista de produtos POS.
- **Criar** `frontend/src/pages/pos/PosBalcao.js`. **Modificar** `PosHome.js` (cartão Balcão ativo) + `PosApp.js` (wiring).

---

### Task 1: Backend — criar pedido de balcão + imprimir (cozinha)

**Files:** Modify `backend/server.py`. Create `backend/pos/counter.py`. Test: `backend/tests/pos/test_counter.py`

**Interfaces — Produces:** `build_counter_items(products_by_id, cart) -> {items:[{title,qty,gross_price,tax_id}], total}` (puro); `counter_ext_ref(order_id)->str`; `_enqueue_order_prints(order_id)` (extraído de `create_order`, cria os print jobs cozinha+caixa); `POST /api/pos/counter/order {items:[{product_id, quantity}]}` (auth pos/admin, exige caixa aberta) → cria order `source="balcao"`, `table_number=None`, imprime cozinha, devolve `{order_id, order_number, items, total}`.

- [ ] **Passo 1: Teste** — `test_counter.py`
```python
from pos.counter import build_counter_items, counter_ext_ref
def test_build_items_e_total():
    prods = {"p1": {"name":"Imperial","base_price":2.0,"vendus_tax_id":"NOR"},
             "p2": {"name":"Pizza","base_price":13.9,"vendus_tax_id":"INT"}}
    cart = [{"product_id":"p1","quantity":2},{"product_id":"p2","quantity":1}]
    r = build_counter_items(prods, cart, default_tax="NOR")
    assert r["total"] == 17.9
    assert r["items"][0] == {"title":"Imperial","qty":2,"gross_price":2.0,"tax_id":"NOR"}
def test_ext_ref_estavel():
    assert counter_ext_ref("abc") == "balcao-abc"
```
- [ ] **Passo 2: Correr** — `cd backend && python -m pytest tests/pos/test_counter.py -q` → FAIL (módulo não existe).
- [ ] **Passo 3: Implementar** — `pos/counter.py`: `build_counter_items` (título = nome do produto; `gross_price=base_price`; `tax_id = vendus_tax_id or default_tax`; `total=round(sum(price*qty),2)`; ignora product_id inexistente). `counter_ext_ref(order_id) = f"balcao-{order_id}"`. Em `server.py`: extrair `_enqueue_order_prints(order_id)` das linhas de `create_order` (1258-1298) e chamá-la lá E no novo endpoint. `POST /pos/counter/order`: `dep = await get_pos_or_admin(...)`; resolver sessão aberta (helper de `pos/cash.py`; 409 se `require_open_cash` e não houver); carregar os produtos do cart (`db.products`), `build_counter_items`, inserir order (`source="balcao"`, `table_number=None`, `status="received"`, `paid=False`, `pos_user_id` do operador, `cash_session_id`), `_enqueue_order_prints`, devolver resumo.
- [ ] **Passo 4: Verificar** — `pytest tests/pos/ -q` verde; manual (homolog.): criar pedido balcão → imprime na cozinha.
- [ ] **Passo 5: Commit** — `git commit -m "POS balcao: criar pedido + imprimir (pos/counter, /pos/counter/order)"`

---

### Task 2: Backend — faturar balcão (FS + pos_sales + recibo)

**Files:** Modify `backend/server.py`. Test: estende `test_counter.py`

**Interfaces — Consumes:** `counter_ext_ref`, `stable`/dedup do `close_table`, `build_pos_sales_rows`, resolução de sessão. **Produces:** `POST /api/pos/counter/checkout {order_id, payment_method_id, nif?}` → emite **1 FS** (itens do order balcão; `external_reference=counter_ext_ref(order_id)`; dedup antes de emitir) → `pos_sales` (kind="balcao", `vendus_document_id`, `table_number=null`, operador, sessão) → imprime recibo (ESC/POS do Vendus) → marca order `paid=True`. Exige caixa aberta.

- [ ] **Passo 1: Teste (mapeamento pos_sales do balcão)** — reutiliza `build_pos_sales_rows` (já testado); acrescentar um teste que confirma `counter_ext_ref` estável entre order e checkout (idempotência): mesmo `order_id` → mesma ref.
- [ ] **Passo 2: Correr** → verde/def.
- [ ] **Passo 3: Implementar** — `POST /pos/counter/checkout`: `get_pos_or_admin` + operador + resolver sessão (409 se fechada). Carregar o order balcão (`source="balcao"`, não pago). Construir `vendus_items` a partir dos itens do order. **Dedup**: procurar no Vendus `external_reference==counter_ext_ref(order_id)`; se existir, reutilizar. Senão `create_invoice(items, payments=[{id:payment_method_id, amount:total}], doc_type="FS", output="escpos", client={fiscal_id:nif} se nif)`. Gravar `pos_sales` via `build_pos_sales_rows([{amount:total}],[doc], payment_method_id, cash_session_id, pos_user_id, kind="balcao", table_number=None)` (índice único absorve retries). Imprimir recibo (job `escpos_direct_b64`, printer_type cashier — como no `close_table`). Marcar order `paid=True, payment_method=str(id), vendus_document_id=doc["id"]`. Devolver `{doc_number, total, change?}`.
- [ ] **Passo 4: Verificar** — `pytest tests/pos/ -q` verde; manual (homolog.): faturar um balcão → FS no Vendus + `pos_sales` kind=balcao + recibo.
- [ ] **Passo 5: Commit** — `git commit -m "POS balcao: faturar (FS idempotente + pos_sales kind=balcao + recibo)"`

---

### Task 3: Frontend — API do balcão + lista de produtos POS

**Files:** Modify `frontend/src/lib/api.js`.

**Interfaces — Produces:** `posCounter = { createOrder(items), checkout(order_id, payment_method_id, nif), products() }` via `posApi` → `POST /pos/counter/order`, `POST /pos/counter/checkout`, e a lista de produtos (reutilizar `GET /products?available_only=true` via `posApi`; o cliente filtra `rodizio_only`). Também `posCounter.categories()` se necessário (via `posApi` a `GET /categories?active_only=true`).

- [ ] **Passo 1: Implementar** os métodos em `api.js` (estilo `posCheckout`). Confirmar que `/products` e `/categories` aceitam device token — se hoje exigem admin JWT, **acrescentar `get_pos_or_admin`** nesses dois GET (catálogo, leitura) num commit separado do backend e notar no relatório.
- [ ] **Passo 2: Verificar** — `craco build` OK.
- [ ] **Passo 3: Commit** — `git commit -m "POS balcao: camada de API (posCounter)"`

---

### Task 4: Frontend — ecrã do Balcão + ativar o cartão

**Files:** Create `frontend/src/pages/pos/PosBalcao.js`. Modify `PosHome.js`, `PosApp.js`.

**Interfaces — Consumes:** `posCounter`.

- [ ] **Passo 1: `PosBalcao.js`** — ecrã cheio: **picker de produtos** (agrupado por categoria, exclui `rodizio_only`/indisponíveis; toque adiciona ao carrinho, +/- qtd) num painel, e o **carrinho + total** no outro. Botão **"Imprimir pedido"** → `posCounter.createOrder(cart)` (guarda o `order_id`, imprime cozinha, feedback "enviado para a cozinha"). Depois **faturação**: método de pagamento (de `checkoutAPI.paymentMethods` via posApi — reutilizar `posCheckout.paymentMethods`), campo valor entregue + **troco**, NIF opcional, botão **"Emitir Documento"** → `posCounter.checkout(order_id, method, nif)` → sucesso: toast "Fatura emitida" + limpar para uma nova venda. Vários balcões = cada venda recomeça do zero.
- [ ] **Passo 2: Ativar o cartão** — em `PosHome.js`, o cartão **Balcão** deixa de dizer "Brevemente" e passa a `onClick` → abrir `<PosBalcao/>` (estado em PosHome/PosApp, como o checkout de mesa). Remover o `aria-disabled`.
- [ ] **Passo 3: Verificar** — `craco build` OK; homolog.: Balcão → escolher produtos → imprimir → faturar → FS sai + recibo; volta ao início.
- [ ] **Passo 4: Commit** — `git commit -m "POS balcao: ecra de venda ao balcao + ativar cartao"`

---

## Auto-revisão
- **Cobertura:** criar pedido+imprimir (T1), faturar FS+pos_sales+recibo (T2), API FE (T3), ecrã (T4). ✅
- **Fiscal:** idempotência via `balcao-{order_id}` + dedup; `pos_sales` kind=balcao ligado à caixa → o Z passa a incluir o balcão (completa a gaveta). ✅
- **Reuso:** `_enqueue_order_prints`, `build_pos_sales_rows`, dedup do `close_table`, `posCheckout.paymentMethods`. Sem tocar em mesas/QR.
- **Fase 3 (fora):** diálogo de produto (qtd/preço/IVA/desconto) + faturação estilo Vendus.

---

## Extra (pedido 2026-07-29): Bloqueio por inatividade + tela de descanso

### Task 5: Backend — listar utilizadores do POS para a tela de bloqueio
`GET /api/pos/users-public` (auth `get_pos_or_admin`, device token) → `[{id, name}]` dos `pos_users` ativos (SÓ nome, sem hash). Para a tela de descanso mostrar os avatares/nomes sem precisar do JWT de admin.

### Task 6: Frontend — auto-lock 2 min + tela de descanso + escolher utilizador→PIN
- **Timer de inatividade (2 min):** no `/pos` (PosApp), a cada interação (click/touch/teclado) reinicia um timer de 120s; ao expirar → estado "bloqueado" (não faz logout do device; guarda a sessão/estado da caixa, só tapa com a tela).
- **Tela de descanso:** ecrã cheio com **relógio grande** (HH:MM:SS a atualizar) + a lista de utilizadores (`GET /pos/users-public`) como **avatares com nome** (como a foto do Vendus).
- **Desbloquear:** clicar num utilizador → ecrã de **PIN** (o `PosLogin` atual, mas já com o utilizador escolhido) → `posAPI.login(pin)` valida; se o PIN for do utilizador certo, desbloqueia e volta ao mesmo sítio. (O login passa a ser **escolher utilizador → PIN**, em vez de só PIN.)
- Aplica-se tanto ao arranque (primeiro login) como ao re-desbloqueio após inatividade.
