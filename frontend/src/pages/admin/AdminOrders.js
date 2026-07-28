import React, { useState, useEffect, useCallback } from 'react';
import { Loader2, RefreshCw, Users } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { toast } from 'sonner';
import AdminLayout from '@/components/AdminLayout';
import { tablesAPI, checkoutAPI } from '@/lib/api';
import TableCheckout from '@/pages/checkout/TableCheckout';

const eur = (v) => `€ ${Number(v || 0).toFixed(2)}`;

const AdminOrders = () => {
  const [tables, setTables] = useState([]);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);

  // Mesa aberta no checkout (só o número — o TableCheckout partilhado lê o
  // resto do snapshot em `selectedTable`, abaixo).
  const [openTableNum, setOpenTableNum] = useState(null);

  const load = useCallback(async (silent = false) => {
    if (silent) setRefreshing(true);
    try {
      const r = await tablesAPI.overview();
      setTables(r.data);
    } catch {
      if (!silent) toast.error('Erro ao carregar as mesas');
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, []);

  useEffect(() => {
    load();
    const id = setInterval(() => load(true), 12000);
    return () => clearInterval(id);
  }, [load]);

  const openTable = (t) => {
    if (!t.occupied) return;
    setOpenTableNum(t.number);
  };

  const closeModal = () => setOpenTableNum(null);

  const selectedTable = tables.find((t) => t.number === openTableNum) || null;

  const occupied = tables.filter((t) => t.occupied);
  const totalOpen = occupied.reduce((s, t) => s + (t.open_total || 0), 0);

  if (loading) {
    return (
      <AdminLayout title="Pedidos">
        <div className="flex items-center justify-center h-64">
          <Loader2 className="h-8 w-8 animate-spin text-primary" />
        </div>
      </AdminLayout>
    );
  }

  return (
    <AdminLayout title="Pedidos">
      {/* Cabeçalho / resumo */}
      <div className="flex flex-wrap items-center justify-between gap-3 mb-6">
        <div className="flex items-baseline gap-4">
          <h2 className="font-heading text-xl font-bold">Mesas</h2>
          <p className="text-sm text-muted-foreground">
            {occupied.length > 0
              ? <><span className="font-semibold text-primary">{occupied.length}</span> ocupada{occupied.length > 1 ? 's' : ''} · <span className="font-semibold text-primary">{eur(totalOpen)}</span> em aberto</>
              : 'Todas as mesas livres'}
          </p>
        </div>
        <Button variant="outline" size="sm" onClick={() => load(true)} disabled={refreshing}>
          <RefreshCw className={`h-4 w-4 mr-2 ${refreshing ? 'animate-spin' : ''}`} />
          Atualizar
        </Button>
      </div>

      {/* Grelha de mesas */}
      {tables.length === 0 ? (
        <div className="rounded-xl border border-dashed py-16 text-center text-muted-foreground">
          Ainda não há mesas. Cria-as em <span className="font-medium">Mesas</span>.
        </div>
      ) : (
        <div className="grid gap-3 [grid-template-columns:repeat(auto-fill,minmax(150px,1fr))]">
          {tables.map((t) => {
            const busy = t.occupied;
            const isMesaName = !t.name || /^mesa\s*\d+$/i.test(String(t.name).trim());
            return (
              <button
                key={t.id}
                onClick={() => openTable(t)}
                disabled={!busy}
                aria-label={`${t.name || `Mesa ${t.number}`}${busy ? `, ${eur(t.open_total)} em aberto` : ', livre'}`}
                className={[
                  'group relative aspect-square rounded-xl border text-left p-4 flex flex-col justify-between transition-all overflow-hidden',
                  busy
                    ? 'border-primary/30 bg-primary/[0.04] hover:bg-primary/[0.08] hover:border-primary/60 hover:shadow-md cursor-pointer'
                    : 'border-border bg-card text-muted-foreground cursor-default',
                ].join(' ')}
              >
                <span className={`absolute inset-x-0 top-0 h-1.5 ${busy ? 'bg-primary' : 'bg-border'}`} />
                <div className="flex items-start justify-between">
                  <div className="min-w-0">
                    {isMesaName ? (
                      <>
                        <p className={`text-[11px] uppercase tracking-wide ${busy ? 'text-primary/70' : 'text-muted-foreground'}`}>Mesa</p>
                        <p className={`font-heading font-bold leading-none text-3xl ${busy ? 'text-primary' : 'text-foreground/40'}`}>{t.number}</p>
                      </>
                    ) : (
                      <p className={`font-heading font-bold leading-tight text-xl break-words ${busy ? 'text-primary' : 'text-foreground/40'}`}>{t.name}</p>
                    )}
                  </div>
                  {busy && <span className="mt-1 h-2.5 w-2.5 shrink-0 rounded-full bg-primary animate-pulse" title="Conta aberta" />}
                </div>
                {busy ? (
                  <div>
                    {t.rodizio && t.rodizio !== 'none' && (
                      <span className="inline-block mb-1 rounded-full bg-primary px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-primary-foreground">
                        🍕 Rodízio {t.rodizio === 'completo' ? 'Completo' : 'Simples'}
                      </span>
                    )}
                    <p className="font-heading text-2xl font-bold tabular-nums text-foreground">{eur(t.open_total)}</p>
                    <p className="text-xs text-muted-foreground flex items-center gap-1 flex-wrap">
                      {t.people ? <><Users className="h-3 w-3" /><span>{t.people}</span><span>·</span></> : null}
                      <span>{t.open_orders} pedido{t.open_orders !== 1 ? 's' : ''}</span>
                    </p>
                  </div>
                ) : (
                  <p className="text-xs">Livre</p>
                )}
              </button>
            );
          })}
        </div>
      )}

      {/* Checkout de mesa — componente partilhado com o POS (Task 6) */}
      <TableCheckout
        api={checkoutAPI}
        tableNumber={openTableNum}
        table={selectedTable}
        onClose={closeModal}
        onChanged={() => load(true)}
      />
    </AdminLayout>
  );
};

export default AdminOrders;
