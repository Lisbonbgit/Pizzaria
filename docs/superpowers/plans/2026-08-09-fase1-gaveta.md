# Fase 1 — Gaveta com caixa fechado (+ registo) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Permitir abrir a gaveta do dinheiro com o caixa fechado (botão no ecrã de Caixa Fechada, depois do PIN) e registar cada abertura para auditoria, visível no backoffice.

**Architecture:** O backend já abre a gaveta sem exigir sessão (`POST /pos/cash/drawer`); só falta (a) registar cada abertura numa coleção `drawer_opens` e (b) expor o botão no ecrã `PosAbrirCaixa`. O backoffice ganha um cartão que lista as aberturas do período, alimentado por um helper puro em `backend/pos/drawer.py`.

**Tech Stack:** FastAPI + Motor (Mongo), React (CRA/craco), pytest (testes síncronos com `asyncio.run`, sem pytest-asyncio).

## Global Constraints

- Textos visíveis ao utilizador em **PT-PT**.
- Helpers puros vivem em `backend/pos/` (padrão do projeto: `cash_math`, `z_report`, `pricing`).
- Testes do POS são **síncronos** e correm a corotina com `asyncio.run`, com `server.db` substituído por um fake em memória (ver `backend/tests/pos/test_cash_drawer.py`). Sem pytest-asyncio.
- Correr testes com o venv do backend: `cd backend && .venv/bin/python -m pytest <caminho> -v`.
- Identidade do operador vem **sempre** do token (`decode_pos_token` do `X-POS-Token`), nunca do corpo do pedido.
- Fluxo git do grupo: ramo `matheus-pos-melhorias` (já criado) → merge no `main` → deploy rsync + rebuild. Não commitar `.env`.

---

### Task 1: Backend — registar cada abertura de gaveta

**Files:**
- Modify: `backend/server.py` (função `open_cash_drawer`, ~3393-3418)
- Test: `backend/tests/pos/test_cash_drawer.py`

**Interfaces:**
- Consumes: `get_pos_or_admin(authorization, x_device_token) -> {"kind","user?"}` (server.py:3133); `decode_pos_token(token) -> payload` (importado de `pos.auth`, server.py:29).
- Produces: documentos em `db.drawer_opens` com a forma `{id: str, operator_id: str|None, operator_name: str, at: iso_utc, had_open_session: bool, cash_session_id: str|None}`.

- [ ] **Step 1: Atualizar o fake de BD do teste para as novas coleções**

O endpoint passará a usar `db.drawer_opens` e `db.cash_sessions`. Adicionar ao topo de `backend/tests/pos/test_cash_drawer.py` (a seguir a `_FakePrintJobs`, antes de `_FakeDb`) uma coleção genérica, e dar ao `_FakeDb` as novas coleções:

```python
class _FakeCollection:
    def __init__(self, docs=None):
        self.docs = list(docs or [])
        self.inserted = []

    async def insert_one(self, doc):
        self.inserted.append(doc)
        self.docs.append(doc)

    async def find_one(self, query, projection=None):
        for d in self.docs:
            if all(d.get(k) == v for k, v in query.items()):
                return d
        return None


class _FakeDb:
    def __init__(self, open_session=None):
        self.print_jobs = _FakePrintJobs()
        self.drawer_opens = _FakeCollection()
        self.cash_sessions = _FakeCollection([open_session] if open_session else [])
```

(Substitui a classe `_FakeDb` atual, que só tinha `print_jobs`.)

- [ ] **Step 2: Escrever o teste que falha (registo do operador + sessão)**

Acrescentar ao fim de `backend/tests/pos/test_cash_drawer.py`:

```python
def test_regista_abertura_com_operador_do_pos_token(monkeypatch):
    # Caixa FECHADA (sem sessão aberta) + operador identificado pelo X-POS-Token.
    fake_db = _FakeDb(open_session=None)
    monkeypatch.setattr(server, "db", fake_db)

    async def fake_valid_device_token(raw: str) -> bool:
        return raw == "dev-ok"

    monkeypatch.setattr(server, "valid_device_token", fake_valid_device_token)

    from server import create_pos_token
    pos_token = create_pos_token("op-1", "Ana")

    async def run():
        return await open_cash_drawer(
            authorization=None, x_device_token="dev-ok", x_pos_token=pos_token
        )

    resultado = asyncio.run(run())
    assert resultado == {"ok": True}

    # Registou a abertura com o operador do token e sem sessão aberta.
    assert len(fake_db.drawer_opens.inserted) == 1
    reg = fake_db.drawer_opens.inserted[0]
    assert reg["operator_id"] == "op-1"
    assert reg["operator_name"] == "Ana"
    assert reg["had_open_session"] is False
    assert reg["cash_session_id"] is None
    # E continua a enfileirar o pulso da gaveta.
    assert len(fake_db.print_jobs.inserted) == 1


def test_regista_had_open_session_quando_ha_caixa_aberta(monkeypatch):
    fake_db = _FakeDb(open_session={"id": "cs-1", "status": "open"})
    monkeypatch.setattr(server, "db", fake_db)

    async def fake_valid_device_token(raw: str) -> bool:
        return raw == "dev-ok"

    monkeypatch.setattr(server, "valid_device_token", fake_valid_device_token)

    async def run():
        return await open_cash_drawer(authorization=None, x_device_token="dev-ok", x_pos_token=None)

    asyncio.run(run())
    reg = fake_db.drawer_opens.inserted[0]
    assert reg["had_open_session"] is True
    assert reg["cash_session_id"] == "cs-1"
    assert reg["operator_name"] == "—"  # sem X-POS-Token e sem admin
```

- [ ] **Step 3: Correr os testes para confirmar que falham**

Run: `cd backend && .venv/bin/python -m pytest tests/pos/test_cash_drawer.py -v`
Expected: os dois testes novos FALHAM (`open_cash_drawer() got an unexpected keyword argument 'x_pos_token'`).

- [ ] **Step 4: Implementar o endpoint com registo**

Substituir a função `open_cash_drawer` (server.py:3393-3418) por:

```python
@api_router.post("/pos/cash/drawer")
async def open_cash_drawer(
    authorization: Optional[str] = Header(None),
    x_device_token: Optional[str] = Header(None),
    x_pos_token: Optional[str] = Header(None),
):
    """Abre a gaveta do dinheiro: enfileira o pulso ESC/POS ("kick") na impressora
    da CAIXA (mesmo mecanismo `print_jobs` + `escpos_direct_b64` +
    `printer_type="cashier"` das faturas e do talão Z). Regista SEMPRE a abertura
    (operador + hora + se havia caixa aberta) em `drawer_opens` — controlo interno,
    já que a gaveta pode ser aberta com o caixa fechado."""
    auth = await get_pos_or_admin(authorization, x_device_token)

    # Operador para o registo: do token POS (PIN) se houver; senão, se veio por
    # JWT de admin, "Administrador". A identidade vem sempre do token.
    operator_id, operator_name = None, None
    if x_pos_token:
        try:
            payload = decode_pos_token(x_pos_token)
            operator_id = payload.get("pos_user_id")
            operator_name = payload.get("name")
        except jwt.InvalidTokenError:
            pass
    if not operator_name and auth.get("kind") == "admin":
        operator_id, operator_name = "admin", "Administrador"

    sessao = await db.cash_sessions.find_one({"status": "open"}, {"_id": 0, "id": 1})
    now_iso = datetime.now(timezone.utc).isoformat()

    await db.drawer_opens.insert_one({
        "id": str(uuid.uuid4()),
        "operator_id": operator_id,
        "operator_name": operator_name or "—",
        "at": now_iso,
        "had_open_session": bool(sessao),
        "cash_session_id": sessao["id"] if sessao else None,
    })

    kick_bytes = b"\x1b\x70\x00\x19\xfa"  # ESC p 0 25 250 — pulso padrão da gaveta
    await db.print_jobs.insert_one({
        "id": str(uuid.uuid4()),
        "order_id": None,
        "escpos_direct_b64": base64.b64encode(kick_bytes).decode("ascii"),
        "printer_id": None,
        "printer_name": "Caixa",
        "printer_type": "cashier",
        "status": "pending",
        "attempts": 0,
        "error": None,
        "created_at": now_iso,
        "updated_at": now_iso,
    })
    return {"ok": True}
```

- [ ] **Step 5: Correr todos os testes do drawer (novos + os 3 antigos)**

Run: `cd backend && .venv/bin/python -m pytest tests/pos/test_cash_drawer.py -v`
Expected: PASS (5 testes — os 3 antigos continuam verdes com o `_FakeDb` atualizado, os 2 novos passam).

- [ ] **Step 6: Commit**

```bash
cd ~/dev/pizzaria && git add backend/server.py backend/tests/pos/test_cash_drawer.py
git commit -m "POS gaveta: regista cada abertura (operador/hora/sessao) em drawer_opens"
```

---

### Task 2: Backend — resumo puro das aberturas + expor no report-data

**Files:**
- Create: `backend/pos/drawer.py`
- Test: `backend/tests/pos/test_drawer_summary.py`
- Modify: `backend/server.py` (import no topo, junto dos outros `from pos...`; e `get_report_data`, ~4707 e ~4743)

**Interfaces:**
- Consumes: documentos `drawer_opens` da Task 1.
- Produces: `summarize_drawer_opens(rows, tz) -> [{"time": "HH:MM", "operator": str, "had_session": bool}]`, ordenado por hora; e a chave `"drawer_opens"` no JSON de `GET /admin/report-data`.

- [ ] **Step 1: Escrever o teste da função pura (falha)**

Criar `backend/tests/pos/test_drawer_summary.py`:

```python
"""Resumo das aberturas de gaveta para o relatório do backoffice."""
from zoneinfo import ZoneInfo

from pos.drawer import summarize_drawer_opens

LISBON = ZoneInfo("Europe/Lisbon")


def test_ordena_por_hora_e_formata_em_lisboa():
    rows = [
        {"at": "2026-08-09T20:30:00+00:00", "operator_name": "Ana", "had_open_session": True},
        {"at": "2026-08-09T18:05:00+00:00", "operator_name": "Rui", "had_open_session": False},
    ]
    out = summarize_drawer_opens(rows, LISBON)
    # Agosto = hora de verão (UTC+1): 18:05Z -> 19:05, 20:30Z -> 21:30.
    assert [o["time"] for o in out] == ["19:05", "21:30"]
    assert out[0] == {"time": "19:05", "operator": "Rui", "had_session": False}
    assert out[1] == {"time": "21:30", "operator": "Ana", "had_session": True}


def test_at_invalido_nao_rebenta():
    out = summarize_drawer_opens([{"at": None, "operator_name": None}], LISBON)
    assert out == [{"time": "—", "operator": "—", "had_session": False}]
```

- [ ] **Step 2: Correr para confirmar que falha**

Run: `cd backend && .venv/bin/python -m pytest tests/pos/test_drawer_summary.py -v`
Expected: FAIL (`ModuleNotFoundError: No module named 'pos.drawer'`).

- [ ] **Step 3: Implementar o helper puro**

Criar `backend/pos/drawer.py`:

```python
"""Helper puro: formata os registos de abertura de gaveta (`db.drawer_opens`)
para o relatório do backoffice — hora local HH:MM, operador, e se havia caixa
aberta. Sem I/O; recebe já os documentos lidos da BD."""
from datetime import datetime


def summarize_drawer_opens(rows, tz):
    out = []
    for r in rows:
        at = r.get("at")
        try:
            dt = datetime.fromisoformat(at.replace("Z", "+00:00")).astimezone(tz)
            hhmm = dt.strftime("%H:%M")
        except Exception:
            hhmm = "—"
        out.append({
            "time": hhmm,
            "operator": r.get("operator_name") or "—",
            "had_session": bool(r.get("had_open_session")),
        })
    out.sort(key=lambda x: x["time"])
    return out
```

- [ ] **Step 4: Correr para confirmar que passa**

Run: `cd backend && .venv/bin/python -m pytest tests/pos/test_drawer_summary.py -v`
Expected: PASS (2 testes).

- [ ] **Step 5: Ligar no `get_report_data`**

No topo de `backend/server.py`, junto dos outros imports `from pos...` (perto da linha 29-33), acrescentar:

```python
from pos.drawer import summarize_drawer_opens
```

Em `get_report_data` (server.py), a seguir ao cálculo de `peak_hours` (imediatamente antes do `return`, ~4742), acrescentar:

```python
    # Aberturas de gaveta do dia (registo de auditoria — Fase 1)
    drawer_rows = await db.drawer_opens.find(
        {"at": {"$gte": start_utc, "$lte": end_utc}}, {"_id": 0}
    ).sort("at", 1).to_list(500)
    drawer_opens = summarize_drawer_opens(drawer_rows, lisbon_tz)
```

E no dicionário do `return` (server.py:4743-4761), acrescentar a chave (depois de `"peak_hours": peak_hours`):

```python
        "peak_hours": peak_hours,
        "drawer_opens": drawer_opens
```

- [ ] **Step 6: Verificar que o backend importa e a suite POS não regride**

Run: `cd backend && .venv/bin/python -c "import server; print('import ok')"`
Expected: `import ok` (sem erro de sintaxe/import).

Run: `cd backend && .venv/bin/python -m pytest tests/pos/ -q`
Expected: PASS (toda a suite pos verde, incluindo os novos testes).

- [ ] **Step 7: Commit**

```bash
cd ~/dev/pizzaria && git add backend/pos/drawer.py backend/tests/pos/test_drawer_summary.py backend/server.py
git commit -m "POS gaveta: resumo das aberturas no report-data (helper puro pos/drawer)"
```

---

### Task 3: Frontend — botão "Abrir Gaveta" no ecrã Caixa Fechada

**Files:**
- Modify: `frontend/src/pages/pos/PosAbrirCaixa.js`

**Interfaces:**
- Consumes: `posAPI.openDrawer()` (lib/api.js:273, já existe).

- [ ] **Step 1: Importar o ícone `Vault`**

Em `frontend/src/pages/pos/PosAbrirCaixa.js:2`, acrescentar `Vault` ao import de `lucide-react`:

```javascript
import { Lock, Loader2, Vault } from 'lucide-react';
```

- [ ] **Step 2: Adicionar estado + handler de abrir gaveta**

Dentro de `PosAbrirCaixa`, a seguir a `const [submitting, setSubmitting] = useState(false);` (linha 40), acrescentar:

```javascript
  const [drawerSubmitting, setDrawerSubmitting] = useState(false);

  const abrirGaveta = useCallback(async () => {
    setDrawerSubmitting(true);
    try {
      await posAPI.openDrawer();
      toast.success('Gaveta aberta');
    } catch (err) {
      console.error('Erro ao abrir a gaveta:', err);
      toast.error(err.response?.data?.detail || 'Não foi possível abrir a gaveta');
    } finally {
      setDrawerSubmitting(false);
    }
  }, []);
```

- [ ] **Step 3: Adicionar o botão secundário (a seguir ao botão "Abrir Caixa")**

Logo depois do `</Button>` de "Abrir Caixa" (linha 107), antes do `</div>` que fecha o ecrã, acrescentar:

```jsx
      <Button
        variant="outline"
        onClick={abrirGaveta}
        disabled={drawerSubmitting}
        className="w-full max-w-xs mt-3 h-12 border-white/30 bg-transparent text-white hover:bg-white/10 hover:text-white"
      >
        <Vault className="h-4 w-4 mr-1.5" />
        {drawerSubmitting ? 'A abrir...' : 'Abrir Gaveta'}
      </Button>
```

- [ ] **Step 4: Verificar que compila**

Run: `cd frontend && npx craco build 2>&1 | tail -15`
Expected: "Compiled successfully" (ou "Compiled with warnings" sem erros). Sem `Failed to compile`.

- [ ] **Step 5: Commit**

```bash
cd ~/dev/pizzaria && git add frontend/src/pages/pos/PosAbrirCaixa.js
git commit -m "POS gaveta: botao Abrir Gaveta no ecra de Caixa Fechada (apos PIN)"
```

---

### Task 4: Frontend — cartão "Aberturas de gaveta" no backoffice

**Files:**
- Modify: `frontend/src/pages/admin/AdminReports.js`

**Interfaces:**
- Consumes: `reportData.drawer_opens` = `[{time, operator, had_session}]` (Task 2). `Wallet`, `Card`, `CardContent`, `CardHeader`, `CardTitle`, `Badge` já importados.

- [ ] **Step 1: Adicionar o cartão a seguir ao "Horários de Pico"**

Em `frontend/src/pages/admin/AdminReports.js`, logo a seguir ao `</Card>` do bloco "Peak Hours" (linha 514) e antes do `</div>` (linha 515), acrescentar:

```jsx
          {/* Aberturas de gaveta (auditoria) */}
          <Card className="mt-6">
            <CardHeader className="pb-3">
              <CardTitle className="text-lg flex items-center gap-2">
                <Wallet className="h-5 w-5" />
                Aberturas de gaveta
              </CardTitle>
            </CardHeader>
            <CardContent>
              {(reportData?.drawer_opens || []).length === 0 ? (
                <p className="text-sm text-muted-foreground text-center py-6">
                  Nenhuma abertura de gaveta registada neste dia
                </p>
              ) : (
                <div className="space-y-2">
                  {reportData.drawer_opens.map((d, idx) => (
                    <div key={idx} className="flex items-center gap-3 p-2 rounded-lg hover:bg-secondary/50">
                      <span className="font-mono text-sm text-muted-foreground w-12">{d.time}</span>
                      <span className="flex-1 font-medium truncate">{d.operator}</span>
                      <Badge variant={d.had_session ? 'secondary' : 'outline'}>
                        {d.had_session ? 'Caixa aberta' : 'Caixa fechada'}
                      </Badge>
                    </div>
                  ))}
                </div>
              )}
            </CardContent>
          </Card>
```

- [ ] **Step 2: Verificar que compila**

Run: `cd frontend && npx craco build 2>&1 | tail -15`
Expected: "Compiled successfully" (sem `Failed to compile`).

- [ ] **Step 3: Commit**

```bash
cd ~/dev/pizzaria && git add frontend/src/pages/admin/AdminReports.js
git commit -m "Backoffice: cartao Aberturas de gaveta no relatorio"
```

---

## Deploy (fim da fase)

Depois das 4 tasks revistas e verdes, seguir o fluxo git do grupo:
1. `git push -u origin matheus-pos-melhorias`
2. Merge no `main` (a partir do `main` atualizado) + `git push origin main`
3. Deploy rsync (dry-run primeiro) + `docker compose up -d --build`
4. Confirmar `health` + fazer um smoke: com caixa fechada, entrar com PIN → "Abrir Gaveta" → confirmar pulso + registo no backoffice.

## Self-review (feito)

- **Cobertura do spec (Fluxo 1):** botão no ecrã de Caixa Fechada após PIN (Task 3) ✓; registo operador+hora+sessão (Task 1) ✓; visível no backoffice (Tasks 2+4) ✓.
- **Sem placeholders:** todo o código está escrito; sem TODO/TBD.
- **Consistência de tipos:** `drawer_opens` gravado na Task 1 tem `operator_name`/`had_open_session`/`at`; a Task 2 lê exatamente esses campos; o cartão da Task 4 consome `{time, operator, had_session}` produzido pela Task 2. ✓
