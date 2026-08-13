# POS — 3 melhorias: gaveta com caixa fechado · balcão editável · fecho + backoffice

**Data:** 2026-08-09
**Autor:** Matheus (dono) + Claude
**Estado:** aprovado (design), por implementar
**Âmbito:** app da pizzaria Lenha e Brasa (FastAPI `backend/` + React `frontend/`), em produção em `pedido.lenhaebrasa.com`.

## Contexto

Três pedidos do dono, independentes entre si, todos no POS/backoffice. O mapa do código (feito antes deste spec) confirmou que o essencial já existe no backend — o trabalho é sobretudo de UX, de um endpoint novo, e de mover/reconstruir relatório. Nenhuma das três mexe na emissão de faturas de forma a criar risco de duplicação fiscal.

## Decisões tomadas (do brainstorming)

1. **Gaveta:** botão no ecrã de *Caixa Fechada* (depois do login por PIN); **com registo** de quem abre e quando.
2. **Balcão:** depois de imprimir, o pedido fica **totalmente editável** (acrescentar **e** editar/anular); reimprime **o pedido completo** para a **cozinha** (não incremento), marcado como atualizado; **sem** pré-conta na reimpressão.
3. **Fecho de caixa:** **parar de imprimir** o talão Z do Vendus (2º papel). **Backoffice** ganha: lista de faturas, produtos vendidos com valor €, e intervalo de datas. **Faturação a prazo: não se constrói** (venda é sempre paga na hora).

---

## Fluxo 1 — Gaveta com caixa fechado (+ registo)

### Como é hoje
- `POST /api/pos/cash/drawer` (`backend/server.py:3393-3418`) já **não** exige caixa aberta — só `get_pos_or_admin` (device token OU admin). Envia um pulso ESC/POS (`\x1b\x70\x00\x19\xfa`) como print job `cashier`. **Não regista nada**, nem com caixa aberto.
- O que impede abrir com caixa fechado é **puramente o frontend**: o botão "Abrir Gaveta" vive no menu "Caixa" do `PosHome`, que só é montado com sessão aberta (`PosApp.js`). Com caixa fechado o operador vê o `PosAbrirCaixa` (só montante + "Abrir Caixa").

### Mudança
- **Frontend** (`frontend/src/pages/pos/PosAbrirCaixa.js`): acrescentar botão secundário **"Abrir Gaveta"** neste ecrã (já atrás do PIN, operador identificado), reutilizando a lógica de `abrirGaveta` do `PosHome.js:147-158`. `posAPI` já está importado.
- **Backend** (`backend/server.py:3393-3418`): o endpoint passa a **registar cada abertura** numa coleção `drawer_opens` com `{operator_id, operator_name, at (UTC), had_open_session: bool, cash_session_id?}`. Ler o operador do `X-POS-Token` quando existir; se vier por JWT admin, `operator_name="Administrador"`. O registo aplica-se a **todas** as aberturas (caixa aberto ou fechado), para o histórico ser completo.
- **Backoffice** (`AdminReports.js` + `GET /admin/report-data`): nova secção pequena **"Aberturas de gaveta"** — lista `hora · operador · (caixa aberto/fechado)` dentro do período selecionado.

### Fiscal / risco
- Nenhum risco fiscal: o pulso não emite documento nem chama o Vendus, não afeta a reconciliação. O registo é controlo interno (anti-furto). Manter a ação **atrás do PIN** (não na lock screen antes do PIN).

### Testes
- Backend: teste de que `POST /pos/cash/drawer` grava um `drawer_opens` com o operador correto (com e sem sessão aberta).

---

## Fluxo 2 — Balcão editável depois de imprimir

### Como é hoje
- No `PosBalcao.js`, `printed = orderId != null`. Depois de "Imprimir Pedido" (`create_counter_order`, `server.py:3788-3874`, cria **um** doc `orders` `source=balcao`, `status=received`, `paid=false`), o **frontend bloqueia tudo** (catálogo, +/-, edição). Mas o documento continua **mutável no backend** até ao checkout — não há endpoint para o alterar.
- `checkout_counter_order` (`server.py:3904-4091`) reconstrói os itens Vendus a partir de `order.items` **frescos** e recalcula o total; `ext_ref = balcao-{order_id}` estável + dedup + paid-guard → **uma só FS** por pedido.
- Impressão: `_enqueue_order_prints` (`server.py:1271-1315`) sem impressoras registadas (caso do APK-ponte) imprime o **pedido todo** e gera **cozinha + caixa**. Já existe o primitivo `order_snapshot` (`server.py:2313-2343`) para imprimir um subconjunto/estado específico.

### Mudança
- **Frontend** (`PosBalcao.js`): remover o bloqueio duro `printed`. Depois de imprimir, o carrinho continua editável (acrescentar linhas, mudar qtd/preço/IVA/desconto, anular). O botão principal passa a **"Reimprimir pedido"**; mantém-se **"Emitir Documento"** para o fecho fiscal.
- **Backend** — novo endpoint **`POST /pos/counter/{order_id}/update`**:
  - Guardas: pedido `source=balcao` existe (404); **recusa** se `paid` ou `cancelled`; exige **caixa aberta** (reutiliza `server.py:3805-3809`); valida overrides (`3827-3835`); filtra `rodizio_only`/indisponível (`3818-3823`).
  - Recebe a **lista completa de itens** atual do carrinho; reconstrói via `build_counter_items` (`backend/pos/counter.py:17-76`); **substitui** `orders.items` e **recalcula** `orders.total` sobre o conjunto completo (padrão do checkout `3971-3977` — nunca `$inc`).
  - **Reimprime o pedido completo só para a cozinha** via `order_snapshot` (nunca `_enqueue_order_prints`, que também imprime caixa), com marcador **«⚠️ ATUALIZADO — substitui o pedido anterior»** + hora no topo do talão.
  - Devolve `{order_number, total, items}`.
- **Frontend** (`frontend/src/lib/api.js`): `posCounter.updateOrder(orderId, items)` → `POST /pos/counter/${orderId}/update`.
- **Fatura:** sem mudança — "Emitir Documento" continua a emitir **uma FS com o estado final** (o checkout já lê itens frescos).

### Fiscal / risco
- **Uma só FS por venda** garantida (mesmo `order_id`/`ext_ref`, paid-guard, dedup). O endpoint **recusa** editar pedido já pago (senão a FS ficaria abaixo do servido).
- **Dupla preparação na cozinha:** o talão reimprime o pedido inteiro → a marca «ATUALIZADO — substitui o anterior» avisa a cozinha para descartar o anterior. (Decisão do dono; a marca é a mitigação.)
- **Corrida update-vs-checkout:** fechar a janela — recusar `update` se o pedido já não está `received`/em edição, ou o checkout marcar um estado antes de emitir.

### Testes
- Backend: `update` recusa pedido pago/cancelado; substitui itens e recalcula total; a FS pós-update reflete os itens finais; continua a ser 1 só FS.

---

## Fluxo 3 — Fecho de caixa + backoffice

### Como é hoje
- As 3 secções que o dono quer tirar (**produtos vendidos, faturação a prazo, lista de cada fatura**) **não existem** no ecrã de fecho (`PosFecharCaixa.js`) nem no talão Z da app (`backend/pos/z_report.py` — só forma de pagamento, movimentos, esperado/contado/diferença, reconciliação). Existem **só no talão Z do Vendus**, impresso como **2º print job** em `close_cash_session` (`server.py:3654-3673`, quando `vendus_resp.get("output")`). Esse talão é ESC/POS opaco gerado pelo Vendus.
- Backoffice (`GET /admin/report-data`, `server.py:4643-4761`, ecrã `AdminReports.js`): já tem produtos vendidos (só **quantidade**, dos nossos pedidos) e formas de pagamento (Vendus). **Não** tem lista fatura-a-fatura. É **só por dia** (um `date`).
- `VendusClient._summarize_docs` (`backend/vendus/client.py:218-277`) **já calcula** o campo `invoices` (`{label, time, amount, method, number}` por fatura, NC a subtrair) — usado no email diário — mas `get_report_data` **descarta-o** no return.

### Mudança
- **Fecho — parar de imprimir o talão Z do Vendus:** remover/condicionar o bloco `server.py:3654-3673`. **Manter** a chamada `_vendus_cash_close_sync` (`server.py:3604` / `3222-3237`) que **fecha o registador** no Vendus — só deixa de se **imprimir** o output. O talão de reconciliação da app e o fecho atómico (`3537-3598`) correm antes e ficam intactos. O Z oficial fica consultável no painel do Vendus.
- **Backoffice — lista de faturas** (dados já existem): guardar `invoices = _summ.get("invoices", [])` (`server.py:4692-4705`) e devolvê-lo no return (`4743-4761`); novo cartão **"Faturas emitidas"** em `AdminReports.js` — tabela **Nº · Hora · Pagamento · Valor**, com **notas de crédito assinaladas** (valor negativo).
- **Backoffice — produtos vendidos com valor €:** estender o cálculo (`server.py:4707-4721`) para somar **valor €** por produto além da quantidade, a partir dos nossos pedidos usando a **mesma via de preço da faturação** (`line_vendus`). **Rodízio:** os itens incluídos ficam a **€0** (coerente com a FS, onde o valor entra por pessoa) — mostrar nota na UI.
- **Backoffice — intervalo de datas:** `reportsAPI.getData` e `get_report_data` passam a aceitar `start`/`end`. Receita/faturas por intervalo via `VendusClient.app_sales_summary_window` (já existe, `client.py:161-193`); produtos por intervalo = agregação multi-dia dos nossos pedidos (query Mongo). **Aviso de performance:** intervalos grandes = uma chamada Vendus por dia — limitar (ex.: máx. 31 dias) e degradar em erro sem rebentar a página.
- **Faturação a prazo:** **não se constrói** (venda sempre paga na hora).

### Fiscal / risco
- Remover só o **print** do Z do Vendus **não parte** a reconciliação nem o fecho (correm antes e independentes). Perde-se o **comprovativo físico** do fecho de registador — fica consultável no painel do Vendus.
- **Não mexer** na secção "Por forma de pagamento" (ecrã `PosFecharCaixa.js:272-290` e `z_report.py:125-137`) — é o coração da reconciliação, não é o que o dono quer tirar.
- Receita/faturas **sempre do Vendus** (fonte fiscal), nunca de `order.total`. Produtos vendidos vêm dos nossos pedidos → a soma dos produtos **pode não bater** ao cêntimo com o faturado (rodízio/descontos); deixar isso claro na UI.
- Não alterar `_summarize_docs` sem correr `backend/tests/vendus/test_client.py` e `backend/tests/test_daily_report.py` (partilhado com o email diário).

### Testes
- Backend: `get_report_data` devolve `invoices` não vazio quando há faturas; produtos com valor €; intervalo start/end usa a janela Vendus; degradação quando o Vendus falha (`invoices=[]`, sem 500).

---

## Faseamento e deploy

Implementação em **3 fases deployáveis à parte**, por ordem de risco:

1. **Fase 1 — Gaveta** (mais simples; frontend + registo backend + secção no backoffice).
2. **Fase 2 — Fecho + backoffice** (parar o print do Z do Vendus; lista de faturas; produtos com €; intervalo).
3. **Fase 3 — Balcão** (endpoint `update` + desbloqueio do carrinho + reimpressão marcada).

Cada fase: ramo → revisão → merge no `main` → deploy rsync + rebuild → health. (Fluxo git do grupo.)

## Fora de âmbito

- Faturação a prazo (venda é sempre paga na hora).
- Alterar o conteúdo interno do talão Z do Vendus secção-a-secção (isso é config no painel do Vendus, não código).
- Paridade das novas secções no email diário (pode acrescentar-se depois, se o dono quiser).
- Exportar (PDF/CSV) a lista de faturas/produtos (pode acrescentar-se depois).
