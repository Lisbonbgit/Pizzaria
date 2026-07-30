import React, { useCallback, useEffect, useState } from 'react';
import {
  ArrowLeft, CheckCircle2, Loader2, Minus, Plus, Printer, Receipt, Pencil,
} from 'lucide-react';
import { toast } from 'sonner';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from '@/components/ui/select';
import {
  Dialog, DialogContent, DialogHeader, DialogTitle,
} from '@/components/ui/dialog';
import { posCounter, posCheckout } from '@/lib/api';

const eur = (v) => `€ ${Number(v || 0).toFixed(2)}`;

// Líquido de uma linha do carrinho (bruto − desconto; € tem precedência sobre %).
const lineGross = (c) => Math.round((Number(c.unitPrice) || 0) * c.qty * 100) / 100;
const lineNet = (c) => {
  const gross = lineGross(c);
  const dv = Number(String(c.discVal).replace(',', '.')) || 0;
  const net = c.discKind === 'eur' ? gross - dv : gross * (1 - Math.min(100, dv) / 100);
  return Math.max(0, Math.round(net * 100) / 100);
};

// Ecrã cheio do Balcão (Fase 2, Task 4) — venda sem mesa. Montado pelo
// PosApp por cima da Home (mesmo mecanismo do PosFecharCaixa: um booleano
// substitui a Home enquanto ativo), para que o fluxo ocupe o ecrã todo tal
// como o resto do POS.
//
// Fluxo, tudo no mesmo ecrã (2 painéis: catálogo à esquerda, carrinho/fatura
// à direita — as mesmas cores do TableCheckout partilhado):
//   1. Escolher produtos (agrupados por categoria) → carrinho com +/-.
//   2. "Imprimir Pedido" → posCounter.createOrder (cozinha) — a partir daqui
//      o carrinho fica bloqueado (o pedido já foi enviado; simplifica não ter
//      de reconciliar edições pós-impressão com a cozinha).
//   3. Faturação → posCounter.checkout (FS + pos_sales + recibo).
//   4. "Nova Venda" reinicia tudo, sem sair do balcão (vários clientes
//      seguidos); o botão Voltar leva à Home (Task 5/6 mesas).
//
// Props:
//   onClose — volta à Home. Desligado enquanto o pedido já foi impresso mas
//             ainda não foi faturado (evita abandonar um pedido na cozinha
//             sem documento fiscal emitido).
const PosBalcao = ({ onClose }) => {
  const [products, setProducts] = useState([]);
  const [categories, setCategories] = useState([]);
  const [methods, setMethods] = useState([]);
  const [loadingCatalog, setLoadingCatalog] = useState(true);

  // Carrinho: [{id, name, qty, unitPrice, tax, taxTouched, discKind, discVal}]
  const [cart, setCart] = useState([]);
  const [selectedCat, setSelectedCat] = useState(null);

  // Diálogo do produto (editar qtd/preço/IVA/desconto de uma linha do carrinho,
  // antes de "Imprimir Pedido").
  const [editIdx, setEditIdx] = useState(null);
  const [edQty, setEdQty] = useState('1');
  const [edPrice, setEdPrice] = useState('');
  const [edTax, setEdTax] = useState('NOR');
  const [edTaxTouched, setEdTaxTouched] = useState(false);
  const [edDiscKind, setEdDiscKind] = useState('pct'); // 'pct' | 'eur'
  const [edDiscVal, setEdDiscVal] = useState('');

  const [printing, setPrinting] = useState(false);
  const [orderId, setOrderId] = useState(null);
  const [orderNumber, setOrderNumber] = useState(null);
  const [orderTotal, setOrderTotal] = useState(null);

  const [paymentId, setPaymentId] = useState('');
  const [nif, setNif] = useState('');
  const [cashReceived, setCashReceived] = useState('');
  const [checkingOut, setCheckingOut] = useState(false);
  const [cancelling, setCancelling] = useState(false);
  const [docNumber, setDocNumber] = useState(null);

  // Catálogo + métodos de pagamento — uma vez, no arranque.
  useEffect(() => {
    Promise.all([
      posCounter.products(),
      posCounter.categories(),
      posCheckout.paymentMethods(),
    ])
      .then(([p, c, m]) => {
        setProducts(p.data || []);
        setCategories(c.data || []);
        setMethods(m.data || []);
      })
      .catch((err) => {
        console.error('Erro ao carregar o catálogo do balcão:', err);
        toast.error('Erro ao carregar produtos/categorias');
      })
      .finally(() => setLoadingCatalog(false));
  }, []);

  const printed = orderId != null;

  const addToCart = useCallback((p) => {
    if (printed) return;
    setCart((prev) => {
      const idx = prev.findIndex((c) => c.id === p.id);
      if (idx >= 0) {
        const next = [...prev];
        next[idx] = { ...next[idx], qty: next[idx].qty + 1 };
        return next;
      }
      return [...prev, {
        id: p.id, name: p.name, qty: 1,
        unitPrice: Number(p.base_price) || 0,
        tax: p.vendus_tax_id === 'INT' ? 'INT' : 'NOR',
        taxTouched: false, discKind: 'pct', discVal: '',
      }];
    });
  }, [printed]);

  const changeQty = useCallback((id, delta) => {
    if (printed) return;
    setCart((prev) => prev
      .map((c) => (c.id === id ? { ...c, qty: c.qty + delta } : c))
      .filter((c) => c.qty > 0));
  }, [printed]);

  const cartTotal = Math.round(cart.reduce((s, c) => s + lineNet(c), 0) * 100) / 100;
  const total = printed ? (orderTotal ?? cartTotal) : cartTotal;

  // Abre o diálogo do produto para a linha `idx` do carrinho (só antes de imprimir).
  const openEdit = (idx) => {
    const c = cart[idx];
    if (!c || printed) return;
    setEdQty(String(c.qty));
    setEdPrice(String(c.unitPrice));
    setEdTax(c.tax);
    setEdTaxTouched(false);
    setEdDiscKind(c.discKind || 'pct');
    setEdDiscVal(c.discVal || '');
    setEditIdx(idx);
  };

  const saveEdit = () => {
    const q = Math.max(1, parseInt(edQty, 10) || 1);
    const price = Math.max(0, Number(String(edPrice).replace(',', '.')) || 0);
    setCart((prev) => prev.map((c, i) => (i === editIdx ? {
      ...c, qty: q, unitPrice: price,
      tax: edTax, taxTouched: c.taxTouched || edTaxTouched,
      discKind: edDiscKind, discVal: edDiscVal,
    } : c)));
    setEditIdx(null);
  };

  // Subtotal previsto no diálogo (bruto − desconto).
  const edSubtotal = (() => {
    const q = Math.max(1, parseInt(edQty, 10) || 1);
    const price = Math.max(0, Number(String(edPrice).replace(',', '.')) || 0);
    const dv = Math.max(0, Number(String(edDiscVal).replace(',', '.')) || 0);
    const gross = Math.round(price * q * 100) / 100;
    const net = edDiscKind === 'eur' ? gross - dv : gross * (1 - Math.min(100, dv) / 100);
    return Math.max(0, Math.round(net * 100) / 100);
  })();

  const imprimirPedido = async () => {
    if (!cart.length) return;
    setPrinting(true);
    try {
      const items = cart.map((c) => {
        const it = { product_id: c.id, quantity: c.qty, unit_price: c.unitPrice };
        // IVA só vai se o staff o mudou (senão o backend usa o do produto).
        if (c.taxTouched) it.vendus_tax_id = c.tax;
        const dv = Number(String(c.discVal).replace(',', '.')) || 0;
        if (dv > 0) {
          if (c.discKind === 'eur') it.discount_amount = dv;
          else it.discount_pct = dv;
        }
        return it;
      });
      const r = await posCounter.createOrder(items);
      setOrderId(r.data.order_id);
      setOrderNumber(r.data.order_number);
      setOrderTotal(r.data.total);
      toast.success('Pedido enviado para a cozinha');
    } catch (err) {
      console.error('Erro ao criar o pedido de balcão:', err);
      toast.error(err.response?.data?.detail || 'Erro ao enviar o pedido');
    } finally {
      setPrinting(false);
    }
  };

  const selectedMethod = methods.find((m) => String(m.id) === String(paymentId));
  const isCash = !!selectedMethod && /dinheiro|numer|cash/i.test(selectedMethod.title || '');
  const received = Number(String(cashReceived).replace(',', '.')) || 0;
  const troco = Math.round((received - total) * 100) / 100;

  const emitirDocumento = async () => {
    if (!orderId || !paymentId) return;
    setCheckingOut(true);
    try {
      const r = await posCounter.checkout(orderId, Number(paymentId), nif.trim() || undefined);
      setDocNumber(r.data.doc_number);
      toast.success('Fatura emitida');
    } catch (err) {
      console.error('Erro ao faturar o balcão:', err);
      toast.error(err.response?.data?.detail || 'Erro ao emitir o documento');
    } finally {
      setCheckingOut(false);
    }
  };

  const novaVenda = () => {
    setCart([]);
    setEditIdx(null);
    setOrderId(null);
    setOrderNumber(null);
    setOrderTotal(null);
    setPaymentId('');
    setNif('');
    setCashReceived('');
    setDocNumber(null);
  };

  // Cancela o pedido já enviado à cozinha mas ainda não faturado (cliente
  // desistiu / erro). `leave=true` sai para a Home a seguir; senão fica no
  // balcão pronto para a próxima venda.
  const cancelSale = async (leave) => {
    if (!orderId) { if (leave) onClose(); return; }
    setCancelling(true);
    try {
      await posCounter.cancelOrder(orderId);
      toast.success('Venda cancelada');
      if (leave) onClose(); else novaVenda();
    } catch (err) {
      console.error('Erro ao cancelar venda de balcão:', err);
      toast.error(err.response?.data?.detail || 'Erro ao cancelar a venda');
    } finally {
      setCancelling(false);
    }
  };

  // Botão Voltar: se há um pedido por faturar, confirma o cancelamento antes de
  // sair (não deixa um pedido na cozinha sem documento). Antes de imprimir, ou
  // já faturado, sai direto.
  const handleBack = () => {
    if (printed && docNumber == null) {
      const ok = window.confirm(
        `Tens o pedido nº ${orderNumber} por faturar. Sair vai CANCELAR este pedido `
        + `(sem fatura). Continuar?`);
      if (!ok) return;
      cancelSale(true);
    } else {
      onClose();
    }
  };

  // Produtos visíveis no picker: exclui rodízio-only e indisponíveis,
  // agrupados por categoria (mesma lógica do "Adicionar produto" do
  // TableCheckout).
  const visibleProducts = products.filter((p) => p.rodizio_only !== true && p.available !== false);
  const catName = (id) => categories.find((c) => c.id === id)?.name || 'Outros';
  const productGroups = (() => {
    const byCat = new Map();
    for (const p of visibleProducts) {
      const cid = p.category_id || '__none';
      if (!byCat.has(cid)) byCat.set(cid, []);
      byCat.get(cid).push(p);
    }
    const order = new Map(categories.map((c, i) => [c.id, i]));
    return [...byCat.entries()]
      .map(([cid, items]) => ({ cid, name: cid === '__none' ? 'Outros' : catName(cid), items }))
      .sort((a, b) => (order.has(a.cid) ? order.get(a.cid) : 999) - (order.has(b.cid) ? order.get(b.cid) : 999));
  })();

  // Separador (tab) ativo por omissão: o primeiro grupo com produtos, assim
  // que o catálogo chega — mesma UX do POS Vendus (separadores no topo, em
  // vez de secções empilhadas).
  useEffect(() => {
    if (selectedCat == null && productGroups.length > 0) {
      setSelectedCat(productGroups[0].cid);
    }
  }, [productGroups, selectedCat]);

  const activeGroup = productGroups.find((g) => g.cid === selectedCat) || productGroups[0] || null;

  // Só pode sair antes de imprimir, ou depois de a venda estar concluída
  // (documento emitido) — nunca a meio, com um pedido já na cozinha e sem
  // fatura.
  const canLeave = !printed || docNumber != null;

  return (
    <div className="min-h-screen flex flex-col bg-[#5a1a1a] text-white">
      {/* Cabeçalho */}
      <header className="flex items-center gap-3 border-b border-white/15 px-5 py-4 sm:px-8">
        <Button
          variant="outline"
          size="icon"
          onClick={handleBack}
          disabled={cancelling}
          title={canLeave ? 'Voltar' : 'Sair (cancela o pedido por faturar)'}
          className="h-11 w-11 shrink-0 border-white/30 bg-transparent text-white hover:bg-white/10 hover:text-white"
        >
          {cancelling ? <Loader2 className="h-5 w-5 animate-spin" /> : <ArrowLeft className="h-5 w-5" />}
        </Button>
        <div className="min-w-0">
          <h1 className="text-xl font-bold leading-tight">POS · Balcão</h1>
          <p className="truncate text-sm text-white/70">
            {orderNumber ? `Pedido nº ${orderNumber}` : 'Venda ao balcão'}
          </p>
        </div>
      </header>

      <main className="flex flex-1 flex-col min-h-0 md:flex-row">
        {/* ESQUERDA — picker de produtos, agrupado por categoria */}
        <div className="flex-1 min-h-0 overflow-y-auto bg-background px-5 py-5 text-foreground sm:px-8 sm:py-6">
          {printed && (
            <div className="mb-4 rounded-lg border border-emerald-600/30 bg-emerald-50 px-3 py-2 text-sm text-emerald-800">
              Pedido já enviado para a cozinha — o carrinho está bloqueado. Usa "Nova Venda" para o próximo cliente.
            </div>
          )}
          {loadingCatalog ? (
            <div className="flex items-center justify-center py-24">
              <Loader2 className="h-8 w-8 animate-spin text-muted-foreground" />
            </div>
          ) : productGroups.length === 0 ? (
            <p className="py-12 text-center text-sm text-muted-foreground">Sem produtos disponíveis.</p>
          ) : (
            <>
              {/* Separadores por categoria (estilo POS Vendus) — um clique troca
                  o grupo visível; a grelha mostra só a categoria ativa. */}
              <div className="mb-4 flex gap-1.5 overflow-x-auto pb-1 [-ms-overflow-style:none] [scrollbar-width:none] [&::-webkit-scrollbar]:hidden">
                {productGroups.map((g) => (
                  <button
                    key={g.cid}
                    type="button"
                    onClick={() => setSelectedCat(g.cid)}
                    className={[
                      'shrink-0 whitespace-nowrap rounded-lg px-4 py-2.5 text-sm font-semibold transition-colors touch-manipulation',
                      g.cid === selectedCat
                        ? 'bg-[#5a1a1a] text-white shadow-sm'
                        : 'bg-muted text-muted-foreground hover:bg-muted/70',
                    ].join(' ')}
                  >
                    {g.name}
                  </button>
                ))}
              </div>

              {activeGroup && (
                <div className="grid gap-2 [grid-template-columns:repeat(auto-fill,minmax(140px,1fr))]">
                  {activeGroup.items.map((p) => (
                    <button
                      key={p.id}
                      type="button"
                      onClick={() => addToCart(p)}
                      disabled={printed}
                      className={[
                        'flex min-h-[76px] flex-col items-start justify-between rounded-lg border p-3 text-left transition-all touch-manipulation active:scale-[0.97]',
                        printed
                          ? 'cursor-not-allowed border-border bg-muted/40 opacity-50'
                          : 'cursor-pointer border-border bg-white hover:border-primary/40 hover:shadow-sm',
                      ].join(' ')}
                    >
                      <span className="text-sm font-medium leading-snug line-clamp-2">{p.name}</span>
                      <span className="mt-2 text-sm font-semibold text-[#5a1a1a] tabular-nums">{eur(p.base_price)}</span>
                    </button>
                  ))}
                </div>
              )}
            </>
          )}
        </div>

        {/* DIREITA — carrinho + faturação */}
        <div className="flex w-full min-h-0 flex-col bg-[#3a1414] text-white md:w-[40%] md:max-w-md">
          <div className="grid grid-cols-[1fr_5.5rem_5rem] gap-2 border-b border-white/10 px-4 py-3 text-[11px] uppercase tracking-wide text-white/50">
            <span>Produto</span><span className="text-center">Qtd</span><span className="text-right">Total</span>
          </div>
          <div className="flex-1 overflow-y-auto">
            {cart.length === 0 ? (
              <p className="py-8 text-center text-sm text-white/50">Carrinho vazio. Toca num produto para adicionar.</p>
            ) : (
              cart.map((c, i) => {
                const dv = Number(String(c.discVal).replace(',', '.')) || 0;
                return (
                  <div
                    key={c.id}
                    onClick={() => openEdit(i)}
                    title={printed ? undefined : 'Tocar para editar (qtd/preço/IVA/desconto)'}
                    className={`grid grid-cols-[1fr_5.5rem_5rem] items-center gap-2 border-b border-white/5 px-4 py-3 ${printed ? '' : 'cursor-pointer hover:bg-white/5'}`}
                  >
                    <span className="min-w-0">
                      <span className="flex items-center gap-1.5">
                        <span className="truncate">{c.name}</span>
                        {!printed && <Pencil className="h-3 w-3 shrink-0 text-white/30" />}
                      </span>
                      <span className="mt-0.5 flex items-center gap-1.5 text-white/40">
                        <span className="text-[11px] tabular-nums">{eur(c.unitPrice)}/un</span>
                        {dv > 0 && (
                          <span className="rounded-full bg-emerald-500/20 px-1.5 py-0.5 text-[10px] text-emerald-200">
                            −{c.discKind === 'eur' ? eur(dv) : `${dv}%`}
                          </span>
                        )}
                        {c.taxTouched && (
                          <span className="rounded-full bg-white/10 px-1.5 py-0.5 text-[10px] text-white/50">
                            {c.tax === 'INT' ? '13%' : '23%'}
                          </span>
                        )}
                      </span>
                    </span>
                    <span className="flex items-center justify-center gap-1" onClick={(e) => e.stopPropagation()}>
                      <Button
                        variant="outline" size="icon"
                        className="h-7 w-7 border-white/25 bg-transparent text-white hover:bg-white/10 hover:text-white"
                        onClick={() => changeQty(c.id, -1)} disabled={printed}
                        aria-label={`Diminuir ${c.name}`}
                      >
                        <Minus className="h-3.5 w-3.5" />
                      </Button>
                      <span className="w-5 text-center tabular-nums">{c.qty}</span>
                      <Button
                        variant="outline" size="icon"
                        className="h-7 w-7 border-white/25 bg-transparent text-white hover:bg-white/10 hover:text-white"
                        onClick={() => changeQty(c.id, 1)} disabled={printed}
                        aria-label={`Aumentar ${c.name}`}
                      >
                        <Plus className="h-3.5 w-3.5" />
                      </Button>
                    </span>
                    <span className="text-right tabular-nums">{eur(lineNet(c))}</span>
                  </div>
                );
              })
            )}
          </div>

          {/* Rodapé — total + ação (imprimir → faturar → nova venda) */}
          <div className="space-y-3 border-t border-white/10 p-4">
            <div className="flex items-center justify-between text-base font-semibold">
              <span>Total</span>
              <span className="tabular-nums">{eur(total)}</span>
            </div>

            {!printed && (
              <Button
                onClick={imprimirPedido}
                disabled={!cart.length || printing}
                className="h-14 w-full bg-white text-base font-semibold text-[#5a1a1a] hover:bg-white/90"
              >
                {printing ? <Loader2 className="h-5 w-5 animate-spin" /> : <Printer className="h-5 w-5" />}
                Imprimir Pedido
              </Button>
            )}

            {printed && docNumber == null && (
              <>
                <div className="space-y-2">
                  <Select value={paymentId} onValueChange={setPaymentId}>
                    <SelectTrigger className="border-white/25 bg-white/10 text-white data-[placeholder]:text-white/50">
                      <SelectValue placeholder="Método de pagamento" />
                    </SelectTrigger>
                    <SelectContent>
                      {methods.map((m) => (
                        <SelectItem key={m.id} value={String(m.id)}>{m.title}</SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                  <Input
                    placeholder="NIF (opcional)"
                    value={nif}
                    onChange={(e) => setNif(e.target.value)}
                    className="border-white/25 bg-white/10 text-white placeholder:text-white/50"
                  />
                </div>

                {isCash && (
                  <div className="space-y-2 rounded-lg border border-white/15 bg-white/5 px-3 py-3">
                    <div className="flex items-center justify-between gap-3">
                      <span className="text-sm">Valor entregue</span>
                      <div className="relative w-32">
                        <span className="absolute left-3 top-1/2 -translate-y-1/2 text-white/50">€</span>
                        <Input
                          type="number" inputMode="decimal" min={0} step="0.5"
                          className="border-white/25 bg-white/10 pl-7 text-right text-white"
                          placeholder="0.00"
                          value={cashReceived}
                          onChange={(e) => setCashReceived(e.target.value)}
                        />
                      </div>
                    </div>
                    {received > 0 && (
                      <div className={`flex items-center justify-between text-sm font-semibold ${troco >= 0 ? 'text-emerald-300' : 'text-red-300'}`}>
                        <span>{troco >= 0 ? 'Troco' : 'Em falta'}</span>
                        <span className="tabular-nums">{eur(Math.abs(troco))}</span>
                      </div>
                    )}
                  </div>
                )}

                <Button
                  onClick={emitirDocumento}
                  disabled={checkingOut || !paymentId}
                  className="h-14 w-full bg-white text-base font-semibold text-[#5a1a1a] hover:bg-white/90"
                >
                  {checkingOut ? <Loader2 className="h-5 w-5 animate-spin" /> : <Receipt className="h-5 w-5" />}
                  Emitir Documento
                </Button>

                <Button
                  variant="ghost"
                  onClick={() => {
                    if (window.confirm(`Cancelar o pedido nº ${orderNumber} sem faturar?`)) cancelSale(false);
                  }}
                  disabled={cancelling || checkingOut}
                  className="h-10 w-full text-sm text-white/60 hover:bg-white/10 hover:text-white"
                >
                  {cancelling ? <Loader2 className="h-4 w-4 animate-spin mr-1" /> : null}
                  Cancelar venda
                </Button>
              </>
            )}

            {docNumber != null && (
              <div className="flex flex-col items-center gap-3 py-2 text-center">
                <CheckCircle2 className="h-11 w-11 text-emerald-300" />
                <div>
                  <p className="text-lg font-bold">Fatura emitida</p>
                  <p className="text-sm text-white/70">Documento nº {docNumber}</p>
                </div>
                <Button
                  onClick={novaVenda}
                  className="h-14 w-full bg-white text-base font-semibold text-[#5a1a1a] hover:bg-white/90"
                >
                  Nova Venda
                </Button>
              </div>
            )}
          </div>
        </div>
      </main>

      {/* Diálogo do produto — editar qtd/preço/IVA/desconto de uma linha (antes de imprimir) */}
      <Dialog open={editIdx != null} onOpenChange={(v) => !v && setEditIdx(null)}>
        <DialogContent className="max-w-sm text-foreground">
          <DialogHeader>
            <DialogTitle className="pr-6 text-lg">
              {editIdx != null && cart[editIdx] ? cart[editIdx].name : 'Produto'}
            </DialogTitle>
          </DialogHeader>
          <div className="space-y-3">
            <div className="grid grid-cols-2 gap-3">
              <div className="space-y-1">
                <label className="text-xs text-muted-foreground">Quantidade</label>
                <Input type="number" inputMode="numeric" min={1} step="1"
                  value={edQty} onChange={(e) => setEdQty(e.target.value)} />
              </div>
              <div className="space-y-1">
                <label className="text-xs text-muted-foreground">Preço unitário</label>
                <div className="relative">
                  <span className="absolute left-3 top-1/2 -translate-y-1/2 text-muted-foreground">€</span>
                  <Input type="number" inputMode="decimal" min={0} step="0.10" className="pl-7 text-right"
                    value={edPrice} onChange={(e) => setEdPrice(e.target.value)} />
                </div>
              </div>
            </div>

            <div className="space-y-1">
              <label className="text-xs text-muted-foreground">IVA</label>
              <Select value={edTax} onValueChange={(v) => { setEdTax(v); setEdTaxTouched(true); }}>
                <SelectTrigger><SelectValue /></SelectTrigger>
                <SelectContent>
                  <SelectItem value="INT">Intermédia — 13% (comida, águas)</SelectItem>
                  <SelectItem value="NOR">Normal — 23% (refrigerantes, bebidas)</SelectItem>
                </SelectContent>
              </Select>
            </div>

            <div className="space-y-1">
              <label className="text-xs text-muted-foreground">Desconto</label>
              <div className="flex gap-2">
                <div className="flex shrink-0 overflow-hidden rounded-md border">
                  <button type="button" onClick={() => setEdDiscKind('pct')}
                    className={`px-3 text-sm ${edDiscKind === 'pct' ? 'bg-primary text-primary-foreground' : 'bg-background text-muted-foreground'}`}>%</button>
                  <button type="button" onClick={() => setEdDiscKind('eur')}
                    className={`border-l px-3 text-sm ${edDiscKind === 'eur' ? 'bg-primary text-primary-foreground' : 'bg-background text-muted-foreground'}`}>€</button>
                </div>
                <Input type="number" inputMode="decimal" min={0} step={edDiscKind === 'pct' ? '1' : '0.10'}
                  className="text-right" placeholder="0"
                  value={edDiscVal} onChange={(e) => setEdDiscVal(e.target.value)} />
              </div>
            </div>

            <div className="flex items-center justify-between rounded-lg bg-muted/40 px-3 py-2">
              <span className="text-sm text-muted-foreground">Subtotal</span>
              <span className="text-xl font-bold text-primary tabular-nums">{eur(edSubtotal)}</span>
            </div>
          </div>
          <div className="mt-2 flex justify-end gap-2">
            <Button variant="outline" onClick={() => setEditIdx(null)}>Cancelar</Button>
            <Button onClick={saveEdit} className="bg-[#5a1a1a] text-white hover:bg-[#4a1414]">Guardar</Button>
          </div>
        </DialogContent>
      </Dialog>
    </div>
  );
};

export default PosBalcao;
