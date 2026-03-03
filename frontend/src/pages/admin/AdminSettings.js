import React, { useState, useEffect } from 'react';
import { Loader2, Save, Building, ImagePlus } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from '@/components/ui/card';
import { toast } from 'sonner';
import AdminLayout from '@/components/AdminLayout';
import api from '@/lib/api';

const BACKEND_URL = process.env.REACT_APP_BACKEND_URL;

const AdminSettings = () => {
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [uploading, setUploading] = useState(false);
  
  const [restaurantConfig, setRestaurantConfig] = useState({
    name: 'Pizzaria',
    cover_image: ''
  });

  useEffect(() => {
    loadSettings();
  }, []);

  const loadSettings = async () => {
    try {
      const response = await api.get('/settings/restaurant');
      setRestaurantConfig(prev => ({ ...prev, ...response.data }));
    } catch (err) {
      console.error('Error loading settings:', err);
    } finally {
      setLoading(false);
    }
  };

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

        {/* Info Box */}
        <Card>
          <CardContent className="p-4">
            <h4 className="font-medium mb-2">Outras Configurações</h4>
            <ul className="text-sm text-muted-foreground space-y-1">
              <li>• <strong>Impressoras:</strong> Configure em "Impressoras" no menu lateral</li>
              <li>• <strong>Print Agent:</strong> Configure o agente local em "Impressoras" {">"} "Print Agent"</li>
              <li>• <strong>Mesas e QR Codes:</strong> Gerencie em "Mesas" no menu lateral</li>
            </ul>
          </CardContent>
        </Card>
      </div>
    </AdminLayout>
  );
};

export default AdminSettings;
