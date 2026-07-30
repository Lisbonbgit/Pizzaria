import React, { useState, useEffect, useCallback } from 'react';
import {
  Loader2, Receipt, Printer, Plus, Users, Store, X, ChevronsUpDown, Trash2, Pencil, Scissors,
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
  Command, CommandInput, CommandList, CommandEmpty, CommandGroup, CommandItem,
} from '@/components/ui/command';
import {
  AlertDialog, AlertDialogAction, AlertDialogCancel, AlertDialogContent,
  AlertDialogDescription, AlertDialogFooter, AlertDialogHeader, AlertDialogTitle,
} from '@/components/ui/alert-dialog';
import { toast } from 'sonner';
import { ordersAPI, productsAPI, categoriesAPI, rodizioAPI } from '@/lib/api';

const eur = (v) => `€ ${Number(v || 0).toFixed(2)}`;
const lineKey = (l) => `${l.order_id}:${l.idx}`;
const lineName = (l) => l.product_name + (l.variation && l.variation.name ? ` (${l.variation.name})` : '');

// Checkout de mesa — Dialog de 2 painéis (total/pagamento à esquerda, itens
// da mesa à direita) partilhado pelo admin (`AdminOrders`) e pela janela do
// POS (`PosHome`). Todas as chamadas de conta/fecho/desconto/void/consulta/
// libertar/métodos-de-pagamento vão pelo `api` recebido por props — no
// admin isso é `checkoutAPI` (JWT admin), no POS é `posCheckout` (device +
// token PIN), para que o backend resolva `kind="pos"` e ligue a venda à
// caixa. As leituras de catálogo (produtos/categorias) e a config pública
// do rodízio ficam fixas nos seus imports — são dados sem dono de sessão
// (produtos/categorias não exigem autenticação; a config do rodízio usa o
// endpoint `/public`, também sem autenticação, para funcionar em ambas as
// janelas — o endpoint admin de rodízio exige JWT e falharia no POS).
//
// Props:
//   api        — objeto no formato checkoutAPI: getBill, closeTable,
//                setItemDiscount, removeItem, printConsulta, freeTable,
//                paymentMethods, overview.
//   tableNumber— número da mesa aberta (null = Dialog fechado).
//   table      — snapshot da linha da grelha (id/name/people/rodizio/
//                rodizio_people/rodizio_paid) da mesa `tableNumber`, tal
//                como devolvido por `api.overview()`/`tables-overview`.
//                Necessário porque `getBill` não traz estes campos.
//   onClose    — chamado quando o Dialog deve fechar.
//   onChanged  — chamado a seguir a qualquer alteração (adicionar/remover
//                item, desconto, fechar, libertar) para o chamador
//                atualizar a sua grelha de mesas.
const TableCheckout = ({ api, tableNumber, table, onClose, onChanged }) => {
  // Dados da mesa aberta (capturados uma vez quando `tableNumber` muda)
  const [openTableId, setOpenTableId] = useState(null);
  const [openTablePeople, setOpenTablePeople] = useState(1);
  const [tableTitle, setTableTitle] = useState('');
  const [billLines, setBillLines] = useState([]);
  const [selected, setSelected] = useState(new Set());
  const [tableLoading, setTableLoading] = useState(false);

  // Catálogo (produtos/categorias) + métodos de pagamento + config do rodízio
  const [products, setProducts] = useState([]);
  const [categories, setCategories] = useState([]);
  const [methods, setMethods] = useState([]);
  const [rodizioCfg, setRodizioCfg] = useState(null);

  // Adicionar produto manual
  const [addProductId, setAddProductId] = useState('');
  const [addQty, setAddQty] = useState(1);
  const [pickerOpen, setPickerOpen] = useState(false);
  const [adding, setAdding] = useState(false);

  // Fecho
  const [paymentId, setPaymentId] = useState('');
  const [nif, setNif] = useState('');
  const [splitCount, setSplitCount] = useState(1);
  const [globalDiscount, setGlobalDiscount] = useState('');
  const [cashReceived, setCashReceived] = useState('');
  const [printingConsulta, setPrintingConsulta] = useState(false);
  const [confirmOpen, setConfirmOpen] = useState(false);
  const [closing, setClosing] = useState(false);
  const [freeOpen, setFreeOpen] = useState(false);
  const [freeing, setFreeing] = useState(false);

  // Rodízio (all-you-can-eat)
  const [rodizioMode, setRodizioMode] = useState('none'); // none | simples | completo
  const [rodAdults, setRodAdults] = useState(0);   // adultos AINDA por pagar
  const [rodChildren, setRodChildren] = useState(0); // crianças AINDA por pagar
  const [freeKids, setFreeKids] = useState(new Set()); // chaves de crianças marcadas grátis
  const [wasteBoxes, setWasteBoxes] = useState(0);

  // Fase 3 (faturação estilo Vendus): por defeito clicar num item à la carte abre
  // o DIÁLOGO do produto (editar qtd/preço/IVA/desconto); o botão "Separar Conta"
  // liga o modo 'split' em que clicar passa o item para a esquerda (cobrar à parte).
  // As entradas de rodízio (pessoas/desperdício) separam SEMPRE ao clicar (não são
  // editáveis) — preserva o fluxo do rodízio.
  const [mode, setMode] = useState('edit'); // 'edit' | 'split'
  const [editingLine, setEditingLine] = useState(null); // linha (l) em edição, ou null
  const [edQty, setEdQty] = useState('1');
  const [edPrice, setEdPrice] = useState('');
  const [edTax, setEdTax] = useState('NOR');       // 'INT' (13%) | 'NOR' (23%)
  const [edTaxTouched, setEdTaxTouched] = useState(false); // só grava o IVA se o staff o mudou
  const [edDiscKind, setEdDiscKind] = useState('pct'); // 'pct' | 'eur'
  const [edDiscVal, setEdDiscVal] = useState('');
  const [savingEdit, setSavingEdit] = useState(false);

  // Gestão do rodízio da mesa (adicionar / corrigir nº de pessoas). `rodPaid`
  // guarda o que já foi faturado, para o diálogo editar o TOTAL corretamente.
  const [rodPaid, setRodPaid] = useState({ adults: 0, children: 0 });
  const [rodizioOpen, setRodizioOpen] = useState(false);
  const [rdTier, setRdTier] = useState('simples'); // none | simples | completo
  const [rdAdults, setRdAdults] = useState(0);
  const [rdChildren, setRdChildren] = useState(0);
  const [savingRodizio, setSavingRodizio] = useState(false);

  // Catálogo + métodos de pagamento + config do rodízio — uma vez, no arranque.
  useEffect(() => {
    api.paymentMethods().then((r) => setMethods(r.data)).catch(() => {});
    productsAPI.list().then((r) => setProducts(r.data)).catch(() => {});
    categoriesAPI.list().then((r) => setCategories(r.data)).catch(() => {});
    // Endpoint público (sem JWT) — o endpoint admin de rodízio exige login
    // e falharia na janela do POS.
    rodizioAPI.public().then((r) => setRodizioCfg(r.data)).catch(() => {});
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const loadBill = useCallback(async (num) => {
    setTableLoading(true);
    try {
      const r = await api.getBill(num);
      setBillLines(r.data.lines || []);
    } catch {
      toast.error('Erro ao carregar a conta da mesa');
    } finally {
      setTableLoading(false);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [api]);

  // Inicializa o painel sempre que uma mesa (diferente) abre. Lê `table`
  // (snapshot da grelha) apenas neste instante — de propósito não reage a
  // atualizações posteriores de `table` (ex.: o poll periódico da grelha),
  // para não repor a seleção/estado a meio da operação do staff.
  useEffect(() => {
    if (tableNumber == null) return;
    const t = table || {};
    setOpenTableId(t.id ?? null);
    setOpenTablePeople(t.people || 1);
    setTableTitle(t.name || `Mesa ${tableNumber}`);
    setPaymentId('');
    setNif('');
    setSplitCount(1);
    setGlobalDiscount('');
    setCashReceived('');
    setAddProductId('');
    setAddQty(1);
    setSelected(new Set());
    setBillLines([]);
    // Rodízio: gera pessoas AINDA por pagar = lotação − já faturado.
    const rmode = t.rodizio && t.rodizio !== 'none' ? t.rodizio : 'none';
    setRodizioMode(rmode);
    const rp = t.rodizio_people || {};
    const paid = t.rodizio_paid || {};
    setRodAdults(rmode !== 'none' ? Math.max(0, (rp.adults || 0) - (paid.adults || 0)) : 0);
    setRodChildren(rmode !== 'none' ? Math.max(0, (rp.children || 0) - (paid.children || 0)) : 0);
    setRodPaid({ adults: paid.adults || 0, children: paid.children || 0 });
    setFreeKids(new Set());
    setWasteBoxes(0);
    setMode('edit');
    setEditingLine(null);
    loadBill(tableNumber);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tableNumber]);

  const closeModal = () => {
    setBillLines([]);
    setSelected(new Set());
    onClose && onClose();
  };

  const toggle = (k) => {
    setSelected((prev) => {
      const n = new Set(prev);
      if (n.has(k)) n.delete(k); else n.add(k);
      return n;
    });
  };

  const toggleFreeKid = (k) => {
    setFreeKids((prev) => {
      const n = new Set(prev);
      if (n.has(k)) n.delete(k); else n.add(k);
      return n;
    });
  };

  const printConsulta = async () => {
    setPrintingConsulta(true);
    try {
      await api.printConsulta(tableNumber);
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
        table_number: tableNumber,
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
      loadBill(tableNumber);
      onChanged && onChanged();
    } catch {
      toast.error('Erro ao adicionar o produto');
    } finally {
      setAdding(false);
    }
  };

  // O scroll-lock do Dialog (react-remove-scroll) bloqueia roda E toque na lista
  // do seletor. Movemos a lista manualmente com listeners NÃO-passivos (única forma
  // fiável no tablet). Bypassa o lock; sem risco de scroll duplo (o nativo é travado).
  const pickerListRef = useCallback((node) => {
    if (!node || node.__scrollBound) return;
    node.__scrollBound = true;
    let lastY = 0;
    node.addEventListener('wheel', (e) => {
      e.preventDefault();
      const f = e.deltaMode === 1 ? 16 : e.deltaMode === 2 ? node.clientHeight : 1;
      node.scrollTop += e.deltaY * f;
    }, { passive: false });
    node.addEventListener('touchstart', (e) => { lastY = e.touches[0].clientY; }, { passive: true });
    node.addEventListener('touchmove', (e) => {
      e.preventDefault();
      const y = e.touches[0].clientY;
      node.scrollTop += (lastY - y);
      lastY = y;
    }, { passive: false });
  }, []);

  const removeItem = async (l) => {
    if (!window.confirm(`Remover "${lineName(l)}" da conta? Não será faturado.`)) return;
    try {
      await api.removeItem(l.order_id, l.idx);
      setSelected((prev) => { const n = new Set(prev); n.delete(lineKey(l)); return n; });
      toast.success('Item removido da conta');
      loadBill(tableNumber);
      onChanged && onChanged();
    } catch (e) {
      toast.error(e.response?.data?.detail || 'Erro ao remover o item');
    }
  };

  // ---- Rodízio: config ----
  const isRodizioTable = rodizioMode === 'simples' || rodizioMode === 'completo';
  const rTier = rodizioCfg?.tiers?.[rodizioMode];
  const rTierPrice = Number(rTier?.price) || 0;
  const rTierName = rTier?.name || (rodizioMode === 'completo' ? 'Rodízio Completo' : 'Rodízio Simples');
  const wasteFee = Number(rodizioCfg?.waste_fee) || 5;

  // ---- Entradas faturáveis: rodízio-por-pessoa (sintéticas) + extras à la carte ----
  const rodizioEntries = [];
  if (isRodizioTable) {
    for (let i = 0; i < rodAdults; i++)
      rodizioEntries.push({ key: `rod:adult:${i}`, kind: 'adult', name: `${rTierName} (adulto)`, price: rTierPrice });
    for (let i = 0; i < rodChildren; i++) {
      const k = `rod:child:${i}`;
      const free = freeKids.has(k);
      rodizioEntries.push({ key: k, kind: 'child', name: `${rTierName} (criança)`, price: free ? 0 : rTierPrice / 2, free });
    }
    for (let i = 0; i < wasteBoxes; i++)
      rodizioEntries.push({ key: `rod:waste:${i}`, kind: 'waste', name: 'Taxa de desperdício', price: wasteFee });
  }
  const pricedItemEntries = billLines
    .filter((l) => (l.total_price || 0) > 0)
    .map((l) => ({ key: lineKey(l), kind: 'item', name: lineName(l), price: l.total_price || 0, line: l }));
  const includedEntries = billLines.filter((l) => (l.total_price || 0) === 0); // "Incluído", não faturáveis

  const billable = [...rodizioEntries, ...pricedItemEntries];
  const selectedEntries = billable.filter((e) => selected.has(e.key));
  const rightEntries = billable.filter((e) => !selected.has(e.key));
  const hasSelection = selectedEntries.length > 0;
  const fullTotal = Math.round(billable.reduce((s, e) => s + (e.price || 0), 0) * 100) / 100;
  const selectedTotal = Math.round(selectedEntries.reduce((s, e) => s + (e.price || 0), 0) * 100) / 100;
  const invoiceTotal = hasSelection ? selectedTotal : fullTotal;
  const globalPct = Math.max(0, Math.min(100, Number(String(globalDiscount).replace(',', '.')) || 0));
  const payTotal = Math.round(invoiceTotal * (1 - globalPct / 100) * 100) / 100; // total já com desconto global
  const splitActive = !isRodizioTable && !hasSelection && splitCount > 1;
  const perPerson = splitActive ? payTotal / splitCount : payTotal;

  const selectedMethod = methods.find((m) => String(m.id) === String(paymentId));
  const isCash = !!selectedMethod && /dinheiro|numer|cash/i.test(selectedMethod.title || '');
  const received = Number(String(cashReceived).replace(',', '.')) || 0;
  const change = Math.round((received - payTotal) * 100) / 100;

  // Diálogo do produto (Fase 3): abre ao clicar num item à la carte (modo 'edit').
  // Pré-preenche com os valores atuais da linha (preço/IVA/desconto override, se
  // houver; senão o IVA do produto).
  const openEdit = (l) => {
    const prod = products.find((p) => p.id === l.product_id);
    const tax = l.vendus_tax_id || prod?.vendus_tax_id || 'NOR';
    setEdQty(String(l.quantity || 1));
    setEdPrice(String(l.unit_price ?? 0));
    setEdTax(tax === 'INT' ? 'INT' : 'NOR');
    setEdTaxTouched(false);
    if (l.discount_amount) {
      setEdDiscKind('eur');
      setEdDiscVal(String(l.discount_amount));
    } else {
      setEdDiscKind('pct');
      setEdDiscVal(l.discount_pct ? String(l.discount_pct) : '');
    }
    setEditingLine(l);
  };

  const saveEdit = async () => {
    const l = editingLine;
    if (!l) return;
    const q = Math.max(1, parseInt(edQty, 10) || 1);
    const price = Math.max(0, Number(String(edPrice).replace(',', '.')) || 0);
    const dv = Math.max(0, Number(String(edDiscVal).replace(',', '.')) || 0);
    setSavingEdit(true);
    try {
      // IVA só vai no payload se o staff o mudou de propósito — assim uma edição
      // de qtd/preço NÃO reescreve o IVA da linha (que poderia forçar um produto
      // fora de INT/NOR para 23%). Sem alteração, o backend mantém o IVA atual.
      const payload = { quantity: q, unit_price: price };
      if (edTaxTouched) payload.vendus_tax_id = edTax;
      await api.editItem(l.order_id, l.idx, payload);
      // Desconto sempre gravado (mesmo 0 → limpa o outro tipo no backend).
      await api.setItemDiscount(l.order_id, l.idx, edDiscKind === 'eur' ? { amount: dv } : { pct: dv });
      toast.success('Produto atualizado');
      setEditingLine(null);
      loadBill(tableNumber);
      onChanged && onChanged();
    } catch (e) {
      toast.error(e.response?.data?.detail || 'Erro ao atualizar o produto');
    } finally {
      setSavingEdit(false);
    }
  };

  // Subtotal previsto no diálogo (bruto − desconto), para o staff confirmar.
  const edSubtotal = (() => {
    const q = Math.max(1, parseInt(edQty, 10) || 1);
    const price = Math.max(0, Number(String(edPrice).replace(',', '.')) || 0);
    const dv = Math.max(0, Number(String(edDiscVal).replace(',', '.')) || 0);
    const gross = Math.round(price * q * 100) / 100;
    const net = edDiscKind === 'eur' ? gross - dv : gross * (1 - Math.min(100, dv) / 100);
    return Math.max(0, Math.round(net * 100) / 100);
  })();

  // ---- Gestão do rodízio da mesa (adicionar / corrigir nº de pessoas) ----
  const openRodizioDialog = () => {
    // Pré-preenche com o TOTAL atual (a-pagar + já-pago) e o tier atual; se a
    // mesa ainda não tem rodízio, arranca em "simples".
    setRdTier(rodizioMode !== 'none' ? rodizioMode : 'simples');
    setRdAdults(rodAdults + (rodPaid.adults || 0));
    setRdChildren(rodChildren + (rodPaid.children || 0));
    setRodizioOpen(true);
  };

  const saveRodizio = async () => {
    const tier = rdTier;
    const adults = Math.max(0, parseInt(rdAdults, 10) || 0);
    const children = Math.max(0, parseInt(rdChildren, 10) || 0);
    if (tier !== 'none' && adults + children < 1) {
      toast.error('Indica pelo menos 1 pessoa no rodízio');
      return;
    }
    setSavingRodizio(true);
    try {
      const r = await api.setRodizio(tableNumber, { tier, adults, children });
      const s = r.data || {};
      const paid = s.rodizio_paid || { adults: 0, children: 0 };
      const people = s.rodizio_people || { adults: 0, children: 0 };
      const mode = s.rodizio && s.rodizio !== 'none' ? s.rodizio : 'none';
      setRodizioMode(mode);
      setRodPaid({ adults: paid.adults || 0, children: paid.children || 0 });
      setRodAdults(mode !== 'none' ? Math.max(0, (people.adults || 0) - (paid.adults || 0)) : 0);
      setRodChildren(mode !== 'none' ? Math.max(0, (people.children || 0) - (paid.children || 0)) : 0);
      if (mode === 'none') { setFreeKids(new Set()); setWasteBoxes(0); }
      toast.success(mode === 'none' ? 'Rodízio removido' : 'Rodízio atualizado');
      setRodizioOpen(false);
      onChanged && onChanged();
    } catch (e) {
      toast.error(e.response?.data?.detail || 'Erro ao atualizar o rodízio');
    } finally {
      setSavingRodizio(false);
    }
  };

  const countEntries = (entries) => {
    let adults = 0, children_half = 0, children_free = 0, waste_boxes = 0;
    const items = [];
    for (const e of entries) {
      if (e.kind === 'adult') adults += 1;
      else if (e.kind === 'child') { if (e.free) children_free += 1; else children_half += 1; }
      else if (e.kind === 'waste') waste_boxes += 1;
      else if (e.kind === 'item') items.push({ order_id: e.line.order_id, idx: e.line.idx });
    }
    return { adults, children_half, children_free, waste_boxes, items };
  };

  const doClose = async () => {
    setConfirmOpen(false);
    setClosing(true);
    try {
      const body = { payment_method_id: Number(paymentId) };
      if (globalPct > 0) body.global_discount_pct = globalPct;
      const toBill = hasSelection ? selectedEntries : billable;
      if (isRodizioTable) {
        const c = countEntries(toBill);
        body.rodizio_tier = rodizioMode;
        body.adults = c.adults;
        body.children_half = c.children_half;
        body.children_free = c.children_free;
        body.waste_boxes = c.waste_boxes;
        body.items = c.items;
        body.nif = nif.trim() || null;
      } else if (hasSelection) {
        body.items = selectedEntries.map((e) => ({ order_id: e.line.order_id, idx: e.line.idx }));
      } else {
        body.nif = nif.trim() || null;
        body.split_count = splitActive ? splitCount : 1;
      }
      const r = await api.closeTable(tableNumber, body);
      const nInv = r.data.invoices || 1;
      toast.success(nInv > 1 ? `${nInv} faturas emitidas` : `Fatura ${r.data.vendus.number} emitida`);
      if (r.data.table_free) {
        closeModal();
        onChanged && onChanged();
      } else {
        // separação parcial: a mesa continua aberta com o resto
        setSelected(new Set());
        setCashReceived('');
        setSplitCount(1);
        setFreeKids(new Set());
        setWasteBoxes(0);
        await loadBill(tableNumber);
        if (isRodizioTable) {
          try {
            const ov = await api.overview();
            const t = (ov.data || []).find((x) => x.number === tableNumber);
            if (t) {
              const rp = t.rodizio_people || {}; const paid = t.rodizio_paid || {};
              setRodAdults(Math.max(0, (rp.adults || 0) - (paid.adults || 0)));
              setRodChildren(Math.max(0, (rp.children || 0) - (paid.children || 0)));
            }
          } catch { /* ignore */ }
        }
        onChanged && onChanged();
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
      const r = await api.freeTable(tableNumber);
      toast.success(r.data.cancelled_orders > 0
        ? `Mesa libertada — ${r.data.cancelled_orders} pedido(s) cancelado(s)`
        : 'Mesa libertada');
      closeModal();
      onChanged && onChanged();
    } catch (e) {
      toast.error(e.response?.data?.detail || 'Erro ao libertar a mesa');
    } finally {
      setFreeing(false);
    }
  };

  // Produtos para "Adicionar produto" agrupados por categoria (para o seletor com pesquisa)
  // Categorias pos_only (ex.: "Venda Aplicações" = preços de delivery) são só do
  // balcão/POS. Uma conta de mesa é dine-in → nunca oferece preços de delivery.
  const posOnlyCatIds = new Set(categories.filter((c) => c.pos_only).map((c) => c.id));
  const availableProducts = products.filter(
    (p) => p.available !== false && !posOnlyCatIds.has(p.category_id));
  const catName = (id) => categories.find((c) => c.id === id)?.name || 'Outros';
  const productGroups = (() => {
    const byCat = new Map();
    for (const p of availableProducts) {
      const cid = p.category_id || '__none';
      if (!byCat.has(cid)) byCat.set(cid, []);
      byCat.get(cid).push(p);
    }
    // ordena os grupos pela ordem das categorias; "Outros" no fim
    const order = new Map(categories.map((c, i) => [c.id, i]));
    return [...byCat.entries()]
      .map(([cid, items]) => ({ cid, name: cid === '__none' ? 'Outros' : catName(cid), items }))
      .sort((a, b) => (order.has(a.cid) ? order.get(a.cid) : 999) - (order.has(b.cid) ? order.get(b.cid) : 999));
  })();
  const selectedProductName = availableProducts.find((p) => p.id === addProductId)?.name || '';

  return (
    <>
      {/* Checkout tipo POS — 2 painéis */}
      <Dialog open={tableNumber != null} onOpenChange={(v) => !v && closeModal()}>
        <DialogContent className="max-w-5xl w-[96vw] h-[90vh] p-0 gap-0 overflow-hidden">
          <div className="flex flex-col md:flex-row h-full min-h-0">

            {/* ESQUERDA — a faturar + pagamento */}
            <div className="flex-1 flex flex-col min-h-0 bg-background">
              <DialogHeader className="px-6 py-4 border-b text-left">
                <DialogTitle className="font-heading text-xl flex items-center justify-between pr-8">
                  <span>{tableTitle}</span>
                  <span className="text-xs font-normal text-muted-foreground uppercase tracking-wide">
                    {hasSelection ? 'A separar' : (isRodizioTable ? rTierName : 'Conta toda')}
                  </span>
                </DialogTitle>
              </DialogHeader>

              <div className="flex-1 overflow-y-auto px-6 py-4 space-y-4">
                <div className="flex items-end justify-between">
                  <span className="text-muted-foreground">{hasSelection ? 'A faturar (selecionados)' : 'Total a pagar'}</span>
                  <span className="text-right">
                    {globalPct > 0 && (
                      <span className="block text-sm text-muted-foreground line-through tabular-nums">{eur(invoiceTotal)}</span>
                    )}
                    <span className="font-heading text-4xl font-bold text-primary tabular-nums">{eur(payTotal)}</span>
                  </span>
                </div>

                {/* Desconto global na conta */}
                <div className="flex items-center justify-between gap-3">
                  <span className="text-sm">Desconto na conta {globalPct > 0 ? `(−${eur(Math.round((invoiceTotal - payTotal) * 100) / 100)})` : ''}</span>
                  <div className="relative w-28">
                    <Input type="number" inputMode="decimal" min={0} max={100} step="1" className="pr-7 text-right"
                      placeholder="0" value={globalDiscount} onChange={(e) => setGlobalDiscount(e.target.value)} aria-label="Desconto global %" />
                    <span className="absolute right-3 top-1/2 -translate-y-1/2 text-muted-foreground">%</span>
                  </div>
                </div>

                {/* Dica do rodízio */}
                {isRodizioTable && (
                  <div className="rounded-lg border bg-primary/[0.04] px-3 py-2 text-sm">
                    <span className="font-semibold text-primary">{rTierName}</span> — {eur(rTierPrice)}/adulto · {eur(rTierPrice / 2)}/criança.
                    <span className="text-muted-foreground"> Toca nas pessoas à direita para separar/pagar à parte.</span>
                  </div>
                )}

                {/* Selecionados (pessoas do rodízio e/ou itens) */}
                {hasSelection && (
                  <div className="rounded-lg border divide-y">
                    {selectedEntries.map((e) => (
                      <button key={e.key} onClick={() => toggle(e.key)}
                        className="w-full flex items-center justify-between gap-2 px-3 py-2 text-sm hover:bg-muted/50 text-left">
                        <span className="truncate">{e.name}{e.kind === 'child' && e.free ? ' — grátis' : ''}</span>
                        <span className="flex items-center gap-2 shrink-0">
                          <span className="tabular-nums">{eur(e.price)}</span>
                          <X className="h-4 w-4 text-muted-foreground" />
                        </span>
                      </button>
                    ))}
                    <p className="px-3 py-1.5 text-xs text-muted-foreground">Toca para devolver à mesa.</p>
                  </div>
                )}

                {/* Dividir — só quando é a conta toda (à la carte) */}
                {!isRodizioTable && !hasSelection && (
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
                    if (!billable.length) { toast.error('Nada para faturar'); return; }
                    if (!paymentId) { toast.error('Escolhe o método de pagamento'); return; }
                    if (payTotal <= 0) { toast.error('Total a zero — seleciona o que faturar'); return; }
                    setConfirmOpen(true);
                  }}
                  disabled={closing || !billable.length}
                  className="w-full h-14 text-base font-semibold bg-[#5a1a1a] hover:bg-[#4a1414]">
                  {closing ? <Loader2 className="h-5 w-5 animate-spin mr-2" /> : <Receipt className="h-5 w-5 mr-2" />}
                  Emitir Documento
                </Button>
              </div>
            </div>

            {/* DIREITA — itens da mesa (toca para separar) */}
            <div className="w-full md:w-[42%] md:max-w-md flex flex-col min-h-0 bg-[#3a1414] text-white">
              <div className="px-4 py-3 grid grid-cols-[1fr_2.5rem_5rem_2rem] gap-2 text-[11px] uppercase tracking-wide text-white/50 border-b border-white/10">
                <span>Produto</span><span className="text-center">Qtd</span><span className="text-right">Preço</span><span></span>
              </div>
              <div className="flex-1 overflow-y-auto">
                {tableLoading ? (
                  <div className="flex items-center gap-2 text-white/70 py-8 justify-center text-sm">
                    <Loader2 className="h-5 w-5 animate-spin" /> A carregar…
                  </div>
                ) : (rightEntries.length === 0 && includedEntries.length === 0) ? (
                  <p className="text-center text-white/50 py-8 text-sm">
                    {hasSelection ? 'Tudo a ser faturado.' : 'Conta vazia.'}
                  </p>
                ) : (
                  <>
                    {rightEntries.map((e) => (
                      <div key={e.key}
                        onClick={() => {
                          // Item à la carte: em 'edit' abre o diálogo; em 'split' separa.
                          // Entradas de rodízio (pessoas/desperdício): separam sempre.
                          if (e.kind === 'item') {
                            if (mode === 'split') toggle(e.key); else openEdit(e.line);
                          } else {
                            toggle(e.key);
                          }
                        }}
                        title={e.kind === 'item' ? (mode === 'split' ? 'Tocar para cobrar à parte' : 'Tocar para editar (qtd/preço/IVA/desconto)') : 'Tocar para separar'}
                        className="w-full grid grid-cols-[1fr_2.5rem_5rem_2rem] gap-2 items-center px-4 py-3 border-b border-white/5 text-left transition-colors cursor-pointer hover:bg-white/10">
                        <span className="truncate flex items-center gap-1.5">
                          {e.name}
                          {e.kind === 'item' && e.line?.source === 'manual' && <Store className="h-3 w-3 text-amber-300 shrink-0" />}
                          {e.kind === 'item' && mode === 'edit' && <Pencil className="h-3 w-3 text-white/30 shrink-0" />}
                          {e.kind === 'item' && (e.line?.discount_amount > 0 || e.line?.discount_pct > 0) && (
                            <span className="text-[10px] px-1.5 py-0.5 rounded-full bg-emerald-500/20 text-emerald-200 shrink-0">
                              −{e.line.discount_amount > 0 ? eur(e.line.discount_amount) : `${e.line.discount_pct}%`}
                            </span>
                          )}
                          {e.kind === 'item' && e.line?.vendus_tax_id && (
                            <span className="text-[10px] px-1.5 py-0.5 rounded-full bg-white/10 text-white/50 shrink-0">
                              {e.line.vendus_tax_id === 'INT' ? '13%' : e.line.vendus_tax_id === 'NOR' ? '23%' : e.line.vendus_tax_id}
                            </span>
                          )}
                          {e.kind === 'child' && (
                            <button type="button" onClick={(ev) => { ev.stopPropagation(); toggleFreeKid(e.key); }}
                              className={`text-[10px] px-1.5 py-0.5 rounded-full border shrink-0 ${e.free ? 'bg-emerald-500/20 border-emerald-400 text-emerald-200' : 'border-white/25 text-white/60'}`}
                              title="Alternar grátis (≤5 anos) / meia (6–12)">
                              {e.free ? 'grátis' : '½'}
                            </button>
                          )}
                        </span>
                        <span className="text-center tabular-nums">{e.kind === 'item' ? (e.line?.quantity || 1) : 1}</span>
                        <span className="text-right tabular-nums">{eur(e.price)}</span>
                        {e.kind === 'item' ? (
                          <button type="button" title="Remover (não fatura)" aria-label="Remover item"
                            onClick={(ev) => { ev.stopPropagation(); removeItem(e.line); }}
                            className="justify-self-end text-white/40 hover:text-red-400 transition-colors">
                            <Trash2 className="h-4 w-4" />
                          </button>
                        ) : <span />}
                      </div>
                    ))}
                    {includedEntries.map((l) => (
                      <div key={lineKey(l)}
                        className="w-full grid grid-cols-[1fr_2.5rem_5rem_2rem] gap-2 items-center px-4 py-3 border-b border-white/5 text-left">
                        <span className="truncate flex items-center gap-1.5 text-white/70">
                          {lineName(l)}
                          {l.source === 'manual' && <Store className="h-3 w-3 text-amber-300 shrink-0" />}
                        </span>
                        <span className="text-center tabular-nums text-white/70">{l.quantity}</span>
                        <span className="text-right text-[11px] text-emerald-300">Incluído</span>
                        <button type="button" title="Remover" aria-label="Remover item"
                          onClick={() => removeItem(l)}
                          className="justify-self-end text-white/40 hover:text-red-400 transition-colors">
                          <Trash2 className="h-4 w-4" />
                        </button>
                      </div>
                    ))}
                  </>
                )}
              </div>

              {/* Rodapé direito — ações */}
              <div className="border-t border-white/10 p-3 space-y-2">
                <div className="flex gap-2">
                  <Button variant="outline" role="combobox"
                    onClick={() => setPickerOpen(true)}
                    className="flex-1 justify-between bg-white/10 border-white/20 text-white hover:bg-white/15 hover:text-white h-9 font-normal">
                    <span className="truncate">{selectedProductName || 'Procurar produto…'}</span>
                    <ChevronsUpDown className="h-4 w-4 opacity-60 shrink-0" />
                  </Button>
                  <Dialog open={pickerOpen} onOpenChange={setPickerOpen}>
                    <DialogContent className="p-0 gap-0 max-w-md overflow-hidden">
                      <DialogHeader className="sr-only"><DialogTitle>Adicionar produto</DialogTitle></DialogHeader>
                      <Command>
                        <CommandInput placeholder="Escreve o nome do produto…" className="pr-10" />
                        <CommandList ref={pickerListRef} className="max-h-[60vh]">
                          <CommandEmpty>Nenhum produto encontrado.</CommandEmpty>
                          {productGroups.map((g) => (
                            <CommandGroup key={g.cid} heading={g.name}>
                              {g.items.map((p) => (
                                <CommandItem key={p.id} value={`${p.name} ${g.name} ${p.id}`}
                                  onSelect={() => { setAddProductId(p.id); setPickerOpen(false); }}>
                                  <span className="flex-1 truncate">{p.name}</span>
                                  <span className="text-muted-foreground tabular-nums">{eur(p.base_price)}</span>
                                </CommandItem>
                              ))}
                            </CommandGroup>
                          ))}
                        </CommandList>
                      </Command>
                    </DialogContent>
                  </Dialog>
                  <Input type="number" min={1} value={addQty} onChange={(e) => setAddQty(e.target.value)}
                    className="w-14 bg-white/10 border-white/20 text-white h-9" aria-label="Quantidade" />
                  <Button variant="secondary" size="icon" className="h-9 w-9 shrink-0" onClick={addProduct} disabled={adding || !addProductId}>
                    {adding ? <Loader2 className="h-4 w-4 animate-spin" /> : <Plus className="h-4 w-4" />}
                  </Button>
                </div>
                {isRodizioTable && (
                  <div className="flex items-center justify-between text-sm text-white/80 px-1">
                    <span>Taxa de desperdício <span className="text-white/50">({eur(wasteFee)}/box)</span></span>
                    <div className="flex items-center gap-2">
                      <Button variant="outline" size="icon" className="h-7 w-7 bg-transparent border-white/25 text-white hover:bg-white/10 hover:text-white"
                        onClick={() => setWasteBoxes((n) => Math.max(0, n - 1))} disabled={wasteBoxes <= 0}>−</Button>
                      <span className="w-6 text-center tabular-nums">{wasteBoxes}</span>
                      <Button variant="outline" size="icon" className="h-7 w-7 bg-transparent border-white/25 text-white hover:bg-white/10 hover:text-white"
                        onClick={() => setWasteBoxes((n) => n + 1)}>+</Button>
                    </div>
                  </div>
                )}
                <div className="flex items-center justify-between text-sm text-white/70 px-1">
                  <span className="flex items-center gap-1"><Users className="h-4 w-4" />{openTablePeople} pessoa{openTablePeople !== 1 ? 's' : ''}</span>
                  <span className="tabular-nums">Total {eur(fullTotal)}</span>
                </div>
                {/* Gerir rodízio: adicionar a uma mesa sem, ou corrigir o nº de pessoas. */}
                <Button variant="outline"
                  onClick={openRodizioDialog}
                  className="w-full bg-transparent border-white/25 text-white hover:bg-white/10 hover:text-white">
                  <Users className="h-4 w-4 mr-1" />
                  {isRodizioTable ? `Rodízio: ${rodAdults} adulto${rodAdults !== 1 ? 's' : ''}${rodChildren ? ` + ${rodChildren} criança${rodChildren !== 1 ? 's' : ''}` : ''}` : 'Adicionar rodízio'}
                </Button>
                {/* Separar Conta: liga o modo em que clicar num produto o passa para a
                    esquerda (cobrar à parte) em vez de abrir o diálogo de edição. */}
                {billable.length > 0 && (
                  <Button
                    onClick={() => setMode((m) => (m === 'split' ? 'edit' : 'split'))}
                    className={mode === 'split'
                      ? 'w-full bg-amber-500 hover:bg-amber-600 text-black font-semibold'
                      : 'w-full bg-transparent border border-white/25 text-white hover:bg-white/10 hover:text-white'}>
                    <Scissors className="h-4 w-4 mr-1" />
                    {mode === 'split' ? 'A separar — toca para terminar' : 'Separar Conta'}
                  </Button>
                )}
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
                ? `Vai faturar ${selectedEntries.length} selecionado(s) (${eur(payTotal)}). O resto fica na mesa.`
                : splitActive
                  ? `Vai emitir ${splitCount} faturas de ${eur(perPerson)} cada e libertar a mesa.`
                  : `Vai emitir a fatura (${eur(payTotal)})${isRodizioTable ? ` do ${rTierName}` : ''} e libertar a mesa.`}
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

      {/* Diálogo do produto (Fase 3) — editar quantidade/preço/IVA/desconto da linha */}
      <Dialog open={!!editingLine} onOpenChange={(v) => !v && setEditingLine(null)}>
        <DialogContent className="max-w-sm">
          <DialogHeader>
            <DialogTitle className="font-heading text-lg pr-6">
              {editingLine ? lineName(editingLine) : 'Produto'}
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
                <div className="flex rounded-md border overflow-hidden shrink-0">
                  <button type="button" onClick={() => setEdDiscKind('pct')}
                    className={`px-3 text-sm ${edDiscKind === 'pct' ? 'bg-primary text-primary-foreground' : 'bg-background text-muted-foreground'}`}>%</button>
                  <button type="button" onClick={() => setEdDiscKind('eur')}
                    className={`px-3 text-sm border-l ${edDiscKind === 'eur' ? 'bg-primary text-primary-foreground' : 'bg-background text-muted-foreground'}`}>€</button>
                </div>
                <Input type="number" inputMode="decimal" min={0} step={edDiscKind === 'pct' ? '1' : '0.10'}
                  className="text-right" placeholder="0"
                  value={edDiscVal} onChange={(e) => setEdDiscVal(e.target.value)} />
              </div>
            </div>

            <div className="flex items-center justify-between rounded-lg bg-muted/40 px-3 py-2">
              <span className="text-sm text-muted-foreground">Subtotal</span>
              <span className="font-heading text-xl font-bold text-primary tabular-nums">{eur(edSubtotal)}</span>
            </div>
          </div>
          <div className="flex justify-end gap-2 mt-2">
            <Button variant="outline" onClick={() => setEditingLine(null)}>Cancelar</Button>
            <Button onClick={saveEdit} disabled={savingEdit} className="bg-[#5a1a1a] hover:bg-[#4a1414]">
              {savingEdit ? <Loader2 className="h-4 w-4 animate-spin mr-1" /> : null}
              Gravar
            </Button>
          </div>
        </DialogContent>
      </Dialog>

      {/* Diálogo — gerir rodízio da mesa (adicionar / corrigir nº de pessoas) */}
      <Dialog open={rodizioOpen} onOpenChange={(v) => !v && setRodizioOpen(false)}>
        <DialogContent className="max-w-sm">
          <DialogHeader>
            <DialogTitle className="font-heading text-lg pr-6">Rodízio — {tableTitle}</DialogTitle>
          </DialogHeader>
          <div className="space-y-3">
            <div className="space-y-1">
              <label className="text-xs text-muted-foreground">Nível</label>
              <Select value={rdTier} onValueChange={setRdTier}>
                <SelectTrigger><SelectValue /></SelectTrigger>
                <SelectContent>
                  <SelectItem value="none">Sem rodízio (à la carte)</SelectItem>
                  {Object.entries(rodizioCfg?.tiers || {}).map(([key, t]) => (
                    <SelectItem key={key} value={key}>{(t?.name || key)} — {eur(t?.price)}/adulto</SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>

            {rdTier !== 'none' && (
              <>
                <div className="flex items-center justify-between">
                  <span className="text-sm">Adultos <span className="text-muted-foreground">({eur(rodizioCfg?.tiers?.[rdTier]?.price)})</span></span>
                  <div className="flex items-center gap-2">
                    <Button variant="outline" size="icon" className="h-8 w-8"
                      onClick={() => setRdAdults((n) => Math.max(0, (parseInt(n, 10) || 0) - 1))}>−</Button>
                    <span className="w-8 text-center font-semibold tabular-nums">{rdAdults}</span>
                    <Button variant="outline" size="icon" className="h-8 w-8"
                      onClick={() => setRdAdults((n) => (parseInt(n, 10) || 0) + 1)}>+</Button>
                  </div>
                </div>
                <div className="flex items-center justify-between">
                  <span className="text-sm">Crianças <span className="text-muted-foreground">(½ · {eur((Number(rodizioCfg?.tiers?.[rdTier]?.price) || 0) / 2)})</span></span>
                  <div className="flex items-center gap-2">
                    <Button variant="outline" size="icon" className="h-8 w-8"
                      onClick={() => setRdChildren((n) => Math.max(0, (parseInt(n, 10) || 0) - 1))}>−</Button>
                    <span className="w-8 text-center font-semibold tabular-nums">{rdChildren}</span>
                    <Button variant="outline" size="icon" className="h-8 w-8"
                      onClick={() => setRdChildren((n) => (parseInt(n, 10) || 0) + 1)}>+</Button>
                  </div>
                </div>
                {(rodPaid.adults > 0 || rodPaid.children > 0) && (
                  <p className="rounded-lg bg-muted/40 px-3 py-2 text-xs text-muted-foreground">
                    Já faturado: {rodPaid.adults} adulto(s){rodPaid.children ? `, ${rodPaid.children} criança(s)` : ''}. Os números acima são os TOTAIS da mesa.
                  </p>
                )}
              </>
            )}
          </div>
          <div className="mt-2 flex justify-end gap-2">
            <Button variant="outline" onClick={() => setRodizioOpen(false)}>Cancelar</Button>
            <Button onClick={saveRodizio} disabled={savingRodizio} className="bg-[#5a1a1a] hover:bg-[#4a1414]">
              {savingRodizio ? <Loader2 className="h-4 w-4 animate-spin mr-1" /> : null}
              Guardar
            </Button>
          </div>
        </DialogContent>
      </Dialog>
    </>
  );
};

export default TableCheckout;
