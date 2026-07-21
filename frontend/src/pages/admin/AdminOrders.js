import React, { useState, useEffect, useCallback } from 'react';
import {
  Loader2, RefreshCw, Receipt, Printer, Clock, Plus,
} from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Badge } from '@/components/ui/badge';
import {
  Dialog, DialogContent, DialogHeader, DialogTitle,
} from '@/components/ui/dialog';
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from '@/components/ui/select';
import { toast } from 'sonner';
import AdminLayout from '@/components/AdminLayout';
import { tablesAPI, ordersAPI, checkoutAPI, productsAPI } from '@/lib/api';

const eur = (v) => `€ ${Number(v || 0).toFixed(2)}`;

const STATUS = {
  received: { label: 'Recebido', cls: 'bg-blue-100 text-blue-800' },
  preparing: { label: 'Em preparação', cls: 'bg-amber-100 text-amber-800' },
  ready: { label: 'Pronto', cls: 'bg-green-100 text-green-800' },
  delivered: { label: 'Entregue', cls: 'bg-gray-100 text-gray-700' },
  cancelled: { label: 'Cancelado', cls: 'bg-red-100 text-red-700' },
};
const STATUS_OPTS = Object.entries(STATUS)
  .filter(([k]) => k !== 'cancelled')
  .map(([value, v]) => ({ value, label: v.label }));

const relTime = (iso) => {
  if (!iso) return '';
  const mins = Math.max(0, Math.floor((Date.now() - new Date(iso).getTime()) / 60000));
  if (mins < 1) return 'agora mesmo';
  if (mins < 60) return `há ${mins} min`;
  const h = Math.floor(mins / 60);
  return `há ${h}h${String(mins % 60).padStart(2, '0')}`;
};

const AdminOrders = () => {
  const [tables, setTables] = useState([]);
  const [products, setProducts] = useState([]);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);

  // Modal da mesa
  const [openTableNum, setOpenTableNum] = useState(null);
  const [openTableId, setOpenTableId] = useState(null);
  const [tableTitle, setTableTitle] = useState('');
  const [tableOrders, setTableOrders] = useState([]);
  const [tableLoading, setTableLoading] = useState(false);

  // Adicionar produto manual
  const [addProductId, setAddProductId] = useState('');
  const [addQty, setAddQty] = useState(1);
  const [adding, setAdding] = useState(false);

  // Fecho
  const [methods, setMethods] = useState([]);
  const [paymentId, setPaymentId] = useState('');
  const [nif, setNif] = useState('');
  const [closing, setClosing] = useState(false);

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

  const loadTableOrders = useCallback(async (num) => {
    setTableLoading(true);
    try {
      const r = await ordersAPI.list({ table_number: num });
      setTableOrders((r.data || []).filter((o) => !o.paid && o.status !== 'cancelled'));
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
    setTableTitle(t.name || `Mesa ${t.number}`);
    setPaymentId('');
    setNif('');
    setAddProductId('');
    setAddQty(1);
    loadTableOrders(t.number);
  };

  const closeModal = () => { setOpenTableNum(null); setTableOrders([]); };

  const changeStatus = async (orderId, status) => {
    try {
      await ordersAPI.updateStatus(orderId, status);
      setTableOrders((prev) => prev.map((o) => (o.id === orderId ? { ...o, status } : o)));
    } catch {
      toast.error('Erro ao atualizar o estado');
    }
  };

  const reprint = async (orderId) => {
    try { await ordersAPI.reprint(orderId, []); toast.success('Reimpressão agendada'); }
    catch { toast.error('Erro ao reimprimir'); }
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
        items: [{
          product_id: p.id, product_name: p.name, quantity: qty,
          unit_price: price, total_price: +(price * qty).toFixed(2),
        }],
        total: +(price * qty).toFixed(2),
      });
      setAddProductId('');
      setAddQty(1);
      toast.success(`${qty}× ${p.name} adicionado à mesa`);
      loadTableOrders(openTableNum);
      load(true);
    } catch {
      toast.error('Erro ao adicionar o produto');
    } finally {
      setAdding(false);
    }
  };

  const tableTotal = tableOrders.reduce((s, o) => s + (o.total || 0), 0);

  const handleClose = async () => {
    if (!paymentId) { toast.error('Escolhe o método de pagamento'); return; }
    setClosing(true);
    try {
      const r = await checkoutAPI.closeTable(openTableNum, {
        payment_method_id: Number(paymentId), nif: nif.trim() || null,
      });
      toast.success(`Mesa fechada — ${r.data.vendus.number}`);
      closeModal();
      load(true);
    } catch (e) {
      toast.error(e.response?.data?.detail || 'Erro ao fechar a mesa');
    } finally {
      setClosing(false);
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
                      <span>{t.open_orders} pedido{t.open_orders > 1 ? 's' : ''}</span>
                      {t.last_activity && <><span>·</span><Clock className="h-3 w-3" /><span>{relTime(t.last_activity)}</span></>}
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

      {/* Popup grande da mesa */}
      <Dialog open={openTableNum != null} onOpenChange={(v) => !v && closeModal()}>
        <DialogContent className="max-w-2xl max-h-[92vh] overflow-y-auto p-0 gap-0">
          <DialogHeader className="px-6 py-4 border-b bg-primary/[0.04]">
            <DialogTitle className="font-heading text-2xl flex items-center justify-between pr-8">
              <span>{tableTitle}</span>
              <span className="text-primary tabular-nums">{eur(tableTotal)}</span>
            </DialogTitle>
          </DialogHeader>

          {/* Adicionar produto manualmente */}
          <div className="px-6 py-3 border-b bg-muted/20 flex flex-col sm:flex-row gap-2">
            <Select value={addProductId} onValueChange={setAddProductId}>
              <SelectTrigger className="flex-1"><SelectValue placeholder="Adicionar produto à mesa..." /></SelectTrigger>
              <SelectContent>
                {products.filter((p) => p.available !== false).map((p) => (
                  <SelectItem key={p.id} value={p.id}>{p.name} — {eur(p.base_price)}</SelectItem>
                ))}
              </SelectContent>
            </Select>
            <Input type="number" min={1} value={addQty}
              onChange={(e) => setAddQty(e.target.value)} className="w-20" aria-label="Quantidade" />
            <Button variant="outline" onClick={addProduct} disabled={adding || !addProductId}>
              {adding ? <Loader2 className="h-4 w-4 animate-spin mr-1" /> : <Plus className="h-4 w-4 mr-1" />}
              Adicionar
            </Button>
          </div>

          <div className="px-6 py-4 space-y-4">
            {tableLoading ? (
              <div className="flex items-center gap-2 text-muted-foreground py-8 justify-center">
                <Loader2 className="h-5 w-5 animate-spin" /> A carregar a conta...
              </div>
            ) : tableOrders.length === 0 ? (
              <p className="text-center text-muted-foreground py-8">Sem pedidos em aberto.</p>
            ) : (
              tableOrders.map((o) => (
                <div key={o.id} className="rounded-lg border">
                  <div className="flex items-center justify-between gap-3 px-4 py-2.5 border-b bg-muted/30">
                    <div className="flex items-center gap-2 flex-wrap">
                      <span className="font-heading font-bold">#{o.order_number}</span>
                      <Badge className={STATUS[o.status]?.cls || ''} variant="secondary">
                        {STATUS[o.status]?.label || o.status}
                      </Badge>
                      <span className="text-xs text-muted-foreground flex items-center gap-1">
                        <Clock className="h-3 w-3" />{relTime(o.created_at)}
                      </span>
                    </div>
                    <span className="font-semibold tabular-nums">{eur(o.total)}</span>
                  </div>
                  <div className="px-4 py-2 space-y-1">
                    {o.items.map((it, i) => (
                      <div key={i} className="flex justify-between text-sm">
                        <span>{it.quantity}× {it.product_name}
                          {it.notes && <span className="text-muted-foreground italic"> — {it.notes}</span>}
                        </span>
                        <span className="tabular-nums text-muted-foreground">{eur(it.total_price)}</span>
                      </div>
                    ))}
                  </div>
                  <div className="flex items-center gap-2 px-4 py-2 border-t">
                    <Select value={o.status} onValueChange={(v) => changeStatus(o.id, v)}>
                      <SelectTrigger className="h-8 w-40 text-xs"><SelectValue /></SelectTrigger>
                      <SelectContent>
                        {STATUS_OPTS.map((s) => <SelectItem key={s.value} value={s.value}>{s.label}</SelectItem>)}
                      </SelectContent>
                    </Select>
                    <Button variant="ghost" size="sm" className="h-8" onClick={() => reprint(o.id)}>
                      <Printer className="h-3.5 w-3.5 mr-1" /> Reimprimir
                    </Button>
                  </div>
                </div>
              ))
            )}
          </div>

          {/* Fecho da mesa */}
          {tableOrders.length > 0 && (
            <div className="px-6 py-4 border-t bg-muted/20 space-y-3">
              <div className="flex items-center justify-between">
                <span className="font-heading text-lg font-bold">Total</span>
                <span className="font-heading text-2xl font-bold text-primary tabular-nums">{eur(tableTotal)}</span>
              </div>
              <div className="flex flex-col sm:flex-row gap-2">
                <Select value={paymentId} onValueChange={setPaymentId}>
                  <SelectTrigger className="sm:w-44"><SelectValue placeholder="Pagamento" /></SelectTrigger>
                  <SelectContent>
                    {methods.map((m) => <SelectItem key={m.id} value={String(m.id)}>{m.title}</SelectItem>)}
                  </SelectContent>
                </Select>
                <Input className="sm:w-40" placeholder="NIF (opcional)" value={nif} onChange={(e) => setNif(e.target.value)} />
                <Button onClick={handleClose} disabled={closing || !paymentId}
                  className="flex-1 bg-[#5a1a1a] hover:bg-[#4a1414]">
                  {closing ? <Loader2 className="h-4 w-4 animate-spin mr-2" /> : <Receipt className="h-4 w-4 mr-2" />}
                  Fechar mesa e faturar no Vendus
                </Button>
              </div>
            </div>
          )}
        </DialogContent>
      </Dialog>
    </AdminLayout>
  );
};

export default AdminOrders;
