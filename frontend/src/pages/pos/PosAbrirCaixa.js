import React, { useCallback, useState } from 'react';
import { Lock, Loader2, Vault } from 'lucide-react';
import { toast } from 'sonner';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { posAPI } from '@/lib/api';

const eur = (v) => `€ ${Number(v || 0).toFixed(2)}`;

// Formata um ISO (UTC) para "dd/mm HH:MM" em hora de Lisboa — usado só na
// linha "Último fecho" abaixo.
const formatDataHora = (iso) => {
  if (!iso) return '';
  try {
    const partes = new Date(iso).toLocaleString('pt-PT', {
      day: '2-digit',
      month: '2-digit',
      hour: '2-digit',
      minute: '2-digit',
      timeZone: 'Europe/Lisbon',
    });
    return partes.replace(',', '');
  } catch {
    return '';
  }
};

// Ecrã "Caixa Fechada": pede o montante de abertura (fundo de troco) e abre
// uma nova sessão de caixa. Espelha a 1ª foto que o dono enviou (ícone +
// montante + botão grande). Em sucesso delega em `onAberta` — o PosApp
// re-resolve a caixa (refreshCaixa) e troca para a Home (Task 5).
//
// `lastClose` (Fase 4b, opcional) — resumo do fecho anterior
// ({closed_by_name, closed_at, counted_amount}), que o PosApp já traz de
// `posAPI.cashCurrent()` (mesma chamada que decidiu mostrar este ecrã); `null`
// se nunca houve nenhum fecho — nesse caso não se mostra nada.
const PosAbrirCaixa = ({ operator, onAberta, lastClose }) => {
  const [montante, setMontante] = useState('0');
  const [submitting, setSubmitting] = useState(false);
  const [drawerSubmitting, setDrawerSubmitting] = useState(false);

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

  const abrir = useCallback(async () => {
    const valor = Number(montante);
    if (Number.isNaN(valor) || valor < 0) {
      toast.error('Montante inválido');
      return;
    }
    setSubmitting(true);
    try {
      await posAPI.cashOpen(valor);
      onAberta();
    } catch (err) {
      console.error('Erro ao abrir a caixa:', err);
      toast.error(err.response?.data?.detail || 'Não foi possível abrir a caixa');
    } finally {
      setSubmitting(false);
    }
  }, [montante, onAberta]);

  return (
    <div className="min-h-screen flex flex-col items-center justify-center bg-[#5a1a1a] p-6 text-white">
      <Lock className="h-14 w-14 text-white/70 mb-4" />
      <h1 className="text-2xl font-bold mb-1">Caixa Fechada</h1>
      <div className="mb-8">
        {operator?.name && <p className="text-white/70 mb-1">Operador: {operator.name}</p>}
        {lastClose && (
          <p className="text-white/50 text-sm">
            Último fecho: {lastClose.closed_by_name || '—'} · {eur(lastClose.counted_amount)} ·{' '}
            {formatDataHora(lastClose.closed_at) || '—'}
          </p>
        )}
      </div>

      <div className="w-full max-w-xs space-y-2 mb-8">
        <Label htmlFor="montante-abertura" className="text-white/80">
          Montante de abertura
        </Label>
        <div className="relative">
          <span className="absolute left-3 top-1/2 -translate-y-1/2 text-white/60">€</span>
          <Input
            id="montante-abertura"
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

      <Button
        onClick={abrir}
        disabled={submitting}
        className="w-full max-w-xs h-14 text-lg font-semibold bg-white text-[#5a1a1a] hover:bg-white/90"
      >
        {submitting ? (
          <>
            <Loader2 className="h-5 w-5 animate-spin" />
            A abrir...
          </>
        ) : (
          'Abrir Caixa'
        )}
      </Button>

      <Button
        variant="outline"
        onClick={abrirGaveta}
        disabled={drawerSubmitting}
        className="w-full max-w-xs mt-3 h-12 border-white/30 bg-transparent text-white hover:bg-white/10 hover:text-white"
      >
        <Vault className="h-4 w-4 mr-1.5" />
        {drawerSubmitting ? 'A abrir...' : 'Abrir Gaveta'}
      </Button>
    </div>
  );
};

export default PosAbrirCaixa;
