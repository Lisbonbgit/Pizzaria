import React, { useCallback, useEffect, useState } from 'react';
import { AlertTriangle, Loader2, Printer, Wallet } from 'lucide-react';
import { toast } from 'sonner';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { posAPI, posCheckout } from '@/lib/api';

const eur = (v) => `€ ${Number(v || 0).toFixed(2)}`;

// Fluxo "Fechar Caixa" (Task 7), ecrã cheio maroon como o resto do POS:
//   1. 'loading'  — verifica mesas abertas (posCheckout.overview()).
//   2. 'aviso'    — só se houver mesas ocupadas: avisa e deixa
//                   cancelar/continuar.
//   3. 'contagem' — pede o montante contado e chama posAPI.cashClose.
//   4. 'z'        — mostra os dados do Z devolvidos pelo fecho (o backend já
//                   pôs o talão na fila de impressão). "Terminar" fecha o
//                   fluxo, refresca o estado da caixa e faz logout (a
//                   próxima pessoa a usar o POS faz login por PIN de novo).
//
// Props:
//   operator  — utilizador POS autenticado (id/name), só para mostrar no ecrã.
//   onCancel  — chamado a partir de 'aviso'/'contagem' para voltar à Home
//               sem fechar a caixa.
//   onClosed  — chamado quando o operador confirma "Terminar" no ecrã do Z
//               (assíncrono: o chamador deve refrescar o estado da caixa e
//               fazer logout).
const PosFecharCaixa = ({ operator, onCancel, onClosed }) => {
  const [step, setStep] = useState('loading');
  const [openTables, setOpenTables] = useState([]);
  const [montante, setMontante] = useState('0');
  const [submitting, setSubmitting] = useState(false);
  const [zData, setZData] = useState(null);
  const [finishing, setFinishing] = useState(false);
  // Pré-visualização do esperado (Fase 4b) — carregada ao entrar em
  // 'contagem', para o operador comparar com o que vai contar na gaveta.
  // `null` enquanto carrega ou se a chamada falhar (best-effort: não bloqueia
  // a contagem, só não mostra a linha).
  const [expected, setExpected] = useState(null);
  const [expectedLoading, setExpectedLoading] = useState(false);

  // Verifica mesas abertas assim que o fluxo arranca. Se a chamada falhar
  // (rede), não bloqueia o fecho — avisa e segue para a contagem.
  useEffect(() => {
    let active = true;
    (async () => {
      try {
        const r = await posCheckout.overview();
        const ocupadas = (r.data || []).filter((t) => t.occupied);
        if (!active) return;
        setOpenTables(ocupadas);
        setStep(ocupadas.length > 0 ? 'aviso' : 'contagem');
      } catch (err) {
        console.error('Erro ao verificar mesas abertas:', err);
        if (!active) return;
        toast.error('Não foi possível verificar as mesas abertas');
        setStep('contagem');
      }
    })();
    return () => {
      active = false;
    };
  }, []);

  // Pré-visualização do esperado: pedida assim que se chega ao ecrã de
  // contagem (quer venha direto, quer depois do aviso de mesas abertas).
  // `GET /pos/cash/expected` é best-effort no backend (nunca 500 por causa do
  // Vendus); aqui, uma falha de rede/token também não bloqueia a contagem —
  // só não mostra a linha do esperado.
  useEffect(() => {
    if (step !== 'contagem') return undefined;
    let active = true;
    setExpectedLoading(true);
    (async () => {
      try {
        const r = await posAPI.cashExpected();
        if (active) setExpected(r.data);
      } catch (err) {
        console.error('Erro ao obter o valor esperado no caixa:', err);
      } finally {
        if (active) setExpectedLoading(false);
      }
    })();
    return () => {
      active = false;
    };
  }, [step]);

  const confirmarFecho = useCallback(async () => {
    const valor = Number(montante);
    if (Number.isNaN(valor) || valor < 0) {
      toast.error('Montante inválido');
      return;
    }
    setSubmitting(true);
    try {
      const r = await posAPI.cashClose(valor);
      setZData(r.data);
      setStep('z');
    } catch (err) {
      console.error('Erro ao fechar a caixa:', err);
      toast.error(err.response?.data?.detail || 'Não foi possível fechar a caixa');
    } finally {
      setSubmitting(false);
    }
  }, [montante]);

  // Não usamos try/finally aqui: `onClosed` faz logout no fim, o que troca
  // de ecrã (PosApp deixa de montar este componente) — não há necessidade
  // (nem é seguro) repor `finishing` depois disso.
  const terminar = useCallback(() => {
    setFinishing(true);
    onClosed();
  }, [onClosed]);

  if (step === 'loading') {
    return (
      <div className="min-h-screen flex items-center justify-center bg-[#5a1a1a]">
        <Loader2 className="h-10 w-10 animate-spin text-white" />
      </div>
    );
  }

  if (step === 'aviso') {
    const nomes = openTables.map((t) => t.name || `Mesa ${t.number}`).join(', ');
    return (
      <div className="min-h-screen flex flex-col items-center justify-center bg-[#5a1a1a] p-6 text-white text-center">
        <AlertTriangle className="h-14 w-14 text-amber-300 mb-4" />
        <h1 className="text-2xl font-bold mb-2">Há mesas abertas</h1>
        <p className="text-white/80 mb-4 max-w-md leading-relaxed">
          Há <span className="font-semibold text-white">{openTables.length}</span> mesa
          {openTables.length > 1 ? 's' : ''} aberta{openTables.length > 1 ? 's' : ''}: {nomes}
        </p>
        <div className="w-full max-w-sm mb-8 max-h-56 overflow-y-auto rounded-xl border border-white/20 bg-white/5 divide-y divide-white/10 text-left">
          {openTables.map((t) => (
            <div key={t.id || t.number} className="flex items-center justify-between px-4 py-2 text-sm">
              <span>{t.name || `Mesa ${t.number}`}</span>
              <span className="tabular-nums text-white/70">{eur(t.open_total)}</span>
            </div>
          ))}
        </div>
        <div className="flex w-full max-w-sm gap-3">
          <Button
            variant="outline"
            onClick={onCancel}
            className="flex-1 h-12 border-white/30 bg-transparent text-white hover:bg-white/10 hover:text-white"
          >
            Cancelar
          </Button>
          <Button
            onClick={() => setStep('contagem')}
            className="flex-1 h-12 font-semibold bg-white text-[#5a1a1a] hover:bg-white/90"
          >
            Fechar mesmo assim
          </Button>
        </div>
      </div>
    );
  }

  if (step === 'contagem') {
    return (
      <div className="min-h-screen flex flex-col items-center justify-center bg-[#5a1a1a] p-6 text-white">
        <Wallet className="h-14 w-14 text-white/70 mb-4" />
        <h1 className="text-2xl font-bold mb-1">Contagem de Caixa</h1>
        {operator?.name && <p className="text-white/70 mb-2">Operador: {operator.name}</p>}

        {expectedLoading ? (
          <p className="text-white/50 text-xs mb-6">A calcular o valor esperado...</p>
        ) : expected ? (
          <p className="text-white/70 text-sm mb-6 text-center">
            Valor esperado no caixa: <span className="font-semibold">{eur(expected.expected_cash)}</span>
            {expected.vendus_ok === false && (
              <span className="block text-white/40 text-xs mt-0.5">(sem ligação ao Vendus — estimativa)</span>
            )}
          </p>
        ) : (
          <div className="mb-6" />
        )}

        <div className="w-full max-w-xs space-y-2 mb-8">
          <Label htmlFor="montante-contado" className="text-white/80">
            Montante contado
          </Label>
          <div className="relative">
            <span className="absolute left-3 top-1/2 -translate-y-1/2 text-white/60">€</span>
            <Input
              id="montante-contado"
              type="number"
              inputMode="decimal"
              min="0"
              step="0.01"
              value={montante}
              onChange={(e) => setMontante(e.target.value)}
              disabled={submitting}
              className="pl-7 h-12 text-lg text-right bg-white/10 border-white/30 text-white placeholder:text-white/40 focus-visible:ring-white/50"
            />
          </div>
        </div>

        <div className="flex w-full max-w-xs gap-3">
          <Button
            variant="outline"
            onClick={onCancel}
            disabled={submitting}
            className="flex-1 h-14 border-white/30 bg-transparent text-white hover:bg-white/10 hover:text-white"
          >
            Cancelar
          </Button>
          <Button
            onClick={confirmarFecho}
            disabled={submitting}
            className="flex-1 h-14 text-lg font-semibold bg-white text-[#5a1a1a] hover:bg-white/90"
          >
            {submitting ? (
              <>
                <Loader2 className="h-5 w-5 animate-spin" />
                A fechar...
              </>
            ) : (
              'Confirmar Fecho'
            )}
          </Button>
        </div>
      </div>
    );
  }

  // step === 'z'
  const totals = Object.entries(zData?.totals_by_method || {}).sort(([a], [b]) => a.localeCompare(b));
  const diferenca = Number(zData?.difference || 0);
  const diffOk = Math.abs(diferenca) < 0.005;
  const diffClass = diffOk ? 'text-emerald-400' : diferenca > 0 ? 'text-amber-400' : 'text-red-400';
  const diffSign = diferenca > 0 ? '+' : diferenca < 0 ? '-' : '';
  const reconciliacao = zData?.reconciliation || null;
  const avisos = zData?.warnings || [];
  const movimentos = zData?.movements || [];

  return (
    <div className="min-h-screen flex flex-col bg-[#5a1a1a] text-white">
      <header className="border-b border-white/15 px-5 py-4 sm:px-8">
        <h1 className="text-xl font-bold leading-tight">Fecho de Caixa · Relatório Z</h1>
        <p className="truncate text-sm text-white/70">
          Fechada por: <span className="font-medium text-white">{zData?.closed_by || operator?.name || '—'}</span>
        </p>
      </header>

      <main className="flex-1 overflow-y-auto px-5 py-5 sm:px-8 sm:py-6 space-y-4">
        {reconciliacao && reconciliacao.ok === false && (
          <div className="rounded-xl border border-amber-400/50 bg-amber-400/10 p-4 text-sm text-amber-100">
            <p className="mb-1 flex items-center gap-2 font-semibold">
              <AlertTriangle className="h-4 w-4" />
              Atenção: divergência com o Vendus
            </p>
            {(reconciliacao.orphans || []).length > 0 && (
              <p>Vendus sem correspondência nas vendas POS: {reconciliacao.orphans.join(', ')}</p>
            )}
            {(reconciliacao.missing || []).length > 0 && (
              <p>Vendas POS sem fatura: {reconciliacao.missing.join(', ')}</p>
            )}
          </div>
        )}

        {avisos.length > 0 && (
          <div className="rounded-xl border border-amber-400/40 bg-amber-400/10 p-3 text-xs text-amber-100 space-y-1">
            {avisos.map((w, i) => (
              <p key={i}>{w}</p>
            ))}
          </div>
        )}

        <div className="rounded-xl border border-white/15 bg-white/5 p-4">
          <h2 className="mb-3 text-sm font-semibold uppercase tracking-wide text-white/70">
            Por forma de pagamento
          </h2>
          {totals.length === 0 ? (
            <p className="text-sm text-white/50">Sem vendas nesta sessão.</p>
          ) : (
            <div className="space-y-2">
              {totals.map(([titulo, v]) => (
                <div key={titulo} className="flex items-center justify-between text-sm">
                  <span className="text-white/85">
                    {titulo} <span className="text-white/50">· {v?.count || 0}x</span>
                  </span>
                  <span className="font-semibold tabular-nums">{eur(v?.total)}</span>
                </div>
              ))}
            </div>
          )}
        </div>

        {movimentos.length > 0 && (
          <div className="rounded-xl border border-white/15 bg-white/5 p-4">
            <h2 className="mb-3 text-sm font-semibold uppercase tracking-wide text-white/70">Movimentos</h2>
            <div className="space-y-1.5">
              {movimentos.map((m, i) => (
                <div key={i} className="flex items-center justify-between text-sm">
                  <span className="text-white/85">
                    {m.type === 'reforco' ? 'Entrada de Dinheiro' : 'Saída de Dinheiro'}
                    {m.reason ? ` · ${m.reason}` : ''}
                  </span>
                  <span className={`tabular-nums font-medium ${m.type === 'reforco' ? 'text-emerald-300' : 'text-amber-300'}`}>
                    {m.type === 'reforco' ? '+' : '-'}
                    {eur(m.amount)}
                  </span>
                </div>
              ))}
            </div>
          </div>
        )}

        <div className="rounded-xl border border-white/15 bg-white/5 p-4 space-y-2">
          <div className="flex items-center justify-between text-sm">
            <span className="text-white/70">Fundo de abertura</span>
            <span className="tabular-nums">{eur(zData?.opening_amount)}</span>
          </div>
          <div className="flex items-center justify-between text-sm">
            <span className="text-white/70">Esperado (dinheiro)</span>
            <span className="tabular-nums">{eur(zData?.expected_cash)}</span>
          </div>
          <div className="flex items-center justify-between text-sm">
            <span className="text-white/70">Contado</span>
            <span className="tabular-nums">{eur(zData?.counted_amount)}</span>
          </div>
          <div className="flex items-center justify-between border-t border-white/15 pt-2 text-base font-bold">
            <span>Diferença</span>
            <span className={`tabular-nums ${diffClass}`}>
              {diffSign}
              {eur(Math.abs(diferenca))}
            </span>
          </div>
        </div>

        <p className="flex items-center gap-2 text-sm text-white/70">
          <Printer className="h-4 w-4" />
          O talão Z foi enviado para impressão.
        </p>
      </main>

      <footer className="border-t border-white/15 px-5 py-4 sm:px-8">
        <Button
          onClick={terminar}
          disabled={finishing}
          className="w-full h-14 text-lg font-semibold bg-white text-[#5a1a1a] hover:bg-white/90"
        >
          {finishing ? (
            <>
              <Loader2 className="h-5 w-5 animate-spin" />
              A terminar...
            </>
          ) : (
            'Terminar'
          )}
        </Button>
      </footer>
    </div>
  );
};

export default PosFecharCaixa;
