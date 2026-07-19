# Resultados do Spike Vendus — 2026-07-19

> Corrido com `backend/scripts/vendus_spike.py` + sondas manuais, em `mode:tests`,
> contra a conta real. Caixa API criada: `id=358144579` ("Caixa API").

## 1. Salas/mesas usadas
- Sala: `316430805` · Mesa: `316430806` ("Mesa 1") · Register API: `358144579`

## 2. Append (R3-a) — vários POST DC na mesma mesa
- POST #1 → doc `358147816` "DC T01P2026/1" (1,00€)
- POST #2 → doc `358147818` "DC T01P2026/2" (2,00€)
- POST #3 (external_reference repetido) → doc `358148567` "DC T01P2026/3" (9,00€)
- **MESMO documento? NÃO** → cada POST cria um **documento DC independente**.
- **PATCH de `items` NÃO permitido** (só `id, stock, status, mode`) → documentos são **imutáveis nas linhas**; não se "acrescenta" a um DC aberto.
- **`external_reference` NÃO é idempotente** → repetir cria outro documento (não protege contra duplicados).
- **Conclusão R3-a: SEPARAM** (e sem forma de append/atualização de linhas).

## 3. Leitura da conta
- `GET /documents?type=DC` só devolve os DC de teste **com `mode=tests`** (senão → 404 "No data").
- Na **listagem**, `rest_table` vem **`None`** → **não dá para filtrar a conta por mesa** pela listagem.
- `GET /documents/{id}` **rejeita `view`** (campos: `mode, copies, output, ...`); o detalhe **não devolve `rest_room`/`rest_table`**. Só o número "DC T01**P**2026/..." sugere a mesa.

## 4. Mesa viva / visibilidade no POS — ❌ CONCLUSIVO: NÃO alimenta a mesa viva
- Teste decisivo (pizzaria fechada, todas as mesas livres): criado **1 DC em modo NORMAL** (não-fiscal) via caixa API na Mesa 1 — `id=358150026`, "DC 01P2026/288", 0,01 €, `observations=None` (real, não formação).
- **No POS (Caixa principal, tipo `rest`) NÃO aparece NADA** — a Mesa 1 não fica ocupada nem mostra o item. (Confirmado visualmente pelo dono.)
- Combinado com `occupation:0` e com os DCs serem documentos separados/imutáveis, a conclusão é firme: **o `POST /documents type=DC` cria documentos avulsos e NÃO alimenta a mesa viva que o staff gere no POS.**
- Nota: não há opção "Sincronização de POS" visível na conta (talvez só com vários equipamentos).
- Extra: documentos DC são **anuláveis** via `PATCH /documents/{id}` com `status=A`.

## Bugs do cliente descobertos pelo spike (a corrigir)
- `_request` não envia `mode` nos GET → não lê documentos de teste. (Nota: `tables/` **rejeita** `mode` — injetar só nos endpoints de `documents`.)
- `get_document` envia `view` → 403. Remover `view`, usar só `mode`.

## DECISÃO — ❌ Premissa central INVIÁVEL via API
A premissa "pedido via API → **mesa viva partilhada** que o staff vê e fecha no POS" **NÃO é viável** com a API pública do Vendus: a API cria **documentos avulsos e imutáveis**, que **não aparecem na mesa viva do POS**.

**Consequência:** caem as 3 peças que dependiam disto — (1) pedido do cliente na mesa viva, (2) adições manuais do POS visíveis na app, (3) fecho no POS a "limpar" a app.

**O que a API FAZ bem** (e onde a caixa API continua útil): criar **documentos/faturas** (DC/FT/FR) e ler produtos/salas/mesas.

**Rumo recomendado (a validar com o dono):**
- (Último de-risk, grátis) **suporte Vendus**: existe ALGUM método de API para alimentar a mesa viva da restauração, ou a API só cria documentos?
- Se não → **rearquitetar**: a **APP é a fonte da conta viva** (QR ordering, como hoje) e o **Vendus entra só no fecho** para emitir a **fatura (FT/FR)** via API. Trade-off: as mesas de QR passam a ser geridas na app, não no POS do Vendus.
