// Janela de tamanho/extras/meia-meia do catálogo do POS (balcão e mesa).
import React, { act } from 'react';
import { createRoot } from 'react-dom/client';
import CatalogoProdutos from './CatalogoProdutos';

// O jest do CRA não conhece o alias "@/" do webpack: aponta-se cada um à mão.
jest.mock('@/components/ui/button', () => jest.requireActual('../ui/button'), { virtual: true });
jest.mock('@/components/ui/dialog', () => jest.requireActual('../ui/dialog'), { virtual: true });
jest.mock('@/lib/meiaMeia', () => jest.requireActual('../../lib/meiaMeia'), { virtual: true });
jest.mock('@/lib/utils', () => jest.requireActual('../../lib/utils'), { virtual: true });

globalThis.IS_REACT_ACT_ENVIRONMENT = true;

// A janela do Radix só se mantém montada durante o fecho se houver animação: o
// jsdom não tem CSS, por isso finge-se uma animação diferente por data-state.
const origGCS = window.getComputedStyle;
beforeAll(() => {
  window.getComputedStyle = (el, ...r) => {
    const st = origGCS(el, ...r);
    if (el.getAttribute && el.getAttribute('role') === 'dialog' && globalThis.__animar) {
      return new Proxy(st, { get: (t, k) => (k === 'animationName'
        ? (el.getAttribute('data-state') === 'open' ? 'entrar' : 'sair') : t[k]) });
    }
    return st;
  };
});
afterAll(() => { window.getComputedStyle = origGCS; });

const M = 'Média (6 Fatias)'; const G = 'Grande (8 Fatias)';
const pz = (id, name, m, g) => ({ id, name, category_id: 'c-piz', base_price: m, available: true,
  variations: [{ name: M, price: m }, { name: G, price: g }], extras: [] });
const marg = pz('a', 'Margherita', 12.9, 16.9);
const frango = pz('b', 'Frango', 14.9, 18.9);
const doDia = { id: 'g', name: 'Pizza do Dia', category_id: 'c-piz', base_price: 9, available: true, variations: [], extras: [] };
const groups = [{ cid: 'c-piz', name: 'Pizzas', items: [marg, frango, doDia] }];

let root; let host; let onAdd;
beforeEach(async () => {
  globalThis.__animar = false;
  onAdd = jest.fn();
  host = document.createElement('div'); document.body.appendChild(host);
  root = createRoot(host);
  await act(async () => { root.render(<CatalogoProdutos groups={groups} onAdd={onAdd} />); });
});
afterEach(async () => { await act(async () => root.unmount()); host.remove(); document.body.innerHTML = ''; });

const botoes = () => [...document.querySelectorAll('button')];
const botao = (txt) => botoes().find((b) => b.textContent.includes(txt));
const clicar = async (txt) => { const b = botao(txt); if (!b) throw new Error(`sem botão "${txt}"`); await act(async () => { b.click(); }); };
const dialogo = () => document.querySelector('[role="dialog"]');

test('meia-meia: antes do tamanho não lista as pizzas sem tamanho', async () => {
  await clicar('Margherita'); await clicar('Fazer meia-meia');
  expect(dialogo().textContent).toContain('Escolhe primeiro o tamanho');
  expect([...dialogo().querySelectorAll('button')].map((b) => b.textContent).join('|')).not.toContain('Pizza do Dia');
});

test('meia-meia: sem outro sabor possível diz-o em vez de uma lista vazia', async () => {
  await clicar('Pizza do Dia'); await clicar('Fazer meia-meia');
  expect(dialogo().textContent).toContain('Nenhum outro sabor disponível');
  expect(dialogo().textContent).not.toContain('neste tamanho');
  expect(dialogo().textContent).not.toContain('Outra metade');
});

test('meia-meia: com tamanho escolhido lista a outra metade', async () => {
  await clicar('Margherita'); await clicar('Fazer meia-meia'); await clicar('Grande');
  expect(dialogo().textContent).toContain('Outra metade');
  expect(dialogo().textContent).toContain('Frango');
});

test('meia-meia ligada → tamanho → desligada: continua a haver botão Adicionar', async () => {
  await clicar('Margherita'); await clicar('Fazer meia-meia'); await clicar('Grande');
  await clicar('Meia-meia ✓');
  const b = botao('Adicionar —');
  expect(b && b.textContent).toBe('Adicionar — € 16.90');
  expect(b.disabled).toBe(false);
  await clicar('Adicionar —');
  expect(onAdd).toHaveBeenCalledWith(marg, marg.variations[1], [], null);
});

test('durante o fecho da janela não há botão Adicionar (tocar-lhe dava onAdd(null))', async () => {
  globalThis.__animar = true;
  await clicar('Pizza do Dia');
  await clicar('Adicionar —');
  expect(onAdd).toHaveBeenCalledTimes(1);
  expect(onAdd).toHaveBeenLastCalledWith(doDia, null, [], null);
  expect(dialogo()).not.toBeNull(); // ainda a animar o fecho
  expect(dialogo().getAttribute('data-state')).toBe('closed');
  const fantasma = [...dialogo().querySelectorAll('button')].find((x) => x.textContent.startsWith('Adicionar'));
  expect(fantasma).toBeUndefined();
});
