import React, { useState, useEffect, useCallback } from 'react';
import { 
  Loader2, 
  Plus, 
  Pencil, 
  Trash2, 
  ImagePlus,
  GripVertical,
  Eye,
  EyeOff,
  Star,
  ChevronUp,
  ChevronDown
} from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Textarea } from '@/components/ui/textarea';
import { Badge } from '@/components/ui/badge';
import { Switch } from '@/components/ui/switch';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter } from '@/components/ui/dialog';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { AlertDialog, AlertDialogAction, AlertDialogCancel, AlertDialogContent, AlertDialogDescription, AlertDialogFooter, AlertDialogHeader, AlertDialogTitle } from '@/components/ui/alert-dialog';
import { toast } from 'sonner';
import AdminLayout from '@/components/AdminLayout';
import { categoriesAPI, productsAPI } from '@/lib/api';

const BACKEND_URL = process.env.REACT_APP_BACKEND_URL;

const AdminMenu = () => {
  const [categories, setCategories] = useState([]);
  const [products, setProducts] = useState([]);
  const [loading, setLoading] = useState(true);
  const [activeTab, setActiveTab] = useState('products');
  
  // Category Modal
  const [categoryModalOpen, setCategoryModalOpen] = useState(false);
  const [editingCategory, setEditingCategory] = useState(null);
  const [categoryForm, setCategoryForm] = useState({ name: '', order: 0, active: true });
  
  // Product Modal
  const [productModalOpen, setProductModalOpen] = useState(false);
  const [editingProduct, setEditingProduct] = useState(null);
  const [productForm, setProductForm] = useState({
    name: '',
    description: '',
    category_id: '',
    base_price: 0,
    image_url: '',
    variations: [],
    extras: [],
    available: true,
    featured: false
  });
  const [newVariation, setNewVariation] = useState({ name: '', price: 0 });
  const [newExtra, setNewExtra] = useState({ name: '', price: 0 });
  const [uploading, setUploading] = useState(false);
  
  // Delete confirmation
  const [deleteDialogOpen, setDeleteDialogOpen] = useState(false);
  const [deleteTarget, setDeleteTarget] = useState(null);
  const [deleteType, setDeleteType] = useState('');

  const loadData = useCallback(async () => {
    try {
      const [catsRes, prodsRes] = await Promise.all([
        categoriesAPI.list(),
        productsAPI.list()
      ]);
      setCategories(catsRes.data);
      setProducts(prodsRes.data);
    } catch (err) {
      console.error('Error loading data:', err);
      toast.error('Erro ao carregar dados');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    loadData();
  }, [loadData]);

  // Category handlers
  const openCategoryModal = (category = null) => {
    if (category) {
      setEditingCategory(category);
      setCategoryForm({ name: category.name, order: category.order, active: category.active });
    } else {
      setEditingCategory(null);
      setCategoryForm({ name: '', order: categories.length, active: true });
    }
    setCategoryModalOpen(true);
  };

  const handleSaveCategory = async () => {
    if (!categoryForm.name.trim()) {
      toast.error('Nome da categoria é obrigatório');
      return;
    }

    try {
      if (editingCategory) {
        await categoriesAPI.update(editingCategory.id, categoryForm);
        toast.success('Categoria atualizada');
      } else {
        await categoriesAPI.create(categoryForm);
        toast.success('Categoria criada');
      }
      setCategoryModalOpen(false);
      loadData();
    } catch (err) {
      console.error('Error saving category:', err);
      toast.error('Erro ao guardar categoria');
    }
  };

  const confirmDeleteCategory = (category) => {
    setDeleteTarget(category);
    setDeleteType('category');
    setDeleteDialogOpen(true);
  };

  const handleDeleteCategory = async () => {
    try {
      await categoriesAPI.delete(deleteTarget.id);
      toast.success('Categoria eliminada');
      setDeleteDialogOpen(false);
      loadData();
    } catch (err) {
      console.error('Error deleting category:', err);
      toast.error('Erro ao eliminar categoria');
    }
  };

  // Product handlers
  const openProductModal = (product = null) => {
    if (product) {
      setEditingProduct(product);
      setProductForm({
        name: product.name,
        description: product.description,
        category_id: product.category_id,
        base_price: product.base_price,
        image_url: product.image_url || '',
        variations: product.variations || [],
        extras: product.extras || [],
        available: product.available,
        featured: product.featured
      });
    } else {
      setEditingProduct(null);
      setProductForm({
        name: '',
        description: '',
        category_id: categories[0]?.id || '',
        base_price: 0,
        image_url: '',
        variations: [],
        extras: [],
        available: true,
        featured: false
      });
    }
    setNewVariation({ name: '', price: 0 });
    setNewExtra({ name: '', price: 0 });
    setProductModalOpen(true);
  };

  const handleImageUpload = async (e) => {
    const file = e.target.files?.[0];
    if (!file) return;

    setUploading(true);
    try {
      const response = await productsAPI.uploadImage(file);
      setProductForm(prev => ({ ...prev, image_url: response.data.url }));
      toast.success('Imagem carregada');
    } catch (err) {
      console.error('Error uploading image:', err);
      toast.error('Erro ao carregar imagem');
    } finally {
      setUploading(false);
    }
  };

  const addVariation = () => {
    if (!newVariation.name.trim() || newVariation.price <= 0) {
      toast.error('Preencha o nome e preço da variação');
      return;
    }
    setProductForm(prev => ({
      ...prev,
      variations: [...prev.variations, { ...newVariation }]
    }));
    setNewVariation({ name: '', price: 0 });
  };

  const removeVariation = (index) => {
    setProductForm(prev => ({
      ...prev,
      variations: prev.variations.filter((_, i) => i !== index)
    }));
  };

  const addExtra = () => {
    if (!newExtra.name.trim() || newExtra.price <= 0) {
      toast.error('Preencha o nome e preço do extra');
      return;
    }
    setProductForm(prev => ({
      ...prev,
      extras: [...prev.extras, { ...newExtra }]
    }));
    setNewExtra({ name: '', price: 0 });
  };

  const removeExtra = (index) => {
    setProductForm(prev => ({
      ...prev,
      extras: prev.extras.filter((_, i) => i !== index)
    }));
  };

  const handleSaveProduct = async () => {
    if (!productForm.name.trim()) {
      toast.error('Nome do produto é obrigatório');
      return;
    }
    if (!productForm.category_id) {
      toast.error('Selecione uma categoria');
      return;
    }

    try {
      if (editingProduct) {
        await productsAPI.update(editingProduct.id, productForm);
        toast.success('Produto atualizado');
      } else {
        await productsAPI.create(productForm);
        toast.success('Produto criado');
      }
      setProductModalOpen(false);
      loadData();
    } catch (err) {
      console.error('Error saving product:', err);
      toast.error('Erro ao guardar produto');
    }
  };

  const confirmDeleteProduct = (product) => {
    setDeleteTarget(product);
    setDeleteType('product');
    setDeleteDialogOpen(true);
  };

  const handleDeleteProduct = async () => {
    try {
      await productsAPI.delete(deleteTarget.id);
      toast.success('Produto eliminado');
      setDeleteDialogOpen(false);
      loadData();
    } catch (err) {
      console.error('Error deleting product:', err);
      toast.error('Erro ao eliminar produto');
    }
  };

  const toggleProductAvailability = async (product) => {
    try {
      await productsAPI.update(product.id, { available: !product.available });
      toast.success(product.available ? 'Produto indisponível' : 'Produto disponível');
      loadData();
    } catch (err) {
      console.error('Error toggling availability:', err);
      toast.error('Erro ao alterar disponibilidade');
    }
  };

  const getCategoryName = (categoryId) => {
    const cat = categories.find(c => c.id === categoryId);
    return cat?.name || 'Sem categoria';
  };

  const getImageUrl = (url) => {
    if (!url) return null;
    if (url.startsWith('http')) return url;
    return `${BACKEND_URL}${url}`;
  };

  if (loading) {
    return (
      <AdminLayout title="Menu">
        <div className="flex items-center justify-center h-64">
          <Loader2 className="h-8 w-8 animate-spin text-primary" />
        </div>
      </AdminLayout>
    );
  }

  return (
    <AdminLayout title="Menu">
      <Tabs value={activeTab} onValueChange={setActiveTab}>
        <TabsList className="mb-6">
          <TabsTrigger value="products">Produtos</TabsTrigger>
          <TabsTrigger value="categories">Categorias</TabsTrigger>
        </TabsList>

        {/* Products Tab */}
        <TabsContent value="products">
          <div className="flex justify-between items-center mb-6">
            <p className="text-muted-foreground">{products.length} produtos</p>
            <Button onClick={() => openProductModal()} data-testid="add-product-btn">
              <Plus className="h-4 w-4 mr-2" />
              Novo Produto
            </Button>
          </div>

          <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-3">
            {products.map((product) => (
              <Card key={product.id} className="overflow-hidden" data-testid={`product-admin-${product.id}`}>
                <div className="relative h-40">
                  <img
                    src={getImageUrl(product.image_url) || 'https://images.unsplash.com/photo-1574071318508-1cdbab80d002?w=400'}
                    alt={product.name}
                    className="w-full h-full object-cover"
                  />
                  {!product.available && (
                    <div className="absolute inset-0 bg-black/60 flex items-center justify-center">
                      <Badge variant="destructive">Indisponível</Badge>
                    </div>
                  )}
                  {product.featured && (
                    <Badge className="absolute top-2 left-2 featured-badge border-0">
                      <Star className="h-3 w-3 mr-1" />
                      Destaque
                    </Badge>
                  )}
                </div>
                <CardContent className="p-4">
                  <div className="flex justify-between items-start mb-2">
                    <div>
                      <h3 className="font-semibold">{product.name}</h3>
                      <p className="text-sm text-muted-foreground">{getCategoryName(product.category_id)}</p>
                    </div>
                    <span className="font-bold">€ {product.base_price.toFixed(2)}</span>
                  </div>
                  <p className="text-sm text-muted-foreground line-clamp-2 mb-3">
                    {product.description}
                  </p>
                  <div className="flex gap-2">
                    <Button variant="outline" size="sm" onClick={() => openProductModal(product)}>
                      <Pencil className="h-4 w-4 mr-1" />
                      Editar
                    </Button>
                    <Button 
                      variant="outline" 
                      size="sm"
                      onClick={() => toggleProductAvailability(product)}
                    >
                      {product.available ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
                    </Button>
                    <Button 
                      variant="outline" 
                      size="sm"
                      onClick={() => confirmDeleteProduct(product)}
                    >
                      <Trash2 className="h-4 w-4 text-destructive" />
                    </Button>
                  </div>
                </CardContent>
              </Card>
            ))}
          </div>
        </TabsContent>

        {/* Categories Tab */}
        <TabsContent value="categories">
          <div className="flex justify-between items-center mb-6">
            <p className="text-muted-foreground">{categories.length} categorias</p>
            <Button onClick={() => openCategoryModal()} data-testid="add-category-btn">
              <Plus className="h-4 w-4 mr-2" />
              Nova Categoria
            </Button>
          </div>

          <div className="space-y-3">
            {[...categories].sort((a, b) => a.order - b.order).map((category, idx, sorted) => (
              <Card key={category.id} data-testid={`category-admin-${category.id}`}>
                <CardContent className="p-4 flex items-center justify-between">
                  <div className="flex items-center gap-4">
                    {/* Move Up/Down Buttons */}
                    <div className="flex flex-col gap-0.5">
                      <Button
                        variant="ghost"
                        size="icon"
                        className="h-7 w-7"
                        disabled={idx === 0}
                        onClick={async () => {
                          const prev = sorted[idx - 1];
                          const newItems = sorted.map((c, i) => {
                            if (c.id === category.id) return { id: c.id, order: prev.order };
                            if (c.id === prev.id) return { id: c.id, order: category.order };
                            return { id: c.id, order: c.order };
                          });
                          try {
                            const res = await categoriesAPI.reorder(newItems);
                            setCategories(res.data);
                            toast.success('Ordem atualizada');
                          } catch { toast.error('Erro ao reordenar'); }
                        }}
                      >
                        <ChevronUp className="h-4 w-4" />
                      </Button>
                      <Button
                        variant="ghost"
                        size="icon"
                        className="h-7 w-7"
                        disabled={idx === sorted.length - 1}
                        onClick={async () => {
                          const next = sorted[idx + 1];
                          const newItems = sorted.map((c) => {
                            if (c.id === category.id) return { id: c.id, order: next.order };
                            if (c.id === next.id) return { id: c.id, order: category.order };
                            return { id: c.id, order: c.order };
                          });
                          try {
                            const res = await categoriesAPI.reorder(newItems);
                            setCategories(res.data);
                            toast.success('Ordem atualizada');
                          } catch { toast.error('Erro ao reordenar'); }
                        }}
                      >
                        <ChevronDown className="h-4 w-4" />
                      </Button>
                    </div>
                    <div>
                      <h3 className="font-semibold">{category.name}</h3>
                      <p className="text-sm text-muted-foreground">
                        {products.filter(p => p.category_id === category.id).length} produtos • Posição {idx + 1}
                      </p>
                    </div>
                    {!category.active && (
                      <Badge variant="secondary">Inativa</Badge>
                    )}
                  </div>
                  <div className="flex gap-2">
                    <Button variant="outline" size="sm" onClick={() => openCategoryModal(category)}>
                      <Pencil className="h-4 w-4" />
                    </Button>
                    <Button 
                      variant="outline" 
                      size="sm"
                      onClick={() => confirmDeleteCategory(category)}
                    >
                      <Trash2 className="h-4 w-4 text-destructive" />
                    </Button>
                  </div>
                </CardContent>
              </Card>
            ))}
          </div>
        </TabsContent>
      </Tabs>

      {/* Category Modal */}
      <Dialog open={categoryModalOpen} onOpenChange={setCategoryModalOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>
              {editingCategory ? 'Editar Categoria' : 'Nova Categoria'}
            </DialogTitle>
          </DialogHeader>
          <div className="space-y-4 py-4">
            <div className="space-y-2">
              <Label htmlFor="cat-name">Nome</Label>
              <Input
                id="cat-name"
                value={categoryForm.name}
                onChange={(e) => setCategoryForm(prev => ({ ...prev, name: e.target.value }))}
                placeholder="Ex: Pizzas"
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="cat-order">Ordem</Label>
              <Input
                id="cat-order"
                type="number"
                value={categoryForm.order}
                onChange={(e) => setCategoryForm(prev => ({ ...prev, order: parseInt(e.target.value) || 0 }))}
              />
            </div>
            <div className="flex items-center gap-2">
              <Switch
                id="cat-active"
                checked={categoryForm.active}
                onCheckedChange={(checked) => setCategoryForm(prev => ({ ...prev, active: checked }))}
              />
              <Label htmlFor="cat-active">Ativa</Label>
            </div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setCategoryModalOpen(false)}>Cancelar</Button>
            <Button onClick={handleSaveCategory}>Guardar</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Product Modal */}
      <Dialog open={productModalOpen} onOpenChange={setProductModalOpen}>
        <DialogContent className="max-w-2xl max-h-[90vh] overflow-y-auto">
          <DialogHeader>
            <DialogTitle>
              {editingProduct ? 'Editar Produto' : 'Novo Produto'}
            </DialogTitle>
          </DialogHeader>
          <div className="space-y-6 py-4">
            {/* Image */}
            <div className="space-y-2">
              <Label>Imagem</Label>
              <div className="flex items-center gap-4">
                {productForm.image_url ? (
                  <img
                    src={getImageUrl(productForm.image_url)}
                    alt="Preview"
                    className="w-24 h-24 object-cover rounded-lg"
                  />
                ) : (
                  <div className="w-24 h-24 bg-secondary rounded-lg flex items-center justify-center">
                    <ImagePlus className="h-8 w-8 text-muted-foreground" />
                  </div>
                )}
                <div>
                  <Input
                    type="file"
                    accept="image/*"
                    onChange={handleImageUpload}
                    disabled={uploading}
                    className="w-auto"
                  />
                  {uploading && <p className="text-sm text-muted-foreground mt-1">A carregar...</p>}
                </div>
              </div>
            </div>

            {/* Basic Info */}
            <div className="grid gap-4 md:grid-cols-2">
              <div className="space-y-2">
                <Label htmlFor="prod-name">Nome</Label>
                <Input
                  id="prod-name"
                  value={productForm.name}
                  onChange={(e) => setProductForm(prev => ({ ...prev, name: e.target.value }))}
                  placeholder="Ex: Margherita"
                />
              </div>
              <div className="space-y-2">
                <Label htmlFor="prod-category">Categoria</Label>
                <Select 
                  value={productForm.category_id}
                  onValueChange={(value) => setProductForm(prev => ({ ...prev, category_id: value }))}
                >
                  <SelectTrigger>
                    <SelectValue placeholder="Selecionar categoria" />
                  </SelectTrigger>
                  <SelectContent>
                    {categories.map(cat => (
                      <SelectItem key={cat.id} value={cat.id}>{cat.name}</SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
            </div>

            <div className="space-y-2">
              <Label htmlFor="prod-desc">Descrição</Label>
              <Textarea
                id="prod-desc"
                value={productForm.description}
                onChange={(e) => setProductForm(prev => ({ ...prev, description: e.target.value }))}
                placeholder="Descrição do produto"
                rows={3}
              />
            </div>

            <div className="grid gap-4 md:grid-cols-2">
              <div className="space-y-2">
                <Label htmlFor="prod-price">Preço Base (€)</Label>
                <Input
                  id="prod-price"
                  type="number"
                  step="0.01"
                  value={productForm.base_price}
                  onChange={(e) => setProductForm(prev => ({ ...prev, base_price: parseFloat(e.target.value) || 0 }))}
                />
              </div>
              <div className="space-y-4 pt-6">
                <div className="flex items-center gap-2">
                  <Switch
                    id="prod-available"
                    checked={productForm.available}
                    onCheckedChange={(checked) => setProductForm(prev => ({ ...prev, available: checked }))}
                  />
                  <Label htmlFor="prod-available">Disponível</Label>
                </div>
                <div className="flex items-center gap-2">
                  <Switch
                    id="prod-featured"
                    checked={productForm.featured}
                    onCheckedChange={(checked) => setProductForm(prev => ({ ...prev, featured: checked }))}
                  />
                  <Label htmlFor="prod-featured">Destaque</Label>
                </div>
              </div>
            </div>

            {/* Variations */}
            <div className="space-y-3">
              <Label>Variações (Tamanhos)</Label>
              {productForm.variations.map((variation, idx) => (
                <div key={idx} className="flex items-center gap-2 p-2 bg-secondary/50 rounded-lg">
                  <span className="flex-1">{variation.name}</span>
                  <span className="font-semibold">€ {variation.price.toFixed(2)}</span>
                  <Button variant="ghost" size="sm" onClick={() => removeVariation(idx)}>
                    <Trash2 className="h-4 w-4 text-destructive" />
                  </Button>
                </div>
              ))}
              <div className="flex gap-2">
                <Input
                  placeholder="Nome (ex: Média)"
                  value={newVariation.name}
                  onChange={(e) => setNewVariation(prev => ({ ...prev, name: e.target.value }))}
                />
                <Input
                  type="number"
                  step="0.01"
                  placeholder="Preço"
                  value={newVariation.price || ''}
                  onChange={(e) => setNewVariation(prev => ({ ...prev, price: parseFloat(e.target.value) || 0 }))}
                  className="w-28"
                />
                <Button variant="outline" onClick={addVariation}>
                  <Plus className="h-4 w-4" />
                </Button>
              </div>
            </div>

            {/* Extras */}
            <div className="space-y-3">
              <Label>Extras</Label>
              {productForm.extras.map((extra, idx) => (
                <div key={idx} className="flex items-center gap-2 p-2 bg-secondary/50 rounded-lg">
                  <span className="flex-1">{extra.name}</span>
                  <span className="font-semibold">+ € {extra.price.toFixed(2)}</span>
                  <Button variant="ghost" size="sm" onClick={() => removeExtra(idx)}>
                    <Trash2 className="h-4 w-4 text-destructive" />
                  </Button>
                </div>
              ))}
              <div className="flex gap-2">
                <Input
                  placeholder="Nome (ex: Borda recheada)"
                  value={newExtra.name}
                  onChange={(e) => setNewExtra(prev => ({ ...prev, name: e.target.value }))}
                />
                <Input
                  type="number"
                  step="0.01"
                  placeholder="Preço"
                  value={newExtra.price || ''}
                  onChange={(e) => setNewExtra(prev => ({ ...prev, price: parseFloat(e.target.value) || 0 }))}
                  className="w-28"
                />
                <Button variant="outline" onClick={addExtra}>
                  <Plus className="h-4 w-4" />
                </Button>
              </div>
            </div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setProductModalOpen(false)}>Cancelar</Button>
            <Button onClick={handleSaveProduct}>Guardar</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Delete Confirmation */}
      <AlertDialog open={deleteDialogOpen} onOpenChange={setDeleteDialogOpen}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Confirmar eliminação</AlertDialogTitle>
            <AlertDialogDescription>
              Tem a certeza que deseja eliminar {deleteType === 'category' ? 'esta categoria' : 'este produto'}?
              Esta ação não pode ser desfeita.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Cancelar</AlertDialogCancel>
            <AlertDialogAction 
              onClick={deleteType === 'category' ? handleDeleteCategory : handleDeleteProduct}
              className="bg-destructive text-destructive-foreground hover:bg-destructive/90"
            >
              Eliminar
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </AdminLayout>
  );
};

export default AdminMenu;
