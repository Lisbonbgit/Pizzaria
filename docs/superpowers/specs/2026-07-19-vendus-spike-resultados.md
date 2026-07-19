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

## 4. Mesa viva / visibilidade no POS — ⚠️ INCONCLUSIVO (confound de modo)
- Após 3 DCs, `GET /tables/316430806` mostra **`occupation: 0`** → os DCs (de teste) **não** marcaram a mesa como ocupada.
- **MAS**: os DCs foram criados em `mode:tests` e o **POS vive em `mode:normal`** — são dois mundos que não se veem. Logo o `occupation:0` **não prova** que em modo normal seria igual.
- **Por resolver:** um `POST` DC em modo consistente (Modo de Formação, ou normal) alimenta a **mesa viva** que o staff vê/fecha no POS? Precisa de verificação visual no POS ou de confirmação do Vendus.

## Bugs do cliente descobertos pelo spike (a corrigir)
- `_request` não envia `mode` nos GET → não lê documentos de teste. (Nota: `tables/` **rejeita** `mode` — injetar só nos endpoints de `documents`.)
- `get_document` envia `view` → 403. Remover `view`, usar só `mode`.

## DECISÃO — ⏸️ PENDENTE
A premissa central ("pedido via API → **mesa viva partilhada** que o staff vê e fecha no POS") **NÃO está confirmada**. O que está provado é que a API cria **documentos DC avulsos e imutáveis**, sem ligação observável à mesa viva (em modo de teste). Antes de rearquitetar, confirmar por:
- (a) teste em **Modo de Formação** + verificação **visual no POS**, e/ou
- (b) **suporte Vendus**: "a API alimenta a mesa viva da restauração, ou só cria documentos?"
