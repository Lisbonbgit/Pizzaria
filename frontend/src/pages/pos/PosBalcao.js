import React, { useCallback, useEffect, useState } from 'react';
import {
  ArrowLeft, CheckCircle2, Loader2, Minus, Plus, Printer, Receipt,
} from 'lucide-react';
import { toast } from 'sonner';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from '@/components/ui/select';
import { posCounter, posCheckout } from '@/lib/api';

const eur = (v) => `€ ${Number(v || 0).toFixed(2)}`;

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

  const [cart, setCart] = useState([]); // [{id, name, price, qty}]

  const [printing, setPrinting] = useState(false);
  const [orderId, setOrderId] = useState(null);
  const [orderNumber, setOrderNumber] = useState(null);
  const [orderTotal, setOrderTotal] = useState(null);

  const [paymentId, setPaymentId] = useState('');
  const [nif, setNif] = useState('');
  const [cashReceived, setCashReceived] = useState('');
  const [checkingOut, setCheckingOut] = useState(false);
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
      return [...prev, { id: p.id, name: p.name, price: Number(p.base_price) || 0, qty: 1 }];
    });
  }, [printed]);

  const changeQty = useCallback((id, delta) => {
    if (printed) return;
    setCart((prev) => prev
      .map((c) => (c.id === id ? { ...c, qty: c.qty + delta } : c))
      .filter((c) => c.qty > 0));
  }, [printed]);

  const cartTotal = Math.round(cart.reduce((s, c) => s + c.price * c.qty, 0) * 100) / 100;
  const total = printed ? (orderTotal ?? cartTotal) : cartTotal;

  const imprimirPedido = async () => {
    if (!cart.length) return;
    setPrinting(true);
    try {
      const items = cart.map((c) => ({ product_id: c.id, quantity: c.qty }));
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
    setOrderId(null);
    setOrderNumber(null);
    setOrderTotal(null);
    setPaymentId('');
    setNif('');
    setCashReceived('');
    setDocNumber(null);
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
          onClick={onClose}
          disabled={!canLeave}
          title={canLeave ? 'Voltar' : 'Termina a faturação para sair'}
          className="h-11 w-11 shrink-0 border-white/30 bg-transparent text-white hover:bg-white/10 hover:text-white"
        >
          <ArrowLeft className="h-5 w-5" />
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
            productGroups.map((g) => (
              <section key={g.cid} className="mb-6">
                <h2 className="mb-3 text-sm font-semibold uppercase tracking-wide text-muted-foreground">
                  {g.name}
                </h2>
                <div className="grid gap-2 [grid-template-columns:repeat(auto-fill,minmax(140px,1fr))]">
                  {g.items.map((p) => (
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
              </section>
            ))
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
              cart.map((c) => (
                <div
                  key={c.id}
                  className="grid grid-cols-[1fr_5.5rem_5rem] items-center gap-2 border-b border-white/5 px-4 py-3"
                >
                  <span className="truncate">{c.name}</span>
                  <span className="flex items-center justify-center gap-1">
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
                  <span className="text-right tabular-nums">{eur(c.price * c.qty)}</span>
                </div>
              ))
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
    </div>
  );
};

export default PosBalcao;
