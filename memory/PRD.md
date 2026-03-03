# Sistema de Pedidos - Pizzaria

## Problema Original
Sistema web de pedidos para pizzaria com QR Code por mesa, impressão automática na cozinha via impressora térmica ESC/POS, e painel administrativo completo.

## Arquitectura
- **Frontend**: React 19 + TailwindCSS + Shadcn/UI
- **Backend**: FastAPI + Motor (async MongoDB)
- **Base de Dados**: MongoDB
- **Email**: Resend (para relatórios diários)
- **Scheduler**: APScheduler (agendamento automático)

## O Que Foi Implementado

### Cliente (Mobile-First)
- Menu com categorias (Pizzas, Bebidas, Entradas, Sobremesas)
- Produtos com foto, descrição, variações (tamanhos) e extras
- Carrinho com quantidades e observações
- Identificação automática da mesa via QR Code (?mesa=X)
- Confirmação de pedido com impressão automática

### Admin
- Login JWT (email/senha via variáveis de ambiente)
- Dashboard com estatísticas do dia
- Gestão de pedidos (estados, reimprimir, marcar pago)
- Gestão de menu (CRUD categorias e produtos)
- Gestão de mesas com geração de QR Codes
- Configuração de impressora térmica (IP, porta, largura, cópias)
- Multi-impressora com formatos distintos (cozinha/caixa)

### Impressão ESC/POS
- Print Agent local para comunicação com impressoras
- Suporte a múltiplas impressoras simultâneas
- Formatos diferentes para cozinha e caixa
- Fila de trabalhos com retry automático
- Formatação para 58mm/80mm

### Relatórios Diários por Email (NOVO - Dezembro 2025)
- Envio automático às 23:59 (Europe/Lisbon)
- Resumo diário com: total de pedidos, receita bruta, ticket médio
- Lista detalhada de pedidos (número, mesa, valor, hora, estado pagamento)
- Endpoint manual para teste: `/api/admin/test-daily-report`
- Scheduler configurável (ativar/desativar via API)
- Histórico de envios em `/api/admin/report-logs`

## Credenciais
- Email: admin@pizzaria.pt
- Senha: admin123

## Configuração Necessária (.env)
```
RESEND_API_KEY=re_xxxxxxx      # Obter em https://resend.com
REPORT_EMAIL=geral@lenhaebrasa.com
```

## Endpoints de Relatórios
- `POST /api/admin/test-daily-report` - Teste manual de envio
- `GET /api/admin/report-config` - Ver configuração atual
- `POST /api/admin/scheduler/enable` - Ativar scheduler
- `POST /api/admin/scheduler/disable` - Desativar scheduler
- `GET /api/admin/scheduler/status` - Estado do scheduler
- `GET /api/admin/report-logs` - Histórico de envios

## Próximos Passos (P1)
- Interface no admin para configurar REPORT_EMAIL e horário
- Notificações em tempo real (WebSocket)
- Histórico de pedidos por cliente

## Próximos Passos (P2)
- Relatórios semanais/mensais
- Exportação de dados (CSV/PDF)
