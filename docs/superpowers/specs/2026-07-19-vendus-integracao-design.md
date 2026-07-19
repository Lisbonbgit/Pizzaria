# Design — Integração Vendus + conta da mesa + impressão por APK Android

> **Projeto:** Pizzaria "Lenha e Brasa" (app standalone: FastAPI + React + MongoDB)
> **Data:** 2026-07-19
> **Estado:** Design aprovado na forma (brainstorming). A aguardar revisão do spec antes do plano de implementação.
> **Base de código:** `git@github.com:Lisbonbgit/Pizzaria.git`, a partir da branch `migracao-hostinger`.

---

## 1. Objetivo

Transformar a app, que hoje é o sistema de pedidos **e** de "conta" próprio, numa app que **alimenta e reflete o Vendus** (POS/faturação já em uso na pizzaria). O Vendus passa a ser a **única fonte de verdade** da mesa, da conta e das vendas. Além disso, substituir o agente de impressão em Windows por um **APK Android** que imprime nas impressoras de rede.

### Fluxo-alvo (na voz do dono)
1. O pedido do cliente (via QR) cai **direto na mesa correspondente do Vendus**, por API.
2. Sempre que o QR é lido, se a mesa tiver conta aberta, o menu abre com uma opção à direita para **ver a conta da mesa**.
3. A mesa só deixa de ter valores **depois de o Vendus fechar a mesa com o pagamento** (feito pelo staff no POS).
4. Se o colaborador **adicionar algo manualmente no Vendus** (cliente pede diretamente), isso **aparece na conta da mesa** na app.
5. A **impressão** deixa de ser pelo agente Windows e passa a ser por um **APK Android** na rede local.

---

## 2. Decisões fechadas (brainstorming)

| # | Decisão | Escolha |
|---|---------|---------|
| 1 | Onde construir | **Evoluir a Pizzaria standalone** (FastAPI + React), não dentro do Menooo |
| 2 | Estado do Vendus | **Já em uso + API disponível** |
| 3 | Fonte do menu | **Menu na app** (fotos/categorias), cada produto **mapeado** a um produto Vendus |
| 4 | Leitura da conta | **Cliente fino, leitura on-demand** (Vendus = única verdade; poller leve só para o fecho) |
| 5 | Relatórios próprios da app | **Remover** (dashboard de stats + email diário) — Vendus é o dono das vendas |
| 6 | Aprovação do pedido | **Direto, mas com kill-switch** (auto-envia + imprime; interruptor para desligar) |
| 7 | Impressão de adições manuais | **Não** — o staff trata no POS do Vendus |
| 8 | Impressão | **APK Android na cozinha → várias impressoras de rede, routing por categoria** |
| 9 | Spike de validação | **Spec primeiro**; spike é a **Fase 0** do plano de implementação |

---

## 3. Restrições reais da API Vendus (investigadas, com fontes)

> Base: `https://www.vendus.pt/ws/v1.1/` · Auth: **HTTP Basic** com a API key como *username* (password vazia) · Formato **JSON** · Rate-limit ~**100 créditos / 20s** (headers `Rate-Limit-*`) · Modo de testes: `mode:"tests"` (sem valor fiscal).

**Viável e documentado:**
- **Lançar pedido na mesa:** `POST /documents` com `type:"DC"` (Consulta de Mesa = "conta aberta"), campos `rest_room`, `rest_table`, `occupation`, e `items[]`. As linhas usam `id`/`reference` do produto Vendus **ou** texto+preço (`title`, `gross_price`, `qty`, `tax_id`, `text`).
- **Mapear menu:** `GET /products` (id, reference, category_id, gross_price, tax_id) + `GET /products/categories`.
- **Fechar com pagamento:** `POST /documents` com `type:"FT"`/`"FR"`/`"FS"` + `payments[]` (feito pelo staff no POS; a **app não fatura**).

**Riscos / limites (moldam o design):**
- **R1 — Sem webhooks.** Só **polling**. `GET /documents?since=&until=` (sem filtro por mesa). A conta não chega em tempo real.
- **R2 — `rooms`/`tables` são só metadados** (id, title, parent). **Não** expõem estado ocupada/livre nem as linhas da conta. A conta reconstrói-se a partir dos **documentos DC**.
- **R3 — Incerteza não documentada (a validar no spike):**
  - (a) Dois `POST` DC à mesma mesa → **somam no mesmo documento** ou criam documentos separados?
  - (b) Item metido **manualmente no POS** cai **no mesmo DC** que a app lê? *(requisito das adições manuais)*
  - (c) Faturar (FT/FR) → **liberta a mesa** e é **detetável por polling**?

Fontes: [documents.doc](https://www.vendus.co.ao/ws/v1.1/documents.doc) · [documents/types.doc](https://www.vendus.pt/ws/v1.1/documents/types.doc) · [rooms.doc](https://www.vendus.pt/ws/v1.1/rooms.doc) · [tables.doc](https://www.vendus.pt/ws/v1.1/tables.doc) · [products.doc](https://www.vendus.pt/ws/v1.1/products.doc) · [overview.doc](https://www.vendus.pt/ws/v1.1/overview.doc) · [requests.doc](https://www.vendus.pt/ws/v1.1/requests.doc) · [consulta-de-mesa](https://www.vendus.pt/ajuda/consulta-de-mesa/) · [implementar-api-vendus](https://www.vendus.pt/ajuda/implementar-api-vendus/)

---

## 4. Fase 0 — Spike de validação (inegociável, antes de comprometer arquitetura)

Um script/notebook pequeno contra a **conta real em `mode:"tests"`** (não gera documentos fiscais). Responde às 3 perguntas de **R3** e a estas verificações:

1. **Append:** criar DC na mesa X; segundo `POST` DC na mesma mesa; ler `GET /documents?type=DC&view=detailed` → **1 ou 2 documentos**? As linhas do 2.º ficam no mesmo?
2. **POS↔API:** com a app "dona" de um DC, adicionar um item **à mão no POS do Vendus** na mesma mesa → aparece **no mesmo DC**?
3. **Fecho:** faturar (FT/FR) essa mesa no POS → o DC é consumido / a mesa fica livre? Isso vê-se por polling (`since=hoje`)?
4. **Ocupação/estado:** confirmar se algum campo de `tables` reflete "ocupada" (não assumir).
5. **Produtos/mapeamento:** confirmar que `reference`/`id` casam com o menu; confirmar `tax_id` esperado.
6. **Módulo de restauração/plano:** confirmar com o Vendus que `rooms`/`tables`/`DC` estão ativos na conta.

**Resultado → decide o desenho:**
- **Cenário "somam" (a=append, b=mesmo DC):** o caminho A é limpo (a app abre/segue um DC por mesa; conta = ler esse DC).
- **Cenário "separam" (documentos distintos por origem):** plano B — a app **reconcilia por polling** todos os DC do dia por `rest_table` (client-side) e apresenta a conta agregada; e usa `external_reference` para reconhecer os seus.

O spec abaixo assume o **cenário "somam"** como caminho principal e marca os pontos que mudam se o spike der "separam".

---

## 5. Frente A — Integração Vendus (núcleo)

### 5.1 Camada de serviço Vendus (novo módulo backend)
`backend/vendus/` (novo): cliente HTTP isolado e testável.
- **`client.py`** — wrapper sobre `httpx`/`requests`: Basic Auth, base URL por país, `mode` (tests/normal), timeout, e tratamento de **rate-limit** (lê `Rate-Limit-Remaining`/`Reset`, faz backoff). Todos os métodos devolvem tipos previsíveis e levantam exceções tipadas (`VendusError`, `VendusRateLimited`, `VendusUnavailable`).
- **`documents.py`** — `create_table_order(room, table, occupation, items, external_reference)`, `get_document(doc_id)`, `list_open_table_docs(since)`, `find_invoice_for_table(...)`.
- **`products.py`** — `list_products()`, `list_categories()` (para o ecrã de mapeamento).
- **`config.py`** — lê env: `VENDUS_API_KEY`, `VENDUS_BASE_URL`, `VENDUS_MODE`, `VENDUS_REGISTER_ID`. **Fail-closed**: sem `VENDUS_API_KEY`, os endpoints de integração recusam (não silenciosamente desligam).

> **Segredo:** a API key vive **só no backend** (`.env`), nunca no frontend. Adicionar ao `.env.example`.

### 5.2 Modelo de dados — mudanças concretas

**Produto** (`ProductCreate`/`Update`/`Response`, server.py:201-240) — acrescentar:
- `vendus_product_id: Optional[str]` (id do produto no Vendus) e/ou `vendus_reference: Optional[str]`.
- `vendus_tax_id: Optional[str]` (ex.: `"NOR"`).
- **Nuance das variações:** produtos com `variations`/`extras`/`complement_groups` têm preço variável. Regra de mapeamento (caminho principal):
  - Mapear **ao nível do produto** (id Vendus) e enviar cada linha com o **`gross_price` calculado pela app** (a app já calcula `unit_price`/`total_price` por item) + a descrição da variação/extras no campo **`text`** da linha.
  - *(Alternativa, se o dono quiser reporting fino por variação: mapear cada variação a um produto Vendus distinto. Fica como opção no plano — não é o default.)*
- **Guarda:** o admin **não deixa publicar/ativar** um produto sem mapeamento Vendus válido.

**Mesa** (`TableCreate`/`Update`/`Response`, server.py:242-258) — acrescentar:
- `vendus_room_id: Optional[str]`, `vendus_table_id: Optional[str]`.
- Configurados no admin, puxando salas/mesas do Vendus.

**Pedido** (`Order`, server.py:272-297) — acrescentar:
- `vendus_document_id: Optional[str]` (o DC onde foi lançado).
- `vendus_sync_status: str` (`pending` | `synced` | `failed`).
- `vendus_external_reference: str` (idempotência).
- `paid`/`payment_method` deixam de ser a autoridade (Vendus fecha) — mantidos só para histórico/legado, não usados na decisão de "conta zerada".

**Sessão de mesa** (nova coleção `table_sessions`, leve) — o *ponteiro* da app para a conta no Vendus:
- `table_id` (app), `vendus_room_id`, `vendus_table_id`, `vendus_document_id`, `status` (`livre`|`aberta`), `opened_at`, `last_synced_at`, `closed_at`.

### 5.3 Fluxos

**F1 — Cliente faz pedido** (reescrever `create_order`, server.py:1038):
1. Validar que **todos** os itens têm mapeamento Vendus (senão 422 claro).
2. Verificar **kill-switch** (§5.5). Se desligado → gravar pedido como `pending` e **não** enviar/imprimir (fica para o staff decidir).
3. Resolver/abrir a **sessão de mesa**: se já há DC aberto → usar; senão criar via `POST /documents type=DC` e guardar `vendus_document_id`. Usar `external_reference` idempotente.
4. `POST` das linhas para o DC (append no cenário "somam").
5. Gravar `order` com `vendus_document_id` + `vendus_sync_status=synced`.
6. Criar **print jobs** (§6) — só para as impressoras/categorias relevantes.
7. Responder ao cliente (confirmação).
- **Falha do Vendus (R1/rate-limit):** o pedido **não se perde** → gravar `vendus_sync_status=pending`, meter numa **fila de retry** (backoff), mostrar ao cliente "pedido recebido, a confirmar". A idempotência (`external_reference`) evita duplicados no retry.

**F2 — Ler QR / ver conta** (`/pedir?mesa=X`):
1. App resolve a mesa → sessão de mesa. Se `status=aberta` (ou consulta on-demand confirma DC aberto) → menu abre com botão **"Ver conta da mesa"** à direita.
2. "Ver conta" → **leitura on-demand**: `GET /documents/{vendus_document_id}?view=detailed` (ou, no cenário "separam", listar DC do dia e filtrar `rest_table` client-side). Mostra linhas + total, **incluindo adições manuais** (se o spike confirmar mesmo documento).
3. Sem chamadas contínuas — só quando o cliente abre a conta (respeita rate-limit).

**F3 — Fecho da mesa** (staff fatura no POS; a app **não** fatura):
1. **Poller leve** (ex.: 30–60s, ou à boleia de F2) faz `GET /documents?since=hoje` e deteta a fatura final (FT/FR) para a mesa / o DC consumido.
2. Marca `table_session.status=livre`, `closed_at`, e **zera a conta** na app (a mesa deixa de mostrar valores).

### 5.4 Mapeamento (ecrãs de admin)
- **Menu ↔ Vendus:** em `AdminMenu.js`, por produto, um seletor que lista produtos Vendus (`GET /products` no backend, cacheado) e grava `vendus_product_id`/`reference`/`tax_id`. Indicador visual de "por mapear".
- **Mesas ↔ Vendus:** em `AdminTables.js`, por mesa, escolher `sala`+`mesa` do Vendus (`GET /rooms`, `GET /tables?parent=`).

### 5.5 Kill-switch
- Definição em `settings` (global) e opcionalmente por mesa: `auto_send_enabled` (bool).
- Desligado → pedidos ficam `pending` (não vão ao Vendus nem imprimem) e aparecem para o staff. Ligado (default) → fluxo F1 automático.
- Toggle no `AdminSettings.js` (e talvez um atalho no `AdminOrders.js`).

### 5.6 Remoção de relatórios (decisão #5)
- Remover: `GET /dashboard/stats` e o ecrã `AdminDashboard.js` (stats de vendas), os endpoints `/admin/report-*`, `/admin/send-daily-report`, `/admin/scheduler/*`, o `backend/scheduler.py` (relatório diário) e a dependência do Resend **se** não for usada para mais nada.
- Manter o `AdminOrders.js` (gestão operacional de pedidos) — isso é fluxo, não relatório de vendas.
- ⚠️ Confirmar que nada mais depende do scheduler antes de o remover.

### 5.7 Tratamento de erros (resumo)
| Situação | Comportamento |
|----------|---------------|
| Vendus 429 / rate-limit | Backoff + fila de retry; cliente vê "a confirmar"; idempotência evita duplicados |
| Vendus indisponível | Pedido gravado `pending`; retry; alerta no admin se persistir |
| Produto sem mapeamento | Bloqueado no admin (falha cedo, não em produção) |
| Dois DC para a mesma mesa (cenário "separam") | Reconciliação por `rest_table`; conta agregada; alerta se ambíguo |

---

## 6. Frente B — APK de impressão (mais isolada)

### 6.1 Princípio de desenho: **backend formata, APK relé**
Hoje o `print_agent.py` (Windows) faz *polling*, **formata** ESC/POS (`ESCPOSPrinter`) e imprime por TCP (porta 9100). O backend já tem um `ESCPOSFormatter` (server.py:400) e o modelo de `Printer` (`ip`, `port`, `width`, `printer_type`). Proposta:
- **Mover a formatação para o backend**: `GET /agent/pending-jobs` passa a devolver, por job, o **payload ESC/POS pronto** (base64) + `printer` alvo (ip/porta). *(No cenário "somam", pouca mudança; é sobretudo garantir que a formatação canónica vive no backend.)*
- O **APK Android** fica **fino**: poll → para cada job, abrir socket TCP para o `ip:porta` da impressora → enviar os bytes → `PUT /agent/jobs/{id}/status`. Sem lógica de formatação nativa (minimiza código nativo).

### 6.2 Routing por categoria (vários pontos)
- Hoje `create_order` cria job para **todas** as impressoras ativas. Refinar para **routing por categoria**:
  - Estender `Printer` com `categories: List[str]` (que categorias de produto vão para esta impressora) — ex.: cozinha (pizzas/pratos), bar (bebidas).
  - `create_order` gera, por impressora, um job **só com as linhas das categorias dessa impressora**.
- Compatibilidade: manter `printer_type` (kitchen/cashier) como está; `categories` é a camada nova de encaminhamento.

### 6.3 A app Android
- **Capacitor** (consistente com o RH e a cozinha do Menooo), num tablet fixo na cozinha, mesma rede Wi-Fi.
- Necessita de **socket TCP cru** → *plugin* nativo de socket (ou pequeno módulo nativo). Config local: lista `impressora → ip:porta` (ou puxada do backend via `/agent/printers`, que já existe).
- Ecrã simples: estado da ligação, últimos jobs, erros, botão de teste.
- **Fora de âmbito nesta frente:** imprimir adições manuais do POS (decisão #7 = não).

### 6.4 Endpoints (reutilização)
- `GET /agent/pending-jobs` (existe — estender payload), `PUT /agent/jobs/{id}/status` (existe), `GET /agent/printers` (existe). O `print_agent.py` Windows é **descontinuado** quando o APK estiver validado (fica como *fallback* até lá).

---

## 7. Decomposição em planos (faseamento)

1. **Plano A — Integração Vendus** (contém a **Fase 0 / spike** como primeiro passo, e as §5). É o núcleo e o risco.
2. **Plano B — APK de impressão** (§6). Mais isolado; pode andar em paralelo depois de a §6.1/6.2 do backend estarem prontas.

Cada plano segue o ciclo normal (writing-plans → execução com checkpoints). A **Fase 0** condiciona o resto do Plano A.

---

## 8. Riscos & questões em aberto

- **[ALTO] Semântica de append e partilha POS↔API** (R3) — resolvida só pelo spike. Se "separam", muda o desenho da leitura da conta (reconciliação).
- **[MÉDIO] Latência / sem tempo real** (R1) — a conta é on-demand; o "fecho" deteta-se por polling com atraso de dezenas de segundos. Aceitável para o caso de uso? (Assumido que sim.)
- **[MÉDIO] Mapeamento de variações/extras** ao Vendus — default: preço calculado + `text`; refinar se for preciso reporting por variação.
- **[MÉDIO] Base de código sobre `migracao-hostinger`** — a migração ainda não está no `main` (o `main` é a versão Emergent viva). Definir a estratégia de branch/merge desta feature.
- **[BAIXO] Rate-limit** em horas de ponta — mitigado por on-demand + backoff; monitorizar.
- **[BAIXO] Plano/módulo de restauração no Vendus** — confirmar ativo (parte do spike).

---

## 9. Fora de âmbito (YAGNI)

- A app **não** processa pagamentos nem emite faturas (Vendus/POS fazem-no).
- **Não** se importam relatórios de vendas para a app (removidos).
- **Não** se imprimem, via app, itens metidos manualmente no POS.
- **Não** se reescreve o menu para vir do Vendus (fica na app, mapeado).

---

### Frase-resumo para retomar
> Evoluir a Pizzaria standalone (FastAPI+React) para integrar o Vendus como fonte de verdade: pedido do cliente → `POST /documents type=DC` na mesa; "ver conta" por leitura on-demand do DC; fecho detetado por polling (staff fatura no POS); menu na app mapeado a produtos Vendus; kill-switch no auto-envio; remover relatórios próprios; e um APK Android (backend formata, APK relé TCP) com routing por categoria a substituir o agente Windows. **Fase 0 = spike de validação** das semânticas não documentadas do Vendus em `mode:tests`.
