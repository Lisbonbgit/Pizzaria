import React, { useState, useEffect, useCallback, useRef } from 'react';
import { useSearchParams } from 'react-router-dom';
import { ShoppingCart, Plus, Minus, X, ChevronRight, Loader2, AlertCircle, CheckCircle2 } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { Sheet, SheetContent, SheetHeader, SheetTitle } from '@/components/ui/sheet';
import { Dialog, DialogContent, DialogHeader, DialogTitle } from '@/components/ui/dialog';
import { Textarea } from '@/components/ui/textarea';
import { ScrollArea } from '@/components/ui/scroll-area';
import { Checkbox } from '@/components/ui/checkbox';
import { RadioGroup, RadioGroupItem } from '@/components/ui/radio-group';
import { Label } from '@/components/ui/label';
import { toast } from 'sonner';
import { useCart } from '@/context/CartContext';
import { categoriesAPI, productsAPI, tablesAPI, ordersAPI, settingsAPI, rodizioAPI } from '@/lib/api';

const BACKEND_URL = process.env.REACT_APP_BACKEND_URL;

const getImageUrl = (url) => {
  if (!url) return null;
  if (url.startsWith('http')) return url;
  return `${BACKEND_URL}${url}`;
};

const MenuPage = () => {
  const [searchParams] = useSearchParams();
  const {
    items: cartItems, 
    tableNumber, 
    tableId,
    orderNotes,
    setOrderNotes,
    addItem, 
    updateItemQuantity, 
    removeItem, 
    clearCart,
    getTotal, 
    getItemCount,
    setTable 
  } = useCart();

  const [categories, setCategories] = useState([]);
  const [products, setProducts] = useState([]);
  const [restaurantName, setRestaurantName] = useState('Pizzaria');
  const [coverImage, setCoverImage] = useState('https://images.unsplash.com/photo-1709548145082-04d0cde481d4?w=1200&q=80');
  const [activeCategory, setActiveCategory] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [cartOpen, setCartOpen] = useState(false);
  const [productModalOpen, setProductModalOpen] = useState(false);
  const [selectedProduct, setSelectedProduct] = useState(null);
  const [productQuantity, setProductQuantity] = useState(1);
  const [selectedVariation, setSelectedVariation] = useState(null);
  const [selectedExtras, setSelectedExtras] = useState([]);
  const [selectedComplements, setSelectedComplements] = useState({});
  const [selectedPreference, setSelectedPreference] = useState(null);
  const [itemNotes, setItemNotes] = useState('');
  const [submitting, setSubmitting] = useState(false);

  // Sessão de mesa (nº de pessoas + conta)
  const [needsPeople, setNeedsPeople] = useState(false);
  const [peopleInput, setPeopleInput] = useState(2);
  const [openingTable, setOpeningTable] = useState(false);
  const [bill, setBill] = useState(null);
  const [billOpen, setBillOpen] = useState(false);
  const [orderSuccessOpen, setOrderSuccessOpen] = useState(false);
  const [rodizioCfg, setRodizioCfg] = useState(null);
  const [mode, setMode] = useState('none'); // none | alacarte | simples | completo
  const [gateStep, setGateStep] = useState('mode'); // mode | people | rodizio
  const [chosenTier, setChosenTier] = useState('simples');
  const [adultsInput, setAdultsInput] = useState(2);
  const [childrenInput, setChildrenInput] = useState(0);

  const eur = (v) => `€ ${Number(v || 0).toFixed(2)}`;
  const isRodizio = mode === 'simples' || mode === 'completo';
  const isIncluded = (p) => {
    if (mode === 'simples') return p.rodizio_incluido === 'ambos';
    if (mode === 'completo') return p.rodizio_incluido === 'ambos' || p.rodizio_incluido === 'completo';
    return false;
  };
  const mediaVariation = (p) => {
    const vs = p.variations || [];
    return vs.find((v) => /m[ée]d/i.test(v.name)) || [...vs].sort((a, b) => (a.price || 0) - (b.price || 0))[0] || null;
  };

  // Refs for scroll tracking
  const sectionRefs = useRef({});
  const categoryBarRef = useRef(null);
  const activeBtnRef = useRef(null);
  const isScrollingProgrammatically = useRef(false);

  // Initialize table from URL
  useEffect(() => {
    const mesa = searchParams.get('mesa');
    if (mesa) {
      const tableNum = parseInt(mesa);
      if (!isNaN(tableNum)) {
        tablesAPI.getByNumber(tableNum)
          .then(res => {
            setTable(res.data.number, res.data.id);
          })
          .catch(() => {
            toast.error('Mesa não encontrada');
          });
        tablesAPI.getSession(tableNum)
          .then(res => {
            setBill(res.data.bill);
            setNeedsPeople(!res.data.open);
            if (res.data.open) setMode(res.data.rodizio && res.data.rodizio !== 'none' ? res.data.rodizio : 'alacarte');
          })
          .catch(() => {});
      }
    }
  }, [searchParams, setTable]);

  // Load menu data
  const loadData = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [catsRes, prodsRes, settingsRes] = await Promise.all([
        categoriesAPI.list(true),
        productsAPI.list(null, true),
        settingsAPI.getRestaurantPublic()
      ]);
      
      setCategories(catsRes.data);
      setProducts(prodsRes.data);
      setRestaurantName(settingsRes.data.name || 'Pizzaria');
      
      if (settingsRes.data.cover_image) {
        const img = settingsRes.data.cover_image;
        if (img.startsWith('/')) {
          setCoverImage(`${process.env.REACT_APP_BACKEND_URL}${img}`);
        } else {
          setCoverImage(img);
        }
      }
      
      if (catsRes.data.length > 0) {
        setActiveCategory(catsRes.data[0].id);
      }
      rodizioAPI.public().then((r) => setRodizioCfg(r.data)).catch(() => {});
    } catch (err) {
      console.error('Error loading menu:', err);
      setError('Erro ao carregar o menu. Tente novamente.');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    loadData();
  }, [loadData]);

  // IntersectionObserver for scroll tracking
  useEffect(() => {
    if (categories.length === 0) return;

    const observerOptions = {
      root: null,
      rootMargin: '-120px 0px -60% 0px',
      threshold: 0
    };

    const observer = new IntersectionObserver((entries) => {
      if (isScrollingProgrammatically.current) return;

      entries.forEach((entry) => {
        if (entry.isIntersecting) {
          const catId = entry.target.getAttribute('data-category-id');
          if (catId) {
            setActiveCategory(catId);
          }
        }
      });
    }, observerOptions);

    // Observe all section elements
    Object.values(sectionRefs.current).forEach((ref) => {
      if (ref) observer.observe(ref);
    });

    return () => observer.disconnect();
  }, [categories, products]);

  // Auto-scroll the category bar to keep active button visible
  useEffect(() => {
    if (activeBtnRef.current && categoryBarRef.current) {
      const bar = categoryBarRef.current;
      const btn = activeBtnRef.current;
      const barRect = bar.getBoundingClientRect();
      const btnRect = btn.getBoundingClientRect();

      if (btnRect.left < barRect.left || btnRect.right > barRect.right) {
        btn.scrollIntoView({ behavior: 'smooth', inline: 'center', block: 'nearest' });
      }
    }
  }, [activeCategory]);

  // Scroll to category section
  const scrollToCategory = (categoryId) => {
    const section = sectionRefs.current[categoryId];
    if (!section) return;

    isScrollingProgrammatically.current = true;
    setActiveCategory(categoryId);

    const stickyBarHeight = 64;
    const sectionTop = section.getBoundingClientRect().top + window.scrollY - stickyBarHeight;

    window.scrollTo({
      top: sectionTop,
      behavior: 'smooth'
    });

    // Re-enable observer after scroll animation finishes
    setTimeout(() => {
      isScrollingProgrammatically.current = false;
    }, 800);
  };

  // Group products by category.
  // Produtos "só rodízio" ficam escondidos do menu normal (à la carte).
  const productsByCategory = categories
    .map(cat => ({
      category: cat,
      products: products.filter(p => p.category_id === cat.id && (isRodizio || !p.rodizio_only))
    }))
    .filter(group => group.products.length > 0);

  const openProductModal = (product) => {
    setSelectedProduct(product);
    setProductQuantity(1);
    setSelectedVariation(
      (isRodizio && isIncluded(product))
        ? mediaVariation(product)
        : (product.variations?.length > 0 ? product.variations[0] : null)
    );
    setSelectedExtras([]);
    setSelectedComplements({});
    setSelectedPreference(null);
    setItemNotes('');
    setProductModalOpen(true);
  };

  const handleAddToCart = () => {
    if (!selectedProduct) return;
    
    // Validate complement groups
    const groups = selectedProduct.complement_groups || [];
    for (const group of groups) {
      const selected = selectedComplements[group.name] || [];
      if (selected.length < group.min_selections) {
        toast.error(`Selecione pelo menos ${group.min_selections} opção em "${group.name}"`);
        return;
      }
    }
    
    // Validate preference
    const prefs = selectedProduct.preference_options;
    if (prefs?.enabled && prefs?.required && !selectedPreference) {
      toast.error(`Selecione uma opção em "${prefs.label || 'Preferências'}"`);
      return;
    }
    
    // Build complements array
    const complementsForCart = groups
      .filter(g => (selectedComplements[g.name] || []).length > 0)
      .map(g => ({
        group_name: g.name,
        items: selectedComplements[g.name] || []
      }));
    
    const included = isRodizio && isIncluded(selectedProduct);
    addItem(
      selectedProduct,
      productQuantity,
      selectedVariation,
      selectedExtras,
      itemNotes,
      complementsForCart,
      selectedPreference,
      included ? 0 : null
    );

    toast.success(included ? 'Incluído no rodízio' : 'Adicionado ao carrinho');
    setProductModalOpen(false);
  };

  const calculateItemPrice = () => {
    if (!selectedProduct) return 0;
    let price = selectedVariation?.price || selectedProduct.base_price;
    price += selectedExtras.reduce((sum, e) => sum + e.price, 0);
    // Add complement prices
    Object.values(selectedComplements).forEach(items => {
      items.forEach(item => { price += item.price || 0; });
    });
    return price * productQuantity;
  };

  const handleSubmitOrder = async () => {
    if (!tableNumber || !tableId) {
      toast.error('Mesa não identificada. Por favor, leia o QR Code da mesa.');
      return;
    }
    
    if (cartItems.length === 0) {
      toast.error('O carrinho está vazio');
      return;
    }

    setSubmitting(true);
    try {
      const orderData = {
        table_id: tableId,
        table_number: tableNumber,
        items: cartItems.map(item => ({
          product_id: item.product_id,
          product_name: item.product_name,
          quantity: item.quantity,
          variation: item.variation,
          extras: item.extras,
          selected_complements: item.selected_complements || [],
          selected_preference: item.selected_preference || null,
          notes: item.notes,
          unit_price: item.unit_price,
          total_price: item.total_price
        })),
        notes: orderNotes,
        total: getTotal()
      };

      await ordersAPI.create(orderData);
      clearCart();
      setCartOpen(false);
      await refreshBill();           // hero passa a mostrar "Ver conta"
      setOrderSuccessOpen(true);
    } catch (err) {
      console.error('Error submitting order:', err);
      toast.error('Erro ao enviar pedido. Tente novamente.');
    } finally {
      setSubmitting(false);
    }
  };

  const toggleExtra = (extra) => {
    setSelectedExtras(prev => {
      const exists = prev.find(e => e.name === extra.name);
      if (exists) {
        return prev.filter(e => e.name !== extra.name);
      }
      return [...prev, extra];
    });
  };

  const submitPeople = async () => {
    if (!tableNumber) return;
    setOpeningTable(true);
    try {
      await tablesAPI.openSession(tableNumber, { people: Math.max(1, Number(peopleInput) || 1) });
      setMode('alacarte');
      setNeedsPeople(false);
    } catch {
      toast.error('Não foi possível abrir a mesa');
    } finally {
      setOpeningTable(false);
    }
  };

  const submitRodizio = async () => {
    if (!tableNumber) return;
    setOpeningTable(true);
    try {
      await tablesAPI.openSession(tableNumber, {
        rodizio: chosenTier,
        adults: adultsInput,
        children: childrenInput,
      });
      setMode(chosenTier);
      setNeedsPeople(false);
      refreshBill();  // a conta já arranca no valor fixo por pessoa
    } catch {
      toast.error('Não foi possível abrir a mesa');
    } finally {
      setOpeningTable(false);
    }
  };

  const refreshBill = async () => {
    if (!tableNumber) return;
    try {
      const res = await tablesAPI.getSession(tableNumber);
      setBill(res.data.bill);
    } catch { /* ignore */ }
  };

  if (loading) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-background">
        <div className="text-center">
          <Loader2 className="h-8 w-8 animate-spin mx-auto text-primary" />
          <p className="mt-4 text-muted-foreground">A carregar menu...</p>
        </div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-background p-4">
        <div className="text-center">
          <AlertCircle className="h-12 w-12 mx-auto text-destructive" />
          <p className="mt-4 text-lg">{error}</p>
          <Button onClick={loadData} className="mt-4">Tentar novamente</Button>
        </div>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-background pb-24">
      {/* Entrada — 1ª leitura do QR numa mesa livre */}
      {needsPeople && tableNumber && (
        <div className="fixed inset-0 z-[60] bg-background flex flex-col items-center justify-center p-6 text-center">
          <div className="w-full max-w-xs space-y-8">
            <div>
              <p className="text-xs uppercase tracking-wide text-muted-foreground">Mesa {tableNumber}</p>
              <h2 className="font-heading text-3xl font-bold mt-2">Bem-vindo à {restaurantName}! 👋</h2>
            </div>

            {rodizioCfg?.available_today && gateStep === 'mode' ? (
              /* Escolha do modo: à la carte vs rodízio */
              <div className="space-y-3">
                <p className="text-muted-foreground">Como querem pedir hoje?</p>
                <button type="button"
                  onClick={() => { setMode('alacarte'); setGateStep('people'); }}
                  className="w-full rounded-xl border-2 p-4 text-left active:scale-[0.98] transition">
                  <p className="font-heading text-lg font-bold">À la carte</p>
                  <p className="text-sm text-muted-foreground">Menu normal, paga o que pedir</p>
                </button>
                <button type="button"
                  onClick={() => { setChosenTier('simples'); setGateStep('rodizio'); }}
                  className="w-full rounded-xl border-2 border-primary bg-primary/5 p-4 text-left active:scale-[0.98] transition">
                  <div className="flex items-baseline justify-between gap-2">
                    <p className="font-heading text-lg font-bold text-primary">{rodizioCfg.tiers?.simples?.name || 'Rodízio Simples'}</p>
                    <p className="text-sm font-semibold text-primary shrink-0">{eur(rodizioCfg.tiers?.simples?.price)}/pessoa</p>
                  </div>
                  {rodizioCfg.tiers?.simples?.description && (
                    <p className="text-xs text-muted-foreground mt-1">{rodizioCfg.tiers.simples.description}</p>
                  )}
                </button>
                <button type="button"
                  onClick={() => { setChosenTier('completo'); setGateStep('rodizio'); }}
                  className="w-full rounded-xl border-2 border-primary bg-primary/5 p-4 text-left active:scale-[0.98] transition">
                  <div className="flex items-baseline justify-between gap-2">
                    <p className="font-heading text-lg font-bold text-primary">{rodizioCfg.tiers?.completo?.name || 'Rodízio Completo'}</p>
                    <p className="text-sm font-semibold text-primary shrink-0">{eur(rodizioCfg.tiers?.completo?.price)}/pessoa</p>
                  </div>
                  {rodizioCfg.tiers?.completo?.description && (
                    <p className="text-xs text-muted-foreground mt-1">{rodizioCfg.tiers.completo.description}</p>
                  )}
                </button>
                {rodizioCfg.waste_note && (
                  <p className="text-xs text-muted-foreground pt-1">{rodizioCfg.waste_note}</p>
                )}
              </div>
            ) : gateStep === 'rodizio' ? (
              /* Rodízio: adultos + crianças */
              <div className="space-y-5">
                <p className="text-muted-foreground">
                  {(chosenTier === 'completo' ? rodizioCfg?.tiers?.completo?.name : rodizioCfg?.tiers?.simples?.name)
                    || 'Rodízio'} — quantos são?
                </p>
                <div className="flex items-center justify-between px-2">
                  <span className="font-medium">Adultos</span>
                  <div className="flex items-center gap-4">
                    <button type="button" onClick={() => setAdultsInput((p) => Math.max(0, p - 1))}
                      className="h-11 w-11 rounded-full border-2 text-xl font-bold text-primary active:scale-95 transition">−</button>
                    <span className="font-heading text-3xl font-bold w-10 tabular-nums">{adultsInput}</span>
                    <button type="button" onClick={() => setAdultsInput((p) => p + 1)}
                      className="h-11 w-11 rounded-full border-2 text-xl font-bold text-primary active:scale-95 transition">+</button>
                  </div>
                </div>
                <div className="flex items-center justify-between px-2">
                  <span className="font-medium">Crianças</span>
                  <div className="flex items-center gap-4">
                    <button type="button" onClick={() => setChildrenInput((p) => Math.max(0, p - 1))}
                      className="h-11 w-11 rounded-full border-2 text-xl font-bold text-primary active:scale-95 transition">−</button>
                    <span className="font-heading text-3xl font-bold w-10 tabular-nums">{childrenInput}</span>
                    <button type="button" onClick={() => setChildrenInput((p) => p + 1)}
                      className="h-11 w-11 rounded-full border-2 text-xl font-bold text-primary active:scale-95 transition">+</button>
                  </div>
                </div>
                <p className="text-xs text-muted-foreground">
                  As idades das crianças (grátis ou meia) são confirmadas pela equipa no fim.
                </p>
                <Button onClick={submitRodizio} disabled={openingTable} className="w-full h-12 text-base">
                  {openingTable ? <Loader2 className="h-5 w-5 animate-spin" /> : 'Ver o menu'}
                </Button>
                <button type="button" className="text-xs text-muted-foreground underline"
                  onClick={() => setGateStep('mode')}>voltar</button>
              </div>
            ) : (
              /* À la carte (ou dia sem rodízio): nº de pessoas */
              <>
                <p className="text-muted-foreground -mt-4">Quantas pessoas estão na mesa?</p>
                <div className="flex items-center justify-center gap-5">
                  <button type="button" onClick={() => setPeopleInput((p) => Math.max(1, p - 1))}
                    className="h-14 w-14 rounded-full border-2 text-2xl font-bold text-primary active:scale-95 transition">−</button>
                  <span className="font-heading text-5xl font-bold w-20 tabular-nums">{peopleInput}</span>
                  <button type="button" onClick={() => setPeopleInput((p) => p + 1)}
                    className="h-14 w-14 rounded-full border-2 text-2xl font-bold text-primary active:scale-95 transition">+</button>
                </div>
                <Button onClick={submitPeople} disabled={openingTable} className="w-full h-12 text-base">
                  {openingTable ? <Loader2 className="h-5 w-5 animate-spin" /> : 'Ver o menu'}
                </Button>
                {rodizioCfg?.available_today && (
                  <button type="button" className="text-xs text-muted-foreground underline"
                    onClick={() => setGateStep('mode')}>voltar às opções</button>
                )}
              </>
            )}
          </div>
        </div>
      )}

      {/* Pedido enviado — voltar ao menu ou ver conta */}
      <Dialog open={orderSuccessOpen} onOpenChange={setOrderSuccessOpen}>
        <DialogContent className="max-w-sm text-center">
          <DialogHeader>
            <DialogTitle className="font-heading text-2xl flex flex-col items-center gap-3">
              <span className="flex h-14 w-14 items-center justify-center rounded-full bg-green-100">
                <CheckCircle2 className="h-8 w-8 text-green-600" />
              </span>
              Pedido enviado!
            </DialogTitle>
          </DialogHeader>
          <p className="text-muted-foreground">
            O seu pedido foi para a cozinha. Deseja pedir mais alguma coisa?
          </p>
          <div className="grid gap-2 pt-2">
            <Button onClick={() => setOrderSuccessOpen(false)} className="w-full h-11">
              Fazer novo pedido
            </Button>
            <Button variant="outline" className="w-full h-11"
              onClick={() => { setOrderSuccessOpen(false); refreshBill(); setBillOpen(true); }}>
              Ver conta
            </Button>
          </div>
        </DialogContent>
      </Dialog>

      {/* Conta da mesa (cliente) */}
      <Dialog open={billOpen} onOpenChange={setBillOpen}>
        <DialogContent className="max-w-sm">
          <DialogHeader>
            <DialogTitle className="font-heading text-xl">Conta da Mesa {tableNumber}</DialogTitle>
          </DialogHeader>
          <div className="space-y-1 py-2 max-h-[60vh] overflow-y-auto">
            {bill && bill.lines && bill.lines.length > 0 ? (
              <>
                {bill.lines.map((l, i) => (
                  <div key={i} className="flex justify-between text-sm border-b last:border-0 py-1.5">
                    <span>
                      {l.quantity}× {l.product_name}
                      {l.source === 'manual' && (
                        <span className="ml-1.5 text-[10px] uppercase tracking-wide text-amber-700 font-semibold">balcão</span>
                      )}
                    </span>
                    <span className="tabular-nums">{`€ ${Number(l.total_price || 0).toFixed(2)}`}</span>
                  </div>
                ))}
                <div className="flex justify-between font-bold text-lg pt-3">
                  <span>Total</span>
                  <span className="tabular-nums">{`€ ${Number(bill.total || 0).toFixed(2)}`}</span>
                </div>
              </>
            ) : (
              <p className="text-center text-muted-foreground py-6">Ainda sem pedidos nesta mesa.</p>
            )}
          </div>
        </DialogContent>
      </Dialog>

      {/* Hero Header */}
      <div 
        className="relative h-48 md:h-64 bg-cover bg-center"
        style={{ 
          backgroundImage: `url('${coverImage}')` 
        }}
      >
        <div className="absolute inset-0 menu-hero-gradient" />
        <div className="absolute inset-0 flex flex-col justify-end p-6">
          <h1 className="font-heading text-4xl md:text-5xl font-bold text-white tracking-tight">
            {restaurantName}
          </h1>
          {tableNumber && (
            <div className="mt-2 flex items-center gap-3">
              <Badge variant="secondary" className="w-fit text-sm px-3 py-1">Mesa {tableNumber}</Badge>
              {bill && bill.orders > 0 && (
                <button onClick={() => { refreshBill(); setBillOpen(true); }}
                  className="text-sm font-medium text-white/90 underline underline-offset-2">
                  Ver conta (€ {Number(bill.total || 0).toFixed(2)})
                </button>
              )}
            </div>
          )}
        </div>
      </div>

      {/* Sticky Category Navigation */}
      <div className="sticky top-0 z-40 bg-background/95 backdrop-blur border-b">
        <div 
          ref={categoryBarRef}
          className="flex gap-2 p-4 overflow-x-auto scrollbar-hide"
          style={{ scrollBehavior: 'smooth' }}
        >
          {productsByCategory.map(({ category: cat }) => {
            const isActive = activeCategory === cat.id;
            return (
              <button
                key={cat.id}
                ref={isActive ? activeBtnRef : null}
                onClick={() => scrollToCategory(cat.id)}
                data-testid={`category-${cat.id}`}
                className={`px-4 py-2 rounded-full text-sm font-medium whitespace-nowrap transition-all ${
                  isActive
                    ? 'bg-primary text-primary-foreground shadow-md'
                    : 'bg-secondary text-secondary-foreground hover:bg-secondary/80'
                }`}
              >
                {cat.name}
              </button>
            );
          })}
        </div>
      </div>

      {/* Banner do modo rodízio */}
      {isRodizio && (
        <div className="mx-4 mt-4 md:mx-6 rounded-xl border border-primary/30 bg-primary/5 p-3 text-center">
          <p className="font-heading font-bold text-primary">
            🍕 {mode === 'completo'
              ? (rodizioCfg?.tiers?.completo?.name || 'Rodízio Completo')
              : (rodizioCfg?.tiers?.simples?.name || 'Rodízio Simples')} ativo
          </p>
          <p className="text-xs text-muted-foreground mt-0.5">
            Os itens marcados <span className="font-semibold text-green-700">Incluído</span> já entram no preço por pessoa. Pizzas servidas em tamanho médio.
            {rodizioCfg?.waste_note ? ` ${rodizioCfg.waste_note}` : ''}
          </p>
          {bill && (bill.total || 0) > 0 && (
            <p className="mt-2 font-heading text-lg font-bold text-primary">
              Conta da mesa: {eur(bill.total)}
            </p>
          )}
        </div>
      )}

      {/* Continuous Scroll — All Categories */}
      <div className="p-4 md:p-6 space-y-10">
        {productsByCategory.map(({ category, products: catProducts }) => (
          <section
            key={category.id}
            ref={(el) => { sectionRefs.current[category.id] = el; }}
            data-category-id={category.id}
            className="scroll-mt-20"
          >
            {/* Category Title */}
            <h2 className="font-heading text-2xl md:text-3xl font-bold mb-4 pb-2 border-b border-border">
              {category.name}
            </h2>

            {/* Products Grid */}
            <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-3">
              {catProducts.map((product) => (
                <div
                  key={product.id}
                  data-testid={`product-card-${product.id}`}
                  onClick={() => openProductModal(product)}
                  className="product-card bg-card rounded-xl overflow-hidden border border-border hover:shadow-lg transition-all cursor-pointer group"
                >
                  <div className="relative h-40 md:h-48 overflow-hidden">
                    <img
                      src={getImageUrl(product.image_url) || 'https://images.unsplash.com/photo-1574071318508-1cdbab80d002?w=600'}
                      alt={product.name}
                      className="product-card-image w-full h-full object-cover"
                    />
                    {product.featured && (
                      <div className="absolute top-3 left-3">
                        <Badge className="featured-badge text-xs border-0">
                          Destaque
                        </Badge>
                      </div>
                    )}
                    {isRodizio && isIncluded(product) && (
                      <div className="absolute top-3 right-3">
                        <Badge className="bg-green-600 text-white text-xs border-0">
                          Incluído
                        </Badge>
                      </div>
                    )}
                  </div>
                  <div className="p-4">
                    <h3 className="font-heading text-lg font-semibold">{product.name}</h3>
                    <p className="text-sm text-muted-foreground mt-1 line-clamp-2">
                      {product.description}
                    </p>
                    <div className="flex items-center justify-between mt-3">
                      {isRodizio && isIncluded(product) ? (
                        <span className="font-bold text-lg text-green-700">Incluído</span>
                      ) : (
                        <span className="font-bold text-lg">
                          € {product.base_price.toFixed(2)}
                        </span>
                      )}
                      <Button size="sm" className="rounded-full px-4">
                        <Plus className="h-4 w-4 mr-1" />
                        Adicionar
                      </Button>
                    </div>
                  </div>
                </div>
              ))}
            </div>
          </section>
        ))}
      </div>

      {/* Product Detail Modal */}
      <Dialog open={productModalOpen} onOpenChange={setProductModalOpen}>
        <DialogContent className="max-w-lg max-h-[90vh] overflow-y-auto">
          {selectedProduct && (
            <>
              <div className="relative h-48 -mx-6 -mt-6 overflow-hidden rounded-t-lg">
                <img
                  src={getImageUrl(selectedProduct.image_url) || 'https://images.unsplash.com/photo-1574071318508-1cdbab80d002?w=600'}
                  alt={selectedProduct.name}
                  className="w-full h-full object-cover"
                />
              </div>
              <DialogHeader className="mt-4">
                <DialogTitle className="font-heading text-2xl">{selectedProduct.name}</DialogTitle>
              </DialogHeader>
              <p className="text-muted-foreground">{selectedProduct.description}</p>

              {/* No rodízio: pizza servida sempre em tamanho médio, sem escolha */}
              {isRodizio && isIncluded(selectedProduct) && selectedProduct.variations?.length > 0 && (
                <div className="mt-4 rounded-lg border border-green-600/30 bg-green-50 p-3 text-sm text-green-800">
                  Servido em tamanho <span className="font-semibold">médio</span> — incluído no rodízio.
                </div>
              )}

              {/* Variations */}
              {selectedProduct.variations?.length > 0 && !(isRodizio && isIncluded(selectedProduct)) && (
                <div className="mt-4">
                  <Label className="text-sm font-semibold uppercase tracking-wide text-muted-foreground">
                    Tamanho
                  </Label>
                  <RadioGroup
                    value={selectedVariation?.name || ''}
                    onValueChange={(value) => {
                      const v = selectedProduct.variations.find(v => v.name === value);
                      setSelectedVariation(v);
                    }}
                    className="mt-2 grid gap-2"
                  >
                    {selectedProduct.variations.map((variation) => (
                      <div
                        key={variation.name}
                        className="flex items-center justify-between p-3 rounded-lg border border-border hover:bg-secondary/50 cursor-pointer"
                        onClick={() => setSelectedVariation(variation)}
                      >
                        <div className="flex items-center gap-3">
                          <RadioGroupItem value={variation.name} id={variation.name} />
                          <Label htmlFor={variation.name} className="cursor-pointer">
                            {variation.name}
                          </Label>
                        </div>
                        <span className="font-semibold">€ {variation.price.toFixed(2)}</span>
                      </div>
                    ))}
                  </RadioGroup>
                </div>
              )}

              {/* Extras */}
              {selectedProduct.extras?.length > 0 && (
                <div className="mt-4">
                  <Label className="text-sm font-semibold uppercase tracking-wide text-muted-foreground">
                    Extras
                  </Label>
                  <div className="mt-2 grid gap-2">
                    {selectedProduct.extras.map((extra) => (
                      <div
                        key={extra.name}
                        className="flex items-center justify-between p-3 rounded-lg border border-border hover:bg-secondary/50 cursor-pointer"
                        onClick={() => toggleExtra(extra)}
                      >
                        <div className="flex items-center gap-3">
                          <Checkbox 
                            checked={selectedExtras.some(e => e.name === extra.name)}
                            onCheckedChange={() => toggleExtra(extra)}
                          />
                          <span>{extra.name}</span>
                        </div>
                        <span className="font-semibold">+ € {extra.price.toFixed(2)}</span>
                      </div>
                    ))}
                  </div>
                </div>
              )}

              {/* Complement Groups */}
              {(selectedProduct.complement_groups || []).map((group) => {
                const selected = selectedComplements[group.name] || [];
                const atMax = selected.length >= group.max_selections;
                return (
                  <div key={group.name} className="mt-4">
                    <div className="flex items-center justify-between">
                      <Label className="text-sm font-semibold uppercase tracking-wide text-muted-foreground">
                        {group.name}
                      </Label>
                      <span className="text-xs text-muted-foreground">
                        {group.min_selections > 0 ? `Mín: ${group.min_selections}` : 'Opcional'} • Máx: {group.max_selections}
                        {selected.length > 0 && ` (${selected.length} selecionado${selected.length > 1 ? 's' : ''})`}
                      </span>
                    </div>
                    <div className="mt-2 grid gap-2">
                      {group.items.map((compItem) => {
                        const isSelected = selected.some(s => s.name === compItem.name);
                        return (
                          <div
                            key={compItem.name}
                            className={`flex items-center justify-between p-3 rounded-lg border cursor-pointer transition-colors ${
                              isSelected ? 'border-primary bg-primary/5' : 'border-border hover:bg-secondary/50'
                            } ${!isSelected && atMax ? 'opacity-50 cursor-not-allowed' : ''}`}
                            onClick={() => {
                              if (isSelected) {
                                setSelectedComplements(prev => ({
                                  ...prev,
                                  [group.name]: prev[group.name].filter(s => s.name !== compItem.name)
                                }));
                              } else if (!atMax) {
                                setSelectedComplements(prev => ({
                                  ...prev,
                                  [group.name]: [...(prev[group.name] || []), compItem]
                                }));
                              }
                            }}
                          >
                            <div className="flex items-center gap-3">
                              <Checkbox checked={isSelected} />
                              <span>{compItem.name}</span>
                            </div>
                            {compItem.price > 0 && (
                              <span className="font-semibold">+ € {compItem.price.toFixed(2)}</span>
                            )}
                          </div>
                        );
                      })}
                    </div>
                  </div>
                );
              })}

              {/* Preference Options */}
              {selectedProduct.preference_options?.enabled && (
                <div className="mt-4">
                  <Label className="text-sm font-semibold uppercase tracking-wide text-muted-foreground">
                    {selectedProduct.preference_options.label || 'Preferências'}
                    {selectedProduct.preference_options.required && (
                      <span className="text-destructive ml-1">*</span>
                    )}
                  </Label>
                  <RadioGroup
                    value={selectedPreference || ''}
                    onValueChange={(value) => setSelectedPreference(value)}
                    className="mt-2 grid gap-2"
                  >
                    {(selectedProduct.preference_options.options || []).map((opt) => (
                      <div
                        key={opt}
                        className="flex items-center gap-3 p-3 rounded-lg border border-border hover:bg-secondary/50 cursor-pointer"
                        onClick={() => setSelectedPreference(opt)}
                      >
                        <RadioGroupItem value={opt} id={`pref-${opt}`} />
                        <Label htmlFor={`pref-${opt}`} className="cursor-pointer flex-1">{opt}</Label>
                      </div>
                    ))}
                  </RadioGroup>
                </div>
              )}

              {/* Notes — hidden for Bebidas */}
              {(() => {
                const cat = categories.find(c => c.id === selectedProduct.category_id);
                const isBebida = cat && cat.name.toLowerCase() === 'bebidas';
                return !isBebida ? (
                  <div className="mt-4">
                    <Label className="text-sm font-semibold uppercase tracking-wide text-muted-foreground">
                      Observações
                    </Label>
                    <Textarea
                      placeholder="Ex: Sem cebola, bem passada..."
                      value={itemNotes}
                      onChange={(e) => setItemNotes(e.target.value)}
                      className="mt-2"
                    />
                  </div>
                ) : null;
              })()}

              {/* Quantity & Add */}
              <div className="mt-6 flex items-center justify-between">
                <div className="flex items-center gap-3 bg-secondary rounded-full p-1">
                  <Button
                    variant="ghost"
                    size="icon"
                    className="h-10 w-10 rounded-full"
                    onClick={() => setProductQuantity(Math.max(1, productQuantity - 1))}
                  >
                    <Minus className="h-4 w-4" />
                  </Button>
                  <span className="w-8 text-center font-semibold text-lg">{productQuantity}</span>
                  <Button
                    variant="ghost"
                    size="icon"
                    className="h-10 w-10 rounded-full"
                    onClick={() => setProductQuantity(productQuantity + 1)}
                  >
                    <Plus className="h-4 w-4" />
                  </Button>
                </div>
                <Button
                  size="lg"
                  className="rounded-full px-8"
                  onClick={handleAddToCart}
                  data-testid="add-to-cart-btn"
                >
                  {isRodizio && isIncluded(selectedProduct)
                    ? 'Adicionar (Incluído)'
                    : `Adicionar € ${calculateItemPrice().toFixed(2)}`}
                </Button>
              </div>
            </>
          )}
        </DialogContent>
      </Dialog>

      {/* Cart Sheet */}
      <Sheet open={cartOpen} onOpenChange={setCartOpen}>
        <SheetContent className="w-full sm:max-w-lg flex flex-col">
          <SheetHeader>
            <SheetTitle className="font-heading text-2xl">O Seu Pedido</SheetTitle>
          </SheetHeader>
          
          {cartItems.length === 0 ? (
            <div className="flex-1 flex flex-col items-center justify-center text-center">
              <ShoppingCart className="h-16 w-16 text-muted-foreground mb-4" />
              <p className="text-lg text-muted-foreground">O carrinho está vazio</p>
              <p className="text-sm text-muted-foreground mt-1">
                Adicione itens do menu para começar
              </p>
            </div>
          ) : (
            <>
              <ScrollArea className="flex-1 -mx-6 px-6">
                <div className="space-y-4 py-4">
                  {cartItems.map((item) => (
                    <div 
                      key={item.id} 
                      className="flex gap-3 p-3 bg-secondary/50 rounded-lg"
                      data-testid={`cart-item-${item.id}`}
                    >
                      <img
                        src={item.product_image || 'https://images.unsplash.com/photo-1574071318508-1cdbab80d002?w=200'}
                        alt={item.product_name}
                        className="w-20 h-20 object-cover rounded-lg"
                      />
                      <div className="flex-1 min-w-0">
                        <div className="flex justify-between items-start">
                          <h4 className="font-semibold truncate pr-2">{item.product_name}</h4>
                          <Button
                            variant="ghost"
                            size="icon"
                            className="h-6 w-6 shrink-0"
                            onClick={() => removeItem(item.id)}
                          >
                            <X className="h-4 w-4" />
                          </Button>
                        </div>
                        {item.variation && (
                          <p className="text-sm text-muted-foreground">{item.variation.name}</p>
                        )}
                        {item.extras?.length > 0 && (
                          <p className="text-xs text-muted-foreground">
                            + {item.extras.map(e => e.name).join(', ')}
                          </p>
                        )}
                        {item.selected_complements?.length > 0 && (
                          <div className="text-xs text-muted-foreground">
                            {item.selected_complements.map((group, gIdx) => (
                              <p key={gIdx}>+ {group.items.map(i => i.name).join(', ')}</p>
                            ))}
                          </div>
                        )}
                        {item.selected_preference && (
                          <p className="text-xs text-primary font-medium">{item.selected_preference}</p>
                        )}
                        {item.notes && (
                          <p className="text-xs text-muted-foreground italic">"{item.notes}"</p>
                        )}
                        <div className="flex items-center justify-between mt-2">
                          <div className="flex items-center gap-2 bg-background rounded-full p-0.5">
                            <Button
                              variant="ghost"
                              size="icon"
                              className="h-7 w-7 rounded-full"
                              onClick={() => updateItemQuantity(item.id, item.quantity - 1)}
                            >
                              <Minus className="h-3 w-3" />
                            </Button>
                            <span className="w-6 text-center text-sm font-semibold">
                              {item.quantity}
                            </span>
                            <Button
                              variant="ghost"
                              size="icon"
                              className="h-7 w-7 rounded-full"
                              onClick={() => updateItemQuantity(item.id, item.quantity + 1)}
                            >
                              <Plus className="h-3 w-3" />
                            </Button>
                          </div>
                          <span className="font-bold">€ {item.total_price.toFixed(2)}</span>
                        </div>
                      </div>
                    </div>
                  ))}
                </div>
              </ScrollArea>

              {/* Order Notes */}
              <div className="py-4 border-t">
                <Label className="text-sm font-semibold uppercase tracking-wide text-muted-foreground">
                  Observações do Pedido
                </Label>
                <Textarea
                  placeholder="Alguma observação para a cozinha?"
                  value={orderNotes}
                  onChange={(e) => setOrderNotes(e.target.value)}
                  className="mt-2"
                />
              </div>

              {/* Total & Submit */}
              <div className="border-t pt-4 space-y-4">
                {tableNumber && (
                  <div className="flex justify-between items-center text-sm">
                    <span className="text-muted-foreground">Mesa</span>
                    <Badge variant="outline">{tableNumber}</Badge>
                  </div>
                )}
                <div className="flex justify-between items-center">
                  <span className="text-lg">Total</span>
                  <span className="text-2xl font-bold">€ {getTotal().toFixed(2)}</span>
                </div>
                <Button 
                  size="lg" 
                  className="w-full rounded-full"
                  onClick={handleSubmitOrder}
                  disabled={submitting || !tableNumber}
                  data-testid="submit-order-btn"
                >
                  {submitting ? (
                    <>
                      <Loader2 className="h-4 w-4 mr-2 animate-spin" />
                      A enviar...
                    </>
                  ) : (
                    <>
                      Finalizar — Enviar para a cozinha
                      <ChevronRight className="h-4 w-4 ml-2" />
                    </>
                  )}
                </Button>
                {!tableNumber && (
                  <p className="text-sm text-center text-muted-foreground">
                    Por favor, leia o QR Code da sua mesa
                  </p>
                )}
              </div>
            </>
          )}
        </SheetContent>
      </Sheet>

      {/* Bottom Cart Button */}
      <div className="fixed bottom-0 left-0 right-0 p-4 bg-background/95 backdrop-blur border-t bottom-nav pb-safe z-50">
        <Button
          size="lg"
          className="w-full rounded-full relative"
          onClick={() => setCartOpen(true)}
          data-testid="open-cart-btn"
        >
          <ShoppingCart className="h-5 w-5 mr-2" />
          Ver Carrinho
          {getItemCount() > 0 && (
            <Badge className="absolute -top-2 -right-2 h-6 min-w-6 rounded-full cart-badge">
              {getItemCount()}
            </Badge>
          )}
          <span className="ml-auto font-bold">€ {getTotal().toFixed(2)}</span>
        </Button>
      </div>
    </div>
  );
};

export default MenuPage;
