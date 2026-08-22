# Ligar produtos ao Vendus — acabar com os artigos-lixo nas faturas

**Data:** 2026-08-22
**Autor:** Matheus (dono) + Claude
**Estado:** aprovado (design), por implementar
**Âmbito:** app da pizzaria Lenha e Brasa (FastAPI `backend/` + React `frontend/`), em produção em `pedido.lenhaebrasa.com`.

## Problema (causa-raiz confirmada)

Cada fatura (FS) emitida no Vendus cria **um artigo novo** no catálogo do Vendus. Ao fim de semanas, o catálogo tem **627 artigos, dos quais 549 são lixo** auto-gerado (duplicados de "5 Queijos (Média)", "Água das Pedras", etc., cada um com uma referência inventada pelo Vendus).

**Porquê:** a linha da fatura é construída por `pos/pricing.py::line_vendus`, que envia cada item **só com `title`** (nome + tamanho), preço e IVA — **nunca a referência/id do artigo**. `create_invoice` (`vendus/client.py:287`) passa os itens tal-e-qual. Sem um identificador de artigo, o Vendus não reconhece o artigo existente e **cria um novo a cada documento**. Confirmado: **0 dos 46 produtos da app** têm `vendus_reference` preenchida. Não é regressão recente — é uma lacuna de origem da integração.

## Estado real (verificado em produção)

- **App (46 produtos):** Pizzas (21, todas com tamanhos Média/Grande), Bebidas (~18, sem tamanho exceto a imperial), Entradas (3), Sobremesas (4). Nenhum ligado ao Vendus.
- **Vendus (627 artigos):** 549 lixo auto-gerado; **78 oficiais** (criados pelo dono), com referência = nome limpo (ex.: "Pizza Calabresa", "Compal de Maracujá", "Água Mineral 50cl"), um artigo por produto **sem tamanho** (o tamanho ia no título da linha e gerava o lixo). Há versões normais e "App" (delivery).

## Decisões (do brainstorming)

- **Ligação: automática por nome, confirmada pelo dono.** O sistema casa cada produto ao artigo oficial por **nome** (normalizado); o **preço** dos dois lados é mostrado como confirmação (não é a chave). O dono confirma/corrige num ecrã antes de valer.
- **Um artigo Vendus por produto** (sem tamanho); o **tamanho e o preço viajam na linha** da fatura. A referência/id identifica o artigo; o Vendus aceita o preço/título do documento.
- **O lixo já criado (549) NÃO se apaga agora** — delicado (podem estar em faturas emitidas; apagar é irreversível). Fica inerte; o objetivo é **parar de criar mais**. Limpeza é tarefa futura à parte.

## Arquitetura da solução

### Passo 0 — Validação (GATE, sem risco fiscal)
Antes de comprometer a implementação, um **spike em modo `tests`** (documento não-fiscal) confirma o comportamento do Vendus:
1. Emitir um documento de teste com um item que traz o **`id`** de um artigo oficial (e o preço/título de um tamanho) → confirmar que o Vendus **reutiliza** esse artigo (não cria um novo) e aceita o preço/título do documento.
2. Se `id` não bastar, testar `reference`.
**Resultado do spike decide a chave** (`id` preferido, por ser único e estável; `reference` como alternativa). Só se avança se um dos dois reutilizar o artigo. Contar artigos antes/depois confirma que não houve criação.

### Passo 1 — Guardar a ligação no produto
- Novo campo no produto: **`vendus_id`** (int, id do artigo oficial no Vendus) — a chave de ligação. Mantém-se `vendus_reference` (já existe) para leitura/backup.
- O casamento e a fatura usam `vendus_id`.

### Passo 2 — Casamento automático + ecrã de confirmação (admin)
- **Backend:** endpoint que (a) puxa os artigos do Vendus, **filtra só os oficiais** (referência que NÃO segue o padrão auto-gerado `…-<6+ dígitos>`), e (b) casa cada produto da app por **nome normalizado** — minúsculas, sem acentos, sem o prefixo "Pizza ", sem tamanho, ignorando "de/da"; **prefere a versão sem "App"**. Devolve, por produto: artigo Vendus sugerido (`id`, nome, preço), o preço da app, e um estado (casado / duvidoso / sem correspondência). Não grava nada — só sugere.
- **Frontend:** ecrã "Ligar ao Vendus" (no admin) que lista produto app → artigo sugerido, com **preços lado a lado**; o dono confirma/corrige (seletor com os 78 oficiais) e grava. Um segundo endpoint grava o `vendus_id` escolhido por produto.
- Produtos **sem correspondência** ficam assinalados; o dono liga a um existente ou cria o artigo no Vendus.

### Passo 3 — A fatura passa a usar a ligação
- `line_vendus` (e a construção da FS no fecho de mesa `close_table` e no balcão `checkout_counter_order`) passa a incluir o **`id`** do artigo Vendus quando o produto está ligado, obtido do produto por `product_id` no momento de faturar (à semelhança de como o `vendus_tax_id` já é resolvido). O título (com tamanho) e o preço continuam na linha.
- Produtos **sem `vendus_id`** continuam como texto livre (comportamento atual) — criariam lixo, por isso a meta é ligar todos; o ecrã do Passo 2 mostra quantos faltam.
- Verificação em **modo `tests`**: emitir uma FS de teste com produtos ligados e confirmar, contando os artigos do Vendus antes/depois, que **não é criado nenhum artigo novo**.

## Fora de âmbito

- Apagar o lixo já existente (549 artigos) — tarefa futura, provavelmente pelo painel/suporte do Vendus.
- Criar automaticamente artigos no Vendus para produtos sem correspondência (o dono cria/liga manualmente).
- Sincronizar preços/IVA app↔Vendus (a fatura continua a mandar o preço/IVA da app na linha).

## Riscos

- **O Vendus reutilizar por `id`/`reference`** — mitigado pelo GATE (Passo 0) antes de qualquer implementação de faturação.
- **Casamento por nome errar** — mitigado pela confirmação humana no ecrã (o preço lado a lado ajuda a detetar enganos).
- **Fiscal:** toda a validação corre em modo `tests`; só se liga em produção depois de confirmado que não cria lixo. A emissão da FS (idempotência, uma-só-FS, totais) não muda — só se acrescenta o identificador do artigo à linha.

## Faseamento

1. **Spike** (Passo 0) — GATE.
2. **Casamento + ecrã + gravar ligação** (Passos 1-2).
3. **Fatura usa a ligação** (Passo 3) + verificação em modo tests.
4. **Ligar em produção** (o dono confirma o mapeamento; verificar 1ª FS real que não cria artigo).
