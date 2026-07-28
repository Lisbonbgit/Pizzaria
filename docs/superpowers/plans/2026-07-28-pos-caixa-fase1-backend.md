# POS + Caixa — Fase 1 (Backend) — Plano de Implementação

> **Para quem executa (agente):** SUB-SKILL OBRIGATÓRIA: usar `superpowers:subagent-driven-development` (recomendado) ou `superpowers:executing-plans` para implementar tarefa a tarefa. Os passos usam checkbox (`- [ ]`).

**Goal:** Base de backend do POS: utilizadores com PIN, auth-duplo (o `/pos` passa a poder faturar), sessão de caixa (abrir/movimentos/fechar) com **relatório Z reconciliado contra o Vendus**, e emissão fiscal **idempotente** (nunca cobrar duas vezes), com `pos_sales` **por documento**.

**Architecture:** Tudo em `backend/`. Reaproveita `close_table` (emissão FS), `VendusClient` e `app_sales_summary`/`list_app_invoices` (reconciliação). Lógica sensível (matemática da gaveta, idempotência, reconciliação, mapeamento venda→documentos) extraída para **helpers PUROS** testáveis (estilo dos testes existentes, sem I/O). Endpoints finos por cima.

**Tech Stack:** FastAPI, Motor (Mongo async), Pydantic v2, PyJWT (HS256), bcrypt, pytest (unitário puro). Base spec: `docs/superpowers/specs/2026-07-28-pos-caixa-design.md`.

## Global Constraints
- **Fiscal ao vivo:** FS comunicadas à AT, register "Caixa API" `VENDUS_REGISTER_ID=358144579`. **Nunca emitir 2ª FS para o mesmo fecho** (idempotência) e **nunca fechar a gaveta só com base no Mongo** (reconciliar com o Vendus).
- **Dinheiro** identifica-se por **`payment_method_id`** (`pos_settings.cash_payment_method_id`), nunca pela string "Dinheiro".
- **Sessão de caixa** resolve-se **no servidor**; nunca aceitar `cash_session_id` nem `pos_user_id` do body. Parâmetro chama-se sempre `cash_session_id` (≠ `table_sessions` do QR).
- **Leitura do Vendus por JANELA TEMPORAL** (`opened_at`→`closed_at`) + `register_id`, nunca por string de data.
- **Não partir** o fluxo QR (`/`, endpoints públicos, `db.table_sessions`) nem o admin existente.
- Dinheiro arredondado a 2 casas. Comentários em PT-PT. Auth: `JWT_SECRET`/HS256 já existentes; `hash_password`/`verify_password` (bcrypt) em `server.py:400-403`.
- Testes: `cd backend && python -m pytest tests/ -q`. Novos helpers puros em `backend/pos/` com testes em `backend/tests/pos/`.

---

## Estrutura de ficheiros
- **Criar** `backend/pos/__init__.py`
- **Criar** `backend/pos/cash_math.py` — helpers puros: `expected_cash(...)`, `reconciliation_diff(...)`.
- **Criar** `backend/pos/idempotency.py` — `stable_ext_ref(table_number, cash_session_id, items)`.
- **Criar** `backend/pos/sales.py` — `build_pos_sales_rows(invoices, docs, payment_method_id, cash_session_id, pos_user_id, kind, table_number)`.
- **Criar** `backend/pos/auth.py` — `create_pos_token/decode_pos_token`, `hash_token/verify_token`.
- **Modificar** `backend/server.py` — modelos, endpoints POS/admin, auth-duplo, hook no `close_table`.
- **Criar** testes em `backend/tests/pos/` (um ficheiro por helper).

---

### Task 1: Utilizadores POS (`pos_users`) — CRUD + PIN

**Files:** Modify `backend/server.py`. Test: `backend/tests/pos/test_pin.py`

**Interfaces — Produces:** coleção `pos_users {id, name, pin_hash, active, created_at}`; endpoints `GET/POST/PUT/DELETE /api/admin/pos/users` (admin JWT via `get_current_user`). Reutiliza `hash_password`/`verify_password`.

- [ ] **Passo 1: Teste (validação do PIN)** — `backend/tests/pos/test_pin.py`
```python
import re
def valid_pin(pin: str) -> bool:
    return bool(re.fullmatch(r"\d{4}", pin or ""))

def test_pin_4_digitos():
    assert valid_pin("1234")
    assert not valid_pin("12a4")
    assert not valid_pin("123")
    assert not valid_pin("")
```
- [ ] **Passo 2: Correr e ver falhar/passar** — `cd backend && python -m pytest tests/pos/test_pin.py -q` (Espera: PASS — é lógica pura).
- [ ] **Passo 3: Implementar no server.py** — modelos `PosUserCreate{name, pin}`, `PosUserUpdate{name?, pin?, active?}`, e os 4 endpoints. No create/update: `if pin: validar 4 dígitos, pin_hash = hash_password(pin)`. Nunca devolver `pin_hash`. Lista devolve `{id,name,active,created_at}`.
- [ ] **Passo 4: Verificar** — arrancar backend local; `POST /api/admin/pos/users {name:"Maicon", pin:"1234"}` (com token admin) → 200; `GET` lista sem `pin_hash`.
- [ ] **Passo 5: Commit** — `git add -A && git commit -m "POS: utilizadores com PIN (pos_users CRUD)"`

---

### Task 2: Dispositivos + device token (`pos_devices`)

**Files:** Create `backend/pos/auth.py`. Modify `backend/server.py`. Test: `backend/tests/pos/test_device_token.py`

**Interfaces — Produces:** `hash_token(raw)->str`, `verify_token(raw, hash)->bool` (bcrypt); coleção `pos_devices {id, token_hash, label, active, created_at, expires_at}`; `POST /api/admin/pos/device-token {label, days?}` → devolve `{token}` **uma vez**; `POST /api/admin/pos/device-token/{id}/revoke`. Helper `async def valid_device_token(raw) -> bool`.

- [ ] **Passo 1: Teste** — `backend/tests/pos/test_device_token.py`
```python
from pos.auth import hash_token, verify_token
def test_token_hash_roundtrip():
    h = hash_token("abc123")
    assert verify_token("abc123", h)
    assert not verify_token("errado", h)
```
- [ ] **Passo 2: Correr** — `python -m pytest tests/pos/test_device_token.py -q` → FAIL (módulo não existe).
- [ ] **Passo 3: Implementar** — `pos/auth.py`: `hash_token = bcrypt.hashpw(...); verify_token = bcrypt.checkpw(...)`. Em `server.py`: gerar token `secrets.token_urlsafe(32)`, guardar `token_hash`, `expires_at = now + days (default 90)`; devolver o token em claro **só na resposta do create**. `valid_device_token(raw)`: procura `pos_devices` ativos não expirados e testa `verify_token` contra cada hash.
- [ ] **Passo 4: Verificar** — `python -m pytest tests/pos/ -q` PASS; criar token via API → 200 com `token`.
- [ ] **Passo 5: Commit** — `git commit -m "POS: device tokens (pos_devices, criar/revogar/validar)"`

---

### Task 3: Login POS + sessão POS curta + dependências de auth

**Files:** Modify `backend/pos/auth.py`, `backend/server.py`. Test: `backend/tests/pos/test_pos_token.py`

**Interfaces — Consumes:** `JWT_SECRET`, `JWT_ALGORITHM`. **Produces:** `create_pos_token(pos_user_id, name)`, `decode_pos_token(token)->dict`; `POST /api/pos/login {pin}` → valida PIN contra `pos_users` ativos → `{token, user}` (token curto, ex.: 12h); dep `get_pos_operator(x_pos_token)` → `{id,name}`; dep `get_pos_or_admin(authorization, x_device_token)` que aceita **admin JWT OU device token válido** (senão 401).

- [ ] **Passo 1: Teste** — `backend/tests/pos/test_pos_token.py`
```python
import os; os.environ.setdefault("JWT_SECRET", "x"*40)
from pos.auth import create_pos_token, decode_pos_token
def test_pos_token_roundtrip():
    t = create_pos_token("u1", "Maicon")
    d = decode_pos_token(t)
    assert d["pos_user_id"] == "u1" and d["name"] == "Maicon"
```
- [ ] **Passo 2: Correr** → FAIL.
- [ ] **Passo 3: Implementar** — `create_pos_token` usa `jwt.encode({"pos_user_id","name","exp"}, JWT_SECRET, HS256)`; `decode_pos_token` valida. Em `server.py`: `POST /pos/login` (procura utilizador ativo cujo `verify_password(pin, pin_hash)` bate; rate-limit simples por device); `get_pos_operator` lê header `X-POS-Token`; `get_pos_or_admin` tenta `get_current_user` (JWT admin) e, se falhar, `valid_device_token(x_device_token)`.
- [ ] **Passo 4: Verificar** — `pytest tests/pos/ -q` PASS; `POST /pos/login {pin:"1234"}` (com device token) → token + user.
- [ ] **Passo 5: Commit** — `git commit -m "POS: login por PIN + sessao POS curta + auth-duplo (get_pos_or_admin)"`

---

### Task 4: Aplicar auth-duplo aos endpoints reutilizados pelo POS

**Files:** Modify `backend/server.py`.

**Interfaces — Consumes:** `get_pos_or_admin` (Task 3). **Produces:** os endpoints que o `/pos` consome aceitam admin JWT **ou** device token.

Endpoints a converter de `get_current_user` → `get_pos_or_admin` (enumerados): `tables-overview`, `GET /tables/{n}/bill`, `GET /vendus/payment-methods`, `POST /tables/{n}/close`, `POST /orders/{id}/items/{idx}/void`, `POST /orders/{id}/items/{idx}/discount`, `POST /tables/{n}/print-consulta`, `POST /tables/{n}/free`, e o endpoint de adicionar item manual à mesa. (Deixar Dashboard/Menu/Reports/Settings a exigir **admin JWT**.)

- [ ] **Passo 1: Teste (dep aceita ambos)** — `backend/tests/pos/test_dual_auth.py`: teste puro que confirma a lógica "admin OU device" com um duplo mock (encode um JWT admin válido → passa; device token válido → passa; nenhum → 401). Usar `HTTPException` capturada.
- [ ] **Passo 2: Correr** → FAIL/def.
- [ ] **Passo 3: Implementar** — trocar a dependência nesses endpoints. Confirmar por `grep -n "get_pos_or_admin" server.py` que aparece nos ~9 sítios certos.
- [ ] **Passo 4: Verificar** — `pytest tests/ -q` (nada partido); manual: `GET /api/tables-overview` com `X-Device-Token` válido → 200.
- [ ] **Passo 5: Commit** — `git commit -m "POS: auth-duplo aplicado aos endpoints de faturacao/mesa"`

---

### Task 5: Definições do POS (`pos_settings`) + método "dinheiro"

**Files:** Modify `backend/server.py`. Test: (trivial, opcional)

**Interfaces — Produces:** `GET/PUT /api/admin/pos/settings` (admin JWT) → `{require_open_cash:true, cash_payment_method_id:int|null, z_footer_text:str}` guardado em `db.settings` key `"pos"`.

- [ ] **Passo 1: Implementar** — get (com defaults) e put. `cash_payment_method_id` escolhido de `/vendus/payment-methods` (o id do "Dinheiro").
- [ ] **Passo 2: Verificar** — PUT/GET round-trip via API.
- [ ] **Passo 3: Commit** — `git commit -m "POS: definicoes (pos_settings + cash_payment_method_id)"`

---

### Task 6: Sessão de caixa — abrir (atómico) + atual

**Files:** Modify `backend/server.py`. Test: `backend/tests/pos/test_cash_open.py`

**Interfaces — Produces:** coleção `cash_sessions` (ver spec §4.1); índice único parcial `{status:"open"}`; `POST /api/pos/cash/open {opening_amount}` (operador de `get_pos_operator`); `GET /api/pos/cash/current`.

- [ ] **Passo 1: Teste (unicidade — lógica)** — `test_cash_open.py`: função pura `pick_open_session(existing, new)` que devolve a existente se `existing` estiver aberta (simula o find-or-create atómico); teste: com uma aberta → devolve-a; sem nenhuma → cria.
- [ ] **Passo 2: Correr** → FAIL.
- [ ] **Passo 3: Implementar** — criar índice `db.cash_sessions.create_index([("status",1)], unique=True, partialFilterExpression={"status":"open"})` no arranque. `open`: tentar `insert_one`; se `DuplicateKeyError` → devolver a sessão aberta atual (idempotente). `current`: `find_one({"status":"open"})`.
- [ ] **Passo 4: Verificar** — `pytest tests/pos/ -q` PASS; abrir 2× seguidas → a 2ª devolve a mesma sessão (não cria).
- [ ] **Passo 5: Commit** — `git commit -m "POS: abrir/consultar caixa (uma so aberta, atomico)"`

---

### Task 7: Movimentos de caixa (sangria/reforço)

**Files:** Modify `backend/server.py`, `backend/pos/cash_math.py`. Test: `backend/tests/pos/test_cash_math.py`

**Interfaces — Produces:** `POST /api/pos/cash/movement {type:"sangria"|"reforco", amount, reason?}` (append a `movements`, operador do token); helper puro `expected_cash(opening, cash_sales, movements)`.

- [ ] **Passo 1: Teste** — `test_cash_math.py`
```python
from pos.cash_math import expected_cash
def test_expected_cash():
    movs = [{"type":"reforco","amount":20.0}, {"type":"sangria","amount":50.0}]
    # 100 abertura + 300 vendas dinheiro + 20 reforco - 50 sangria = 370
    assert expected_cash(100.0, 300.0, movs) == 370.0
```
- [ ] **Passo 2: Correr** → FAIL.
- [ ] **Passo 3: Implementar** — `expected_cash`: `round(opening + cash_sales + sum(reforço) - sum(sangria), 2)`. Endpoint valida sessão aberta + `amount>0`.
- [ ] **Passo 4: Verificar** — PASS; movimento aparece na sessão.
- [ ] **Passo 5: Commit** — `git commit -m "POS: sangria/reforco + expected_cash puro"`

---

### Task 8: `pos_sales` por documento + resolução da sessão no `close_table`

**Files:** Create `backend/pos/sales.py`. Modify `backend/server.py` (`close_table`). Test: `backend/tests/pos/test_pos_sales.py`

**Interfaces — Consumes:** `invoices[]` e `docs[]` do `close_table`. **Produces:** `build_pos_sales_rows(invoices, docs, payment_method_id, cash_session_id, pos_user_id, kind, table_number) -> list[dict]` (uma linha por documento); coleção `pos_sales` com índice único `vendus_document_id`; `close_table` grava as linhas e resolve a sessão **no servidor**.

- [ ] **Passo 1: Teste** — `test_pos_sales.py`
```python
from pos.sales import build_pos_sales_rows
def test_uma_linha_por_documento():
    invoices=[{"amount":40.0},{"amount":45.0}]
    docs=[{"id":11,"number":"FS 1"},{"id":12,"number":"FS 2"}]
    rows=build_pos_sales_rows(invoices, docs, 316430468, "s1", "u1", "mesa", 5)
    assert len(rows)==2
    assert rows[0]["vendus_document_id"]==11 and rows[0]["amount"]==40.0
    assert rows[1]["doc_number"]=="FS 2" and rows[1]["cash_session_id"]=="s1"
```
- [ ] **Passo 2: Correr** → FAIL.
- [ ] **Passo 3: Implementar** — `build_pos_sales_rows`: `zip(invoices, docs)` → dict por documento. No arranque criar índice único `vendus_document_id`. No `close_table`: depois de `docs = await _emit_all()`, **resolver a sessão**: se veio por device token → `find_one(cash_sessions status=open)`; se não houver → `409 "Abra a caixa primeiro"` (só quando `require_open_cash`); se veio por admin JWT (legado) → seguir sem gravar. Inserir as linhas com `insert_many(ordered=False)` (o índice único absorve duplicados de retry). Passar `pos_user_id` do `get_pos_operator`.
- [ ] **Passo 4: Verificar** — `pytest tests/pos/ -q` PASS; manual: fechar mesa com `split_count=2` → **2 linhas** em `pos_sales`.
- [ ] **Passo 5: Commit** — `git commit -m "POS: pos_sales por documento + sessao resolvida no servidor"`

---

### Task 9: Idempotência fiscal (referência estável + dedup)

**Files:** Create `backend/pos/idempotency.py`. Modify `backend/server.py`. Test: `backend/tests/pos/test_idempotency.py`

**Interfaces — Produces:** `stable_ext_ref(table_number, cash_session_id, items) -> str` (determinística); `close_table` usa-a nas `invoices` e faz **dedup antes de emitir**.

- [ ] **Passo 1: Teste** — `test_idempotency.py`
```python
from pos.idempotency import stable_ext_ref
def test_ref_estavel_e_sensivel():
    items=[{"title":"Pizza","qty":1,"gross_price":13.9,"tax_id":"INT"}]
    a=stable_ext_ref(5,"s1",items); b=stable_ext_ref(5,"s1",items)
    assert a==b                          # mesmo fecho -> mesma ref (idempotente)
    assert a.startswith("mesa-5-s1-")
    items2=items+[{"title":"Coca","qty":1,"gross_price":2.0,"tax_id":"NOR"}]
    assert stable_ext_ref(5,"s1",items2) != a   # itens diferentes -> ref diferente
```
- [ ] **Passo 2: Correr** → FAIL.
- [ ] **Passo 3: Implementar** — `stable_ext_ref`: `h = sha1(json.dumps(items, sort_keys=True).encode()).hexdigest()[:10]; return f"mesa-{table}-{cash_session_id}-{h}"`. Substituir os `ext_ref` de `mesa-{N}-{ts}` no `close_table` (ambos os ramos; no split, juntar `-{i+1}de{n}`). Antes do `_emit_all`, para cada `inv`, consultar `list_app_invoices(date=hoje)` e se já existir doc com esse `external_reference`, **reutilizá-lo** em vez de emitir. (Marcar a mesa `a_faturar` com a ref prevista antes de chamar o Vendus; recuperação no arranque fica documentada para Task 10/Fase seguinte se exceder o tempo.)
- [ ] **Passo 4: Verificar** — PASS; manual: emitir, forçar retry do mesmo fecho → **não** cria 2ª FS (reutiliza).
- [ ] **Passo 5: Commit** — `git commit -m "POS: idempotencia fiscal (ext_ref estavel + dedup antes de emitir)"`

---

### Task 10: Fechar caixa + reconciliação + dados do Z

**Files:** Modify `backend/server.py`, `backend/pos/cash_math.py`. Test: `backend/tests/pos/test_reconcile.py`

**Interfaces — Consumes:** `VendusClient.app_sales_summary`/`list_app_invoices` (por janela). **Produces:** `reconciliation_diff(vendus_by_method, pos_sales_by_method) -> {ok, orphans, missing}`; `POST /api/pos/cash/close {counted_amount}` → calcula esperado (Vendus, janela+register, por `cash_payment_method_id`), reconcilia, grava `expected_cash/counted/difference/totals_by_method/reconciliation` e devolve dados do Z.

- [ ] **Passo 1: Teste** — `test_reconcile.py`
```python
from pos.cash_math import reconciliation_diff
def test_reconcile_ok_e_orfaos():
    v={"Dinheiro":{"total":56.25,"count":1},"Multibanco":{"total":199.65,"count":3}}
    p={"Dinheiro":{"total":56.25,"count":1},"Multibanco":{"total":199.65,"count":3}}
    assert reconciliation_diff(v,p)["ok"] is True
    p2={"Dinheiro":{"total":56.25,"count":1}}     # falta Multibanco em pos_sales
    r=reconciliation_diff(v,p2)
    assert r["ok"] is False and "Multibanco" in r["orphans"]
```
- [ ] **Passo 2: Correr** → FAIL.
- [ ] **Passo 3: Implementar** — `reconciliation_diff`: compara totais/contagens por método; `ok` se batem; lista divergências. Novo método no `VendusClient`: `app_sales_summary_window(start_iso, end_iso)` (como `app_sales_summary` mas filtra por **janela temporal** em vez de `startswith(data)`; mesmo `register_id`). `close`: lê Vendus na janela `opened_at`→agora; soma dinheiro por `cash_payment_method_id`; `expected_cash(...)`; reconcilia vs `pos_sales` da sessão; grava tudo; `status="closed"`, `closed_at`, operador. Se reconciliação `ok=False` → devolver o Z **com aviso** (não apagar dados).
- [ ] **Passo 4: Verificar** — `pytest tests/pos/ -q` PASS; manual: abrir caixa, fechar 1 mesa em dinheiro, fechar caixa → esperado = abertura + valor; reconciliação `ok`.
- [ ] **Passo 5: Commit** — `git commit -m "POS: fechar caixa + reconciliacao Vendus (janela) + dados do Z"`

---

### Task 11: Impressão do relatório Z + reimpressão

**Files:** Modify `backend/server.py`. Test: manual/smoke.

**Interfaces — Consumes:** dados do Z (Task 10), caminho de `print_jobs`. **Produces:** talão Z ESC/POS enviado à ponte no fecho; `GET /api/pos/cash/{id}/z` para reobter/reimprimir.

- [ ] **Passo 1: Implementar** — função `build_z_escpos(session)` (cabeçalho, totais por método, movimentos, fundo/esperado/contado/diferença, aviso de reconciliação, `z_footer_text`). No `close`, criar `print_jobs` com `escpos_direct_b64` (printer_type cashier), como as faturas. `GET .../z` devolve os dados.
- [ ] **Passo 2: Verificar** — fechar caixa → talão Z imprime na caixa; `GET .../z` devolve os dados.
- [ ] **Passo 3: Commit** — `git commit -m "POS: relatorio Z imprimivel + reimpressao"`

---

## Auto-revisão (checklist do plano)
- **Cobertura do spec (§ Fase 1):** utilizadores+PIN (T1), device token (T2), auth-duplo (T3-T4), definições/cash method (T5), caixa abrir/atual (T6), movimentos (T7), pos_sales-por-doc + sessão server-side (T8), idempotência (T9), fecho+reconciliação+Z (T10-T11). ✅
- **Coerência de interfaces:** `get_pos_or_admin`/`get_pos_operator` (T3) usados em T4/T8/T10; `expected_cash`/`reconciliation_diff` (T7/T10) puros; `stable_ext_ref` (T9) e `build_pos_sales_rows` (T8) puros. ✅
- **Sem placeholders:** cada passo tem teste/código concreto. Tarefas de I/O (T4/T5/T11) verificadas por API/manual porque o harness é unitário puro (sem fixtures de Mongo). ✅
- **Frontend NÃO incluído:** a janela `/pos`, ecrãs (login/abrir/fechar caixa), gestão `/admin/pos` e renomear a nav (`AdminLayout.js:21`) ficam para o **plano da Fase 1 (Frontend)**, a escrever a seguir a este.
