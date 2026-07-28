# POS + Caixa — Fase 1 (Frontend) — Plano de Implementação

> **Para quem executa (agente):** SUB-SKILL OBRIGATÓRIA: `superpowers:subagent-driven-development` (ou `executing-plans`). O frontend **não tem harness de testes** (só o backend tem pytest) → o "gate" de cada tarefa é **`craco build` passar sem erros + verificação no browser**, não TDD. Passos com checkbox (`- [ ]`).

**Goal:** A janela `/pos` a sério: login por PIN, abrir/fechar caixa (com relatório Z), grelha de mesas com o checkout atual, e a página de gestão `/admin/pos` (utilizadores, definições, "Iniciar POS"). Consome os endpoints do backend da Fase 1 (ramo `pos-caixa-fase1`).

**Architecture:** React CRA/craco + Tailwind + shadcn/ui (mesmo estilo do resto do admin). O `/pos` é uma rota de **ecrã cheio fora do `/admin`**. Ponto crítico de auth: o `/pos` usa uma instância axios **`posApi`** própria que envia **`X-Device-Token` + `X-POS-Token`** e **NUNCA** o `Authorization: Bearer <admin_token>` — senão, com o dono também logado no admin no mesmo browser, o backend resolvia `kind="admin"` e a venda NÃO entrava na sessão de caixa.

**Tech Stack:** React, axios, react-router-dom, shadcn/ui (`@/components/ui/*`), sonner (toasts), lucide-react. Backend já no ramo `pos-caixa-fase1`.

## Global Constraints
- **`posApi` ≠ `api`:** `posApi` (nova instância) envia SÓ `X-Device-Token` (localStorage `pos_device_token`) + `X-POS-Token` (localStorage `pos_token`). NUNCA envia o JWT de admin. Os ecrãs do `/pos` usam SEMPRE `posApi`/`posAPI`, nunca o `api` de admin.
- **Não partir** o admin existente nem o fluxo QR (`/`). O `AdminTables` (`/admin/tables`, CRUD de mesas) fica INTACTO — é distinto do POS.
- **Definições do POS:** o PUT `/admin/pos/settings` substitui o objeto todo → o formulário tem de enviar SEMPRE a config completa (não só o campo alterado).
- **Fase 1 reutiliza o checkout ATUAL** (o de `AdminOrders`), não o estilo-Vendus (isso é Fase 3). O balcão é Fase 2 → na Fase 1 o cartão "Balcão" mostra "Brevemente".
- Gate de cada tarefa: `cd frontend && npx craco build` passa (0 erros) + verificação no browser descrita na tarefa. PT-PT na UI. Seguir os componentes/estilos existentes (mirar `AdminOrders.js`, `AdminReports.js`).
- Dinheiro apresentado a 2 casas com €.

---

## Estrutura de ficheiros
- **Modificar** `frontend/src/lib/api.js` — `posApi` (instância) + `posAPI` (login/caixa) + wrappers POS dos endpoints reutilizados + `adminPosAPI` (users/settings/device-token).
- **Modificar** `frontend/src/App.js` — rota `/pos` (fora do `ProtectedRoute` de admin) + `/admin/pos`.
- **Modificar** `frontend/src/components/AdminLayout.js` — nav "Pedidos"→"POS" (`/admin/orders`→`/admin/pos`).
- **Criar** `frontend/src/pages/admin/AdminPos.js` — gestão (utilizadores + definições + Iniciar POS).
- **Criar** `frontend/src/pages/pos/PosApp.js` — shell do `/pos` (guard device token + máquina de estados).
- **Criar** `frontend/src/pages/pos/PosLogin.js`, `PosAbrirCaixa.js`, `PosHome.js` (mesas+balcão), `PosFecharCaixa.js`.
- **Criar/mover** o checkout de mesa reutilizável (ver Task 6).

---

### Task 1: Camada de API do POS (`posApi` + métodos)

**Files:** Modify `frontend/src/lib/api.js`.

**Interfaces — Produces:**
- `posApi` — `axios.create({ baseURL: API_BASE })` com interceptor que adiciona `X-Device-Token` (de `localStorage.pos_device_token`) e `X-POS-Token` (de `localStorage.pos_token`), se existirem. **Não** adiciona `Authorization`.
- `posAPI = { login(pin), cashCurrent(), cashOpen(opening_amount), cashMovement(type, amount, reason), cashClose(counted_amount), cashZ(id) }` → `POST /pos/login`, `GET/POST /pos/cash/...`, `GET /pos/cash/{id}/z` (via `posApi`).
- `posCheckout = { overview(), paymentMethods(), getBill(n), closeTable(n, data), setItemDiscount(o,i,pct), removeItem(o,i), printConsulta(n), freeTable(n) }` → os MESMOS caminhos que o `checkoutAPI`/`tablesAPI` admin, mas via `posApi` (auth device+POS).
- `adminPosAPI = { listUsers(), createUser(d), updateUser(id,d), deleteUser(id), getSettings(), saveSettings(d), createDeviceToken(label) }` → `/admin/pos/*` via `api` (admin JWT).

- [ ] **Passo 1: Implementar** as instâncias/métodos acima em `api.js`, seguindo o estilo dos exports existentes (`checkoutAPI`, `reportsAPI`). O interceptor do `posApi`:
```js
export const posApi = axios.create({ baseURL: API_BASE, headers: { 'Content-Type': 'application/json' } });
posApi.interceptors.request.use((config) => {
  const dev = localStorage.getItem('pos_device_token');
  const pos = localStorage.getItem('pos_token');
  if (dev) config.headers['X-Device-Token'] = dev;
  if (pos) config.headers['X-POS-Token'] = pos;
  return config;
});
```
- [ ] **Passo 2: Verificar** — `cd frontend && npx craco build` passa. (Sem browser ainda; é só a camada.)
- [ ] **Passo 3: Commit** — `git commit -m "POS frontend: camada de API (posApi device+POS token, posAPI, adminPosAPI)"`

---

### Task 2: Nav "Pedidos"→"POS" + página de gestão `/admin/pos`

**Files:** Modify `AdminLayout.js` (nav), `App.js` (rota). Create `pages/admin/AdminPos.js`.

**Interfaces — Consumes:** `adminPosAPI` (Task 1).

- [ ] **Passo 1: Nav** — em `AdminLayout.js`, mudar `{ path: '/admin/orders', label: 'Pedidos', icon: ClipboardList }` para `{ path: '/admin/pos', label: 'POS', icon: ClipboardList }`.
- [ ] **Passo 2: Rota** — em `App.js`, adicionar `<Route path="/admin/pos" element={<ProtectedRoute><AdminPos /></ProtectedRoute>} />` (manter `/admin/orders` a apontar para `AdminOrders` por agora, ou redirecionar `/admin/orders`→`/admin/pos`).
- [ ] **Passo 3: Página `AdminPos.js`** (dentro de `<AdminLayout title="POS">`), 3 cartões (estilo `AdminReports.js`):
  - **Utilizadores**: lista (`listUsers`) + form criar (nome + PIN 4 díg.) + ativar/desativar (`updateUser`) + apagar (`deleteUser`). Validar PIN = 4 dígitos no cliente.
  - **Definições**: `getSettings` → form com Switch `require_open_cash`, dropdown `cash_payment_method_id` (opções de `posCheckout.paymentMethods()` OU `checkoutAPI.paymentMethods()`), input `z_footer_text`. Guardar com `saveSettings` **enviando o objeto completo** (o PUT substitui tudo).
  - **Iniciar POS**: botão → `createDeviceToken('terminal')` → guardar o `token` devolvido em `localStorage.pos_device_token` → `window.open('/pos', '_blank')`. Mostrar aviso "abre uma janela nova do POS neste dispositivo".
- [ ] **Passo 4: Verificar** — build passa; no browser (admin logado) a aba mostra "POS", cria um utilizador, guarda definições, e "Iniciar POS" abre `/pos` (mesmo que ainda em branco).
- [ ] **Passo 5: Commit** — `git commit -m "POS frontend: aba POS + gestao (utilizadores, definicoes, Iniciar POS)"`

---

### Task 3: Shell do `/pos` + guard do device token + login PIN

**Files:** Modify `App.js` (rota `/pos` FORA do ProtectedRoute admin). Create `pages/pos/PosApp.js`, `pages/pos/PosLogin.js`.

**Interfaces — Consumes:** `posAPI.login`, `posAPI.cashCurrent`.

- [ ] **Passo 1: Rota** — `App.js`: `<Route path="/pos" element={<PosApp />} />` (sem ProtectedRoute — o guard é o device token + PIN).
- [ ] **Passo 2: `PosApp.js`** — máquina de estados por `useState`:
  - Se `!localStorage.pos_device_token` → ecrã "Este dispositivo não está autorizado. Abre o POS pelo botão **Iniciar POS** no painel (Admin → POS)." (sem login).
  - Senão, se sem `pos_token` (ou inválido) → `<PosLogin/>`.
  - Senão → resolver a caixa (Task 4).
- [ ] **Passo 3: `PosLogin.js`** — teclado numérico (0-9, limpar, OK), mostra 4 pontos. Ao 4º dígito (ou OK) → `posAPI.login(pin)`; sucesso → `localStorage.pos_token = token`, guardar `user` no estado, avançar; erro → toast "PIN inválido" + limpar. Ecrã cheio, tema maroon.
- [ ] **Passo 4: Verificar** — abrir `/pos` sem device token → mensagem; com device token (via Iniciar POS) → teclado PIN; PIN certo → passa; PIN errado → erro.
- [ ] **Passo 5: Commit** — `git commit -m "POS frontend: shell /pos + guard device token + login PIN"`

---

### Task 4: Porta da caixa + Abrir Caixa

**Files:** Modify `PosApp.js`. Create `pages/pos/PosAbrirCaixa.js`.

**Interfaces — Consumes:** `posAPI.cashCurrent`, `posAPI.cashOpen`.

- [ ] **Passo 1:** Depois do login, `PosApp` chama `posAPI.cashCurrent()`: se não houver sessão aberta → `<PosAbrirCaixa/>`; se houver → `<PosHome/>` (Task 5).
- [ ] **Passo 2: `PosAbrirCaixa.js`** — ecrã "Caixa Fechada" (ícone) + campo **Montante** (pode ser 0) + botão **Abrir Caixa** → `posAPI.cashOpen(montante)` → em sucesso, re-resolver a caixa (mostra `PosHome`). (Espelha a 1ª foto que o dono enviou.)
- [ ] **Passo 3: Verificar** — com caixa fechada, `/pos` mostra Abrir Caixa; abrir com 0 → passa à Home; reabrir a app → continua aberta (não pede outra vez).
- [ ] **Passo 4: Commit** — `git commit -m "POS frontend: porta da caixa + Abrir Caixa"`

---

### Task 5: Home do POS — grelha de mesas + Balcão + Fechar Caixa

**Files:** Create `pages/pos/PosHome.js`. Modify `PosApp.js`.

**Interfaces — Consumes:** `posCheckout.overview()`.

- [ ] **Passo 1: `PosHome.js`** — cabeçalho com o nome do operador + estado da caixa + botão **Fechar Caixa** (Task 7). Corpo: **grelha de mesas** (mirar o layout de `AdminOrders.js`: cartões por mesa, cor "ocupada" vs "livre", via `posCheckout.overview()` com refresh periódico) + um cartão **"Balcão"** que na Fase 1 mostra **"Brevemente"** (Fase 2). Legenda "Mesa Livre / Mesa Ocupada".
- [ ] **Passo 2:** Clicar numa mesa → abre o checkout dessa mesa (Task 6).
- [ ] **Passo 3: Verificar** — com caixa aberta, ver a grelha; mesas ocupadas (com pedidos QR) aparecem marcadas; Balcão diz "Brevemente".
- [ ] **Passo 4: Commit** — `git commit -m "POS frontend: home (mesas + balcao placeholder + botao fechar caixa)"`

---

### Task 6: Checkout de mesa no POS (reutilizar o atual, via posApi)

**Files:** Refactor the checkout out of `pages/admin/AdminOrders.js` into a shared component `pages/checkout/TableCheckout.js` that takes an **`apiClient` prop** (the `checkoutAPI`-shaped object). Use it from `AdminOrders` (with the admin `checkoutAPI`) AND from `PosHome` (with `posCheckout`).

**Interfaces — Consumes:** `posCheckout.*` (getBill, closeTable, setItemDiscount, removeItem, printConsulta, freeTable, paymentMethods).

- [ ] **Passo 1: Extrair** o painel de checkout de mesa (o Dialog de 2 painéis já existente em `AdminOrders.js` — total, separar/dividir, desconto por item, produto manual, emitir) para `TableCheckout.js`, recebendo `api` (o objeto de métodos) e `tableNumber` por props. Substituir as chamadas `checkoutAPI.x(...)` por `props.api.x(...)`. Manter o comportamento idêntico (é o checkout ATUAL, não o estilo-Vendus).
- [ ] **Passo 2:** `AdminOrders.js` passa a usar `<TableCheckout api={checkoutAPI} .../>` (comportamento inalterado no admin).
- [ ] **Passo 3:** `PosHome.js` usa `<TableCheckout api={posCheckout} .../>` — assim o fecho vai por `posApi` (device+POS token) → o backend resolve `kind="pos"` → grava `pos_sales` e liga à caixa.
- [ ] **Passo 4: Verificar** — build passa; no admin o checkout de mesa funciona como antes; no `/pos` (caixa aberta) abrir uma mesa, ver a conta, e (em homologação com Vendus) fechar → a venda fica ligada à sessão de caixa.
- [ ] **Passo 5: Commit** — `git commit -m "POS frontend: checkout de mesa reutilizavel (admin + POS via posApi)"`

---

### Task 7: Fechar Caixa + relatório Z

**Files:** Create `pages/pos/PosFecharCaixa.js`. Modify `PosHome.js`.

**Interfaces — Consumes:** `posCheckout.overview()` (mesas abertas), `posAPI.cashClose`, `posAPI.cashMovement` (sangria/reforço, opcional na Fase 1).

- [ ] **Passo 1: `PosFecharCaixa.js`** — ao clicar "Fechar Caixa": (a) se houver **mesas abertas** (overview), avisar e deixar cancelar/continuar; (b) ecrã de **contagem**: campo **Montante contado**; (c) `posAPI.cashClose(contado)` → mostra o **Z** devolvido (por forma de pagamento, esperado vs contado, **diferença**, aviso de reconciliação se houver) e confirma que foi enviado para impressão. Botão "Terminar" → volta ao login/estado inicial (limpa `pos_token`).
- [ ] **Passo 2:** (opcional Fase 1) botões **Sangria/Reforço** na Home → `posAPI.cashMovement` (dialog simples: valor + motivo).
- [ ] **Passo 3: Verificar** — abrir caixa, (em homologação) fechar uma mesa em dinheiro, Fechar Caixa → esperado = abertura + dinheiro; diferença calculada; Z aparece e imprime.
- [ ] **Passo 4: Commit** — `git commit -m "POS frontend: fechar caixa + relatorio Z"`

---

## Auto-revisão (checklist do plano)
- **Cobertura:** camada API POS (T1), gestão+nav (T2), shell+login (T3), abrir caixa (T4), home mesas+balcão (T5), checkout reutilizável via posApi (T6), fechar caixa+Z (T7). ✅
- **Auth correta:** `posApi` nunca envia JWT de admin (T1); o checkout no POS usa `posCheckout` → backend resolve `kind="pos"` → grava `pos_sales` (T6). Ponto MAIS crítico — o revisor tem de o confirmar.
- **Sem TDD:** o frontend não tem harness; gate = build + browser. Verificação ao vivo (fecho real de mesa/caixa) só em **homologação** com Mongo+Vendus reais.
- **Não incluído (fases seguintes):** Balcão a sério (Fase 2), faturação estilo Vendus + diálogo do produto (Fase 3).
- **Deploy:** só depois desta fase + homologação; admins fazem re-login uma vez (mudança `typ` nos tokens, backend).
