# Divisão da conta sequencial — mesa + balcão (geral)

## Problema

Dividir uma conta e dar a cada pessoa a **sua** fatura (com o **seu NIF** e a
**sua forma de pagamento**) não funciona:

- **Mesa** (`close_table` com `split_count=N`): emite **as N faturas de uma só
  vez**, com **um único** método de pagamento, **ignora o NIF** e **fecha a mesa
  logo**.
- **Balcão** (`checkout_counter_order`): **não tem divisão** — emite **uma** FS
  para a venda toda.

## Objetivo

**Geral** (mesa E balcão): dividir por N e emitir **uma fatura de cada vez**.
Cada parte leva o seu **método de pagamento** e o seu **NIF** (podem diferir). O
contentor (mesa/venda) **fica aberto** ("Parte i de N · falta X €") até sair a
última parte, que **finaliza** (fecha a mesa / marca a venda paga).

Partes **iguais** (total÷N, exato ao cêntimo por IVA). Fora de âmbito: rodízio
(mantém o pagamento por pessoa próprio), divisão **por itens** (continua igual),
partes **desiguais**.

## Comportamento atual (referências)

- Mesa: `backend/server.py` `close_table` — split em `server.py:2058-2074`
  (constrói N faturas sintéticas "Conta dividida Mesa X (i/n)" por IVA, refs
  `{stable_ext_ref}-{i}de{n}`), NIF só `n==1` (`:2076`), `_emit_all` dedup
  (`:2098`), `build_pos_sales_rows` (`:2168`), marca linhas pagas + fecha sessão
  (`:2209-2217`), imprime (`:2218-2240`).
- Balcão: `checkout_counter_order` (`server.py:4043`) — 1 FS,
  `ext_ref = counter_ext_ref(order_id)` = `balcao-{order_id}`, `pos_sales`
  source `balcao`, marca a order paga.
- Frontend: mesa `frontend/src/pages/checkout/TableCheckout.js` `doClose`
  (`:431`, `splitActive` `:314`); balcão `frontend/src/pages/pos/PosBalcao.js`
  `emitirDocumento` (`:225`).

## Fluxo desejado (igual para mesa e balcão)

1. Operador escolhe **dividir por N** (N ≥ 2) e toca em **"Emitir parte 1 de N"**.
2. O sistema **fotografa** a conta (total + por IVA) e reparte em N partes iguais
   (exato — as N partes somam ao cêntimo o total).
3. Emite **uma** parte (a próxima por pagar) com o `payment_method_id` e o `nif`
   **dessa** parte. Sai **1 FS**, imprime na caixa.
4. O contentor **fica aberto**: "Parte 2 de N · falta X €". O operador escolhe o
   pagamento/NIF da parte seguinte e emite. Repete.
5. Na **última** parte: finaliza — mesa marca linhas pagas + fecha sessão;
   balcão marca a order paga — e apaga o plano.

## Modelo de dados — `db.split_plans`

Um plano aberto por contentor (mesa ou venda de balcão):

```
{
  target: { kind: "table" | "counter", id: <int table_number | str order_id> },  # chave única
  cash_session_id: str | None,
  n: int,
  total: float,
  # como finalizar no fim:
  finalize: { line_ids: [[order_id, idx]] }   # kind=table
           | { order_id: str },                # kind=counter
  shares: [
    { items: [{title, qty, gross_price, tax_id}],
      amount: float,
      ext_ref: str,          # {base_ext_ref}-{i}de{n}, ESTÁVEL
      paid: bool,
      doc_number: str | None }
  ],
  created_at, updated_at
}
```

Índice único em `target` (um só plano aberto por contentor). Apagado ao emitir a
última parte (ou no cancelamento). `base_ext_ref`: mesa =
`stable_ext_ref(table_number, cash_session_id, line_ids)`; balcão =
`counter_ext_ref(order_id)`.

## Núcleo puro — `backend/pos/split_plan.py` (sem I/O, testável)

- `compute_shares(by_tax, n, title) -> list[dict]` — N partes por IVA, resto do
  arredondamento na **última** (soma EXATA do total). Extrai a regra hoje inline
  em `server.py:2058-2074`, agora partilhada por mesa e balcão.
- `next_unpaid_index(shares) -> int | None`
- `remaining_amount(shares) -> float`
- `is_last(shares) -> bool`

Única lógica com ramos → **teste unitário obrigatório**, validado por mutação.

## Emissão fiscal PARTILHADA (uma só via, sem divergência)

Um helper único emite **uma** parte: dedup por `ext_ref` (reutiliza se já
existir), `create_invoice` com `payments=[{id, amount}]` e
`client={fiscal_id: nif}` se houver NIF, regista `pos_sales`
(`build_pos_sales_rows`, source `mesa`/`balcao`) e imprime na caixa. É o **mesmo**
comportamento já existente — mesa e balcão split usam este helper. Objetivo:
**uma** via de emissão fiscal, não uma segunda cópia. (O plano de implementação
decide extrair do `close_table`/`checkout` existente vs. helper dedicado; a regra
inegociável é não duplicar a lógica de dedup/idempotência.)

## Mesa — `close_table` *plan-driven* para split

Quando o pedido é divisão (`split_count>1` ou já há plano `table:N`): carrega-ou-
cria o plano (1ª chamada fotografa `by_tax`/`total`/`line_ids`, `compute_shares`),
emite a **próxima parte por pagar** pelo helper partilhado, marca `paid`+
`doc_number`. Se era a última → marca `line_ids` pagas + fecha a sessão + apaga o
plano (`table_free=true`); senão mesa fica aberta (`table_free=false`,
`remaining_total`, `part`, `of`). Sessão/operador resolvidos no servidor.

## Balcão — `checkout_counter_order` *plan-driven* para split

Quando vem `split_count>1` ou já há plano `counter:order_id`: carrega-ou-cria o
plano (fotografa o total da order + `compute_shares`; `base_ext_ref =
counter_ext_ref(order_id)`), emite a **próxima parte** pelo mesmo helper
partilhado (payment/NIF da parte). Se era a última → marca a order paga + apaga o
plano; senão a venda fica aberta com o restante. `already_paid` continua a
proteger contra dupla emissão da order.

## Finalizar / travar edições / cancelar

- **Travar edições (SERVIDOR)**: enquanto existir plano aberto, os endpoints que
  mutam esse contentor recusam **409** — mesa (adicionar/anular item, desconto,
  fecho normal/por-itens); balcão (`/pos/counter/{id}/update`, fecho normal). O
  total fotografado não pode mudar a meio.
- **Cancelar**: `POST /tables/{n}/split-cancel` e `POST
  /pos/counter/{order_id}/split-cancel` — só **antes** de sair a 1ª parte
  (nenhuma `paid`); apaga o plano e devolve 200. Com parte já paga → **409**.

## Fiscal & idempotência

- `ext_ref` estável por parte (`…-{i}de{n}`) + dedup por `external_reference` →
  retry da mesma parte **reutiliza** a FS (nunca 2ª).
- Finaliza (marca pago/fecha) **só na última parte** → retry a meio nunca fecha
  por engano.
- `pos_sales` idempotente pelo índice único em `vendus_document_id`.
- Vendus a falhar a meio: a parte não fica `paid`; repete-se sem cobrança dupla.

## Frontend

- **Mesa** (`TableCheckout.js`): botão passa a **"Emitir parte i de N"**; cada
  emissão chama `closeTable({split_count:N, payment_method_id, nif})`
  (`split_count` só conta na 1ª); recarrega, mostra **"Parte i de N · falta X €"**
  + campos pagamento/NIF limpos; **"Cancelar divisão"** só enquanto `part==0`;
  última fecha o diálogo.
- **Balcão** (`PosBalcao.js`): no passo **"Emitir Documento"** ganha um seletor
  **"dividir por N"**; mesma emissão parte-a-parte (pagamento/NIF por parte);
  "Nova Venda" só depois da última.
- Ambos bloqueiam edição do carrinho/conta enquanto a divisão está a meio
  (espelha a guarda do servidor).

## Testes

- **Unitários puros** (`backend/tests/pos/test_split_plan.py`): `compute_shares`
  (soma EXATA; resto na última; 2 IVAs; N=1), `next_unpaid_index`,
  `remaining_amount`, `is_last`. Validar por mutação.
- **Regressão**: fecho/idempotência (mesa e balcão) existentes verdes.
- **Happy-path manual** (com o dono, FS reais), mesa e balcão: dividir por 2 →
  parte 1 (NIF A, Multibanco) → contentor fica aberto "falta metade" → parte 2
  (NIF B, Dinheiro) → finaliza; 2 FS no Vendus, somam ao total, cada uma com o
  seu NIF/pagamento, **0 artigos-lixo**.

## Estratégia de implementação (fases, núcleo partilhado)

1. **Núcleo + emissão partilhada**: `pos/split_plan.py` + helper de emissão +
   `db.split_plans` + testes.
2. **Fase A — mesa**: `close_table` plan-driven + guardas + frontend
   `TableCheckout` + deploy + happy-path.
3. **Fase B — balcão**: `checkout_counter_order` plan-driven + guardas + frontend
   `PosBalcao` + deploy + happy-path.

Cada fase completa e verificada antes da seguinte.

## Fora de âmbito

- **Rodízio**: mantém o pagamento por pessoa próprio.
- **Divisão por itens** (seleção): continua igual; ganha NIF/pagamento por parte
  só se for pedido mais tarde.
- Partes **desiguais** (valores ajustáveis): não — partes iguais.
