# Rodízio (all-you-can-eat) — Design

Data: 2026-07-22
Sistema: Pizzaria "Lenha e Brasa" (FastAPI + React + Mongo), pedidos por QR na mesa.

## Objetivo

Em certos dias, a pizzaria oferece **rodízio** (pizzas à vontade) cobrado **por
pessoa**. O cliente, ao abrir o menu, escolhe entre **à la carte** (preços
normais) ou **rodízio**. Há **dois níveis**: Simples e Completo. Quem escolhe
rodízio pode pedir pizzas (médias) sem custo adicional; só se paga o valor por
pessoa (+ extras não incluídos + eventual taxa de desperdício).

## Requisitos (decididos no brainstorming)

- **Mesa inteira em rodízio**: se a mesa escolhe rodízio, todas as pessoas entram
  (não há misto rodízio/à la carte na mesma mesa).
- **Escalões de criança** (editáveis): até **5** anos grátis; até **12** meia;
  acima, inteiro.
- **Dois níveis:**
  - **Simples**: pizzas médias + bebidas incluídas (limonadas, frutos vermelhos,
    hortelã).
  - **Completo**: entradas + pizzas médias + bebidas incluídas + sobremesas.
- **Pizzas do rodízio são sempre médias**, a €0.
- **Cliente escolhe, staff confirma**: o cliente escolhe o nível e indica quantos
  são; no fecho o staff confirma/afina a contagem antes de faturar.
- **Menu normal com incluídos a €0**: no rodízio o cliente vê o menu completo; os
  itens incluídos aparecem como "Incluído" (€0); os não incluídos mantêm o preço
  e somam à conta.
- **Taxa de desperdício**: aviso ao cliente ("sobras podem ter taxa de 5 €/box") +
  o staff pode cobrar 5 € por box no fecho.
- **Disponibilidade por dias**: o rodízio fica ativo automaticamente nos dias
  marcados nas Definições; fora deles, é só o menu normal.
- **Faturação**: Fatura Simplificada (FS) no Vendus, IVA 13% (INT) no rodízio.

## Abordagem: rodízio integrado no menu (Opção A, aprovada)

O rodízio é um **modo da sessão da mesa**, não um produto. A configuração vive nas
Definições; o menu do cliente adapta-se ao modo; o fecho calcula o valor por
pessoa. Alternativas rejeitadas: rodízio-como-produto (não faz incluídos a €0 nem
escalões) e só-no-fecho (o cliente não vê o modo rodízio no menu).

## Modelo de dados

### Configuração do rodízio — `db.settings` chave `"rodizio"`
```json
{
  "enabled": true,
  "days": [0, 2, 3],
  "child_free_max_age": 5,
  "child_half_max_age": 12,
  "tax_id": "INT",
  "waste_fee": 5.00,
  "waste_fee_tax_id": "INT",
  "tiers": {
    "simples":  { "name": "Rodízio Simples",  "price": 18.90 },
    "completo": { "name": "Rodízio Completo", "price": 22.90 }
  }
}
```
`disponivel_hoje = enabled and (hoje in days)` (fuso Europe/Lisbon, 0=Seg..6=Dom).

### Produto — novo campo `rodizio_incluido`
Valores: `"nao"` | `"ambos"` | `"completo"`.
- `nao`: só à la carte (ex.: Coca-Cola, pizza grande).
- `ambos`: incluído no Simples e no Completo (pizzas médias, bebidas incluídas).
- `completo`: incluído só no Completo (entradas, sobremesas).

Defaults ao gravar/migrar (para não configurar um a um), com override manual:
Pizzas → `ambos`; Entradas/Sobremesas → `completo`; resto → `nao`. Depois o admin
marca as **3 bebidas incluídas** como `ambos`.

Regra de inclusão de um item no modo M (`simples`/`completo`):
- M=`simples`: incluído se `rodizio_incluido == "ambos"`.
- M=`completo`: incluído se `rodizio_incluido in ("ambos", "completo")`.

### Sessão da mesa — `db.table_sessions` novos campos
```json
{ "rodizio": "none|simples|completo",
  "rodizio_people": { "adults": 3, "children": 1 } }
```
`rodizio_people` é o que o cliente declarou; a divisão final grátis/meia é feita
pelo staff no fecho.

### Itens de pedido no rodízio
Ao pedir um item **incluído** em modo rodízio, o item é criado com
`unit_price = 0`, `total_price = 0` e `rodizio_included = true`; pizzas forçadas à
variação **média** — identificada pelo nome da variação que contém "méd"
(case-insensitive); se não existir, usa a variação mais barata. Itens **não
incluídos** mantêm o preço normal. Assim a conta
da mesa (soma dos `total_price`) já reflete só os extras pagos; o valor do rodízio
por pessoa é somado no fecho.

## Parte 1 — Configuração (admin)

**Definições → secção "Rodízio":** ativar (on/off), dias (chips Seg–Dom), os dois
níveis (nome + preço/adulto), regras de criança (idade grátis / idade meia), taxa
de desperdício (€/box) e IVA. Endpoints: `GET/PUT /api/settings/rodizio` (admin) e
`GET /api/settings/rodizio/public` (cliente: dias, níveis, preços, regras,
aviso).

**Editor de produto:** campo "Incluído no rodízio" (Não / Simples e Completo / Só
Completo) em `ProductCreate/Update/Response`. Migração única para pôr os defaults
por categoria nos produtos atuais. As categorias antigas "All You Can Eat
(18,90/22,90)" são removidas/reaproveitadas.

## Parte 2 — Menu do cliente

Num dia com rodízio, após ler o QR a mesa vê um **ecrã de escolha**: À la carte /
Rodízio Simples (preço) / Rodízio Completo (preço), com o aviso do desperdício.
- **À la carte** → menu normal de hoje.
- **Rodízio** → indica **adultos** e **crianças** (2 campos, com aviso dos
  escalões); mostra estimativa; grava na sessão (`POST /tables/{n}/open` estendido
  ou novo `POST /tables/{n}/rodizio`).

Menu em **modo rodízio**: faixa no topo (nível + "pizzas médias e bebidas
incluídas" + aviso de desperdício); itens incluídos a **"Incluído" €0** (a verde),
pizzas só média; não incluídos com preço. Pedir itens incluídos → vão à cozinha a
€0; extras pagos somam. O modo fica na sessão — quem ler o mesmo QR a seguir entra
já em rodízio (a mesa é uma só). `productsAPI.list` público passa a incluir
`rodizio_incluido`; `get_table_session` devolve o modo.

## Parte 3 — Fecho e faturação

No popup POS, mesa em rodízio → painel esquerdo mostra:
- **Contagem confirmada pelo staff** (pré-preenchida com o que o cliente
  declarou): Adultos [−N+], Crianças 6–12 meia [−N+], Crianças ≤5 grátis [−N+].
- **Valor do rodízio** = adultos×preço + crianças_meia×(preço/2) + 0.
- **Extras à la carte**: itens não incluídos (com preço) somam automaticamente;
  os incluídos aparecem como "Incluído €0".
- **Taxa de desperdício**: campo "[n] boxes × 5 €".
- Total = rodízio + extras + taxa. Pagamento, troco, **Emitir Documento**.

**close_table** passa a aceitar (quando a sessão é rodízio): `rodizio_tier`,
`adults`, `children_half`, `children_free`, `waste_boxes`. Constrói as linhas
Vendus (FS, IVA INT):
- `{tier.name} (adulto)` × adults @ tier.price
- `{tier.name} (criança)` × children_half @ tier.price/2
- cada extra pago (dos itens da conta com preço > 0)
- `Taxa desperdício` × waste_boxes @ waste_fee (IVA `waste_fee_tax_id`)

Marca todos os itens da mesa como pagos e fecha a sessão (reaproveita a mecânica
atual). As pizzas €0 **não** vão à fatura (estão cobertas pelo rodízio) mas
imprimem na **cozinha** normalmente.

**Dividir/Separar:** o "Dividir por N" (partes iguais do total) continua a
funcionar no rodízio. O "Separar por itens" fica para as contas à la carte (no
rodízio o valor é por pessoa).

## Fora de âmbito / decisões

- Sem misto rodízio/à la carte na mesma mesa (decidido).
- O cliente declara adultos+crianças; o split grátis/meia é do staff no fecho.
- Validação server-side dos preços €0 dos incluídos fica para endurecimento
  posterior (fase 2); na fase 1 o frontend aplica as regras e o staff confirma.
- IVA da taxa de desperdício: configurável (`waste_fee_tax_id`), default INT.

## Faseamento sugerido

1. Config (Definições + campo no produto + público) e migração de defaults.
2. Menu do cliente (ecrã de escolha, contagem, modo rodízio com incluídos a €0).
3. Fecho/faturação (contagem do staff, extras, taxa, linhas Vendus).
