// Pizza meia-meia — regras do lado do ecrã (o servidor confere tudo outra vez:
// backend/pos/meia_meia.py). Usado pelo menu do cliente e pelo catálogo do POS.

const semAcentos = (s) => String(s || '').normalize('NFD').replace(/[\u0300-\u036f]/g, '');

// Só categorias de pizza (nome com "pizza"), ativas e não pos_only.
export const categoriaElegivel = (cat) => !!cat && cat.active !== false && !cat.pos_only
  && semAcentos(cat.name).toLowerCase().includes('pizza');

// Preço no tamanho, ou null se não existir. Sem variações, só "sem tamanho".
export const precoNoTamanho = (p, nomeTamanho) => {
  const vs = p?.variations || [];
  if (!vs.length) return nomeTamanho ? null : Number(p?.base_price) || 0;
  const v = vs.find((x) => x.name === nomeTamanho);
  return v ? Number(v.price) || 0 : null;
};

// Pizza com tamanhos ainda sem tamanho (ou num que não tem) → nenhum candidato,
// como o servidor ("Escolhe o tamanho"); senão as pizzas sem tamanho apareciam.
export const candidatosMeia = (produto, nomeTamanho, produtos) => (
  precoNoTamanho(produto, nomeTamanho) == null ? [] : produtos.filter((p) => (
    p.id !== produto.id && p.category_id === produto.category_id
    && p.available !== false && precoNoTamanho(p, nomeTamanho) != null)));

export const nomeMeiaMeia = (a, b) => `1/2 ${a} + 1/2 ${b}`;

export const precoBaseMeia = (a, b, nomeTamanho) => Math.max(
  precoNoTamanho(a, nomeTamanho) || 0, precoNoTamanho(b, nomeTamanho) || 0);
