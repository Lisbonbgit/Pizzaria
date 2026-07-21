import React, { useState, useEffect, useCallback } from 'react';
import {
  Loader2, RefreshCw, Receipt, Printer, Plus, Users, Store, X,
} from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import {
  Dialog, DialogContent, DialogHeader, DialogTitle,
} from '@/components/ui/dialog';
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from '@/components/ui/select';
import {
  AlertDialog, AlertDialogAction, AlertDialogCancel, AlertDialogContent,
  AlertDialogDescription, AlertDialogFooter, AlertDialogHeader, AlertDialogTitle,
} from '@/components/ui/alert-dialog';
import { toast } from 'sonner';
import AdminLayout from '@/components/AdminLayout';
import { tablesAPI, ordersAPI, checkoutAPI, productsAPI } from '@/lib/api';

const eur = (v) => `€ ${Number(v || 0).toFixed(2)}`;
const lineKey = (l) => `${l.order_id}:${l.idx}`;
const lineName = (l) => l.product_name + (l.variation && l.variation.name ? ` (${l.variation.name})` : '');

const AdminOrders = () => {
  const [tables, setTables] = useState([]);
  const [products, setProducts] = useState([]);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);

  // Modal da mesa
  const [openTableNum, setOpenTableNum] = useState(null);
  const [openTableId, setOpenTableId] = useState(null);
  const [openTablePeople, setOpenTablePeople] = useState(1);
  const [tableTitle, setTableTitle] = useState('');
  const [billLines, setBillLines] = useState([]);
  const [selected, setSelected] = useState(new Set());
  const [tableLoading, setTableLoading] = useState(false);

  // Adicionar produto manual
  const [addProductId, setAddProductId] = useState('');
  const [addQty, setAddQty] = useState(1);
  const [adding, setAdding] = useState(false);

  // Fecho
  const [methods, setMethods] = useState([]);
  const [paymentId, setPaymentId] = useState('');
  const [nif, setNif] = useState('');
  const [splitCount, setSplitCount] = useState(1);
  const [cashReceived, setCashReceived] = useState('');
  const [printingConsulta, setPrintingConsulta] = useState(false);
  const [confirmOpen, setConfirmOpen] = useState(false);
  const [closing, setClosing] = useState(false);
  const [freeOpen, setFreeOpen] = useState(false);
  const [freeing, setFreeing] = useState(false);

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
    checkoutAPI.paymentMethods().then((r) => setMethods(r.data)).catch(() => {});
    productsAPI.list().then((r) => setProducts(r.data)).catch(() => {});
    const id = setInterval(() => load(true), 12000);
    return () => clearInterval(id);
  }, [load]);

  const loadBill = useCallback(async (num) => {
    setTableLoading(true);
    try {
      const r = await checkoutAPI.getBill(num);
      setBillLines(r.data.lines || []);
    } catch {
      toast.error('Erro ao carregar a conta da mesa');
    } finally {
      setTableLoading(false);
    }
  }, []);

  const openTable = (t) => {
    if (!t.occupied) return;
    setOpenTableNum(t.number);
    setOpenTableId(t.id);
    setOpenTablePeople(t.people || 1);
    setTableTitle(t.name || `Mesa ${t.number}`);
    setPaymentId('');
    setNif('');
    setSplitCount(1);
    setCashReceived('');
    setAddProductId('');
    setAddQty(1);
    setSelected(new Set());
    setBillLines([]);
    loadBill(t.number);
  };

  const closeModal = () => { setOpenTableNum(null); setBillLines([]); setSelected(new Set()); };

  const toggle = (l) => {
    const k = lineKey(l);
    setSelected((prev) => {
      const n = new Set(prev);
      if (n.has(k)) n.delete(k); else n.add(k);
      return n;
    });
  };

  const printConsulta = async () => {
    setPrintingConsulta(true);
    try {
      await checkoutAPI.printConsulta(openTableNum);
      toast.success('Consulta enviada para impressão');
    } catch (e) {
      toast.error(e.response?.data?.detail || 'Erro ao imprimir a consulta');
    } finally {
      setPrintingConsulta(false);
    }
  };

  const reprintKitchen = async () => {
    const ids = [...new Set(billLines.map((l) => l.order_id))];
    try {
      await Promise.all(ids.map((id) => ordersAPI.reprint(id, [])));
      toast.success('Reimpressão enviada para a cozinha');
    } catch { toast.error('Erro ao reimprimir'); }
  };

  const addProduct = async () => {
    const p = products.find((x) => x.id === addProductId);
    if (!p) { toast.error('Escolhe um produto'); return; }
    const qty = Math.max(1, Number(addQty) || 1);
    setAdding(true);
    try {
      const price = Number(p.base_price) || 0;
      await ordersAPI.create({
        table_id: openTableId,
        table_number: openTableNum,
        source: 'manual',
        items: [{
          product_id: p.id, product_name: p.name, quantity: qty,
          unit_price: price, total_price: +(price * qty).toFixed(2),
        }],
        total: +(price * qty).toFixed(2),
      });
      setAddProductId('');
      setAddQty(1);
      toast.success(`${qty}× ${p.name} adicionado à mesa`);
      loadBill(openTableNum);
      load(true);
    } catch {
      toast.error('Erro ao adicionar o produto');
    } finally {
      setAdding(false);
    }
  };

  // ---- valores derivados ----
  const selectedLines = billLines.filter((l) => selected.has(lineKey(l)));
  const rightLines = billLines.filter((l) => !selected.has(lineKey(l)));
  const hasSelection = selectedLines.length > 0;
  const fullTotal = billLines.reduce((s, l) => s + (l.total_price || 0), 0);
  const selectedTotal = selectedLines.reduce((s, l) => s + (l.total_price || 0), 0);
  const invoiceTotal = hasSelection ? selectedTotal : fullTotal;
  const splitActive = !hasSelection && splitCount > 1;
  const perPerson = splitActive ? invoiceTotal / splitCount : invoiceTotal;
  const selectedMethod = methods.find((m) => String(m.id) === String(paymentId));
  const isCash = !!selectedMethod && /dinheiro|numer|cash/i.test(selectedMethod.title || '');
  const received = Number(String(cashReceived).replace(',', '.')) || 0;
  const change = Math.round((received - invoiceTotal) * 100) / 100;

  const doClose = async () => {
    setConfirmOpen(false);
    setClosing(true);
    try {
      const body = { payment_method_id: Number(paymentId) };
      if (hasSelection) {
        body.items = selectedLines.map((l) => ({ order_id: l.order_id, idx: l.idx }));
      } else {
        body.nif = nif.trim() || null;
        body.split_count = splitActive ? splitCount : 1;
      }
      const r = await checkoutAPI.closeTable(openTableNum, body);
      const nInv = r.data.invoices || 1;
      toast.success(nInv > 1 ? `${nInv} faturas emitidas` : `Fatura ${r.data.vendus.number} emitida`);
      if (r.data.table_free) {
        closeModal();
        load(true);
      } else {
        // separação parcial: a mesa continua aberta com o resto
        setSelected(new Set());
        setCashReceived('');
        setSplitCount(1);
        await loadBill(openTableNum);
        load(true);
        toast.info(`Falta faturar ${eur(r.data.remaining_total)} nesta mesa`);
      }
    } catch (e) {
      toast.error(e.response?.data?.detail || 'Erro ao faturar');
    } finally {
      setClosing(false);
    }
  };

  const doFree = async () => {
    setFreeOpen(false);
    setFreeing(true);
    try {
      const r = await checkoutAPI.freeTable(openTableNum);
      toast.success(r.data.cancelled_orders > 0
        ? `Mesa libertada — ${r.data.cancelled_orders} pedido(s) cancelado(s)`
        : 'Mesa libertada');
      closeModal();
      load(true);
    } catch (e) {
      toast.error(e.response?.data?.detail || 'Erro ao libertar a mesa');
    } finally {
      setFreeing(false);
    }
  };

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

      {/* Checkout tipo POS — 2 painéis */}
      <Dialog open={openTableNum != null} onOpenChange={(v) => !v && closeModal()}>
        <DialogContent className="max-w-5xl w-[96vw] h-[90vh] p-0 gap-0 overflow-hidden">
          <div className="flex flex-col md:flex-row h-full min-h-0">

            {/* ESQUERDA — a faturar + pagamento */}
            <div className="flex-1 flex flex-col min-h-0 bg-background">
              <DialogHeader className="px-6 py-4 border-b text-left">
                <DialogTitle className="font-heading text-xl flex items-center justify-between pr-8">
                  <span>{tableTitle}</span>
                  <span className="text-xs font-normal text-muted-foreground uppercase tracking-wide">
                    {hasSelection ? 'A separar itens' : 'Conta toda'}
                  </span>
                </DialogTitle>
              </DialogHeader>

              <div className="flex-1 overflow-y-auto px-6 py-4 space-y-4">
                <div className="flex items-end justify-between">
                  <span className="text-muted-foreground">{hasSelection ? 'A faturar (selecionados)' : 'Total'}</span>
                  <span className="font-heading text-4xl font-bold text-primary tabular-nums">{eur(invoiceTotal)}</span>
                </div>

                {/* Itens selecionados (separação) */}
                {hasSelection && (
                  <div className="rounded-lg border divide-y">
                    {selectedLines.map((l) => (
                      <button key={lineKey(l)} onClick={() => toggle(l)}
                        className="w-full flex items-center justify-between gap-2 px-3 py-2 text-sm hover:bg-muted/50 text-left">
                        <span className="truncate">{l.quantity}× {lineName(l)}</span>
                        <span className="flex items-center gap-2 shrink-0">
                          <span className="tabular-nums">{eur(l.total_price)}</span>
                          <X className="h-4 w-4 text-muted-foreground" />
                        </span>
                      </button>
                    ))}
                    <p className="px-3 py-1.5 text-xs text-muted-foreground">Toca num item para o devolver à mesa.</p>
                  </div>
                )}

                {/* Dividir — só quando é a conta toda */}
                {!hasSelection && (
                  <div className="flex items-center justify-between gap-3">
                    <span className="text-sm">Dividir por</span>
                    <div className="flex items-center gap-2">
                      <Button variant="outline" size="icon" className="h-8 w-8"
                        onClick={() => setSplitCount((n) => Math.max(1, n - 1))} disabled={splitCount <= 1}>−</Button>
                      <span className="w-8 text-center font-semibold tabular-nums">{splitCount}</span>
                      <Button variant="outline" size="icon" className="h-8 w-8"
                        onClick={() => setSplitCount((n) => n + 1)}>+</Button>
                      <span className="text-sm text-muted-foreground">pessoa{splitCount > 1 ? 's' : ''}</span>
                    </div>
                  </div>
                )}
                {splitActive && (
                  <div className="flex items-center justify-between text-sm bg-primary/[0.06] rounded-lg px-3 py-2">
                    <span>Cada pessoa paga</span>
                    <span className="font-semibold text-primary tabular-nums">{eur(perPerson)}</span>
                  </div>
                )}

                {/* Pagamento + NIF */}
                <div className="space-y-2">
                  <Select value={paymentId} onValueChange={setPaymentId}>
                    <SelectTrigger><SelectValue placeholder="Método de pagamento" /></SelectTrigger>
                    <SelectContent>
                      {methods.map((m) => <SelectItem key={m.id} value={String(m.id)}>{m.title}</SelectItem>)}
                    </SelectContent>
                  </Select>
                  {!hasSelection && (
                    <Input placeholder="NIF (opcional)" value={nif} onChange={(e) => setNif(e.target.value)} />
                  )}
                </div>

                {/* Troco (dinheiro) */}
                {isCash && (
                  <div className="rounded-lg border bg-muted/20 px-3 py-3 space-y-2">
                    <div className="flex items-center justify-between gap-3">
                      <span className="text-sm">Com quanto vai pagar?</span>
                      <div className="relative w-32">
                        <span className="absolute left-3 top-1/2 -translate-y-1/2 text-muted-foreground">€</span>
                        <Input type="number" inputMode="decimal" min={0} step="0.5" className="pl-7 text-right"
                          placeholder="0.00" value={cashReceived} onChange={(e) => setCashReceived(e.target.value)} />
                      </div>
                    </div>
                    {received > 0 && (
                      <div className={`flex items-center justify-between text-sm font-semibold ${change >= 0 ? 'text-green-700' : 'text-destructive'}`}>
                        <span>{change >= 0 ? 'Troco' : 'Em falta'}</span>
                        <span className="tabular-nums">{eur(Math.abs(change))}</span>
                      </div>
                    )}
                  </div>
                )}
              </div>

              {/* Rodapé — Emitir */}
              <div className="px-6 py-4 border-t">
                <Button
                  onClick={() => {
                    if (!billLines.length) { toast.error('Conta vazia'); return; }
                    if (!paymentId) { toast.error('Escolhe o método de pagamento'); return; }
                    setConfirmOpen(true);
                  }}
                  disabled={closing || !billLines.length}
                  className="w-full h-14 text-base font-semibold bg-[#5a1a1a] hover:bg-[#4a1414]">
                  {closing ? <Loader2 className="h-5 w-5 animate-spin mr-2" /> : <Receipt className="h-5 w-5 mr-2" />}
                  Emitir Documento
                </Button>
              </div>
            </div>

            {/* DIREITA — itens da mesa (toca para separar) */}
            <div className="w-full md:w-[42%] md:max-w-md flex flex-col min-h-0 bg-[#3a1414] text-white">
              <div className="px-4 py-3 grid grid-cols-[1fr_2.5rem_5rem] gap-2 text-[11px] uppercase tracking-wide text-white/50 border-b border-white/10">
                <span>Produto</span><span className="text-center">Qtd</span><span className="text-right">Preço</span>
              </div>
              <div className="flex-1 overflow-y-auto">
                {tableLoading ? (
                  <div className="flex items-center gap-2 text-white/70 py-8 justify-center text-sm">
                    <Loader2 className="h-5 w-5 animate-spin" /> A carregar…
                  </div>
                ) : rightLines.length === 0 ? (
                  <p className="text-center text-white/50 py-8 text-sm">
                    {hasSelection ? 'Todos os itens estão a ser faturados.' : 'Conta vazia.'}
                  </p>
                ) : (
                  rightLines.map((l) => (
                    <button key={lineKey(l)} onClick={() => toggle(l)}
                      className="w-full grid grid-cols-[1fr_2.5rem_5rem] gap-2 items-center px-4 py-3 border-b border-white/5 hover:bg-white/10 text-left transition-colors">
                      <span className="truncate flex items-center gap-1.5">
                        {lineName(l)}
                        {l.source === 'manual' && <Store className="h-3 w-3 text-amber-300 shrink-0" />}
                      </span>
                      <span className="text-center tabular-nums">{l.quantity}</span>
                      <span className="text-right tabular-nums">{eur(l.total_price)}</span>
                    </button>
                  ))
                )}
              </div>

              {/* Rodapé direito — ações */}
              <div className="border-t border-white/10 p-3 space-y-2">
                <div className="flex gap-2">
                  <Select value={addProductId} onValueChange={setAddProductId}>
                    <SelectTrigger className="flex-1 bg-white/10 border-white/20 text-white h-9"><SelectValue placeholder="Adicionar produto…" /></SelectTrigger>
                    <SelectContent>
                      {products.filter((p) => p.available !== false).map((p) => (
                        <SelectItem key={p.id} value={p.id}>{p.name} — {eur(p.base_price)}</SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                  <Input type="number" min={1} value={addQty} onChange={(e) => setAddQty(e.target.value)}
                    className="w-14 bg-white/10 border-white/20 text-white h-9" aria-label="Quantidade" />
                  <Button variant="secondary" size="icon" className="h-9 w-9 shrink-0" onClick={addProduct} disabled={adding || !addProductId}>
                    {adding ? <Loader2 className="h-4 w-4 animate-spin" /> : <Plus className="h-4 w-4" />}
                  </Button>
                </div>
                <div className="flex items-center justify-between text-sm text-white/70 px-1">
                  <span className="flex items-center gap-1"><Users className="h-4 w-4" />{openTablePeople} pessoa{openTablePeople !== 1 ? 's' : ''}</span>
                  <span className="tabular-nums">Total {eur(fullTotal)}</span>
                </div>
                <div className="grid grid-cols-2 gap-2">
                  <Button variant="outline" className="bg-transparent border-white/25 text-white hover:bg-white/10 hover:text-white"
                    onClick={printConsulta} disabled={printingConsulta}>
                    {printingConsulta ? <Loader2 className="h-4 w-4 animate-spin mr-1" /> : <Printer className="h-4 w-4 mr-1" />}
                    Consulta
                  </Button>
                  <Button variant="outline" className="bg-transparent border-white/25 text-white hover:bg-white/10 hover:text-white"
                    onClick={reprintKitchen} disabled={!billLines.length}>
                    <Printer className="h-4 w-4 mr-1" /> Cozinha
                  </Button>
                </div>
                <Button variant="ghost" className="w-full h-8 text-xs text-white/60 hover:bg-white/10 hover:text-white"
                  onClick={() => setFreeOpen(true)} disabled={freeing}>
                  {freeing ? <Loader2 className="h-3.5 w-3.5 animate-spin mr-1" /> : <X className="h-3.5 w-3.5 mr-1" />}
                  Libertar mesa (sem faturar)
                </Button>
              </div>
            </div>
          </div>
        </DialogContent>
      </Dialog>

      {/* Confirmação */}
      <AlertDialog open={confirmOpen} onOpenChange={setConfirmOpen}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Emitir documento — {tableTitle}?</AlertDialogTitle>
            <AlertDialogDescription>
              {hasSelection
                ? `Vai faturar ${selectedLines.length} item(ns) selecionado(s) (${eur(invoiceTotal)}). O resto da conta fica na mesa.`
                : splitActive
                  ? `Vai emitir ${splitCount} faturas simplificadas de ${eur(perPerson)} cada e libertar a mesa.`
                  : `Vai emitir a fatura simplificada (${eur(invoiceTotal)}) e libertar a mesa.`}
              {isCash && received > 0 && change >= 0 ? ` Troco a devolver: ${eur(change)}.` : ''} Esta ação não se desfaz.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Cancelar</AlertDialogCancel>
            <AlertDialogAction onClick={doClose} className="bg-[#5a1a1a] hover:bg-[#4a1414]">
              Sim, emitir
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>

      {/* Confirmação — libertar mesa sem faturar */}
      <AlertDialog open={freeOpen} onOpenChange={setFreeOpen}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Libertar {tableTitle} sem faturar?</AlertDialogTitle>
            <AlertDialogDescription>
              {billLines.length > 0
                ? `Esta mesa tem ${billLines.length} item(ns) por faturar (${eur(fullTotal)}). Libertar vai CANCELAR esses pedidos SEM emitir fatura — usa só se ninguém consumiu (ex.: leram o QR por engano ou o cliente saiu).`
                : 'A mesa não tem pedidos — vai apenas fechar a sessão e ficar livre.'}
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Cancelar</AlertDialogCancel>
            <AlertDialogAction onClick={doFree} className="bg-destructive hover:bg-destructive/90">
              Sim, libertar
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </AdminLayout>
  );
};

export default AdminOrders;
