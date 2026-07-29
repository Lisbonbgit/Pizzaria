import React, { useCallback, useEffect, useState } from 'react';
import {
  ArrowDownCircle, ArrowUpCircle, ChevronDown, Info, Loader2, LogOut, RefreshCw,
  Store, Users, Vault, Wallet,
} from 'lucide-react';
import { toast } from 'sonner';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import {
  Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle,
} from '@/components/ui/dialog';
import {
  DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu';
import { posAPI, posCheckout } from '@/lib/api';
import TableCheckout from '@/pages/checkout/TableCheckout';

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
// + cartão "Balcão" (Fase 2, Task 4: abre `PosBalcao`, ecrã cheio, montado
// pelo PosApp via `onBalcao`) + cabeçalho com o operador, o estado da caixa
// e os botões menu Caixa / Sair.
//
// Espelha o layout/cores da grelha de AdminOrders.js (cartão por mesa, cor
// "ocupada" vs "livre", total/pessoas/pedidos quando ocupada), reskinado
// para o ecrã cheio maroon do POS (tablet): mesa ocupada = cartão branco em
// destaque; mesa livre = contorno subtil sobre o fundo maroon.
//
// `onFecharCaixa` abre o fluxo cheio de fecho de caixa (Task 7,
// `PosFecharCaixa`, montado pelo PosApp por cima desta Home). `refreshCaixa`
// fica disponível (não é chamado por este componente) para esse fluxo voltar
// a resolver o estado da caixa depois do fecho de verdade.
//
// O checkout de mesa (Task 6) é o `TableCheckout` partilhado com o admin —
// aqui é aberto com `api={posCheckout}` para que o fecho vá pelo device+PIN
// token (não o JWT admin) e o backend ligue a venda à sessão de caixa.
//
// Menu "Caixa" (Task 7, estilo Vendus): dropdown no cabeçalho com Estado da
// Caixa, Entrada/Saída de Dinheiro (dialog partilhado, tipo interno continua
// sangria/reforco — só o rótulo muda), Abrir Gaveta (posAPI.openDrawer) e
// Fechar Caixa. Não altera a grelha de mesas, por isso não mexe em
// `tables`/`load`.
const PosHome = ({ session, operator, onFecharCaixa, onBalcao, refreshCaixa, onLogout }) => {
  const [tables, setTables] = useState([]);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [selectedTableNum, setSelectedTableNum] = useState(null);
  const [movDialogOpen, setMovDialogOpen] = useState(false);
  const [movType, setMovType] = useState('sangria');
  const [movValor, setMovValor] = useState('');
  const [movMotivo, setMovMotivo] = useState('');
  const [movSubmitting, setMovSubmitting] = useState(false);
  const [estadoOpen, setEstadoOpen] = useState(false);
  const [estadoLoading, setEstadoLoading] = useState(false);
  const [estadoSessao, setEstadoSessao] = useState(null);
  const [drawerSubmitting, setDrawerSubmitting] = useState(false);

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

  // `type` é sempre passado pelo item do menu Caixa (reforco = Entrada,
  // sangria = Saída) — o dialog só pede o valor/motivo, o tipo já vem escolhido.
  const abrirMovDialog = useCallback((type) => {
    setMovType(type);
    setMovValor('');
    setMovMotivo('');
    setMovDialogOpen(true);
  }, []);

  const registarMovimento = useCallback(async () => {
    const valor = Number(movValor);
    if (Number.isNaN(valor) || valor <= 0) {
      toast.error('Indique um montante válido');
      return;
    }
    setMovSubmitting(true);
    try {
      await posAPI.cashMovement(movType, valor, movMotivo.trim() || undefined);
      toast.success(movType === 'reforco' ? 'Entrada registada' : 'Saída registada');
      setMovDialogOpen(false);
    } catch (err) {
      console.error('Erro ao registar movimento de caixa:', err);
      toast.error(err.response?.data?.detail || 'Não foi possível registar o movimento');
    } finally {
      setMovSubmitting(false);
    }
  }, [movType, movValor, movMotivo]);

  // Estado da Caixa: reconsulta `posAPI.cashCurrent()` para mostrar dados
  // frescos (aberta por / desde / fundo) em vez de confiar só na prop
  // `session`, que só é atualizada pelo componente-pai (PosApp).
  const abrirEstadoCaixa = useCallback(async () => {
    setEstadoOpen(true);
    setEstadoLoading(true);
    try {
      const r = await posAPI.cashCurrent();
      setEstadoSessao(r.data || null);
    } catch (err) {
      console.error('Erro ao obter o estado da caixa:', err);
      setEstadoSessao(session || null);
    } finally {
      setEstadoLoading(false);
    }
  }, [session]);

  const abrirGaveta = useCallback(async () => {
    setDrawerSubmitting(true);
    try {
      await posAPI.openDrawer();
      toast.success('Gaveta aberta');
    } catch (err) {
      console.error('Erro ao abrir a gaveta:', err);
      toast.error(err.response?.data?.detail || 'Não foi possível abrir a gaveta');
    } finally {
      setDrawerSubmitting(false);
    }
  }, []);

  const occupiedCount = tables.filter((t) => t.occupied).length;
  const selectedTable = tables.find((t) => t.number === selectedTableNum) || null;
  const movLabel = movType === 'reforco' ? 'Entrada de Dinheiro' : 'Saída de Dinheiro';

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
          {/* Menu "Caixa" (estilo Vendus): Estado / Entrada / Saída / Abrir Gaveta / Fechar */}
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <Button
                variant="outline"
                className="h-11 border-white/30 bg-transparent px-3 text-white hover:bg-white/10 hover:text-white"
              >
                <Wallet className="h-4 w-4 sm:mr-1.5" />
                <span className="hidden sm:inline">Caixa</span>
                <ChevronDown className="h-4 w-4 ml-1" />
              </Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end" className="w-60">
              <DropdownMenuItem onSelect={abrirEstadoCaixa}>
                <Info className="h-4 w-4" />
                Estado da Caixa
              </DropdownMenuItem>
              <DropdownMenuSeparator />
              <DropdownMenuItem onSelect={() => abrirMovDialog('reforco')}>
                <ArrowDownCircle className="h-4 w-4" />
                Entrada de Dinheiro
              </DropdownMenuItem>
              <DropdownMenuItem onSelect={() => abrirMovDialog('sangria')}>
                <ArrowUpCircle className="h-4 w-4" />
                Saída de Dinheiro
              </DropdownMenuItem>
              <DropdownMenuSeparator />
              <DropdownMenuItem onSelect={abrirGaveta} disabled={drawerSubmitting}>
                <Vault className="h-4 w-4" />
                Abrir Gaveta
              </DropdownMenuItem>
              <DropdownMenuSeparator />
              <DropdownMenuItem onSelect={onFecharCaixa}>
                <Wallet className="h-4 w-4" />
                Fechar Caixa
              </DropdownMenuItem>
            </DropdownMenuContent>
          </DropdownMenu>
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
                    onClick={() => setSelectedTableNum(t.number)}
                    disabled={!busy}
                    aria-label={`${t.name || `Mesa ${t.number}`}${
                      busy ? `, ocupada, ${eur(t.open_total)} em aberto` : ', livre'
                    }`}
                    className={[
                      'group relative flex aspect-square touch-manipulation flex-col justify-between overflow-hidden rounded-xl border p-4 text-left transition-all active:scale-[0.98]',
                      busy
                        ? 'border-amber-300/60 bg-white text-[#5a1a1a] hover:shadow-lg cursor-pointer'
                        : 'border-white/20 bg-white/5 text-white/70 hover:bg-white/10 cursor-default',
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

              {/* Balcão — Fase 2, Task 4: venda sem mesa (PosBalcao, ecrã cheio) */}
              <button
                type="button"
                onClick={onBalcao}
                aria-label="Balcão, nova venda sem mesa"
                className="group relative flex aspect-square touch-manipulation flex-col justify-between overflow-hidden rounded-xl border border-amber-300/60 bg-white p-4 text-left text-[#5a1a1a] transition-all hover:shadow-lg active:scale-[0.98]"
              >
                <span className="absolute inset-x-0 top-0 h-1.5 bg-amber-400" />
                <div>
                  <Store className="mb-1 h-5 w-5 opacity-70" />
                  <p className="text-lg font-bold leading-tight">Balcão</p>
                </div>
                <p className="text-xs uppercase tracking-wide text-[#5a1a1a]/60">Nova venda</p>
              </button>
            </div>
          </>
        )}
      </main>

      {/* Checkout de mesa — componente partilhado com o admin (Task 6), aberto
          via posCheckout para que o fecho fique ligado à sessão de caixa. */}
      <TableCheckout
        api={posCheckout}
        tableNumber={selectedTableNum}
        table={selectedTable}
        onClose={() => setSelectedTableNum(null)}
        onChanged={() => load(true)}
      />

      {/* Entrada/Saída de Dinheiro (menu Caixa) — dialog partilhado sobre
          posAPI.cashMovement; o tipo já vem escolhido pelo item do menu
          (abrirMovDialog), aqui só se pede valor + motivo. */}
      <Dialog open={movDialogOpen} onOpenChange={(open) => !movSubmitting && setMovDialogOpen(open)}>
        <DialogContent className="sm:max-w-sm">
          <DialogHeader>
            <DialogTitle>{movLabel}</DialogTitle>
          </DialogHeader>
          <div className="space-y-4">
            <div className="space-y-2">
              <Label htmlFor="mov-valor">Valor</Label>
              <div className="relative">
                <span className="absolute left-3 top-1/2 -translate-y-1/2 text-muted-foreground">€</span>
                <Input
                  id="mov-valor"
                  type="number"
                  inputMode="decimal"
                  min="0"
                  step="0.01"
                  value={movValor}
                  onChange={(e) => setMovValor(e.target.value)}
                  disabled={movSubmitting}
                  className="pl-7"
                />
              </div>
            </div>
            <div className="space-y-2">
              <Label htmlFor="mov-motivo">Motivo (opcional)</Label>
              <Input
                id="mov-motivo"
                value={movMotivo}
                onChange={(e) => setMovMotivo(e.target.value)}
                disabled={movSubmitting}
              />
            </div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setMovDialogOpen(false)} disabled={movSubmitting}>
              Cancelar
            </Button>
            <Button onClick={registarMovimento} disabled={movSubmitting}>
              {movSubmitting && <Loader2 className="h-4 w-4 animate-spin" />}
              Confirmar
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Estado da Caixa (menu Caixa) — consulta posAPI.cashCurrent() ao abrir. */}
      <Dialog open={estadoOpen} onOpenChange={setEstadoOpen}>
        <DialogContent className="sm:max-w-sm">
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2">
              <Info className="h-5 w-5" />
              Estado da Caixa
            </DialogTitle>
          </DialogHeader>
          {estadoLoading ? (
            <div className="flex items-center justify-center py-6">
              <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
            </div>
          ) : estadoSessao ? (
            <div className="space-y-3 text-sm">
              <div className="flex items-center justify-between">
                <span className="text-muted-foreground">Aberta por</span>
                <span className="font-medium">{estadoSessao.opened_by_name || '—'}</span>
              </div>
              <div className="flex items-center justify-between">
                <span className="text-muted-foreground">Desde</span>
                <span className="font-medium">{formatHora(estadoSessao.opened_at) || '—'}</span>
              </div>
              <div className="flex items-center justify-between">
                <span className="text-muted-foreground">Fundo de abertura</span>
                <span className="font-medium">{eur(estadoSessao.opening_amount)}</span>
              </div>
            </div>
          ) : (
            <p className="py-4 text-center text-sm text-muted-foreground">Caixa fechada.</p>
          )}
          <DialogFooter>
            <Button variant="outline" onClick={() => setEstadoOpen(false)}>
              Fechar
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
};

export default PosHome;
