import { categoriaElegivel, precoNoTamanho, candidatosMeia, nomeMeiaMeia, precoBaseMeia } from './meiaMeia';

const M = 'Média (6 Fatias)'; const G = 'Grande (8 Fatias)';
const pz = (id, name, m, g, extra = {}) => ({ id, name, category_id: 'c-piz', base_price: m, available: true,
  variations: [{ name: M, price: m }, { name: G, price: g }], ...extra });
const marg = pz('a', 'Margherita', 12.9, 16.9);
const frango = pz('b', 'Frango', 14.9, 18.9);
const esgotada = pz('c', 'Calabresa', 13.9, 17.9, { available: false });
const soMedia = pz('d', 'Atum', 12, 0, { variations: [{ name: M, price: 12 }] });
const coca = { id: 'e', name: 'Coca', category_id: 'c-beb', base_price: 3, variations: [] };

test('categorias de pizza, ativas, não pos_only', () => {
  expect(categoriaElegivel({ name: 'Pizzas' })).toBe(true);
  expect(categoriaElegivel({ name: 'Pízzas Doces' })).toBe(true);
  expect(categoriaElegivel({ name: 'Bebidas' })).toBe(false);
  expect(categoriaElegivel({ name: 'Pizzas', pos_only: true })).toBe(false);
  expect(categoriaElegivel({ name: 'Pizzas', active: false })).toBe(false);
  expect(categoriaElegivel(null)).toBe(false);
});

test('candidatos: mesma categoria, outro sabor, disponível, no mesmo tamanho', () => {
  const todos = [marg, frango, esgotada, soMedia, coca];
  expect(candidatosMeia(marg, G, todos).map((p) => p.id)).toEqual(['b']);
  expect(candidatosMeia(marg, M, todos).map((p) => p.id)).toEqual(['b', 'd']);
});

test('preço é o da mais cara no tamanho', () => {
  expect(precoBaseMeia(marg, frango, G)).toBe(18.9);
  expect(precoNoTamanho(marg, 'Gigante')).toBeNull();
  expect(precoNoTamanho(coca, null)).toBe(3);
  expect(nomeMeiaMeia('A', 'B')).toBe('1/2 A + 1/2 B');
});
