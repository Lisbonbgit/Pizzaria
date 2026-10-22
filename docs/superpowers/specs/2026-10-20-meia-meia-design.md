# Pizza meia-meia — desenho

**Data:** 2026-10-20 · **Pedido do dono:** os clientes poderem pedir pizza meia-meia
(metade de um sabor, metade de outro).

## Decisões do dono

| Tema | Decisão |
|---|---|
| Preço | O da **metade mais cara**, no tamanho escolhido |
| Tamanhos | **Todos** (Média e Grande); as duas metades sempre no **mesmo** tamanho |
| Sabores | Só **dentro da mesma categoria** |
| Quem | **Clientes (QR)** e **staff no POS** (Balcão e "Adicionar produtos" da mesa) |
| Rodízio | Sim, **só entre sabores incluídos** no nível da mesa, a 0 € |
| Abordagem | "Fazer meia-meia" **dentro de cada pizza** (não um produto à parte) |

## Que produtos podem ser meia-meia

Só produtos de categorias **cujo nome contém "pizza"** (sem maiúsculas/acentos),
**ativas e não `pos_only`** — a mesma heurística que o botão de inclusões do rodízio já
usa (`server.py`, ~1059). Em produção (20/10) isto é só a categoria **"Pizzas"**: 19
sabores, todos com os tamanhos "Média (6 Fatias)" e "Grande (8 Fatias)". Bebidas,
Entradas, Massas, Sobremesas e "Venda Aplicações" (pos_only) ficam de fora.

O 2.º sabor tem de ser: da **mesma categoria** que o 1.º, **diferente** dele,
**disponível** (`available !== false`) e ter uma variação com **o mesmo nome** do
tamanho escolhido (ou, se o 1.º não tiver variações, também não ter).

## 1. O que se vê

**Cliente (QR, `MenuPage.js`).** No diálogo de uma pizza elegível, por baixo do tamanho,
um botão **"Fazer meia-meia"** abre a lista dos 2.ºs sabores possíveis (regra acima) com
o preço de cada um nesse tamanho. Escolhido o 2.º sabor, o título passa a
"1/2 A + 1/2 B" e o preço do botão é o da mais cara (+ extras). Mudar de tamanho mantém
o 2.º sabor se ele existir nesse tamanho; senão retira-o com um aviso. Extras (ex.:
Borda) são da pizza inteira e cobram-se uma vez. Observações iguais a hoje.

**Rodízio.** O botão só aparece se a pizza estiver incluída no nível da mesa; a lista
só mostra sabores incluídos nesse mesmo nível. A linha sai a 0 € como hoje. No POS, como
hoje, os produtos entram sempre ao preço (o POS não põe incluídos a 0 €).

**POS (`CatalogoProdutos.js`, usado pelo Balcão e pela mesa).** A janela de tamanho e
extras ganha o mesmo "Fazer meia-meia" com a mesma lista (candidatos = itens do mesmo
grupo/categoria que cumprem a regra). `onAdd(produto, variação, extras, segundaMetade)`.
O carrinho do balcão e a lista "A adicionar à mesa" mostram "1/2 A + 1/2 B (Tamanho)".
Uma pizza de categoria elegível abre sempre a janela (mesmo sem tamanhos/extras), para o
botão estar disponível.

## 2. Como fica guardado e o que o servidor confere

**Uma linha por pizza.** O item é o do **1.º sabor** (`product_id` = A, o seu IVA e o seu
`vendus_id`), com o tamanho e os extras, mais:

- no **pedido** (entrada): `half_product_id: Optional[str]` em `OrderItemCreate` e
  `CounterOrderItem` (sem isto o pydantic descarta o campo em silêncio);
- no **item gravado**: `halves: [{product_id, product_name}, {product_id, product_name}]`
  (A e B, com os nomes do **catálogo**) e `product_name = "1/2 A + 1/2 B"`, montado
  **pelo servidor**.

Como o `product_name` composto flui sozinho para a conta (`_open_bill_lines`), a
consulta, a cópia da caixa e o título da FS (`line_vendus`), estes sítios não precisam
de lógica nova. Dividir a conta, "Separar Conta" e editar a linha funcionam como hoje
(é uma linha, quantidade inteira).

**Regra num módulo puro novo, `backend/pos/meia_meia.py`** (sem I/O, testável):

- `elegivel(categoria) -> bool` — nome com "pizza", ativa, não pos_only;
- `preco_no_tamanho(produto, nome_tamanho) -> float | None`;
- `montar_meia_meia(prod_a, prod_b, nome_tamanho, extras_escolhidos) -> {unit_price,
  product_name, halves}` ou erro legível (categoria diferente, mesmo sabor, indisponível,
  tamanho inexistente);
- `incluida_no_rodizio(produto, nivel) -> bool` (mesma regra do menu: `ambos` ou o nível).

**Onde é chamada:** `POST /orders` (cliente QR e "Adicionar produtos" da mesa — rota
pública) e `POST /pos/counter/order` + `/update` (balcão, via
`pos/counter.build_counter_items`, que hoje impõe o nome do catálogo). **No balcão** (POS
autenticado) o servidor valida os sabores e monta nome e metades, mas **mantém o preço
que o POS manda**, como já faz hoje com tamanhos, extras e alterações do staff no
diálogo da linha. **Na rota pública**, para cada item com `half_product_id`, o servidor:

1. carrega A e B do catálogo e valida (erros → **400** com mensagem em português);
2. **calcula o preço**: `max(preço A, preço B no tamanho) + extras e complementos de A
   (preços do catálogo; um extra/complemento que A não tenha → 400)`; grava `unit_price`, `total_price = unit_price × qty`, `product_name` e
   `halves`. Quando o pedido tem meia-meias, o `total` do pedido passa a ser a soma dos
   `total_price` (hoje o servidor aceita o total do browser);
3. **rodízio**: uma meia-meia que chegue a **0 €** só é aceite se a mesa tiver sessão de
   rodízio aberta e A e B estiverem incluídos nesse nível; senão **400**.

## 3. O que sai depois do pedido

- **Talão da cozinha** (`format_kitchen`): com `halves`, em vez do nome composto imprime
  `1x MEIA-MEIA` (2×2) e por baixo `1/2 MARGHERITA` / `1/2 FRANGO COM CATUPIRY` (2×2,
  uma por linha), depois tamanho, extras e OBS como hoje. Sempre "1/2" em ASCII (a página
  de código da impressora não está fixada; "½" pode sair lixo).
- **Cópia da caixa, consulta, conta no ecrã:** nome composto "1/2 A + 1/2 B (Tamanho)".
- **FS (Vendus):** ligada ao artigo de A (`vendus_id`), título "1/2 A + 1/2 B (Tamanho)";
  o Vendus imprime o nome do artigo e o título por baixo. IVA de A (= de B, mesma
  categoria). Notas de crédito continuam a funcionar (todas as linhas com `id`).
  **Limite de caracteres do título:** confirmar com uma fatura em modo de **testes** do
  Vendus; se for curto, abreviar de forma legível.
- **Relatório de produtos** (`pos/report.summarize_products`, agrupado por nome): um item
  com `halves` soma **0,5** da quantidade e **metade** do valor a cada sabor (pelo nome do
  catálogo em `halves`). O total faturado não muda (vem do Vendus).

## 4. Construção, testes e publicação

**Fases** (cada uma completa antes da seguinte):
1. **Servidor:** `pos/meia_meia.py` + ligação a `POST /orders`, balcão, talão da
   cozinha, relatório; confirmar o limite do título no Vendus (modo de testes).
2. **Menu do cliente (QR):** "Fazer meia-meia" no `MenuPage.js` + chave/nome/preço no
   `CartContext.js` (a chave do item inclui o id do 2.º sabor; envio de `half_product_id`).
3. **POS:** `CatalogoProdutos.js` (botão + lista), `PosBalcao.js` (chave, envio,
   `itemToCartLine` a partir de `halves`), `TableCheckout.js` (`addPend`/`confirmAdd`).

**Testes:** unitários da regra (preço da mais cara, mesmo sabor recusado, categoria
diferente recusada, tamanho inexistente recusado, indisponível recusado, rodízio só com
incluídos), de **ligação** em cada rota (o campo não pode ser descartado; o preço do
browser é ignorado), do talão e do relatório (0,5). Cada um validado por **mutação**.
Ensaio no browser com o banco de ensaio (`~/dev/pizzaria-ensaio`): QR, balcão, mesa,
rodízio; e o desenho do talão (`talao_preview.py`) antes de publicar.

**Publicação:** tudo junto no fim, com o ok do dono; depois, uma meia-meia real numa
mesa para ver talão e FS no papel.

**Fora desta versão:** três sabores; sabores de categorias diferentes; trocar um sabor
depois de enviado (anula-se a linha e lança-se de novo); estatística por sabor dentro do
próprio Vendus (lá conta como o 1.º sabor).
