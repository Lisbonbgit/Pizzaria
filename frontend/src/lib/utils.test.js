import { detalheErro } from './utils';

const erro = (detail) => ({ response: { data: { detail } } });

test('mostra o detail do servidor quando é texto; senão o texto por omissão', () => {
  expect(detalheErro(erro('Calabresa está esgotada'), 'Erro')).toBe('Calabresa está esgotada');
  expect(detalheErro(erro([{ loc: ['body'], msg: 'field required' }]), 'Erro')).toBe('Erro');
  expect(detalheErro(erro(''), 'Erro')).toBe('Erro');
  expect(detalheErro(new Error('Network Error'), 'Erro')).toBe('Erro');
});
