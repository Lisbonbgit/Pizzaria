import React, { useState, useEffect, useCallback, useRef } from 'react';
import { useSearchParams, useNavigate } from 'react-router-dom';
import { ShoppingCart, Plus, Minus, X, ChevronRight, Loader2, AlertCircle } from 'lucide-react';
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
import { categoriesAPI, productsAPI, tablesAPI, ordersAPI, seedAPI, settingsAPI } from '@/lib/api';

const BACKEND_URL = process.env.REACT_APP_BACKEND_URL;

const getImageUrl = (url) => {
  if (!url) return null;
  if (url.startsWith('http')) return url;
  return `${BACKEND_URL}${url}`;
};

const MenuPage = () => {
  const [searchParams] = useSearchParams();
  const navigate = useNavigate();
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
  const [itemNotes, setItemNotes] = useState('');
  const [submitting, setSubmitting] = useState(false);

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
      }
    }
  }, [searchParams, setTable]);

  // Load menu data
  const loadData = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      await seedAPI.seed().catch(() => {});
      
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

  // Group products by category
  const productsByCategory = categories
    .map(cat => ({
      category: cat,
      products: products.filter(p => p.category_id === cat.id)
    }))
    .filter(group => group.products.length > 0);

  const openProductModal = (product) => {
    setSelectedProduct(product);
    setProductQuantity(1);
    setSelectedVariation(product.variations?.length > 0 ? product.variations[0] : null);
    setSelectedExtras([]);
    setItemNotes('');
    setProductModalOpen(true);
  };

  const handleAddToCart = () => {
    if (!selectedProduct) return;
    
    addItem(
      selectedProduct,
      productQuantity,
      selectedVariation,
      selectedExtras,
      itemNotes
    );
    
    toast.success('Adicionado ao carrinho');
    setProductModalOpen(false);
  };

  const calculateItemPrice = () => {
    if (!selectedProduct) return 0;
    let price = selectedVariation?.price || selectedProduct.base_price;
    price += selectedExtras.reduce((sum, e) => sum + e.price, 0);
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
          notes: item.notes,
          unit_price: item.unit_price,
          total_price: item.total_price
        })),
        notes: orderNotes,
        total: getTotal()
      };

      const response = await ordersAPI.create(orderData);
      clearCart();
      setCartOpen(false);
      navigate(`/pedido/${response.data.id}`);
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
            <Badge variant="secondary" className="mt-2 w-fit text-sm px-3 py-1">
              Mesa {tableNumber}
            </Badge>
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
          {categories.map((cat) => {
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
                  </div>
                  <div className="p-4">
                    <h3 className="font-heading text-lg font-semibold">{product.name}</h3>
                    <p className="text-sm text-muted-foreground mt-1 line-clamp-2">
                      {product.description}
                    </p>
                    <div className="flex items-center justify-between mt-3">
                      <span className="font-bold text-lg">
                        € {product.base_price.toFixed(2)}
                      </span>
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

              {/* Variations */}
              {selectedProduct.variations?.length > 0 && (
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
                  Adicionar € {calculateItemPrice().toFixed(2)}
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
                      Finalizar Pedido
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
