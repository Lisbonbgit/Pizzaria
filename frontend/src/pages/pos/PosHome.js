import React, { useCallback, useEffect, useState } from 'react';
import { Loader2, LogOut, RefreshCw, Store, Users, Wallet } from 'lucide-react';
import { toast } from 'sonner';
import { Button } from '@/components/ui/button';
import { posCheckout } from '@/lib/api';

const eur = (v) => `€ ${Number(v || 0).toFixed(2)}`;
const REFRESH_MS = 10000;

// Formata "opened_at" (ISO em UTC) para hora de Lisboa, ex.: "14:32".
const formatHora = (iso) => {
  if (!iso) return '';
  try {
    return new Date(iso).toLocaleTimeString('pt-PT', {
      hour: '2-digit',
      minute: '2-digit',
      timeZone: 'Europe/Lisbon',
    });
  } catch {
    return '';
  }
};

// Home do POS: grelha de mesas (com refresh periódico via posCheckout.overview())
// + cartão "Balcão" (placeholder "Brevemente", Fase 2) + cabeçalho com o
// operador, o estado da caixa e os botões Fechar Caixa / Sair.
//
// Espelha o layout/cores da grelha de AdminOrders.js (cartão por mesa, cor
// "ocupada" vs "livre", total/pessoas/pedidos quando ocupada), reskinado
// para o ecrã cheio maroon do POS (tablet): mesa ocupada = cartão branco em
// destaque; mesa livre = contorno subtil sobre o fundo maroon.
//
// `onFecharCaixa` e `onOpenTable` são, nesta tarefa, placeholders passados
// pelo PosApp (o fecho de caixa real é a Task 7; o checkout de mesa é a
// Task 6) — aqui limitamo-nos a chamar os props ao clicar. `refreshCaixa`
// fica disponível (não é chamado por este componente) para a Task 7 voltar
// a resolver o estado da caixa depois do fecho de verdade.
const PosHome = ({ session, operator, onFecharCaixa, onOpenTable, refreshCaixa, onLogout }) => {
  const [tables, setTables] = useState([]);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);

  const load = useCallback(async (silent = false) => {
    if (silent) setRefreshing(true);
    try {
      const r = await posCheckout.overview();
      setTables(r.data || []);
    } catch (err) {
      console.error('Erro ao carregar as mesas:', err);
      if (!silent) toast.error('Erro ao carregar as mesas');
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, []);

  useEffect(() => {
    load();
    const id = setInterval(() => load(true), REFRESH_MS);
    return () => clearInterval(id);
  }, [load]);

  const occupiedCount = tables.filter((t) => t.occupied).length;

  return (
    <div className="min-h-screen flex flex-col bg-[#5a1a1a] text-white">
      {/* Cabeçalho */}
      <header className="flex flex-wrap items-center justify-between gap-3 border-b border-white/15 px-5 py-4 sm:px-8">
        <div className="min-w-0">
          <h1 className="text-xl font-bold leading-tight">POS · Mesas</h1>
          <p className="truncate text-sm text-white/70">
            Operador: <span className="font-medium text-white">{operator?.name || '—'}</span>
            {session?.opened_at && (
              <span className="text-white/50">
                {' '}· Caixa aberta às {formatHora(session.opened_at)} ({eur(session.opening_amount)})
              </span>
            )}
          </p>
        </div>
        <div className="flex shrink-0 items-center gap-2">
          <Button
            variant="outline"
            onClick={() => load(true)}
            disabled={refreshing}
            className="h-11 border-white/30 bg-transparent px-3 text-white hover:bg-white/10 hover:text-white"
          >
            <RefreshCw className={`h-4 w-4 sm:mr-1.5 ${refreshing ? 'animate-spin' : ''}`} />
            <span className="hidden sm:inline">Atualizar</span>
          </Button>
          <Button
            onClick={onFecharCaixa}
            className="h-11 bg-white px-4 font-semibold text-[#5a1a1a] hover:bg-white/90"
          >
            <Wallet className="h-4 w-4 mr-1.5" />
            Fechar Caixa
          </Button>
          <Button
            variant="outline"
            onClick={onLogout}
            className="h-11 border-white/30 bg-transparent px-3 text-white hover:bg-white/10 hover:text-white"
          >
            <LogOut className="h-4 w-4 sm:mr-1.5" />
            <span className="hidden sm:inline">Sair</span>
          </Button>
        </div>
      </header>

      {/* Corpo */}
      <main className="flex-1 overflow-y-auto px-5 py-5 sm:px-8 sm:py-6">
        <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
          <p className="text-sm text-white/70">
            {occupiedCount > 0 ? (
              <>
                <span className="font-semibold text-white">{occupiedCount}</span> mesa
                {occupiedCount > 1 ? 's' : ''} ocupada{occupiedCount > 1 ? 's' : ''}
              </>
            ) : (
              'Todas as mesas livres'
            )}
          </p>
          {/* Legenda */}
          <div className="flex items-center gap-4 text-xs text-white/70">
            <span className="flex items-center gap-1.5">
              <span className="h-2.5 w-2.5 rounded-full border border-white/40 bg-transparent" />
              Mesa Livre
            </span>
            <span className="flex items-center gap-1.5">
              <span className="h-2.5 w-2.5 rounded-full bg-amber-400" />
              Mesa Ocupada
            </span>
          </div>
        </div>

        {loading ? (
          <div className="flex items-center justify-center py-24">
            <Loader2 className="h-8 w-8 animate-spin text-white/70" />
          </div>
        ) : (
          <>
            {tables.length === 0 && (
              <p className="mb-3 text-sm text-white/50">Ainda não há mesas configuradas.</p>
            )}
            <div className="grid gap-3 [grid-template-columns:repeat(auto-fill,minmax(150px,1fr))]">
              {tables.map((t) => {
                const busy = t.occupied;
                return (
                  <button
                    key={t.id || t.number}
                    type="button"
                    onClick={() => onOpenTable(t.number)}
                    aria-label={`${t.name || `Mesa ${t.number}`}${
                      busy ? `, ocupada, ${eur(t.open_total)} em aberto` : ', livre'
                    }`}
                    className={[
                      'group relative flex aspect-square touch-manipulation flex-col justify-between overflow-hidden rounded-xl border p-4 text-left transition-all active:scale-[0.98]',
                      busy
                        ? 'border-amber-300/60 bg-white text-[#5a1a1a] hover:shadow-lg'
                        : 'border-white/20 bg-white/5 text-white/70 hover:bg-white/10',
                    ].join(' ')}
                  >
                    <span className={`absolute inset-x-0 top-0 h-1.5 ${busy ? 'bg-amber-400' : 'bg-white/15'}`} />
                    <div className="flex items-start justify-between">
                      <div className="min-w-0">
                        <p className={`text-[11px] uppercase tracking-wide ${busy ? 'text-[#5a1a1a]/60' : 'text-white/50'}`}>
                          Mesa
                        </p>
                        <p className={`text-3xl font-bold leading-none ${busy ? 'text-[#5a1a1a]' : 'text-white/60'}`}>
                          {t.number}
                        </p>
                      </div>
                      {busy && <span className="mt-1 h-2.5 w-2.5 shrink-0 animate-pulse rounded-full bg-amber-400" />}
                    </div>
                    {busy ? (
                      <div>
                        <p className="text-2xl font-bold tabular-nums">{eur(t.open_total)}</p>
                        <p className="flex flex-wrap items-center gap-1 text-xs opacity-70">
                          {t.people ? (
                            <>
                              <Users className="h-3 w-3" />
                              <span>{t.people}</span>
                              <span>·</span>
                            </>
                          ) : null}
                          <span>
                            {t.open_orders} pedido{t.open_orders !== 1 ? 's' : ''}
                          </span>
                        </p>
                      </div>
                    ) : (
                      <p className="text-xs">Livre</p>
                    )}
                  </button>
                );
              })}

              {/* Balcão — Fase 2, ainda por implementar */}
              <div
                aria-disabled="true"
                className="relative flex aspect-square cursor-not-allowed select-none flex-col justify-between rounded-xl border border-dashed border-white/20 bg-white/[0.03] p-4 text-white/40"
              >
                <div>
                  <Store className="mb-1 h-5 w-5 opacity-60" />
                  <p className="text-lg font-bold leading-tight">Balcão</p>
                </div>
                <p className="text-xs uppercase tracking-wide">Brevemente</p>
              </div>
            </div>
          </>
        )}
      </main>
    </div>
  );
};

export default PosHome;
