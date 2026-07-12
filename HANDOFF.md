# HANDOFF — Migração Pizzaria "Lenha e Brasa" (Emergent → Hostinger)

> Documento de passagem de contexto entre sessões. Estado em 2026-07-12.
> **Fonte da verdade:** `git@github.com:Lisbonbgit/Pizzaria.git`, branch **`migracao-hostinger`** (commit `ed3bc2c`).

---

## 1. O que é o projeto
Sistema full-stack de **pedidos por QR code na mesa** para a pizzaria **"Lenha e Brasa"**.

- **Backend:** FastAPI + Motor (MongoDB) — `backend/server.py` (~2100 linhas), `backend/scheduler.py`.
- **Frontend:** React (CRA/craco) + Tailwind + shadcn/ui — `frontend/`.
- **Print Agent:** script Python (só usa `requests`) que corre num PC Windows na pizzaria e imprime em impressoras térmicas ESC/POS (cozinha/caixa) por polling — `print_agent/`.
- **Email:** relatório diário de vendas às 23:59 (Europe/Lisbon) via **Resend**.
- Login admin por env vars (`ADMIN_EMAIL` / `ADMIN_PASSWORD_HASH` bcrypt). Imagens guardadas na própria BD (coleção `images`, base64).

## 2. GitHub — onde está tudo
- **Repo:** `git@github.com:Lisbonbgit/Pizzaria.git`
- **Branch de trabalho:** **`migracao-hostinger`** — commit **`ed3bc2c`**
- **`main`** = `6d24e33` — **NÃO tocar** (versão que está no ar no Emergent, na pizzaria).
- **Continuar noutra sessão:** clonar e `git checkout migracao-hostinger`. **Clonar para FORA do OneDrive** (ver §7).

Commits novos na branch:
1. `d732d37` — desemergentização + Docker/Caddy + documentação
2. `ed3bc2c` — correções de segurança da auditoria + build reprodutível

## 3. Decisões de arquitetura (já tomadas pelo dono)
- **Deploy:** Docker Compose num **Hostinger VPS**.
- **Base de dados:** **MongoDB Atlas** (gerido, plano grátis M0) — externo aos containers.
- **Edge:** **Caddy** com **HTTPS automático** (Let's Encrypt).
- **3 containers:** `caddy` (80/443) → `/api/*` para `backend` (FastAPI:8001), tudo o resto para `frontend` (nginx/SPA).
- **Same-origin:** frontend buildado com `REACT_APP_BACKEND_URL=""` → chama `/api` na própria origem → **sem CORS**.

## 4. O que foi feito (mudanças no código)
**Desemergentização:**
- Removido `.emergent/` (e no `.gitignore` porque o OneDrive o restaura).
- URLs fixas do Emergent removidas (`backend_test.py`, `print_agent/print_agent.py`, `print_agent/config.env`).
- `requirements.txt` limpo de ~140 → 16 deps. O Emergent usava **versões fictícias do mirror interno** (`python-multipart==0.0.22`, `pillow==12.1.0` não existem no PyPI → `pip install` falhava). Passei a intervalos com versões reais.

**Ficheiros Docker (novos):** `docker-compose.yml`, `Caddyfile`, `backend/Dockerfile`, `frontend/Dockerfile` (multi-stage), `frontend/nginx.conf`, `.dockerignore` (backend+frontend), `.env.example` (raiz + backend + frontend).

**Melhorias de código:** `@app.on_event`→`lifespan`; endpoint `/api/health`; arranque resiliente a falhas da BD; entrypoint local (`python server.py`); print_agent passa a ler `config.env`; `scripts/backup_mongo.sh` (backup diário com retenção).

**Documentação:** `DEPLOY.md` (guia passo-a-passo Hostinger VPS), `README.md` reescrito, `print_agent/README.md` atualizado.

## 5. Auditoria de segurança (workflow adversarial) — 4 achados corrigidos em `ed3bc2c`
- **[ALTA] `JWT_SECRET` fail-closed** — antes caía num default fixo committado (`pizzaria-secret-key-2024`) só com aviso → qualquer um forjava tokens de admin. Agora **recusa arrancar** se faltar ou for o default.
- **[MÉDIA] `POST /api/seed`** — era **sem autenticação**, devolvia a API key do print-agent na resposta e era auto-chamado pelo menu do cliente. Agora exige admin, não devolve a chave, e removi o auto-seed do `MenuPage.js`.
- **[BAIXA] CORS fail-safe** quando `CORS_ORIGINS` não está definido.
- **[BAIXA] `DEPLOY.md`** — `mongorestore` corrigido (`OLD_DB` + `--drop`).
- Extra: `PRINT_AGENT_API_KEY` do `.env` passou a ser honrada; `yarn.lock` committado + Dockerfile com `--frozen-lockfile` (builds reprodutíveis). *(9 falsos-positivos foram rejeitados na verificação cética.)*

## 6. Validação já feita (empírica)
- Backend importa e serve `/api/health`; `JWT_SECRET` fail-closed testado.
- `requirements.txt` instala com versões reais do PyPI.
- Frontend: `yarn build` → **Compiled successfully**; bundle same-origin, sem URL do Emergent.
- **Veredito: GO — código pronto para deploy.**

## 7. ⚠️ Gotcha ambiental (OneDrive)
O repo local está em `/Users/matheus.moraes/Library/CloudStorage/OneDrive-Pessoal/Claude/Pizzaria`, mas a app principal do OneDrive costuma estar parada → ficheiros ficam **"dataless"** e `rsync`/`tar`/`cat`/`git` dão **timeout** (o object store `.git` também). **Solução:** trabalhar sempre a partir de um **clone fora do OneDrive** (ex.: `~/dev/Pizzaria`). `node` v20 está em `~/.local/node/bin` (fora do PATH), com `yarn`.

## 8. Segredos já gerados (para `backend/.env`)
```
JWT_SECRET=bb346a152e5260b103a25b84d2448bfae13cc35294e66c660dc8504ace6bfdc3
PRINT_AGENT_API_KEY=76153def7b648cfe1369c0ee85533920787253ba17f705db
```

## 9. O que FALTA fazer (no VPS) — seguir o `DEPLOY.md`
1. Criar cluster **MongoDB Atlas** → obter `MONGO_URL`; adicionar o IP do VPS ao Network Access.
2. Apontar **DNS** (registo A) do domínio/subdomínio (ex.: `app.lenhaebrasa.com`) para o IP do VPS.
3. Instalar **Docker** no VPS; `git clone` + `checkout migracao-hostinger`.
4. Preencher `.env` (raiz: `DOMAIN`, `ACME_EMAIL`) e `backend/.env` (Atlas, JWT, hash admin via `python scripts/generate_password_hash.py`, chave Resend).
5. `docker compose up -d --build` → testar `https://.../api/health`.
6. (Opcional) Migrar dados do Emergent com `mongodump`→`mongorestore`.
7. **Print agent:** editar `print_agent/config.env` (`BACKEND_URL` + `API_KEY`) no PC da pizzaria.
8. **Switch final:** só quando o novo estiver validado, mudar o `BACKEND_URL` do print agent e o domínio do QR code. O Emergent fica vivo como rede de segurança até lá.

## 10. Estratégia de segurança do deploy
- **Zero downtime:** montar o novo em paralelo (subdomínio de teste), validar, e só depois "switch" deliberado.
- Push só na branch `migracao-hostinger` → mesmo que o Emergent tenha redeploy automático, só olha para o `main`, por isso a pizzaria nunca foi afetada.

---

### Frase pronta para colar numa nova sessão
> Continuo a migração da Pizzaria "Lenha e Brasa" de Emergent para Hostinger VPS. Todo o trabalho está em `git@github.com:Lisbonbgit/Pizzaria.git`, branch **`migracao-hostinger`** (commit `ed3bc2c`); o `main` é a versão viva no Emergent, não tocar. Stack: FastAPI + React + MongoDB, deploy com Docker Compose + Caddy (HTTPS auto) + MongoDB Atlas, guia completo no `DEPLOY.md` e resumo no `HANDOFF.md`. Código validado e pronto (GO). Clonar para fora do OneDrive (`~/dev`). Falta o deploy no VPS: Atlas → DNS → `.env` → `docker compose up -d --build`.
