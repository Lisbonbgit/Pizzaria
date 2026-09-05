# Divisão da conta sequencial (mesa) — Fase 1

## Problema

Ao **dividir a conta por N pessoas** numa mesa à la carte, o fecho atual
(`close_table` com `split_count=N`) emite **as N faturas de uma só vez**, com
**um único método de pagamento**, **ignora o NIF** e **fecha a mesa logo**. Não
há forma de dar a cada pessoa a sua fatura com o **seu NIF** e a **sua forma de
pagamento**.

## Objetivo

Dividir por N e emitir **uma fatura de cada vez**. Cada parte leva o seu
**método de pagamento** e o seu **NIF** (podem diferir). A mesa **fica aberta**
("Parte i de N · falta X €") até sair a última parte, que **fecha a mesa**.

Aplica-se a mesas **à la carte**. Fora de âmbito nesta fase: rodízio (já tem
pagamento por pessoa próprio), divisão **por itens** (continua igual), e o
**balcão** (Fase 2).

## Comportamento atual (referências)

- `backend/server.py` `close_table` (`CloseTableRequest.split_count`,
  `server.py:1608`). Para `n>1` constrói N faturas sintéticas "Conta dividida
  Mesa X (i/n)" agrupadas por IVA (`server.py:2058-2074`), com refs estáveis
  `{stable_ext_ref}-{i}de{n}`. NIF só para `n==1` (`server.py:2076`). Emite tudo
  em `_emit_all` (dedup fiscal por `external_reference`, `server.py:2098-2129`),
  regista `pos_sales` por documento (`build_pos_sales_rows`, `server.py:2168`),
  marca as linhas pagas e fecha a sessão (`server.py:2209-2217`), imprime cada
  FS na caixa (`server.py:2218-2240`).
- Frontend `frontend/src/pages/checkout/TableCheckout.js` `doClose`
  (`:431`): no ramo sem seleção envia `split_count = splitActive ? splitCount : 1`
  e `nif`. `splitActive = !isRodizioTable && !hasSelection && splitCount > 1`
  (`:314`).

## Comportamento desejado (fluxo)

1. Operador escolhe **dividir por N** (N ≥ 2) e toca em **"Emitir parte 1 de N"**.
2. O sistema **fotografa** a conta (linhas a faturar + total) e reparte em N
   partes iguais (exato, por IVA — as N partes somam ao cêntimo o total).
3. Emite **uma** parte (a próxima por pagar) com o `payment_method_id` e o
   `nif` **dessa** parte. Sai **1 FS**, imprime na caixa.
4. A mesa **fica aberta**: "Parte 2 de N · falta X €". O operador escolhe o
   pagamento/NIF da parte seguinte e emite. Repete.
5. Ao emitir a **última** parte: marca **todas** as linhas fotografadas como
   pagas, **fecha a sessão** e apaga o plano de divisão.

## Modelo de dados — `db.table_splits`

Um plano de divisão aberto por mesa (no máximo um):

```
{
  table_number: int,            # chave (único por mesa aberta)
  cash_session_id: str | None,
  n: int,                       # nº de partes
  total: float,                 # total fotografado
  line_ids: [[order_id, idx]],  # linhas a marcar pagas no FIM
  shares: [                     # partes pré-calculadas (soma == total)
    { items: [{title, qty, gross_price, tax_id}],  # linhas sintéticas por IVA
      amount: float,
      ext_ref: str,             # {stable_ext_ref}-{i}de{n}, ESTÁVEL
      paid: bool,               # já emitida?
      doc_number: str | None }
  ],
  created_at, updated_at
}
```

Índice único em `table_number` (garante um só plano aberto por mesa). O plano é
apagado quando a última parte é emitida (ou no cancelamento).

## Núcleo puro — `backend/pos/split_plan.py` (sem I/O, testável)

- `compute_shares(by_tax: dict[str,float], n: int) -> list[dict]` — dado o total
  por IVA e N, devolve N partes, cada uma `{items:[{title,qty,gross_price,
  tax_id}], amount}`, agrupadas por IVA, com o **resto do arredondamento na
  última** para somar EXATAMENTE o total (mesma regra do `server.py:2058-2074`,
  extraída para aqui). O `title` recebe-se por parâmetro/prefixo
  ("Conta dividida Mesa X").
- `next_unpaid_index(shares) -> int | None` — índice da próxima parte por pagar.
- `remaining_amount(shares) -> float` — soma das partes por pagar.
- `is_last(shares) -> bool` — só falta uma por pagar.

Estas funções são a única lógica com ramos → **teste unitário obrigatório**,
validado por mutação (partes somam ao total; resto na última; progressão).

## Endpoint — `close_table` passa a *plan-driven* para split

Estende-se `close_table` (NÃO se duplica o caminho fiscal): quando o pedido é uma
divisão por N (há `split_count>1` **ou** já existe plano aberto para a mesa),
em vez de emitir as N de uma vez:

1. **Carrega-ou-cria** o plano (`db.table_splits`). Na 1ª chamada: exige `n≥2`,
   mesa **à la carte** com linhas por faturar; fotografa `by_tax`/`total`/
   `line_ids`, chama `compute_shares`, grava o plano. (Recusa 409 se já houver
   plano e vier `split_count` diferente, ou mesa vazia/rodízio.)
2. Escolhe a **próxima parte por pagar** (`next_unpaid_index`).
3. Emite **essa** parte (uma FS) pelo **mesmo** `_emit_all` já existente:
   `invoices = [share]`, `payments=[{id: req.payment_method_id, amount}]`,
   `client = {fiscal_id: req.nif}` (agora o NIF **é aceite por parte**). A dedup
   fiscal por `ext_ref` mantém a idempotência num retry.
4. Regista `pos_sales` **dessa** FS (o mesmo `build_pos_sales_rows`) e imprime.
5. Marca `shares[i].paid=true` + `doc_number`, grava o plano (`updated_at`).
6. **Se era a última** (`is_last` antes / nenhuma por pagar depois): marca as
   `line_ids` pagas, marca as orders pagas, **fecha a sessão** e **apaga** o
   plano. Devolve `table_free=true`.
   **Senão**: NÃO toca nas linhas; mesa fica aberta. Devolve `table_free=false`,
   `remaining_total = remaining_amount`, `part=i+1`, `of=n`.

O caminho fiscal (dedup, emissão, `pos_sales`, impressão) é **exatamente** o de
hoje — só muda **quantas** faturas se emitem por chamada (uma) e **quando** se
marca pago/fecha (só na última). Continua a resolver sessão/operador no servidor
(`get_pos_operator`, nunca do corpo).

### Cancelar divisão

Endpoint dedicado `POST /tables/{table_number}/split-cancel` — só permitido
**antes** de sair a 1ª parte (nenhuma `paid`); apaga o plano e devolve 200.
Se já houver parte paga, recusa **409** (há FS emitida, não se desfaz).

### Travar edições durante a divisão (no SERVIDOR)

Enquanto existir plano aberto para a mesa, os endpoints que **mutam** a conta
(adicionar item, anular item, desconto, e o fecho normal/por-itens) **recusam
409** ("divisão em curso; termina ou cancela"). A porta fecha-se no servidor,
não só no ecrã — o total fotografado não pode mudar a meio.

## Fiscal & idempotência

- Cada parte tem `ext_ref` **estável** `{stable_ext_ref}-{i}de{n}`; a dedup
  fiscal por `external_reference` (já existente) garante que um retry da mesma
  parte **reutiliza** a FS em vez de emitir 2ª.
- Linhas só ficam **pagas na última parte** → um retry a meio nunca fecha a
  mesa por engano.
- `pos_sales` idempotente pelo índice único em `vendus_document_id`.
- Se o Vendus falhar a meio, a parte não fica `paid`; a mesa fica aberta nessa
  parte e o operador repete (sem cobrança dupla, pela dedup).

## Frontend — `TableCheckout.js`

- No modo `splitActive`, o botão passa a **"Emitir parte i de N"**. Cada emissão
  chama `closeTable` com `{ split_count: N, payment_method_id, nif }` (o
  `split_count` só importa na 1ª; depois o servidor segue o plano).
- Após cada parte: recarrega a conta, mostra **"Parte i de N · falta X €"** e os
  campos de **pagamento + NIF** para a parte seguinte (limpos).
- Botão **"Cancelar divisão"** visível só enquanto `part==0`.
- A última parte fecha o diálogo (`table_free`).
- O ecrã bloqueia adicionar/editar itens enquanto a divisão está a meio (espelha
  a guarda do servidor).

## Testes

- **Unitários puros** (`backend/tests/pos/test_split_plan.py`): `compute_shares`
  (N partes somam EXATAMENTE o total; resto na última; agrupa por IVA; N=1;
  valores com 2 IVAs), `next_unpaid_index`, `remaining_amount`, `is_last`.
  Validar por mutação.
- **Regressão**: os testes de fecho/idempotência existentes continuam verdes.
- **Happy-path manual** (com o dono, FS reais): mesa com 2 IVAs → dividir por 2 →
  emitir parte 1 (NIF A, Multibanco) → mesa fica aberta "falta metade" → emitir
  parte 2 (NIF B, Dinheiro) → mesa fecha; confirmar 2 FS no Vendus, valores
  somam ao total, cada uma com o seu NIF/pagamento, **0 artigos-lixo**.

## Fora de âmbito (Fase 2 / não mexer)

- **Balcão**: mesmo mecanismo, fica para Fase 2 (a confirmar).
- **Rodízio**: mantém o pagamento por pessoa próprio.
- **Divisão por itens** (seleção): continua igual (já é sequencial); só ganha o
  NIF/pagamento por parte se for pedido mais tarde (não nesta fase).
- Valores **ajustáveis** por parte (partes desiguais): não — partes iguais.
