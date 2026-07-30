# POS + Caixa — Fase 3 (Faturação estilo Vendus) — Plano de Implementação

> **Para quem executa (agente):** SUB-SKILL: `superpowers:subagent-driven-development`. Backend = pytest (helpers puros); frontend = `craco build`. Passos com checkbox.

**Goal:** O ecrã de faturação (mesa, partilhado via `TableCheckout`) fica com o **fluxo do Vendus**: clicar num produto abre um **diálogo** (Quantidade, Preço unitário, IVA, Desconto % ou €); o botão **"Finalizar"** liga o modo **Separar Conta** (só aí clicar num produto o passa para a esquerda para cobrar à parte). As edições por linha (preço/IVA/qtd) chegam **corretamente à FS real**.

**Architecture:** Reutiliza `TableCheckout.js` (já partilhado admin+POS) e o `close_table`. **Fiscal-crítico:** o `close_table` (deployado) tem de ler os **overrides por linha** (preço/IVA/qtd/desconto) ANTES dos fallbacks (IVA do produto, preço do pedido), nos **dois ramos** (à la carte E extras de rodízio).

**Tech Stack:** FastAPI + Motor, React CRA/craco, shadcn/ui. Base: Fase 1+2 (em main+deploy).

## Global Constraints
- **Fiscal:** os overrides (preço/IVA/qtd/desconto por linha) têm de refletir-se na **FS real** (register 358144579). O `close_table` lê o override do item ANTES de cair no `tax_by_prod`/preço do pedido. Desconto vai ao Vendus como `discount_percentage` (%) ou `discount_amount` (€) — NUNCA o campo `discount` (dá 403).
- **Não partir** o fluxo atual: hoje o `TableCheckout` já é usado no admin E no `/pos`; o rodízio, separar/dividir, produto manual, consulta, free têm de continuar a funcionar. As mesas/QR ficam iguais por baixo.
- Money 2 casas. PT-PT. `posApi` no /pos, `api` no admin (já resolvido pelo prop `api`). Só importar componentes UI existentes.
- Deploy só depois de smoke.

## Estrutura de ficheiros
- **Modificar** `backend/server.py` — `set_item_discount` (aceita € além de %), novo `POST /orders/{id}/items/{idx}/edit` (preço/IVA/qtd), `_open_bill_lines` (surface `vendus_tax_id` + `discount_amount`), `close_table` (ler overrides).
- **Criar** `backend/pos/pricing.py` — helper puro `line_vendus(item, product_tax, default_tax)` (resolve preço/IVA/desconto efetivos de uma linha).
- **Criar** `backend/tests/pos/test_pricing.py`.
- **Modificar** `frontend/src/pages/checkout/TableCheckout.js` — diálogo do produto + modo Finalizar/Separar.
- **Criar** `frontend/src/lib/api.js` — `checkoutAPI.editItem` + `posCheckout.editItem`.

---

### Task 1: Backend — helper puro de preço/IVA/desconto por linha + overrides

**Files:** Create `backend/pos/pricing.py`, `backend/tests/pos/test_pricing.py`. Modify `backend/server.py`.

**Interfaces — Produces:** `line_vendus(item, product_tax_id, default_tax_id) -> {title, qty, gross_price, tax_id, discount_percentage?, discount_amount?}` (puro): resolve `qty=item.quantity`, `gross_price=item.unit_price`, `tax_id = item.vendus_tax_id or product_tax_id or default`, e o desconto do item (`discount_pct` → `discount_percentage`; `discount_amount` → `discount_amount`). Novo `POST /orders/{id}/items/{idx}/edit {unit_price?, quantity?, vendus_tax_id?}` grava esses campos no item. `set_item_discount` passa a aceitar `{pct?}` OU `{amount?}` (guarda `discount_pct` ou `discount_amount`, mutuamente exclusivos).

- [ ] **Passo 1: Teste** — `test_pricing.py`
```python
from pos.pricing import line_vendus
def test_override_iva_e_preco():
    it = {"product_name":"Pizza","quantity":2,"unit_price":15.0,"vendus_tax_id":"NOR"}
    r = line_vendus(it, product_tax_id="INT", default_tax_id="INT")
    assert r["tax_id"] == "NOR"          # override do item ganha ao IVA do produto
    assert r["gross_price"] == 15.0 and r["qty"] == 2
def test_fallback_iva_produto():
    it = {"product_name":"Água","quantity":1,"unit_price":1.0}
    assert line_vendus(it, product_tax_id="INT", default_tax_id="NOR")["tax_id"] == "INT"
def test_desconto_pct_vs_amount():
    a = line_vendus({"product_name":"X","quantity":1,"unit_price":10.0,"discount_pct":10}, "INT","INT")
    assert a["discount_percentage"] == 10 and "discount_amount" not in a
    b = line_vendus({"product_name":"X","quantity":1,"unit_price":10.0,"discount_amount":2.5}, "INT","INT")
    assert b["discount_amount"] == 2.5 and "discount_percentage" not in b
```
- [ ] **Passo 2: Correr** — `cd backend && python -m pytest tests/pos/test_pricing.py -q` → FAIL.
- [ ] **Passo 3: Implementar** — `pos/pricing.py` conforme acima. Em `server.py`: `POST /orders/{id}/items/{idx}/edit` (auth `get_pos_or_admin`, valida `unit_price>=0`, `quantity>=1`, `vendus_tax_id in {INT,NOR}` se dado; grava só os campos presentes). `set_item_discount`: aceitar `amount` (guarda `discount_amount`, limpa `discount_pct`) ou `pct` (guarda `discount_pct`, limpa `discount_amount`).
- [ ] **Passo 4: Verificar** — `pytest tests/pos/ -q` verde.
- [ ] **Passo 5: Commit** — `git commit -m "POS Fase3: helper line_vendus + edit de linha (preco/IVA/qtd) + desconto em €"`

---

### Task 2: Backend — `close_table` usa `line_vendus` (overrides na FS real)

**Files:** Modify `backend/server.py` (`close_table`, `_open_bill_lines`). **FISCAL-CRÍTICO.**

**Interfaces — Consumes:** `line_vendus` (Task 1). **Produces:** `close_table` constrói as linhas Vendus via `line_vendus` em AMBOS os ramos (à la carte E extras de rodízio), lendo o override do item. `_open_bill_lines` passa a incluir `vendus_tax_id` e `discount_amount` na linha devolvida.

- [ ] **Passo 1: Teste** — estende `test_pricing.py`: um teste que simula a linha de `_open_bill_lines` (dict com override) → `line_vendus` devolve o IVA/preço override (a lógica pura já testada na Task 1; aqui confirma o mapeamento dos nomes de campo que `_open_bill_lines` usa).
- [ ] **Passo 2: Correr** → verde/def.
- [ ] **Passo 3: Implementar** — `_open_bill_lines`: acrescentar `vendus_tax_id` e `discount_amount` ao dict de cada linha (a partir do item). No `close_table`: substituir a construção manual de `vendus_items` (o `li = {title, qty, gross_price, tax_id}` + desconto) por `line_vendus(l, tax_by_prod.get(l["product_id"]), VENDUS_DEFAULT_TAX_ID)` — no ramo à la carte E no ramo de extras de rodízio. Manter o `_eff_disc` (desconto global) a combinar-se: o desconto global % aplica-se por cima do desconto de linha (documentar a ordem; se a linha já tem `discount_amount`, o global % aplica-se ao preço; garantir que o total enviado bate). Confirmar que os `by_tax`/`total` continuam corretos.
- [ ] **Passo 4: Verificar** — `pytest tests/ -q` (baseline test_daily_report inalterado). Manual (homolog.): editar o IVA de uma linha → a FS real sai com esse IVA (não o do produto).
- [ ] **Passo 5: Commit** — `git commit -m "POS Fase3: close_table lê overrides por linha (line_vendus) na FS real"`

---

### Task 3: Frontend — diálogo do produto (qtd/preço/IVA/desconto)

**Files:** Modify `frontend/src/lib/api.js` (`editItem` no `checkoutAPI` e `posCheckout`), `frontend/src/pages/checkout/TableCheckout.js`.

**Interfaces — Consumes:** `api.editItem(orderId, idx, {unit_price, quantity, vendus_tax_id})`, `api.setItemDiscount(orderId, idx, {pct} | {amount})`. **Produces:** um `<Dialog>` que abre ao clicar num produto (em modo edição) com campos Quantidade, Preço unitário, IVA (INT/NOR), Desconto (% ou €) e "Gravar" → chama editItem + setItemDiscount → `onChanged`/reload.

- [ ] **Passo 1:** `api.js`: `editItem: (orderId, idx, data) => api.post('/orders/{orderId}/items/{idx}/edit', data)` no `checkoutAPI` (via `api`) e no `posCheckout` (via `posApi`). Evoluir `setItemDiscount` para aceitar `{pct}` ou `{amount}`.
- [ ] **Passo 2:** `TableCheckout.js`: criar o diálogo (estado `editingLine`). Campos pré-preenchidos com os valores atuais da linha. "Gravar" → `api.editItem(...)` + (se desconto) `api.setItemDiscount(...)` → fecha + `onChanged()`/reload. Mostra o subtotal calculado.
- [ ] **Passo 3: Verificar** — `craco build` OK.
- [ ] **Passo 4: Commit** — `git commit -m "POS Fase3: dialogo do produto (qtd/preco/IVA/desconto) no checkout"`

---

### Task 4: Frontend — modo "Finalizar" → Separar Conta ao clicar

**Files:** Modify `frontend/src/pages/checkout/TableCheckout.js`.

**Interfaces — Consumes:** o diálogo (Task 3). **Produces:** por defeito (modo edição) clicar num produto abre o **diálogo** (Task 3), NÃO separa. Um botão **"Finalizar"** (ou "Separar Conta") liga o **modo separar**: aí clicar num produto passa-o para a esquerda (o comportamento `toggle` atual). Um jeito de voltar ao modo edição.

- [ ] **Passo 1:** `TableCheckout.js`: estado `mode` ("edit" | "split"). No `onClick` do produto (direita, ~linha 567): se `mode==="edit"` → abre o diálogo (Task 3); se `mode==="split"` → `toggle(e.key)` (atual). Botão "Finalizar" alterna para `split`. O painel esquerdo (separar/dividir/emitir) só faz sentido em `split` (ou mantém-se sempre visível — decidir para não perder o rodízio, que já usa a seleção). **Cuidado:** o rodízio já usa `toggle` para separar pessoas — garantir que o rodízio continua a funcionar (talvez o rodízio arranque já em `split`, ou o diálogo só se aplica a itens à la carte, não às "pessoas" do rodízio).
- [ ] **Passo 2: Verificar** — `craco build` OK. Manual (homolog.): mesa à la carte → clicar produto abre diálogo; "Finalizar" → clicar separa; rodízio continua a separar por pessoa.
- [ ] **Passo 3: Commit** — `git commit -m "POS Fase3: modo Finalizar -> separar conta ao clicar (edicao por defeito)"`

---

### Task 5: Frontend — polir o visual (estilo Vendus)

**Files:** Modify `frontend/src/pages/checkout/TableCheckout.js`.

- [ ] **Passo 1:** Ajustar o layout dos 2 painéis para ficar mais próximo da foto do Vendus (Total/Cliente/Pagamento à esquerda; lista de produtos Produto/Qtd/Preço à direita; botões Separar/Dividir/Consulta/Finalizar; troco). Sem mudar a lógica — só apresentação. Manter tudo o que já existe.
- [ ] **Passo 2: Verificar** — `craco build` OK; revisão visual.
- [ ] **Passo 3: Commit** — `git commit -m "POS Fase3: polir visual do checkout (estilo Vendus)"`

---

## Auto-revisão
- **Cobertura:** helper+edit+desconto€ (T1), close_table usa overrides na FS (T2, fiscal), diálogo do produto (T3), modo Finalizar/separar (T4), visual (T5). ✅
- **Fiscal:** os overrides por linha chegam à FS real via `line_vendus` nos dois ramos; desconto por `discount_percentage`/`discount_amount` (nunca `discount`). Revisão da T2 com opus.
- **Não regredir:** rodízio/separar/dividir/consulta/free/produto manual continuam; T4 tem de preservar o rodízio (que usa `toggle`).
- **Risco:** T2 toca no `close_table` deployado — revisão cuidada + smoke antes do deploy.
