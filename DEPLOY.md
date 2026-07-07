# Deploy no Hostinger VPS (Docker Compose + MongoDB Atlas)

Guia completo para tirar o sistema do Emergent e colocá-lo num **Hostinger VPS**.

Resumo: a aplicação corre em 3 containers (Caddy, frontend, backend) e a base de
dados fica no **MongoDB Atlas** (gerido, plano grátis). O **Caddy** trata do HTTPS
automaticamente (Let's Encrypt).

---

## 0. Pré-requisitos

- [ ] **Hostinger VPS** com Ubuntu 22.04+ e acesso SSH (root ou sudo).
- [ ] Um **domínio** (ou subdomínio), ex.: `app.lenhaebrasa.com`.
- [ ] Conta **MongoDB Atlas** — https://www.mongodb.com/atlas (plano M0 grátis).
- [ ] Conta **Resend** — https://resend.com (para o email do relatório diário).

---

## 1. MongoDB Atlas

1. Crie um cluster gratuito (M0).
2. **Database Access** → criar utilizador (ex.: `pizzaria`) com password forte.
3. **Network Access** → adicionar o **IP do VPS** (ou `0.0.0.0/0` para testar; restrinja depois).
4. **Connect → Drivers** → copiar a connection string, do tipo:
   ```
   mongodb+srv://pizzaria:PASSWORD@cluster0.xxxxx.mongodb.net/?retryWrites=true&w=majority
   ```
   Guarde-a — vai para `MONGO_URL` no `backend/.env`.

---

## 2. DNS do domínio

No painel onde gere o domínio, crie um registo **A**:

| Tipo | Nome | Valor |
|------|------|-------|
| A | `app` (ou `@`) | `IP_DO_SEU_VPS` |

Aguarde a propagação (alguns minutos). Confirme: `ping app.lenhaebrasa.com` deve dar o IP do VPS.
**Importante:** o Caddy só consegue emitir o certificado HTTPS depois do DNS apontar para o VPS.

---

## 3. Preparar o VPS (instalar Docker)

Por SSH no VPS:

```bash
# Docker + Docker Compose plugin (script oficial)
curl -fsSL https://get.docker.com | sh
sudo usermod -aG docker $USER     # opcional: usar docker sem sudo (re-login depois)

# Confirmar
docker --version
docker compose version
```

> A Hostinger tem um *template* de VPS "Ubuntu com Docker" que já traz isto instalado.

---

## 4. Clonar o projeto e configurar

```bash
git clone git@github.com:Lisbonbgit/Pizzaria.git
cd Pizzaria

cp .env.example .env
cp backend/.env.example backend/.env
```

### 4.1 `.env` (raiz — usado pelo Caddy)

```ini
DOMAIN=app.lenhaebrasa.com
ACME_EMAIL=seu-email@exemplo.com
```

### 4.2 `backend/.env`

```ini
MONGO_URL="mongodb+srv://pizzaria:PASSWORD@cluster0.xxxxx.mongodb.net/?retryWrites=true&w=majority"
DB_NAME="pizzaria"

JWT_SECRET="<gerar — ver passo 4.3>"
CORS_ORIGINS="https://app.lenhaebrasa.com"

ADMIN_EMAIL="admin@lenhaebrasa.com"
ADMIN_PASSWORD_HASH="<gerar — ver passo 4.3>"

PRINT_AGENT_API_KEY="<gerar — ver passo 4.3>"

RESEND_API_KEY="re_xxx"                 # de https://resend.com
REPORT_EMAIL="dono@lenhaebrasa.com"
REPORT_SENDER_EMAIL="onboarding@resend.dev"
```

### 4.3 Gerar segredos

```bash
# JWT_SECRET e PRINT_AGENT_API_KEY
openssl rand -hex 32      # → JWT_SECRET
openssl rand -hex 24      # → PRINT_AGENT_API_KEY

# Hash da password do admin (precisa de python + bcrypt; ou faça depois dentro do container)
python3 scripts/generate_password_hash.py
```

Cole os valores no `backend/.env`.

---

## 5. Arrancar

```bash
docker compose up -d --build
```

- O build do frontend (React) demora 1–3 min na primeira vez.
- O Caddy obtém o certificado HTTPS automaticamente.

Verificar:

```bash
docker compose ps          # 3 serviços "running"
docker compose logs -f     # acompanhar o arranque (Ctrl+C para sair)

curl -k https://app.lenhaebrasa.com/api/health   # → {"status":"ok"}
```

Abra `https://app.lenhaebrasa.com` (cliente) e `https://app.lenhaebrasa.com/admin/login` (admin).

---

## 6. (Opcional) Migrar os dados do Emergent

Se quiser trazer o menu/pedidos existentes do Emergent (em vez de começar do zero):

```bash
# 1. No ambiente antigo, obtenha a MONGO_URL do Emergent (backend/.env de lá).
# 2. Defina UMA vez o nome da base antiga (evita divergência entre dump e restore):
OLD_DB=NOME_ANTIGO

# 3. Exportar a base antiga:
mongodump --uri="MONGO_URL_ANTIGA" --db="$OLD_DB" --archive=pizzaria.archive.gz --gzip

# 4. Importar para o Atlas (--drop garante import limpo e idempotente):
mongorestore --uri="MONGO_URL_ATLAS" --drop \
  --nsFrom="$OLD_DB.*" --nsTo="pizzaria.*" \
  --archive=pizzaria.archive.gz --gzip
```

> **Confirme o resultado:** o `mongorestore` deve terminar com `X document(s) restored`
> (X > 0). Se aparecer `0 document(s) restored`, o `OLD_DB` não corresponde ao nome
> real da base antiga — descubra-o com
> `mongosh "MONGO_URL_ANTIGA" --eval "db.adminCommand('listDatabases')"` e repita.
> O `--drop` limpa as coleções de destino antes de importar, para poder correr o
> comando mais que uma vez sem duplicar dados.

> Não tem acesso à base antiga? Sem problema: um deploy novo começa com a base vazia —
> faça login no Admin e crie o menu/mesas (o menu real da pizzaria). As imagens são
> guardadas na própria base de dados (coleção `images`), por isso um dump normal inclui-as.

---

## 7. Print Agent (PC local na pizzaria)

O agente corre no computador Windows ligado às impressoras (não no VPS).

1. Copie a pasta [`print_agent/`](print_agent/) para o PC.
2. Edite [`print_agent/config.env`](print_agent/config.env):
   ```ini
   BACKEND_URL=https://app.lenhaebrasa.com
   API_KEY=<o mesmo PRINT_AGENT_API_KEY do backend/.env, ou o gerado no Admin>
   ```
3. Instale Python 3.8+ e a dependência:
   ```bash
   pip install requests
   ```
4. Arranque com duplo-clique em `iniciar_agent.bat` (ou `python print_agent.py`).

Detalhes e configuração das impressoras: [`print_agent/README.md`](print_agent/README.md).

---

## 8. Backups automáticos

```bash
# Instalar mongodump (uma vez)
sudo apt-get update && sudo apt-get install -y mongodb-database-tools

# Testar
./scripts/backup_mongo.sh        # cria backups/ com o dump comprimido

# Agendar diariamente às 03:00 (crontab -e)
0 3 * * * /caminho/Pizzaria/scripts/backup_mongo.sh >> /var/log/pizzaria-backup.log 2>&1
```

Mantém os últimos 14 dias (configurável via `RETENTION_DAYS`).
O Atlas também tem snapshots automáticos próprios.

---

## 9. Atualizar a aplicação

```bash
cd Pizzaria
git pull
docker compose up -d --build
```

Comandos úteis:

```bash
docker compose restart backend     # reiniciar só o backend (ex.: após mudar .env)
docker compose logs -f backend     # ver logs do backend
docker compose down                # parar tudo
```

---

## 10. Resolução de problemas

| Sintoma | Causa provável | Solução |
|---------|----------------|---------|
| HTTPS não emite / erro de certificado | DNS ainda não aponta para o VPS, ou portas 80/443 fechadas | Confirme o registo A e a firewall (`ufw allow 80,443/tcp`) |
| `/api/health` não responde | Backend não arrancou | `docker compose logs backend` |
| Login admin falha | `ADMIN_PASSWORD_HASH` vazio/errado | Regenerar com o script e `docker compose restart backend` |
| Backend não liga ao Atlas | IP do VPS não está no Network Access do Atlas | Adicionar o IP no Atlas |
| Email do relatório não envia | `RESEND_API_KEY`/`REPORT_EMAIL` em falta | Preencher no `backend/.env` |
| Impressora não imprime | `config.env` do agente errado ou impressora offline | Verificar `BACKEND_URL`/`API_KEY` e IP da impressora |

### Firewall (se usar UFW)

```bash
sudo ufw allow OpenSSH
sudo ufw allow 80/tcp
sudo ufw allow 443/tcp
sudo ufw enable
```
