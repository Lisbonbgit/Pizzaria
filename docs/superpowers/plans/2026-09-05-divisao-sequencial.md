# Divisão da conta sequencial (mesa + balcão) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Dividir uma conta por N e emitir **uma fatura de cada vez**, cada parte com o seu método de pagamento e NIF, no **balcão e na mesa**; o contentor só finaliza na última parte.

**Architecture:** Um núcleo **puro** (`pos/split_plan.py`) calcula as N partes iguais e a progressão. Um **plano** persistido (`db.split_plans`) guarda a fotografia da conta e que partes já saíram. `close_table` (mesa) e `checkout_counter_order` (balcão) passam a *plan-driven*: em vez de emitirem tudo, emitem **a próxima parte por pagar** pelo **seu próprio caminho fiscal já existente** (dedup por `external_reference` → `create_invoice` → `pos_sales` → impressão). Nada de emissão fiscal duplicada: cada endpoint reutiliza a via que já tem hoje; só muda **quantas** faturas leva por chamada (uma) e **quando** finaliza (só na última).

**Tech Stack:** FastAPI + Motor/MongoDB (backend), React CRA (frontend), Vendus (FS), pytest.

## Global Constraints

- Trabalhar em `~/dev/pizzaria` (NUNCA OneDrive). Ramo já criado: `matheus-mesa-divisao-sequencial`.
- Correr testes com `./.venv/bin/python -m pytest`, sempre com `PYTHONDONTWRITEBYTECODE=1` (o bytecode em cache já mascarou mutações neste Mac).
- **Partes iguais**: as N partes somam **EXATAMENTE** o total (resto do arredondamento na última). Dinheiro sempre `round(...,2)`.
- **Idempotência fiscal inegociável**: cada parte tem `ext_ref` estável `{base_ext_ref}-{i}de{n}`; a dedup por `external_reference` já existente tem de continuar a apanhar retries. NUNCA emitir 2ª FS para a mesma parte.
- **Finalizar só na última parte** (marcar linhas/venda pagas, fechar sessão). Um retry a meio não pode fechar nada.
- Sessão de caixa e operador resolvem-se **no servidor** (`get_pos_operator`), nunca do corpo.
- Âmbito: mesas **à la carte** e balcão. **Rodízio não muda.** Divisão **por itens** não muda. Partes **desiguais** não existem.
- Não fazer deploy sem autorização explícita do dono. Deploy = rsync `git ls-files` + `--exclude '**/.env'`, sem `--delete`.

## File Structure

- **Create** `backend/pos/split_plan.py` — núcleo puro: reparte o total por IVA em N partes e responde "qual a próxima", "quanto falta", "é a última". Sem I/O.
- **Create** `backend/tests/pos/test_split_plan.py` — testes do núcleo.
- **Modify** `backend/server.py`:
  - helpers do plano (`db.split_plans`) + índice único;
  - `close_table` (mesa) plan-driven no ramo de divisão;
  - `checkout_counter_order` (balcão) plan-driven;
  - guardas 409 nos endpoints que mutam um contentor com divisão a meio;
  - `POST /tables/{n}/split-cancel` e `POST /pos/counter/{order_id}/split-cancel`.
- **Modify** `frontend/src/pages/checkout/TableCheckout.js` — emissão parte-a-parte na mesa.
- **Modify** `frontend/src/pages/pos/PosBalcao.js` — divisão no passo "Emitir Documento".
- **Modify** `frontend/src/lib/api.js` — chamadas de cancelar divisão.

---

### Task 1: Núcleo puro `pos/split_plan.py`

**Files:**
- Create: `backend/pos/split_plan.py`
- Test: `backend/tests/pos/test_split_plan.py`

**Interfaces:**
- Consumes: nada.
- Produces:
  - `compute_shares(by_tax: dict[str, float], n: int, title: str) -> list[dict]` → lista de partes `{"items":[{"title","qty","gross_price","tax_id"}], "amount": float}`; **só partes com `amount > 0`** (uma parte que dê 0 não gera FS).
  - `next_unpaid_index(shares: list[dict]) -> int | None`
  - `remaining_amount(shares: list[dict]) -> float`

- [ ] **Step 1: Write the failing tests**

Criar `backend/tests/pos/test_split_plan.py`:

```python
"""Divisão da conta em N partes iguais — lógica pura, sem I/O.

Alimenta a divisão sequencial da mesa (`close_table`) e do balcão
(`checkout_counter_order`): cada parte é uma FS própria, com o seu NIF e
método de pagamento.
"""
from pos.split_plan import compute_shares, next_unpaid_index, remaining_amount


def test_duas_partes_somam_exatamente_o_total():
    shares = compute_shares({"INT": 20.01}, 2, "Conta dividida Mesa 3")
    assert len(shares) == 2
    assert round(sum(s["amount"] for s in shares), 2) == 20.01


def test_resto_do_arredondamento_vai_para_a_ultima():
    # 10.01 / 3 = 3.336... -> 3.34, 3.34, 3.33 (a última leva o resto)
    shares = compute_shares({"INT": 10.01}, 3, "Conta dividida Mesa 1")
    assert [s["amount"] for s in shares] == [3.34, 3.34, 3.33]
    assert round(sum(s["amount"] for s in shares), 2) == 10.01


def test_agrupa_por_iva_com_uma_linha_por_taxa():
    shares = compute_shares({"INT": 10.0, "NOR": 4.0}, 2, "Conta dividida Mesa 5")
    assert len(shares) == 2
    for s in shares:
        assert s["amount"] == 7.0
        taxes = sorted(i["tax_id"] for i in s["items"])
        assert taxes == ["INT", "NOR"]
        for i in s["items"]:
            assert i["qty"] == 1
            assert i["title"].startswith("Conta dividida Mesa 5")


def test_titulo_numera_a_parte():
    shares = compute_shares({"INT": 10.0}, 2, "Conta dividida Mesa 7")
    assert shares[0]["items"][0]["title"] == "Conta dividida Mesa 7 (1/2)"
    assert shares[1]["items"][0]["title"] == "Conta dividida Mesa 7 (2/2)"


def test_n_igual_a_um_devolve_uma_parte_com_tudo():
    shares = compute_shares({"INT": 12.5}, 1, "Conta dividida Mesa 2")
    assert len(shares) == 1
    assert shares[0]["amount"] == 12.5


def test_partes_a_zero_sao_descartadas():
    # 0.01 dividido por 3: só uma parte tem valor; não se emitem FS de 0.
    shares = compute_shares({"INT": 0.01}, 3, "Conta dividida Mesa 4")
    assert all(s["amount"] > 0 for s in shares)
    assert round(sum(s["amount"] for s in shares), 2) == 0.01


def test_progressao_das_partes():
    shares = [{"amount": 5.0, "paid": False}, {"amount": 5.0, "paid": False}]
    assert next_unpaid_index(shares) == 0
    assert remaining_amount(shares) == 10.0

    shares[0]["paid"] = True
    assert next_unpaid_index(shares) == 1
    assert remaining_amount(shares) == 5.0

    shares[1]["paid"] = True
    assert next_unpaid_index(shares) is None
    assert remaining_amount(shares) == 0.0
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd ~/dev/pizzaria/backend && PYTHONDONTWRITEBYTECODE=1 ./.venv/bin/python -m pytest tests/pos/test_split_plan.py -q
```
Esperado: FAIL — `ModuleNotFoundError: No module named 'pos.split_plan'`.

- [ ] **Step 3: Write the implementation**

Criar `backend/pos/split_plan.py`:

```python
"""Divisão da conta em N partes iguais — lógica pura, sem I/O.

Cada parte é uma FS própria (com o seu NIF e método de pagamento), emitida
uma de cada vez. A regra de repartição é a MESMA que o fecho de mesa já usava
inline: reparte por taxa de IVA e põe o resto do arredondamento na ÚLTIMA
parte, para as partes somarem EXATAMENTE o total (dinheiro, nunca aproximar).
"""


def compute_shares(by_tax: dict, n: int, title: str) -> list:
    """N partes iguais a partir do total por IVA.

    `by_tax`: {tax_id: total_dessa_taxa}. Devolve
    `[{"items": [{"title","qty","gross_price","tax_id"}], "amount": float}]`.
    Partes que dessem 0 são descartadas (não se emite FS de valor zero), por
    isso o resultado pode ter menos de `n` partes em contas muito pequenas.
    """
    n = max(1, int(n))
    shares_by_tax = {}
    for tax, sub in by_tax.items():
        base = round(float(sub) / n, 2)
        # A última leva o resto: base*(n-1) + resto == sub, ao cêntimo.
        shares_by_tax[tax] = [base] * (n - 1) + [round(float(sub) - base * (n - 1), 2)]

    out = []
    for i in range(n):
        items_i, amount_i = [], 0.0
        for tax, parts in shares_by_tax.items():
            share = parts[i]
            if share and share > 0:
                items_i.append({
                    "title": f"{title} ({i + 1}/{n})",
                    "qty": 1,
                    "gross_price": share,
                    "tax_id": tax,
                })
                amount_i += share
        if items_i:
            out.append({"items": items_i, "amount": round(amount_i, 2)})
    return out


def next_unpaid_index(shares: list):
    """Índice da próxima parte por pagar, ou None se já saíram todas."""
    for i, s in enumerate(shares):
        if not s.get("paid"):
            return i
    return None


def remaining_amount(shares: list) -> float:
    """Quanto falta faturar (soma das partes por pagar)."""
    return round(sum(s.get("amount", 0) or 0 for s in shares if not s.get("paid")), 2)
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd ~/dev/pizzaria/backend && PYTHONDONTWRITEBYTECODE=1 ./.venv/bin/python -m pytest tests/pos/test_split_plan.py -q
```
Esperado: `7 passed`.

- [ ] **Step 5: Validar por mutação (obrigatório)**

Trocar em `compute_shares` a linha do resto por `[base] * n` (deixa de fechar a conta), correr os testes: `test_duas_partes_somam_exatamente_o_total` e `test_resto_do_arredondamento_vai_para_a_ultima` têm de ficar **VERMELHOS**. Repor e confirmar verde outra vez.

- [ ] **Step 6: Commit**

```bash
cd ~/dev/pizzaria && git add backend/pos/split_plan.py backend/tests/pos/test_split_plan.py
git commit -m "Divisão: núcleo puro das N partes iguais (soma exata, resto na última)"
```

---

### Task 2: Armazenamento do plano (`db.split_plans`)

**Files:**
- Modify: `backend/server.py` (helpers junto aos outros helpers de POS; índice no arranque)

**Interfaces:**
- Consumes: `pos.split_plan.compute_shares`.
- Produces (async helpers em `server.py`):
  - `_split_target(kind: str, ident) -> dict` → `{"kind": kind, "id": ident}`
  - `_get_split_plan(target: dict) -> dict | None`
  - `_create_split_plan(target, n, total, by_tax, title, base_ext_ref, finalize, cash_session_id) -> dict`
  - `_mark_share_paid(target, index, doc_number) -> dict` (devolve o plano atualizado)
  - `_delete_split_plan(target) -> None`

- [ ] **Step 1: Criar o índice único**

Junto aos outros `create_index` do arranque, adicionar:

```python
await db.split_plans.create_index("target", unique=True)
```

- [ ] **Step 2: Escrever os helpers**

Adicionar em `server.py` (perto dos helpers de POS):

```python
# --- Divisão da conta em N partes (mesa e balcão) ---
# O plano fotografa a conta no início e guarda que partes já saíram. As linhas
# (mesa) ou a venda (balcão) só ficam PAGAS na última parte — um retry a meio
# nunca fecha nada. Um plano aberto por contentor (índice único em `target`).

def _split_target(kind: str, ident) -> dict:
    return {"kind": kind, "id": ident}


async def _get_split_plan(target: dict):
    return await db.split_plans.find_one({"target": target}, {"_id": 0})


async def _create_split_plan(target: dict, n: int, total: float, by_tax: dict,
                             title: str, base_ext_ref: str, finalize: dict,
                             cash_session_id):
    shares = compute_shares(by_tax, n, title)
    for i, s in enumerate(shares):
        s["ext_ref"] = f"{base_ext_ref}-{i + 1}de{len(shares)}"
        s["paid"] = False
        s["doc_number"] = None
    plan = {
        "target": target, "cash_session_id": cash_session_id,
        "n": len(shares), "total": round(float(total), 2),
        "finalize": finalize, "shares": shares,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    await db.split_plans.insert_one(dict(plan))
    return plan


async def _mark_share_paid(target: dict, index: int, doc_number):
    await db.split_plans.update_one({"target": target}, {"$set": {
        f"shares.{index}.paid": True,
        f"shares.{index}.doc_number": doc_number,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }})
    return await _get_split_plan(target)


async def _delete_split_plan(target: dict) -> None:
    await db.split_plans.delete_one({"target": target})
```

Adicionar o import no topo, junto aos outros `from pos...`:

```python
from pos.split_plan import compute_shares, next_unpaid_index, remaining_amount
```

- [ ] **Step 3: Verificar que o server importa**

```bash
cd ~/dev/pizzaria/backend && PYTHONDONTWRITEBYTECODE=1 ./.venv/bin/python -c "import server; print('import OK')"
```
Esperado: `import OK`.

- [ ] **Step 4: Correr a suite (sem regressões)**

```bash
cd ~/dev/pizzaria/backend && PYTHONDONTWRITEBYTECODE=1 ./.venv/bin/python -m pytest tests/pos tests/vendus -q
```
Esperado: tudo verde (o `tests/test_daily_report.py` já falhava antes — não conta).

- [ ] **Step 5: Commit**

```bash
cd ~/dev/pizzaria && git add backend/server.py
git commit -m "Divisão: plano persistido em db.split_plans (mesa e balcão)"
```

---

### Task 3: Mesa — `close_table` *plan-driven*

**Files:**
- Modify: `backend/server.py` — `close_table` (ramo da divisão, `:2044-2076`), NIF (`:2076`), finalização à la carte (`:2209-2217`), retorno (`:2241-2247`)

**Interfaces:**
- Consumes: helpers da Task 2, núcleo da Task 1.
- Produces: `close_table` devolve, na divisão, `{"part": int, "of": int, "table_free": bool, "remaining_total": float, ...}`.

- [ ] **Step 1: Substituir a construção das N faturas por "a próxima parte"**

Em `close_table`, no ramo à la carte, trocar o bloco que hoje constrói as N faturas (`server.py:2044-2074`) por: carregar-ou-criar o plano e escolher **uma** parte.

```python
        # Divisão por N: em vez de emitir as N faturas de uma vez, emite UMA
        # parte por chamada (cada uma com o seu NIF e método de pagamento). O
        # plano fotografa a conta na 1ª chamada; as linhas só ficam pagas na
        # última parte.
        n_req = 1 if partial else max(1, min(int(req.split_count or 1), 50))
        line_ids = sorted((l["order_id"], l["idx"]) for l in lines)
        base_ext_ref = stable_ext_ref(table_number, cash_session_id, line_ids)
        split_target = _split_target("table", table_number)
        plan = await _get_split_plan(split_target)

        if plan is None and n_req > 1:
            plan = await _create_split_plan(
                split_target, n_req, total, by_tax,
                f"Conta dividida Mesa {table_number}", base_ext_ref,
                {"line_ids": [list(x) for x in line_ids]}, cash_session_id)

        if plan is not None:
            idx = next_unpaid_index(plan["shares"])
            if idx is None:
                raise HTTPException(status_code=409, detail="Divisão já concluída")
            share = plan["shares"][idx]
            invoices = [{"items": share["items"], "amount": share["amount"],
                         "ext_ref": share["ext_ref"]}]
        else:
            invoices = [{"items": vendus_items, "amount": total,
                         "ext_ref": base_ext_ref}]

        # NIF aceite SEMPRE (antes só quando n==1): cada parte pode levar o seu.
        client = {"fiscal_id": req.nif} if req.nif else None
```

- [ ] **Step 2: Marcar a parte paga e finalizar só na última**

Depois do bloco que regista `pos_sales` (`server.py:2163-2177`) e ANTES da finalização à la carte (`:2209`), inserir:

```python
    # Divisão a meio: marca a parte emitida e só finaliza na última.
    split_part = split_of = None
    split_done = True
    split_remaining = 0.0
    if plan is not None:
        plan = await _mark_share_paid(split_target, idx, docs[0].get("number"))
        split_part, split_of = idx + 1, plan["n"]
        split_done = next_unpaid_index(plan["shares"]) is None
        if split_done:
            # Última parte: agora sim, marca TODAS as linhas fotografadas pagas.
            for oid, lidx in plan["finalize"]["line_ids"]:
                await db.orders.update_one({"id": oid},
                                           {"$set": {f"items.{lidx}.paid": True}})
            await _delete_split_plan(split_target)
        else:
            split_remaining = remaining_amount(plan["shares"])
```

> **Obrigatório:** inicializar `plan = None`, `idx = None` e
> `split_target = _split_target("table", table_number)` **no topo de
> `close_table`** (antes de qualquer ramo), para que o caminho do rodízio e o
> fecho por itens passem por aqui sem `NameError`.

- [ ] **Step 3: Não fechar a mesa a meio da divisão**

Na finalização à la carte (`server.py:2209-2217`), quando a divisão está a meio, a mesa NÃO fecha e o `remaining_total` é o que falta da divisão:

```python
    else:
        remaining = await _open_bill_lines(table_number)
        settled = not remaining
        remaining_total = round(sum((l.get("total_price", 0) or 0) for l in remaining), 2)
        if plan is not None and not split_done:
            settled = False                      # divisão a meio: mesa fica aberta
            remaining_total = split_remaining     # falta o resto das partes
        if settled:
            await db.table_sessions.update_many(
                {"table_number": table_number, "status": "open"},
                {"$set": {"status": "closed", "closed_at": datetime.now(timezone.utc).isoformat()}},
            )
```

- [ ] **Step 4: Devolver o progresso da divisão**

No `return` (`server.py:2241`), acrescentar `part`/`of`:

```python
    return {"table_number": table_number, "total": total,
            "invoices": len(docs), "split": (split_of or 1), "partial": partial,
            "part": split_part, "of": split_of,
            "table_free": settled,
            "remaining_total": remaining_total,
            "vendus": {"id": docs[0].get("id"), "number": docs[0].get("number"),
                       "atcud": docs[0].get("atcud")},
            "numbers": [d.get("number") for d in docs]}
```

- [ ] **Step 5: Verificar import + suite**

```bash
cd ~/dev/pizzaria/backend && PYTHONDONTWRITEBYTECODE=1 ./.venv/bin/python -c "import server; print('import OK')" && PYTHONDONTWRITEBYTECODE=1 ./.venv/bin/python -m pytest tests/pos tests/vendus -q
```
Esperado: `import OK` e suite verde.

- [ ] **Step 6: Commit**

```bash
cd ~/dev/pizzaria && git add backend/server.py
git commit -m "Mesa: divisão emite UMA parte por chamada (NIF+pagamento próprios), finaliza só na última"
```

---

### Task 4: Mesa — guardas 409 e cancelar divisão

**Files:**
- Modify: `backend/server.py` — endpoints que mutam a conta da mesa; novo `POST /tables/{table_number}/split-cancel`

**Interfaces:**
- Consumes: `_get_split_plan`, `_delete_split_plan`, `_split_target`.
- Produces: `POST /tables/{table_number}/split-cancel` → `{"cancelled": true}` ou 409.

- [ ] **Step 1: Guarda partilhada**

```python
async def _assert_no_open_split(kind: str, ident):
    """Recusa mutações enquanto há uma divisão a meio (o total fotografado não
    pode mudar). A porta fecha-se no SERVIDOR, não só no ecrã."""
    if await _get_split_plan(_split_target(kind, ident)):
        raise HTTPException(status_code=409,
                            detail="Divisão em curso — termina ou cancela a divisão")
```

- [ ] **Step 2: Aplicar a guarda**

Chamar `await _assert_no_open_split("table", table_number)` no início de: adicionar item à mesa, anular item (`/orders/{id}/items/{idx}/void`), desconto por item e desconto global, e no `close_table` **quando NÃO é uma chamada de divisão** (ou seja: quando há plano aberto e vem um fecho normal/por-itens, recusar 409).

- [ ] **Step 3: Endpoint de cancelamento**

```python
@api_router.post("/tables/{table_number}/split-cancel")
async def cancel_table_split(table_number: int,
                             authorization: Optional[str] = Header(None),
                             x_device_token: Optional[str] = Header(None)):
    """Cancela uma divisão AINDA sem nenhuma parte emitida. Com FS já emitida
    não há cancelamento (documento fiscal não se desfaz)."""
    await get_pos_or_admin(authorization, x_device_token)
    target = _split_target("table", table_number)
    plan = await _get_split_plan(target)
    if not plan:
        raise HTTPException(status_code=404, detail="Não há divisão em curso")
    if any(s.get("paid") for s in plan["shares"]):
        raise HTTPException(status_code=409,
                            detail="Já foi emitida uma parte — não é possível cancelar")
    await _delete_split_plan(target)
    return {"cancelled": True}
```

- [ ] **Step 4: Verificar + commit**

```bash
cd ~/dev/pizzaria/backend && PYTHONDONTWRITEBYTECODE=1 ./.venv/bin/python -c "import server; print('import OK')"
cd ~/dev/pizzaria && git add backend/server.py
git commit -m "Mesa: trava edições durante a divisão + cancelar antes da 1ª parte"
```

---

### Task 5: Mesa — frontend parte-a-parte

**Files:**
- Modify: `frontend/src/pages/checkout/TableCheckout.js` (`doClose` `:431`, painel esquerdo `:538+`)
- Modify: `frontend/src/lib/api.js` (adicionar `cancelTableSplit`)

**Interfaces:**
- Consumes: resposta de `closeTable` com `part`, `of`, `table_free`, `remaining_total`.
- Produces: UI que emite "parte i de N".

- [ ] **Step 1: `api.js`**

```javascript
  cancelTableSplit: (tableNumber) =>
    api.post(`/tables/${tableNumber}/split-cancel`),
```

- [ ] **Step 2: Estado do progresso**

Em `TableCheckout.js`, acrescentar `const [splitPart, setSplitPart] = useState(0);` e `const [splitOf, setSplitOf] = useState(0);`.

- [ ] **Step 3: `doClose` guarda o progresso e limpa os campos da parte seguinte**

No `else` do `doClose` (fecho parcial, `:459`), acrescentar antes de `loadBill`:

```javascript
        if (r.data.of) {
          setSplitPart(r.data.part || 0);
          setSplitOf(r.data.of);
          setPaymentId('');      // cada parte escolhe o SEU método
          setNif('');            // e o SEU NIF
        }
```

E no sucesso total (`table_free`), repor `setSplitPart(0); setSplitOf(0);`.

- [ ] **Step 4: Rótulo do botão e aviso**

O botão de fechar passa a mostrar, quando `splitActive || splitOf`:
`Emitir parte {(splitPart || 0) + 1} de {splitOf || splitCount}`.
Por cima, quando `splitOf > 0`, mostrar: `Parte {splitPart} de {splitOf} emitida · falta {eur(remaining)}`.

- [ ] **Step 5: Botão "Cancelar divisão"**

Visível só quando `splitOf > 0 && splitPart === 0` (ainda nenhuma parte emitida) — chama `api.cancelTableSplit(tableNumber)` e recarrega.

- [ ] **Step 6: Build do frontend**

```bash
cd ~/dev/pizzaria/frontend && PATH="$HOME/.local/node/bin:$PATH" CI=true node_modules/.bin/craco build 2>&1 | tail -5
```
Esperado: `Compiled successfully.`

- [ ] **Step 7: Commit**

```bash
cd ~/dev/pizzaria && git add frontend/src/pages/checkout/TableCheckout.js frontend/src/lib/api.js
git commit -m "Mesa (frontend): emitir parte a parte, pagamento/NIF por parte, cancelar divisão"
```

---

### Task 6: Fase A no ar (mesa) + happy-path

- [ ] **Step 1: Pedir autorização ao dono para deploy.** Sem "sim" explícito, PARAR aqui.
- [ ] **Step 2:** Merge do ramo em `main` e push.
- [ ] **Step 3:** `git ls-files > /tmp/f.txt && rsync -azci --files-from=/tmp/f.txt --exclude '**/.env' ./ root@185.158.107.3:/root/pizzaria/` (dry-run `-n` primeiro, rever os envios).
- [ ] **Step 4:** `docker compose up -d --build` (detached) e esperar `healthy`.
- [ ] **Step 5: Happy-path com o dono (FS reais):** mesa com 2 IVAs → dividir por 2 → parte 1 (NIF A, Multibanco) → mesa fica aberta "falta metade" → parte 2 (NIF B, Dinheiro) → mesa fecha. Confirmar no Vendus: 2 FS, somam ao total, cada uma com o seu NIF/pagamento, **0 artigos-lixo**.

---

> **Fase B (Tasks 7-9):** os passos abaixo estão ao nível de desenho de
> propósito. Antes de executar a Fase B, **expandir estas tasks com o código
> concreto** (como nas Tasks 1-5), já com o que a Fase A ensinar em produção —
> escrever agora código especulativo para o balcão seria adivinhar.

### Task 7: Balcão — `checkout_counter_order` *plan-driven*

**Files:**
- Modify: `backend/server.py` — `checkout_counter_order` (`:4043`), `CounterCheckoutRequest` (aceitar `split_count`), novo `POST /pos/counter/{order_id}/split-cancel`

**Interfaces:**
- Consumes: Tasks 1 e 2.
- Produces: `checkout_counter_order` devolve `part`, `of`, `remaining_total`, `order_paid`.

- [ ] **Step 1: `split_count` no pedido**

Acrescentar `split_count: int = 1` ao modelo do checkout do balcão.

- [ ] **Step 2: Emitir uma parte**

Depois de construir `vendus_items`/`total` (`:4119-4126`), aplicar o MESMO padrão da Task 3: agrupar o total por IVA (`by_tax` a partir de `vendus_items`), carregar-ou-criar o plano com
`target = _split_target("counter", body.order_id)`,
`base_ext_ref = counter_ext_ref(body.order_id)`,
`title = f"Venda dividida"`, `finalize = {"order_id": body.order_id}`;
emitir **uma** parte (`invoices = [share]`), NIF/pagamento do corpo.

- [ ] **Step 3: Finalizar só na última**

Marcar a parte paga; se `next_unpaid_index(...) is None` → marcar a order paga (como hoje) e apagar o plano; senão devolver `order_paid=False` + `remaining_total = remaining_amount(...)` sem tocar na order.

- [ ] **Step 4: Guarda + cancelamento**

`await _assert_no_open_split("counter", order_id)` no `/pos/counter/{id}/update`; endpoint `POST /pos/counter/{order_id}/split-cancel` igual ao da mesa (404 sem plano, 409 com parte paga).

- [ ] **Step 5: Verificar + commit**

```bash
cd ~/dev/pizzaria/backend && PYTHONDONTWRITEBYTECODE=1 ./.venv/bin/python -c "import server; print('import OK')" && PYTHONDONTWRITEBYTECODE=1 ./.venv/bin/python -m pytest tests/pos tests/vendus -q
cd ~/dev/pizzaria && git add backend/server.py
git commit -m "Balcão: divisão emite UMA parte por chamada, finaliza só na última"
```

---

### Task 8: Balcão — frontend

**Files:**
- Modify: `frontend/src/pages/pos/PosBalcao.js` (`emitirDocumento` `:225`, painel de faturação)
- Modify: `frontend/src/lib/api.js` (`cancelCounterSplit`)

- [ ] **Step 1:** Seletor "dividir por N" (− / N / +) no painel de "Emitir Documento", ao lado do método de pagamento.
- [ ] **Step 2:** `emitirDocumento` envia `split_count` e, na resposta com `of`, guarda `part`/`of`, limpa `paymentId` e `nif`, e mostra `Parte i de N · falta X €`.
- [ ] **Step 3:** Só mostra "Nova Venda" quando `order_paid` (última parte).
- [ ] **Step 4:** "Cancelar divisão" enquanto nenhuma parte saiu.
- [ ] **Step 5:** Build (`craco build`) → `Compiled successfully.`
- [ ] **Step 6:** Commit.

---

### Task 9: Fase B no ar (balcão) + happy-path

- [ ] **Step 1: Pedir autorização ao dono.** Sem "sim", PARAR.
- [ ] **Step 2-4:** Merge/push, rsync (dry-run primeiro), rebuild, esperar `healthy`.
- [ ] **Step 5: Happy-path com o dono:** venda de balcão → dividir por 2 → parte 1 (NIF A) → venda fica aberta → parte 2 (NIF B) → finaliza. Confirmar 2 FS no Vendus, somam ao total, **0 artigos-lixo**.
