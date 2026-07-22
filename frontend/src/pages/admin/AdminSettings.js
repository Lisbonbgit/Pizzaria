import React, { useState, useEffect } from 'react';
import { Loader2, Save, Building, ImagePlus, Download, Printer } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from '@/components/ui/card';
import { Switch } from '@/components/ui/switch';
import { toast } from 'sonner';
import AdminLayout from '@/components/AdminLayout';
import api, { rodizioAPI } from '@/lib/api';

const BACKEND_URL = process.env.REACT_APP_BACKEND_URL;

const AdminSettings = () => {
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [uploading, setUploading] = useState(false);
  
  const [restaurantConfig, setRestaurantConfig] = useState({
    name: 'Pizzaria',
    cover_image: ''
  });
  const [apkInfo, setApkInfo] = useState({ available: false, size_kb: 0 });
  const [agentKey, setAgentKey] = useState('');
  const [rodizio, setRodizio] = useState(null);
  const [savingRodizio, setSavingRodizio] = useState(false);

  useEffect(() => {
    loadSettings();
  }, []);

  const loadSettings = async () => {
    try {
      const response = await api.get('/settings/restaurant');
      setRestaurantConfig(prev => ({ ...prev, ...response.data }));
      try {
        const info = await api.get('/app/print-bridge/info');
        setApkInfo(info.data);
      } catch { /* APK opcional */ }
      try {
        const pa = await api.get('/settings/print-agent');
        setAgentKey(pa.data?.api_key || '');
      } catch { /* chave opcional */ }
      try {
        const r = await rodizioAPI.get();
        setRodizio(r.data);
      } catch { /* rodízio opcional */ }
    } catch (err) {
      console.error('Error loading settings:', err);
    } finally {
      setLoading(false);
    }
  };

  const saveRodizio = async () => {
    if (!rodizio) return;
    setSavingRodizio(true);
    try {
      await rodizioAPI.update(rodizio);
      toast.success('Rodízio guardado');
    } catch { toast.error('Erro ao guardar o rodízio'); }
    finally { setSavingRodizio(false); }
  };

  const applyRodizioDefaults = async () => {
    try {
      const r = await rodizioAPI.seedDefaults();
      toast.success(`${r.data.updated} produto(s) atualizado(s) por categoria`);
    } catch { toast.error('Erro a aplicar defaults'); }
  };

  const setTier = (key, field, value) =>
    setRodizio(prev => ({ ...prev, tiers: { ...prev.tiers, [key]: { ...prev.tiers[key], [field]: value } } }));

  const toggleDay = (d) =>
    setRodizio(prev => ({ ...prev, days: prev.days.includes(d) ? prev.days.filter(x => x !== d) : [...prev.days, d].sort((a, b) => a - b) }));

  const handleSave = async () => {
    setSaving(true);
    try {
      await api.put('/settings/restaurant', restaurantConfig);
      toast.success('Definições guardadas');
    } catch (err) {
      console.error('Error saving settings:', err);
      toast.error('Erro ao guardar definições');
    } finally {
      setSaving(false);
    }
  };

  const handleImageUpload = async (e) => {
    const file = e.target.files?.[0];
    if (!file) return;

    if (!file.type.startsWith('image/')) {
      toast.error('Por favor selecione uma imagem');
      return;
    }

    setUploading(true);
    try {
      const formData = new FormData();
      formData.append('file', file);
      const response = await api.post('/products/upload-image', formData, {
        headers: { 'Content-Type': 'multipart/form-data' }
      });
      setRestaurantConfig(prev => ({ ...prev, cover_image: response.data.url }));
      toast.success('Imagem carregada');
    } catch (err) {
      console.error('Error uploading image:', err);
      toast.error('Erro ao carregar imagem');
    } finally {
      setUploading(false);
    }
  };

  const getImageUrl = (url) => {
    if (!url) return null;
    if (url.startsWith('http')) return url;
    return `${BACKEND_URL}${url}`;
  };

  if (loading) {
    return (
      <AdminLayout title="Definições">
        <div className="flex items-center justify-center h-64">
          <Loader2 className="h-8 w-8 animate-spin text-primary" />
        </div>
      </AdminLayout>
    );
  }

  return (
    <AdminLayout title="Definições">
      <div className="max-w-2xl space-y-6">
        {/* Restaurant Settings */}
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <Building className="h-5 w-5" />
              Informações do Restaurante
            </CardTitle>
            <CardDescription>
              Configure as informações básicas do restaurante
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-6">
            {/* Restaurant Name */}
            <div className="space-y-2">
              <Label htmlFor="restaurant-name">Nome do Restaurante</Label>
              <Input
                id="restaurant-name"
                value={restaurantConfig.name}
                onChange={(e) => setRestaurantConfig(prev => ({ ...prev, name: e.target.value }))}
                placeholder="Nome que aparece no menu"
                data-testid="restaurant-name-input"
              />
              <p className="text-xs text-muted-foreground">
                Este nome aparece no topo do menu e nos talões impressos
              </p>
            </div>

            {/* Cover Image */}
            <div className="space-y-3">
              <Label>Imagem de Capa</Label>
              <div className="flex items-start gap-4">
                {restaurantConfig.cover_image ? (
                  <img
                    src={getImageUrl(restaurantConfig.cover_image)}
                    alt="Capa"
                    className="w-40 h-24 object-cover rounded-lg border"
                  />
                ) : (
                  <div className="w-40 h-24 bg-secondary rounded-lg flex items-center justify-center border">
                    <ImagePlus className="h-8 w-8 text-muted-foreground" />
                  </div>
                )}
                <div className="flex-1 space-y-2">
                  <Input
                    type="file"
                    accept="image/*"
                    onChange={handleImageUpload}
                    disabled={uploading}
                    className="w-full"
                  />
                  {uploading && <p className="text-sm text-muted-foreground">A carregar...</p>}
                  <p className="text-xs text-muted-foreground">
                    Ou cole um URL de imagem:
                  </p>
                  <Input
                    placeholder="https://exemplo.com/imagem.jpg"
                    value={restaurantConfig.cover_image || ''}
                    onChange={(e) => setRestaurantConfig(prev => ({ ...prev, cover_image: e.target.value }))}
                  />
                </div>
              </div>
              <p className="text-xs text-muted-foreground">
                Imagem recomendada: 1200x400 pixels. Aparece no topo da página do menu.
              </p>
            </div>

            {/* Actions */}
            <div className="flex gap-4 pt-4">
              <Button onClick={handleSave} disabled={saving} data-testid="save-settings">
                {saving ? (
                  <>
                    <Loader2 className="h-4 w-4 mr-2 animate-spin" />
                    A guardar...
                  </>
                ) : (
                  <>
                    <Save className="h-4 w-4 mr-2" />
                    Guardar Definições
                  </>
                )}
              </Button>
            </div>
          </CardContent>
        </Card>

        {/* Rodízio (all-you-can-eat) */}
        {rodizio && (
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center justify-between">
              <span>Rodízio (all-you-can-eat)</span>
              <Switch checked={rodizio.enabled} onCheckedChange={(v) => setRodizio(prev => ({ ...prev, enabled: v }))} />
            </CardTitle>
            <CardDescription>Pizzas à vontade cobradas por pessoa, só nos dias escolhidos.</CardDescription>
          </CardHeader>
          <CardContent className="space-y-5">
            <div className="space-y-2">
              <Label>Dias com rodízio</Label>
              <div className="flex flex-wrap gap-1.5">
                {[['Seg', 0], ['Ter', 1], ['Qua', 2], ['Qui', 3], ['Sex', 4], ['Sáb', 5], ['Dom', 6]].map(([lbl, d]) => {
                  const on = rodizio.days.includes(d);
                  return (
                    <button key={d} type="button" onClick={() => toggleDay(d)}
                      className={`h-9 w-12 rounded-lg border text-sm font-medium transition ${on ? 'bg-primary text-primary-foreground border-primary' : 'bg-background hover:bg-muted'}`}>{lbl}</button>
                  );
                })}
              </div>
            </div>

            <div className="grid gap-3 sm:grid-cols-2">
              {['simples', 'completo'].map((k) => (
                <div key={k} className="rounded-lg border p-3 space-y-2">
                  <Label className="text-xs uppercase text-muted-foreground">{k === 'simples' ? 'Nível Simples' : 'Nível Completo'}</Label>
                  <Input value={rodizio.tiers[k].name} onChange={(e) => setTier(k, 'name', e.target.value)} placeholder="Nome" />
                  <div className="relative">
                    <span className="absolute left-3 top-1/2 -translate-y-1/2 text-muted-foreground">€</span>
                    <Input type="number" step="0.01" className="pl-7" value={rodizio.tiers[k].price}
                      onChange={(e) => setTier(k, 'price', parseFloat(e.target.value) || 0)} placeholder="Preço/adulto" />
                  </div>
                  <textarea
                    value={rodizio.tiers[k].description || ''}
                    onChange={(e) => setTier(k, 'description', e.target.value)}
                    placeholder="O que inclui (mostrado ao cliente na escolha)"
                    rows={2}
                    className="w-full rounded-md border border-input bg-background px-3 py-2 text-sm resize-none focus:outline-none focus:ring-2 focus:ring-ring"
                  />
                </div>
              ))}
            </div>

            <div className="grid gap-3 sm:grid-cols-3">
              <div className="space-y-1">
                <Label className="text-xs">Grátis até (anos)</Label>
                <Input type="number" value={rodizio.child_free_max_age} onChange={(e) => setRodizio(prev => ({ ...prev, child_free_max_age: parseInt(e.target.value) || 0 }))} />
              </div>
              <div className="space-y-1">
                <Label className="text-xs">Meia até (anos)</Label>
                <Input type="number" value={rodizio.child_half_max_age} onChange={(e) => setRodizio(prev => ({ ...prev, child_half_max_age: parseInt(e.target.value) || 0 }))} />
              </div>
              <div className="space-y-1">
                <Label className="text-xs">Taxa desperdício (€/box)</Label>
                <Input type="number" step="0.5" value={rodizio.waste_fee} onChange={(e) => setRodizio(prev => ({ ...prev, waste_fee: parseFloat(e.target.value) || 0 }))} />
              </div>
            </div>

            <div className="flex flex-wrap gap-2 pt-1">
              <Button onClick={saveRodizio} disabled={savingRodizio}>
                {savingRodizio ? <Loader2 className="h-4 w-4 mr-2 animate-spin" /> : <Save className="h-4 w-4 mr-2" />}
                Guardar Rodízio
              </Button>
              <Button variant="outline" onClick={applyRodizioDefaults}>Aplicar inclusões por categoria</Button>
            </div>
            <p className="text-xs text-muted-foreground">
              O que está incluído define-se por produto no <strong>Menu → Produtos</strong> (campo "Incluído no rodízio").
              O botão acima aplica os defaults: pizzas → Simples e Completo; entradas/sobremesas → Só Completo. Depois marca as bebidas incluídas.
            </p>
          </CardContent>
        </Card>
        )}

        {/* App de Impressão (APK) */}
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <Printer className="h-5 w-5" />
              App de Impressão (Android)
            </CardTitle>
            <CardDescription>
              Ponte que imprime os pedidos automaticamente. Instala no tablet ligado às
              impressoras e configura o URL, a chave e os IPs.
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            {apkInfo.available ? (
              <a href={`${BACKEND_URL}/api/app/print-bridge.apk`} download>
                <Button data-testid="download-apk">
                  <Download className="h-4 w-4 mr-2" />
                  Descarregar APK{apkInfo.size_kb ? ` (${apkInfo.size_kb} KB)` : ''}
                </Button>
              </a>
            ) : (
              <p className="text-sm text-muted-foreground">APK ainda não publicado.</p>
            )}

            {agentKey && (
              <div className="space-y-2 rounded-lg border bg-muted/30 p-3">
                <p className="text-sm font-medium">Configuração a introduzir na app</p>
                <div className="flex items-center gap-2 text-sm">
                  <span className="w-16 shrink-0 text-muted-foreground">URL</span>
                  <code className="flex-1 truncate">{BACKEND_URL}</code>
                  <Button type="button" size="sm" variant="outline"
                    onClick={() => { navigator.clipboard?.writeText(BACKEND_URL); toast.success('URL copiado'); }}>
                    Copiar
                  </Button>
                </div>
                <div className="flex items-center gap-2 text-sm">
                  <span className="w-16 shrink-0 text-muted-foreground">API Key</span>
                  <code className="flex-1 truncate">{agentKey}</code>
                  <Button type="button" size="sm" variant="outline"
                    onClick={() => { navigator.clipboard?.writeText(agentKey); toast.success('API Key copiada'); }}>
                    Copiar
                  </Button>
                </div>
                <p className="text-xs text-muted-foreground">
                  Falta só indicar, na app, os IPs das impressoras (cozinha e caixa).
                </p>
              </div>
            )}
          </CardContent>
        </Card>

        {/* Info Box */}
        <Card>
          <CardContent className="p-4">
            <h4 className="font-medium mb-2">Outras Configurações</h4>
            <ul className="text-sm text-muted-foreground space-y-1">
              <li>• <strong>Impressão:</strong> instala o APK acima no tablet ligado às impressoras</li>
              <li>• <strong>Menu:</strong> categorias e produtos em "Menu" no menu lateral</li>
              <li>• <strong>Mesas e QR Codes:</strong> gere em "Mesas" no menu lateral</li>
            </ul>
          </CardContent>
        </Card>
      </div>
    </AdminLayout>
  );
};

export default AdminSettings;
