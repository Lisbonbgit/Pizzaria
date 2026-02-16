# Sistema de Pedidos - Pizzaria

## Problema Original
Sistema web de pedidos para pizzaria com QR Code por mesa, impressão automática na cozinha via impressora térmica ESC/POS, e painel administrativo completo.

## Arquitectura
- **Frontend**: React 19 + TailwindCSS + Shadcn/UI
- **Backend**: FastAPI + Motor (async MongoDB)
- **Base de Dados**: MongoDB

## O Que Foi Implementado

### Cliente (Mobile-First)
- Menu com categorias (Pizzas, Bebidas, Entradas, Sobremesas)
- Produtos com foto, descrição, variações (tamanhos) e extras
- Carrinho com quantidades e observações
- Identificação automática da mesa via QR Code (?mesa=X)
- Confirmação de pedido com impressão automática

### Admin
- Login JWT (email/senha)
- Dashboard com estatísticas do dia
- Gestão de pedidos (estados, reimprimir, marcar pago)
- Gestão de menu (CRUD categorias e produtos)
- Gestão de mesas com geração de QR Codes
- Configuração de impressora térmica (IP, porta, largura, cópias)

### Impressão ESC/POS
- Conexão TCP direta para impressora na rede
- Fila de trabalhos com retry automático
- Formatação para 58mm/80mm
- Teste de impressão

## Credenciais
- Email: admin@pizzaria.pt
- Senha: admin123

## Próximos Passos (P1)
- Notificações em tempo real (WebSocket)
- Histórico de pedidos por cliente
- Relatórios de vendas
