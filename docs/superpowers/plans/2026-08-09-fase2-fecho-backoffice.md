# Fase 2 — Fecho (parar talão Z Vendus) + Backoffice (faturas, produtos €, intervalo) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deixar de imprimir o talão Z do Vendus no fecho de caixa, e no backoffice passar a ter lista de cada fatura, produtos vendidos com valor €, e escolha de intervalo de datas.

**Architecture:** O fecho já fecha o registador Vendus e imprime o talão Z da app (reconciliação) — remove-se apenas o job que imprime o talão Z *do Vendus*. No backoffice, o `GET /admin/report-data` passa a expor o `invoices` que o cliente Vendus já calcula (hoje descartado), a agregar produtos com valor € via um helper puro que reutiliza a via de preço da faturação (`line_vendus`+`combine_global`), e a aceitar `start`/`end` usando o `app_sales_summary_window` que já existe. **Não se altera `_summarize_docs`** (partilhado com o email diário).

**Tech Stack:** FastAPI + Motor (Mongo), React (CRA/craco), pytest (síncrono, sem pytest-asyncio).

## Global Constraints

- Textos visíveis ao utilizador em **PT-PT**.
- Helpers puros vivem em `backend/pos/` (padrão: `cash_math`, `drawer`, `pricing`).
- Testes do POS síncronos; correr com `cd backend && .venv/bin/python -m pytest <caminho> -v`.
- **NÃO alterar** `backend/vendus/client.py::_summarize_docs` nem o email diário (`scheduler.py`) — são partilhados; esta fase só consome o que já existe.
- Receita e faturas vêm **sempre** do Vendus (`app_sales_summary`/`app_sales_summary_window`), nunca de `order.total`. Produtos vendidos vêm dos nossos pedidos (a soma dos produtos pode não bater ao cêntimo com o faturado — é esperado; rodízio a €0).
- Frontend: node fora do PATH — `export PATH="$HOME/.local/node/bin:$HOME/Library/pnpm:$PATH"` antes de `cd frontend && npx craco build`.
- Fluxo git do grupo: ramo `matheus-pos-fase2` (já criado) → merge no `main` → deploy rsync + rebuild.

---

### Task 1: Backend — parar de imprimir o talão Z do Vendus no fecho

**Files:**
- Modify: `backend/server.py` (função `close_cash_session`, bloco 3682-3701)

**Interfaces:**
- Consumes/Produces: nenhuma interface nova. Remoção de um job de impressão best-effort.

- [ ] **Step 1: Remover o bloco que enfileira o talão Z do Vendus**

Em `backend/server.py`, dentro de `close_cash_session`, apagar por completo este bloco (linhas ~3682-3701) — o comentário e o `if`:

```python
    # Imprime o talão Z REAL do Vendus, se a sincronização acima teve sucesso e
    # devolveu o ESC/POS — job de impressão SEPARADO do Z da app, mesma
    # impressora da CAIXA. Best-effort: uma falha aqui também é só registada.
    if vendus_resp and vendus_resp.get("output"):
        try:
            await db.print_jobs.insert_one({
                "id": str(uuid.uuid4()),
                "order_id": None,
                "escpos_direct_b64": vendus_resp["output"],
                "printer_id": None,
                "printer_name": "Caixa",
                "printer_type": "cashier",
                "status": "pending",
                "attempts": 0,
                "error": None,
                "created_at": datetime.now(timezone.utc).isoformat(),
                "updated_at": datetime.now(timezone.utc).isoformat(),
            })
        except Exception as e:
            logger.error(f"Falha a enfileirar impressão do Z do Vendus (sessão {sessao['id']}): {e}")
```

Substituir por um comentário curto que explica a decisão:

```python
    # O talão Z do Vendus (2º papel) DEIXOU de ser impresso no fecho (decisão do
    # dono, Fase 2): o registador Vendus continua a ser fechado por
    # `_vendus_cash_close_sync` acima; o comprovativo Z oficial fica consultável
    # no backoffice do Vendus. O talão Z da APP (reconciliação, acima) mantém-se.
```

**Não** tocar: a chamada `_vendus_cash_close_sync` (3632, fecha o registador), o `vendus_closed` (usado no `z_data`), nem o bloco `build_z_escpos` (3664-3678, o Z da app).

- [ ] **Step 2: Confirmar que o backend importa e a suite POS não regride**

Run: `cd backend && .venv/bin/python -c "import server; print('import ok')"`
Expected: `import ok`.

Run: `cd backend && .venv/bin/python -m pytest tests/pos/ -q`
Expected: PASS (baseline igual — nenhum teste dependia deste print).

- [ ] **Step 3: Commit**

```bash
cd ~/dev/pizzaria && git add backend/server.py
git commit -m "POS fecho: deixar de imprimir o talao Z do Vendus (registador continua a fechar)"
```

---

### Task 2: Backend — helper puro de produtos vendidos com valor €

**Files:**
- Create: `backend/pos/report.py`
- Test: `backend/tests/pos/test_report_products.py`
- Modify: `backend/server.py` (import no topo + `get_report_data`, cálculo de `top_products`)

**Interfaces:**
- Consumes: `line_vendus`, `combine_global` (de `pos.pricing`).
- Produces: `summarize_products(orders, default_tax_id, top=15) -> [{"name": str, "quantity": int, "revenue": float}]`, ordenado por quantidade desc, top-N.

- [ ] **Step 1: Escrever o teste puro (falha)**

Criar `backend/tests/pos/test_report_products.py`:

```python
"""Agregação de produtos vendidos (quantidade + valor €) para o backoffice."""
from pos.report import summarize_products


def test_agrega_quantidade_e_valor_a_la_carte_e_desconto():
    orders = [
        {"items": [
            {"product_name": "Pizza", "quantity": 2, "unit_price": 10.0},
            {"product_name": "Água", "quantity": 1, "unit_price": 1.5},
        ]},
        {"items": [
            {"product_name": "Pizza", "quantity": 1, "unit_price": 10.0, "discount_pct": 50},
        ]},
    ]
    out = summarize_products(orders, "NOR")
    by = {r["name"]: r for r in out}
    assert by["Pizza"]["quantity"] == 3
    assert by["Pizza"]["revenue"] == 25.0   # 2*10 + 1*10*0.5
    assert by["Água"]["revenue"] == 1.5


def test_rodizio_incluido_conta_quantidade_mas_valor_zero():
    orders = [{"items": [
        {"product_name": "Costela (rodízio)", "quantity": 3, "unit_price": 0.0},
    ]}]
    out = summarize_products(orders, "NOR")
    assert out[0]["quantity"] == 3
    assert out[0]["revenue"] == 0.0


def test_ignora_itens_anulados():
    orders = [{"items": [
        {"product_name": "X", "quantity": 1, "unit_price": 5.0, "removed": True},
        {"product_name": "Y", "quantity": 1, "unit_price": 3.0},
    ]}]
    out = summarize_products(orders, "NOR")
    assert {r["name"] for r in out} == {"Y"}
```

- [ ] **Step 2: Correr para confirmar que falha**

Run: `cd backend && .venv/bin/python -m pytest tests/pos/test_report_products.py -v`
Expected: FAIL (`ModuleNotFoundError: No module named 'pos.report'`).

- [ ] **Step 3: Implementar o helper**

Criar `backend/pos/report.py`:

```python
"""Helper puro: agrega os produtos vendidos (quantidade + valor €) a partir dos
nossos pedidos, para o relatório do backoffice. O valor € por linha usa a MESMA
via da faturação (`line_vendus` + `combine_global` sem desconto global), pelo
que itens de rodízio incluídos (unit_price=0) entram a €0 e os descontos de
linha são respeitados. Ignora itens anulados (soft-void, `removed`). Sem I/O."""
from pos.pricing import line_vendus, combine_global


def summarize_products(orders, default_tax_id, top=15):
    """`orders`: pedidos NÃO cancelados. Devolve top-N produtos por quantidade,
    cada um com `quantity` e `revenue` (€ líquido, 2 casas)."""
    qty_by = {}
    rev_by = {}
    for o in orders:
        for item in o.get("items", []):
            if item.get("removed"):
                continue
            name = item.get("product_name", "Desconhecido")
            qty = item.get("quantity", 1) or 1
            _, net = combine_global(line_vendus(item, None, default_tax_id), 0)
            qty_by[name] = qty_by.get(name, 0) + qty
            rev_by[name] = round(rev_by.get(name, 0.0) + net, 2)
    rows = [
        {"name": k, "quantity": v, "revenue": rev_by.get(k, 0.0)}
        for k, v in qty_by.items()
    ]
    rows.sort(key=lambda x: x["quantity"], reverse=True)
    return rows[:top]
```

- [ ] **Step 4: Correr para confirmar que passa**

Run: `cd backend && .venv/bin/python -m pytest tests/pos/test_report_products.py -v`
Expected: PASS (3 testes).

- [ ] **Step 5: Ligar no `get_report_data` (substituir o cálculo inline de top_products)**

No topo de `backend/server.py`, junto dos outros `from pos...` (perto da linha 37-38), acrescentar:

```python
from pos.report import summarize_products
```

Em `get_report_data`, substituir todo o bloco atual de "Top products" (o cálculo de `product_counts` e `top_products`, ~server.py:4707-4721) por:

```python
    # Produtos vendidos: quantidade + valor € (via de preço da faturação;
    # rodízio a €0). `non_cancelled` já exclui cancelados.
    top_products = summarize_products(non_cancelled, VENDUS_DEFAULT_TAX_ID)
```

(O `return` continua a devolver `"top_products": top_products` — agora cada item tem também `revenue`.)

- [ ] **Step 6: Verificar import + suite POS**

Run: `cd backend && .venv/bin/python -c "import server; print('import ok')"`
Expected: `import ok`.

Run: `cd backend && .venv/bin/python -m pytest tests/pos/ -q`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
cd ~/dev/pizzaria && git add backend/pos/report.py backend/tests/pos/test_report_products.py backend/server.py
git commit -m "Backoffice: produtos vendidos com valor EUR (helper puro pos/report)"
```

---

### Task 3: Backend — report-data: lista de faturas + intervalo de datas

**Files:**
- Modify: `backend/server.py` (`get_report_data`)

**Interfaces:**
- Consumes: `VendusClient.app_sales_summary_window(start_lisbon_iso, end_lisbon_iso)` (já existe, devolve `{total, by_method, count, invoices, documents}`).
- Produces: `GET /admin/report-data` aceita `start`/`end` (YYYY-MM-DD, além do `date` legado) e devolve, além do que já devolve, `"invoices"` (lista fatura-a-fatura) e um bloco `"range"` `{start, end, days}`.

- [ ] **Step 1: Reescrever o cabeçalho/janela e a fonte de receita de `get_report_data`**

Em `backend/server.py`, na função `get_report_data`:

(a) Assinatura — aceitar `start`/`end`:

```python
@api_router.get("/admin/report-data")
async def get_report_data(date: Optional[str] = None, start: Optional[str] = None,
                          end: Optional[str] = None, authorization: Optional[str] = Header(None)):
```

(b) Substituir o bloco que calcula `target_date`/`start_of_day`/`end_of_day`/`start_utc`/`end_utc` por uma janela `[start_date, end_date]` (retrocompatível: `start` > `date` > hoje; `end` default = `start_date`):

```python
    await get_current_user(authorization)

    from zoneinfo import ZoneInfo
    lisbon_tz = ZoneInfo('Europe/Lisbon')
    today_str = datetime.now(lisbon_tz).strftime("%Y-%m-%d")

    def _valid_day(s):
        try:
            datetime.fromisoformat(s)
            return True
        except Exception:
            return False

    start_date = start if (start and _valid_day(start)) else (date if (date and _valid_day(date)) else today_str)
    end_date = end if (end and _valid_day(end)) else start_date
    if end_date < start_date:
        end_date = start_date

    start_dt = datetime.fromisoformat(start_date).replace(hour=0, minute=0, second=0, microsecond=0, tzinfo=lisbon_tz)
    end_dt = datetime.fromisoformat(end_date).replace(hour=23, minute=59, second=59, microsecond=999999, tzinfo=lisbon_tz)
    start_utc = start_dt.astimezone(timezone.utc).isoformat()
    end_utc = end_dt.astimezone(timezone.utc).isoformat()
```

(c) A query de `orders` mantém-se (`created_at` entre `start_utc` e `end_utc`).

(d) Substituir a fonte de receita (o bloco `c.app_sales_summary(target_date...)`) por `app_sales_summary_window`, e **guardar o `invoices`**:

```python
    total_revenue = 0.0
    avg_ticket = 0.0
    invoices_count = 0
    payment_methods = {}
    invoices = []
    revenue_source = "vendus"
    revenue_error = None
    try:
        c = _vendus_client()
        try:
            _summ = c.app_sales_summary_window(f"{start_date}T00:00:00", f"{end_date}T23:59:59")
        finally:
            c.close()
        total_revenue = _summ["total"]
        payment_methods = _summ["by_method"]
        invoices_count = _summ["count"]
        invoices = _summ.get("invoices", [])
        avg_ticket = (total_revenue / invoices_count) if invoices_count else 0.0
    except Exception as e:
        revenue_source = "erro"
        revenue_error = str(e)[:200]
        logger.error(f"report-data: falha ao obter vendas do Vendus: {revenue_error}")
```

- [ ] **Step 2: Atualizar o `return` — `date`/`range` + `invoices`**

Substituir o `return` de `get_report_data` por (mantém tudo o que já devolvia, acrescenta `range` e `invoices`; `date`/`date_formatted` passam a descrever o início da janela para retrocompatibilidade da UI atual):

```python
    days = (end_dt.date() - start_dt.date()).days + 1
    return {
        "date": start_date,
        "date_formatted": start_dt.strftime("%d/%m/%Y"),
        "range": {"start": start_date, "end": end_date, "days": days},
        "summary": {
            "total_orders": total_orders,
            "total_revenue": round(total_revenue, 2),
            "avg_ticket": round(avg_ticket, 2),
            "invoices_count": invoices_count,
            "revenue_source": revenue_source,
            "revenue_error": revenue_error,
            "cancelled_orders": cancelled_orders,
            "delivered_orders": delivered_orders,
            "paid_orders": paid_orders,
            "unpaid_orders": unpaid_orders
        },
        "payment_methods": payment_methods,
        "top_products": top_products,
        "peak_hours": peak_hours,
        "drawer_opens": drawer_opens,
        "invoices": invoices
    }
```

(O `drawer_opens` já era devolvido na Fase 1; a sua query por `{"at": {"$gte": start_utc, "$lte": end_utc}}` passa a cobrir a janela automaticamente. **Nota:** o `summarize_drawer_opens` ordena por "HH:MM" — para um intervalo multi-dia isto interleava dias; aceitável como conhecido nesta fase, o TODO já está no código. As `peak_hours` continuam a agregar por hora ao longo da janela.)

- [ ] **Step 3: Verificar import + suite**

Run: `cd backend && .venv/bin/python -c "import server; print('import ok')"`
Expected: `import ok`.

Run: `cd backend && .venv/bin/python -m pytest tests/pos/ tests/vendus/ -q`
Expected: PASS (não se tocou em `_summarize_docs` nem no email; `app_sales_summary_window` já existia e tem testes).

- [ ] **Step 4: Commit**

```bash
cd ~/dev/pizzaria && git add backend/server.py
git commit -m "Backoffice: report-data devolve lista de faturas + aceita intervalo de datas (start/end)"
```

---

### Task 4: Frontend — cartão "Faturas emitidas" + valor € nos produtos

**Files:**
- Modify: `frontend/src/pages/admin/AdminReports.js`

**Interfaces:**
- Consumes: `reportData.invoices` = `[{label, time, amount, method, number}]`; `reportData.top_products[].revenue`. `Receipt`, `Card*`, `Badge` já importados.

- [ ] **Step 1: Mostrar o valor € em cada produto**

Em `frontend/src/pages/admin/AdminReports.js`, no cartão "Produtos Mais Vendidos", a linha do badge da quantidade (~`AdminReports.js:461`) passa a mostrar também o valor €. Substituir:

```jsx
                        <Badge variant="secondary">{product.quantity}x</Badge>
```

por:

```jsx
                        <div className="flex items-center gap-2">
                          <span className="text-sm text-muted-foreground">€ {(product.revenue || 0).toFixed(2)}</span>
                          <Badge variant="secondary">{product.quantity}x</Badge>
                        </div>
```

- [ ] **Step 2: Adicionar o cartão "Faturas emitidas" (a seguir ao cartão "Aberturas de gaveta" da Fase 1)**

Logo a seguir ao `</Card>` do cartão "Aberturas de gaveta" (Fase 1), acrescentar:

```jsx
          {/* Faturas emitidas */}
          <Card className="mt-6">
            <CardHeader className="pb-3">
              <CardTitle className="text-lg flex items-center gap-2">
                <Receipt className="h-5 w-5" />
                Faturas emitidas
              </CardTitle>
            </CardHeader>
            <CardContent>
              {(reportData?.invoices || []).length === 0 ? (
                <p className="text-sm text-muted-foreground text-center py-6">
                  Nenhuma fatura neste período
                </p>
              ) : (
                <div className="space-y-1">
                  {reportData.invoices.map((inv, idx) => (
                    <div key={idx} className="flex items-center gap-3 p-2 rounded-lg hover:bg-secondary/50 text-sm">
                      <span className="font-mono text-muted-foreground w-12">{inv.time}</span>
                      <span className="flex-1 truncate">{inv.number || inv.label}</span>
                      <span className="text-muted-foreground truncate max-w-[120px]">{inv.method}</span>
                      <span className={`font-medium tabular-nums ${inv.amount < 0 ? 'text-red-600' : ''}`}>
                        € {inv.amount.toFixed(2)}
                      </span>
                    </div>
                  ))}
                </div>
              )}
            </CardContent>
          </Card>
```

- [ ] **Step 3: Verificar que compila**

Run: `export PATH="$HOME/.local/node/bin:$HOME/Library/pnpm:$PATH" && cd frontend && npx craco build 2>&1 | tail -15`
Expected: "Compiled successfully" (sem "Failed to compile").

- [ ] **Step 4: Commit**

```bash
cd ~/dev/pizzaria && git add frontend/src/pages/admin/AdminReports.js
git commit -m "Backoffice: cartao Faturas emitidas + valor EUR por produto"
```

---

### Task 5: Frontend — seletor de intervalo de datas (De / Até)

**Files:**
- Modify: `frontend/src/pages/admin/AdminReports.js`
- Modify: `frontend/src/lib/api.js` (`reportsAPI.getData`)

**Interfaces:**
- Produces: `reportsAPI.getData(start, end)` → `GET /admin/report-data?start=&end=`.

- [ ] **Step 1: `reportsAPI.getData` aceita start/end**

Em `frontend/src/lib/api.js`, substituir (linhas 165-166):

```javascript
  getData: (date = null) =>
    api.get('/admin/report-data', { params: date ? { date } : {} }),
```

por:

```javascript
  getData: (start = null, end = null) =>
    api.get('/admin/report-data', {
      params: { ...(start ? { start } : {}), ...(end ? { end } : {}) },
    }),
```

- [ ] **Step 2: Estado `endDate` + `loadReport` passa start/end**

Em `AdminReports.js`, a seguir ao `selectedDate` state (~linha 62-65), acrescentar:

```javascript
  const [endDate, setEndDate] = useState(() => new Date().toISOString().split('T')[0]);
```

`loadReport` (~121-132) passa a mandar o intervalo (garante `end >= start`):

```javascript
  const loadReport = useCallback(async () => {
    setLoading(true);
    try {
      const end = endDate < selectedDate ? selectedDate : endDate;
      const response = await reportsAPI.getData(selectedDate, end);
      setReportData(response.data);
    } catch (err) {
      console.error('Error loading report:', err);
      toast.error('Erro ao carregar relatório');
    } finally {
      setLoading(false);
    }
  }, [selectedDate, endDate]);
```

- [ ] **Step 3: Campo "Até" no seletor**

No bloco do seletor de datas (~`AdminReports.js:201-210`), a seguir ao `</div>` do input "De" (o que tem `value={selectedDate}`) e antes do botão `ChevronRight`, acrescentar um segundo input rotulado:

```jsx
          <span className="text-muted-foreground text-sm">até</span>
          <div className="flex items-center gap-2 px-4 py-2 rounded-lg border bg-card justify-center">
            <CalendarDays className="h-4 w-4 text-muted-foreground" />
            <input
              type="date"
              value={endDate}
              min={selectedDate}
              max={new Date().toISOString().split('T')[0]}
              onChange={(e) => setEndDate(e.target.value)}
              className="bg-transparent border-0 outline-none font-medium text-sm cursor-pointer"
            />
          </div>
```

(As setas ±1 dia continuam a mover o "De" — `changeDate` fica como está; quando `endDate < selectedDate`, o `loadReport` usa `selectedDate` como fim, i.e. um dia único.)

- [ ] **Step 4: Verificar que compila**

Run: `export PATH="$HOME/.local/node/bin:$HOME/Library/pnpm:$PATH" && cd frontend && npx craco build 2>&1 | tail -15`
Expected: "Compiled successfully".

- [ ] **Step 5: Commit**

```bash
cd ~/dev/pizzaria && git add frontend/src/pages/admin/AdminReports.js frontend/src/lib/api.js
git commit -m "Backoffice: seletor de intervalo de datas (De/Ate) no relatorio"
```

---

## Deploy (fim da fase)

Depois das 5 tasks revistas e verdes + revisão final whole-branch:
1. Push do ramo `matheus-pos-fase2` → merge no `main` (a partir do main atualizado) → push.
2. Deploy rsync (dry-run primeiro) + `docker compose up -d --build`.
3. Confirmar `health` + smoke: (a) fechar uma caixa e confirmar que já **não** sai o 2º talão (Vendus); (b) no backoffice, abrir Relatórios, ver a lista de faturas, o € por produto, e experimentar um intervalo de datas.

## Self-review (feito)

- **Cobertura do spec (Fluxo 3):** parar talão Z Vendus (T1) ✓; lista de faturas no backoffice (T2 backend expõe invoices, T4 cartão) ✓; produtos com € (T2 helper + T4 UI) ✓; intervalo de datas (T3 backend + T5 UI) ✓; faturação a prazo — fora de âmbito, não implementada (conforme decisão) ✓.
- **Não altera código partilhado:** `_summarize_docs` e `scheduler.py` (email) intactos — só se consome `invoices`/`app_sales_summary_window`.
- **Sem placeholders:** código completo em cada passo.
- **Consistência de tipos:** T2 produz `top_products[].revenue`; T4 lê `product.revenue`. T3 devolve `invoices` = `[{label,time,amount,method,number}]` (forma de `_summarize_docs`); T4 lê `inv.time/number/label/method/amount`. T5 `getData(start,end)` ↔ T3 `start`/`end`.
