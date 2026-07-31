import React, { useCallback, useEffect, useState } from 'react';
import { ArrowLeft, Loader2, RefreshCw, Undo2, ChevronRight } from 'lucide-react';
import { toast } from 'sonner';
import { Button } from '@/components/ui/button';
import {
  AlertDialog, AlertDialogAction, AlertDialogCancel, AlertDialogContent,
  AlertDialogDescription, AlertDialogFooter, AlertDialogHeader, AlertDialogTitle,
} from '@/components/ui/alert-dialog';
import { posCreditNote } from '@/lib/api';

const eur = (v) => `€ ${Number(v || 0).toFixed(2)}`;

// Ecrã cheio de Nota de Crédito (montado pelo PosApp por cima da Home, como o
// Balcão). Lista as faturas recentes (hoje + ontem) da caixa da app; tocar numa
// abre a confirmação e emite a NC TOTAL no Vendus. Após emitir, a fatura sai da
// lista (já não se pode creditar duas vezes).
//   onClose — volta à Home.
const PosCreditNote = ({ onClose }) => {
  const [invoices, setInvoices] = useState([]);
  const [loading, setLoading] = useState(true);
  const [selected, setSelected] = useState(null); // fatura a creditar (abre confirmação)
  const [submitting, setSubmitting] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const r = await posCreditNote.listInvoices();
      setInvoices(r.data.invoices || []);
    } catch (err) {
      console.error('Erro ao carregar faturas p/ NC:', err);
      toast.error(err.response?.data?.detail || 'Erro ao carregar as faturas');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  const emitir = async () => {
    if (!selected) return;
    setSubmitting(true);
    try {
      const r = await posCreditNote.create(selected.id);
      const d = r.data || {};
      toast.success(`Nota de crédito emitida: ${d.nc_number || ''} (${eur(d.credited_total)})`);
      // Remove a fatura creditada da lista (já não é creditável).
      setInvoices((prev) => prev.filter((x) => x.id !== selected.id));
      setSelected(null);
    } catch (err) {
      console.error('Erro ao emitir NC:', err);
      toast.error(err.response?.data?.detail || 'Erro ao emitir a nota de crédito');
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="min-h-screen flex flex-col bg-[#5a1a1a] text-white">
      {/* Cabeçalho */}
      <header className="flex items-center gap-3 border-b border-white/15 px-5 py-4 sm:px-8">
        <Button
          variant="outline" size="icon" onClick={onClose}
          title="Voltar"
          className="h-11 w-11 shrink-0 border-white/30 bg-transparent text-white hover:bg-white/10 hover:text-white"
        >
          <ArrowLeft className="h-5 w-5" />
        </Button>
        <div className="min-w-0 flex-1">
          <h1 className="text-xl font-bold leading-tight">Nota de crédito</h1>
          <p className="truncate text-sm text-white/70">Escolhe a fatura a creditar (estorno total)</p>
        </div>
        <Button
          variant="outline" size="icon" onClick={load} disabled={loading}
          title="Atualizar"
          className="h-11 w-11 shrink-0 border-white/30 bg-transparent text-white hover:bg-white/10 hover:text-white"
        >
          <RefreshCw className={`h-5 w-5 ${loading ? 'animate-spin' : ''}`} />
        </Button>
      </header>

      {/* Corpo — lista de faturas */}
      <main className="flex-1 overflow-y-auto bg-background px-5 py-5 text-foreground sm:px-8 sm:py-6">
        {loading ? (
          <div className="flex items-center justify-center py-24">
            <Loader2 className="h-8 w-8 animate-spin text-muted-foreground" />
          </div>
        ) : invoices.length === 0 ? (
          <p className="py-16 text-center text-sm text-muted-foreground">
            Sem faturas recentes para creditar (hoje e ontem).
          </p>
        ) : (
          <div className="mx-auto flex max-w-2xl flex-col gap-2">
            {invoices.map((inv) => (
              <button
                key={inv.id}
                type="button"
                onClick={() => setSelected(inv)}
                className="flex items-center gap-3 rounded-xl border border-border bg-white p-4 text-left transition-all hover:border-primary/40 hover:shadow-sm active:scale-[0.99] touch-manipulation"
              >
                <div className="min-w-0 flex-1">
                  <div className="flex items-center gap-2">
                    <span className="font-semibold text-[#5a1a1a]">{inv.label}</span>
                    <span className="text-xs text-muted-foreground">{inv.number}</span>
                  </div>
                  <div className="mt-0.5 text-xs text-muted-foreground">
                    {inv.date} · {inv.time}{inv.method ? ` · ${inv.method}` : ''}
                  </div>
                </div>
                <span className="shrink-0 font-bold tabular-nums text-foreground">{eur(inv.amount)}</span>
                <ChevronRight className="h-4 w-4 shrink-0 text-muted-foreground" />
              </button>
            ))}
          </div>
        )}
      </main>

      {/* Confirmação */}
      <AlertDialog open={!!selected} onOpenChange={(v) => !v && !submitting && setSelected(null)}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle className="flex items-center gap-2">
              <Undo2 className="h-5 w-5 text-[#5a1a1a]" />
              Emitir nota de crédito?
            </AlertDialogTitle>
            <AlertDialogDescription>
              {selected && (
                <>
                  Vai estornar a fatura <strong>{selected.number}</strong> ({selected.label}) no valor de{' '}
                  <strong>{eur(selected.amount)}</strong>. Isto cria um documento fiscal (NC) no Vendus e
                  imprime o talão na caixa. Esta ação não se desfaz.
                </>
              )}
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel disabled={submitting}>Cancelar</AlertDialogCancel>
            <AlertDialogAction
              onClick={(e) => { e.preventDefault(); emitir(); }}
              disabled={submitting}
              className="bg-[#5a1a1a] hover:bg-[#4a1414]"
            >
              {submitting ? <Loader2 className="h-4 w-4 animate-spin mr-1" /> : null}
              Sim, emitir NC
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  );
};

export default PosCreditNote;
