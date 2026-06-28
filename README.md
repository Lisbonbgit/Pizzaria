# Pizzaria — Sistema de Pedidos (Lenha e Brasa)

Sistema full-stack de pedidos por **QR code na mesa**, com painel de administração
completo, impressão em impressoras térmicas locais (ESC/POS) e relatório diário
automático por email.

> Migrado da plataforma Emergent para um **Hostinger VPS** com **Docker Compose**
> e **MongoDB Atlas**. Guia completo de instalação em **[DEPLOY.md](DEPLOY.md)**.

## Arquitetura

```
  Cliente (telemóvel)                    Admin
        │ QR code                          │
        ▼                                  ▼
  ┌─────────────────────────────────────────────┐
  │  Caddy (HTTPS automático, portas 80/443)     │
  │   /api/*  ──────────►  Backend (FastAPI)     │
  │   /*      ──────────►  Frontend (React/nginx)│
  └─────────────────────────────────────────────┘
                              │
                              ▼
                      MongoDB Atlas
                              ▲
                              │ polling /api/print-jobs
                   Print Agent (PC local na pizzaria)
                              │
                              ▼
                  Impressoras térmicas (cozinha / caixa)
```

| Componente | Tecnologia | Pasta |
|------------|------------|-------|
| Backend    | FastAPI + Motor (MongoDB) | [`backend/`](backend/) |
| Frontend   | React (CRA/craco) + Tailwind + shadcn/ui | [`frontend/`](frontend/) |
| Print Agent| Python (só `requests`) | [`print_agent/`](print_agent/) |
| Email      | Resend (relatório diário 23:59 Europe/Lisbon) | [`backend/scheduler.py`](backend/scheduler.py) |

## Funcionalidades

- **Cliente:** menu dinâmico por categorias, variações/extras/complementos, carrinho e pedido por mesa.
- **Admin:** dashboard, gestão de menu, mesas (com QR code), pedidos em tempo real, impressoras e relatórios.
- **Autenticação:** JWT; credenciais de admin em variáveis de ambiente.
- **Impressão:** múltiplas impressoras com formatos distintos (cozinha / caixa) via agente local.
- **Relatório diário:** resumo de vendas enviado por email automaticamente.

## Arrancar (produção, Hostinger VPS)

```bash
git clone git@github.com:Lisbonbgit/Pizzaria.git
cd Pizzaria
cp .env.example .env                 # domínio + email (Caddy)
cp backend/.env.example backend/.env # Atlas, JWT, admin, Resend...
# preencher os .env (ver DEPLOY.md)
docker compose up -d --build
```

Passo-a-passo detalhado (Atlas, DNS, HTTPS, migração de dados, backups): **[DEPLOY.md](DEPLOY.md)**.

## Desenvolvimento local

```bash
# Backend
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env        # usar MONGO_URL local ou Atlas
python server.py            # http://localhost:8001  (docs em /docs)

# Frontend (noutro terminal)
cd frontend
yarn install
cp .env.example .env        # REACT_APP_BACKEND_URL=http://localhost:8001
yarn start                  # http://localhost:3000
```

## Variáveis de ambiente

- **Backend** → [`backend/.env.example`](backend/.env.example)
- **Frontend** → [`frontend/.env.example`](frontend/.env.example)
- **Compose (raiz)** → [`.env.example`](.env.example)
