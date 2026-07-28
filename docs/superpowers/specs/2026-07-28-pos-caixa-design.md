# POS + Caixa (estilo Vendus) — Documento de Design

**Data:** 2026-07-28 · **Revisto:** 2026-07-28 (após revisão multi-ângulo)
**Projeto:** Pizzaria Lenha e Brasa (FastAPI + React + Mongo, NO AR em pedido.lenhaebrasa.com)
**Objetivo:** Transformar a app no **POS principal** do restaurante — parecido com o Vendus — para deixar de usar o POS do Vendus para umas coisas e a "Caixa API" para outras. Passa a ser **tudo na app**, com **sessão de caixa (abrir/fechar) 100% na app**, utilizadores com PIN, venda ao balcão e faturação estilo Vendus. As faturas continuam a ser emitidas como **FS na "Caixa API" do Vendus** (fiscais, comunicadas à AT), como já hoje.

> ⚠️ **Sistema fiscal ao vivo.** Cada FS é comunicada à AT e é irreversível (só se corrige com Nota de Crédito no Vendus). O design abaixo dá **prioridade absoluta a: (a) não cobrar duas vezes, (b) o Z bater certo com a gaveta física**. As secções §2.4 (atomicidade/idempotência) e §4 (reconciliação) são o coração disto e não são opcionais.

---

## 1. Decisões (validadas com o dono)

| Tema | Decisão |
|---|---|
| Modelo de caixa | **Caixa 100% na app**: abertura com fundo, soma vendas por forma de pagamento, fecho com esperado vs contado + relatório Z. FS continuam a ir à "Caixa API" do Vendus. |
| Utilizadores | **Identificação simples**: nome + PIN de 4 dígitos. Sem níveis de permissão. Fica registado quem abriu/fechou a caixa e quem fez cada venda. |
| Balcão | **Venda rápida (paga logo)**: produtos → imprimir → faturar/pagar. Sem morada. Vários em simultâneo. |
| Diálogo do produto | **Essencial**: Quantidade, Preço unitário, IVA, Desconto (% ou €). |
| Fecho de caixa | **Completo**: esperado vs contado → diferença; sangria/reforço; relatório Z por forma de pagamento (imprimível). "Tudo parecido com o Vendus." |

**Preferências do dono:** PT-PT, construir **por fases** (cada fase completa e testável).

---

## 2. Arquitetura

### 2.1 O que se reaproveita (já existe)
- **Emissão de FS** (`close_table` → `create_invoice`, `doc_type="FS"`, `output="escpos"`, register "Caixa API" 358144579).
- **Descontos** por item (`items.{idx}.discount_pct`) e global (`global_discount_pct`) → Vendus `discount_percentage`.
- **Separar/Dividir conta** e **rodízio parcial** no fecho (que emitem **vários** documentos por fecho — ver §2.3).
- **Impressão** pela ponte APK (ESC/POS server-side). **Métodos de pagamento** do Vendus (`/vendus/payment-methods`).
- **Grelha de mesas** / `tables-overview`. **`app_sales_summary(date)`** e **`list_app_invoices`** (leem o registo Vendus por `register_id`) — a **base da reconciliação** (§4).
- **QR dos clientes** — continua em paralelo (`db.table_sessions`, endpoints públicos), **ortogonal** às `cash_sessions` (§2.5).

### 2.2 Coleções novas
- **`pos_users`**: `{id, name, pin_hash (bcrypt), active, created_at}`. PIN 4 díg. nunca em claro.
- **`pos_devices`**: `{id, token_hash, label, active, created_at, expires_at}`. Persistência server-side do device token (§2.6).
- **`cash_sessions`** (a "caixa"): ver §4.1.
- **`pos_sales`** (ligação venda↔caixa): **UMA linha por DOCUMENTO fiscal emitido** — não por chamada (§2.3). `{id, cash_session_id, pos_user_id, vendus_document_id (ÚNICO), doc_number, amount, payment_method_id, payment_method_title, kind: "mesa"|"balcao"|"estorno", table_number?, created_at}`. **Índice único** em `vendus_document_id` (idempotência) e índice em `cash_session_id`.
- **`pos_settings`** (`db.settings` key `"pos"`): `{require_open_cash: true, cash_payment_method_id: <id Vendus do "Dinheiro">, z_footer_text, ...}`.

### 2.3 `pos_sales` = uma linha por documento (não por chamada)
Um único `close_table` pode emitir **N faturas**: `separar/dividir conta` (uma FS por pessoa) e **rodízio parcial** (documento a documento). O `close_table` já constrói uma lista `invoices[]` e devolve `docs[]` (as respostas do Vendus). O hook de gravação, **no fim** do fecho, **percorre `docs[]`** e insere **uma linha `pos_sales` por documento** (`vendus_document_id = doc["id"]`, `doc_number = doc["number"]`, `amount = invoices[i]["amount"]`, método e `pos_user_id`). Assim o Z nunca sub-conta uma conta dividida. Casos de teste obrigatórios: `split n>1` e rodízio parcial.

### 2.4 Atomicidade e idempotência fiscal (❗ crítico)
Problema: a FS é comunicada à AT **antes** dos writes em Mongo. Uma falha (luz, browser, timeout) *depois* de emitir e *antes* de gravar deixa a mesa "por pagar" → o staff refatura → **2ª FS real** ao mesmo cliente.

Regras (a implementar já na Fase 1, no `close_table`):
1. **Referência estável por tentativa de fecho:** `external_reference = f"mesa-{N}-{cash_session_id}-{hash(itens+valores)}"` (determinística), **não** `mesa-{N}-{timestamp}`. Um retis do mesmo fecho gera a **mesma** referência.
2. **Dedup antes de emitir:** antes de chamar `create_invoice`, procurar no Vendus (`list_app_invoices`/por `external_reference`) se já existe FS com essa referência; se existir, **reutilizar** esse documento em vez de emitir outro.
3. **Estado `a_faturar`:** marcar a mesa/venda como `a_faturar` (com a `external_reference` prevista) **antes** de chamar o Vendus; ao arrancar a app, detetar vendas nesse estado e **reconciliar** (se a FS existe no Vendus → seguir para o fim; senão → limpar) em vez de re-emitir.
4. **Idempotência do Z:** `pos_sales` com **índice único em `vendus_document_id`** — reinserir o mesmo documento é no-op, nunca duplica no Z.

### 2.5 `cash_sessions` ≠ `table_sessions`
São conceitos **ortogonais**: `table_sessions` (fluxo QR do cliente, por mesa) já existe e é usado no `close_table`. A caixa é `cash_sessions`. O parâmetro no backend chama-se sempre **`cash_session_id`** para não haver conflação (risco fiscal).

### 2.6 Autenticação — auth-duplo (❗ bloqueador da Fase 1)
Hoje **todos** os endpoints reutilizados exigem **JWT de admin** (`get_current_user`, ~50 chamadas): `get_table_bill` (`/tables/{n}/bill`), `tables-overview`, `vendus/payment-methods`, `close_table`, `set_item_discount`, `void_order_item`, `print-consulta`, `free`, adicionar item manual, etc. Sem mudança, o `/pos` (device token) dá **401** e nem lista mesas.

Solução (Fase 1): dependência **`get_pos_or_admin`** que aceita **JWT de admin OU device token válido** (`pos_devices`: hash+active+não-expirado). Aplicar a **todo o conjunto** que o `/pos` consome (enumerar no plano). Além disso:
- **`/pos/login`** (PIN) devolve um **token de sessão POS de curta duração** ligado ao `pos_user_id`. Endpoints sensíveis (abrir/fechar caixa, sangria/reforço, faturar) derivam o **operador desse token** e **ignoram** qualquer `pos_user_id` vindo do body (responsabilização não-falsificável).
- **Emissão fiscal** exige a sessão POS curta (não só o device token permanente). Device token = autoriza o dispositivo; sessão POS = identifica a pessoa.
- **PIN**: hash bcrypt, rate-limit por dispositivo. Considerar re-pedir PIN em operações sensíveis (fechar caixa, sangria).
- **Device token**: criado em `POST /admin/pos/device-token` (devolvido **uma vez**), com **expiração/rotação** (não "nunca expira"); revogar = `active=false`.

---

## 3. Rotas e ecrãs (frontend)

### 3.1 Admin — "Pedidos" passa a "POS" (gestão)
- Renomear o item de menu em **`AdminLayout.js`** ("Pedidos"→"POS") e a rota `/admin/orders`→`/admin/pos`.
- **Mover** a grelha de mesas + checkout (`AdminOrders.js`, `AdminCheckout.js`) para o `/pos`; `/admin/pos` passa a ser **gestão** (Definições, Utilizadores, Iniciar POS).
- **Deixar `AdminTables` (`/admin/tables`, CRUD de mesas + QR) INTACTO** — são duas entidades: `/admin/pos` (gestão POS) vs `/admin/tables` (CRUD). Verificar que Dashboard/Reports não importam esses componentes.

### 3.2 Janela POS (`/pos`) — ecrã cheio
1. **Login PIN** (teclado numérico) → sessão POS curta (identifica o utilizador).
2. **Caixa fechada** → **"Abrir Caixa"** (montante, pode ser 0).
3. **Caixa aberta** → grelha de **mesas** + cartão **Balcão** + botão **Fechar Caixa**. *Sem caixa aberta não se fatura* (§8).
4. **Mesa** → checkout (Fase 1: o atual; Fase 3: estilo Vendus).
5. **Balcão** (Fase 2) → produtos → imprimir → faturação → paga logo.
6. **Faturação** (Fase 3): clique no produto → diálogo (qtd/preço/IVA/desconto); "Finalizar" → separar conta; "Emitir Documento" → FS + troco.
7. **Fechar Caixa** → §4.

---

## 4. Sessão de caixa e relatório Z

### 4.1 Modelo `cash_sessions`
```
{ id, status:"open"|"closed",
  opened_by, opened_by_name, opened_at, opening_amount,
  movements:[ {type:"sangria"|"reforco", amount, reason?, by, at} ],
  closed_by, closed_by_name, closed_at,
  counted_amount, expected_cash, difference,
  reconciliation: { vendus_total, pos_sales_total, orphans:[...], ok:bool },
  totals_by_method: { "<title>": {count,total} }   # snapshot no fecho
}
```
**Unicidade atómica** (uma só caixa aberta): **índice único parcial** em `{status:"open"}` **ou** `find_one_and_update` atómico que devolve a existente em vez de criar 2ª. Teste de abertura concorrente na Fase 1.

### 4.2 Fonte de verdade do Z = registo Vendus (não só Mongo)
O Z lê os totais **do registo Vendus** para a **janela temporal da sessão** (`opened_at`→`closed_at` ou "agora") **filtrado por `register_id`** (reutilizar `app_sales_summary`/`list_app_invoices` **por janela temporal, nunca por string de data** — §4.5). `pos_sales` serve para **atribuição** (quem vendeu) e **deteção de anomalias**. Assim, qualquer FS na Caixa API na janela conta (mesa, balcão, ou entrada manual), e cruza-se com `pos_sales` para apanhar órfãos.

**Método "dinheiro" por ID:** a gaveta soma pelo **`payment_method_id`** configurado em `pos_settings.cash_payment_method_id` (escolhido no admin a partir de `/vendus/payment-methods`), **não** por comparar a string "Dinheiro" (o Vendus pode renomear p/ "Numerário").

```
vendas_dinheiro   = soma(docs da sessão onde payment_method_id == cash_payment_method_id)
esperado_dinheiro = opening_amount + vendas_dinheiro + reforços − sangrias
diferenca         = counted_amount − esperado_dinheiro    # >0 sobra, <0 falta
```

### 4.3 Reconciliação obrigatória no fecho
Cruzar **totais por método do Vendus** (janela+register) com **`pos_sales`**: se divergirem (nº docs ou total), **avisar/bloquear** e mostrar os **documentos órfãos**. Cobrir: (a) FS no Vendus mas sem `pos_sales`; (b) vendas manuais batidas à mão no Vendus; (c) mesas fechadas pelo fluxo admin legado. **Nunca fechar a gaveta só com base no Mongo.**

### 4.4 Estornos / Notas de Crédito
Modelar antes de confiar no Z: como o Z lê o **registo Vendus líquido**, uma NC emitida no Vendus **já reduz** o total da janela. Registar também em `pos_sales` uma linha `kind:"estorno"` (valor negativo, ligada ao doc de NC) para atribuição. Definir o fluxo de emitir NC (no Vendus/ backoffice) e como se reflete no Z da sessão. *(Fluxo de anulação na app pode ser fase futura; para já a NC faz-se no Vendus e o Z reflete-a por ler o registo.)*

### 4.5 Sessão a atravessar a meia-noite
Toda a leitura Vendus é por **janela temporal** (`opened_at`→`closed_at`) + `register_id`, **nunca** por string `YYYY-MM-DD` (o `app_sales_summary` atual filtra por `startswith(data)` — insuficiente p/ sessões que cruzam a meia-noite). Cuidado com o **fuso** (timestamps do Vendus podem não ser Europe/Lisbon; o código mistura UTC e Lisbon). Documentar a relação entre o **relatório automático das 23:30** (por data) e o **Z de sessão** (por janela) para não haver "duas verdades" do mesmo dinheiro.

### 4.6 Relatório Z (imprimível)
Cabeçalho (restaurante, "Fecho de Caixa", data/hora, aberto/fechado por) · totais **por forma de pagamento** · movimentos · fundo, esperado, contado, **diferença** · aviso de reconciliação se houver órfãos. Enviado à ponte ESC/POS.

---

## 5. Faturação estilo Vendus (Fase 3)

Layout 2 painéis (como a 4ª foto). **Direita:** produtos (Produto, Qtd, Preço) + botões (Delivery, Pessoa, Separar/Dividir Conta, Consulta, Finalizar). **Esquerda:** Total, Cliente, Pagamento, Emitir Documento, valor entregue + **Troco**, Mais Opções (desconto global).

**Dois modos de clique no produto:**
- **Edição (antes de Finalizar):** abre **diálogo do produto** — Quantidade, **Preço unitário (o `unit_price` da LINHA, ≠ `base_price` do produto)**, **IVA**, Desconto (% ou €).
- **Separar (após Finalizar, com "Separar Conta"):** clicar passa o produto p/ a esquerda p/ cobrar à parte (mecanismo existente).

**Overrides por linha (❗ fiscal):** um novo `POST /orders/{id}/items/{idx}/edit` grava `unit_price`/`tax_id`/`quantity` por linha. O `close_table` tem de **ler estes overrides ANTES** de cair no IVA do produto (`tax_by_prod`) e no preço do pedido — em **ambos os ramos** (à la carte **e** extras de rodízio). `set_item_discount` (só grava `discount_pct`) **não chega**; sem isto a FS real usaria o IVA/preço antigos.

---

## 6. Endpoints (backend)

**Gestão (admin JWT):** `GET/POST/PUT/DELETE /admin/pos/users` · `GET/PUT /admin/pos/settings` · `POST /admin/pos/device-token` (+ revogar).
**POS (device token + sessão POS):** `POST /pos/login` (PIN→token curto) · `GET /pos/cash/current` · `POST /pos/cash/open` · `POST /pos/cash/movement` · `POST /pos/cash/close` (calcula, reconcilia, gera Z) · `GET /pos/cash/{id}/z`.
**Faturação (`get_pos_or_admin`, exige caixa aberta):** reutiliza `/tables/{n}/bill`, `/tables/{n}/close` (agora resolve `cash_session_id` **no servidor** e grava `pos_sales` por documento) e novos p/ balcão (`POST /pos/counter/checkout`). **Diálogo:** `POST /orders/{id}/items/{idx}/edit` (qtd/preço/IVA) + `set_item_discount` evoluído p/ €.

**Nomes reais do modelo (para o plano):** produto = **`base_price`**, `vendus_tax_id`, **`rodizio_incluido`** (`'nao'|'ambos'|'completo'`), **`rodizio_only`**; linha do pedido = **`unit_price`**, `quantity`.

---

## 7. Fases (reordenadas: gaveta correta antes do polish)

### Fase 1 — Fundação + caixa correta (só mesas)
Entregável: iniciar POS, login PIN, abrir caixa, **faturar mesas** (checkout atual), **fechar caixa com Z reconciliado**. Inclui **auth-duplo (§2.6)**, **idempotência fiscal (§2.4)**, **`pos_sales` por documento (§2.3)**, **reconciliação vs Vendus (§4)**, unicidade atómica da caixa.
- ⚠️ O Z desta fase é **só-mesas**. Enquanto o balcão estiver fora da app (feito no Vendus), dar uma **válvula de escape**: registar essas vendas como **ajuste/reforço** no Z, ou lançá-las manualmente. O texto do ecrã deixa isto claro.

### Fase 2 — Balcão (completa a gaveta)
Entregável: cartão **Balcão** → produtos → imprimir → faturação (checkout atual) → paga logo → FS na Caixa API + `pos_sales`. **Depende da Fase 1** (sessão + pos_sales), **não** da faturação nova. A partir daqui **todas** as vendas passam pela app → o Z bate a 100% com a gaveta.

### Fase 3 — Faturação estilo Vendus (polish)
Entregável: diálogo do produto (qtd/preço/IVA/desconto) com **overrides no `close_table`** (§5), "Finalizar→separar", visual Vendus. Aplica-se a mesas e balcão.

---

## 8. Regras e casos-limite
- **Faturar exige caixa aberta:** o servidor resolve a **única `cash_session` `open`**; se vier por device token e não houver → **409 "Abra a caixa primeiro"**. Se vier por **admin JWT (legado)** → passa sem gravar `pos_sales`. **Nunca** aceitar `cash_session_id` do body.
- **Abrir com uma já aberta** → devolve a atual (atómico, §4.1).
- **Fechar com mesas por fechar** → listar e confirmar/cancelar.
- **Vendus indisponível ao emitir** → erro claro; venda não entra em `pos_sales`. **Crash após emitir** → recuperado por §2.4 (estado `a_faturar` + dedup).
- **Duas janelas POS** → partilham a única caixa.
- **PIN errado** → mensagem + rate-limit.
- **Pagamento misto (multi-tender)** — *opcional/futuro*: lista `{método, valor}` em `create_invoice` e `pos_sales` (uma linha por tranche). Fora do âmbito das Fases 1–3 salvo pedido do dono.

## 9. Pressupostos
- Uma só caixa para o restaurante. Sem níveis de permissão (fase futura). Device token com expiração/rotação. Anulação/NC feita no Vendus (a app reflete via reconciliação); fluxo de NC na app é fase futura.
