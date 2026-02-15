import React, { useState, useEffect } from 'react';
import { Loader2, Printer, Save, TestTube } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Switch } from '@/components/ui/switch';
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from '@/components/ui/card';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { toast } from 'sonner';
import AdminLayout from '@/components/AdminLayout';
import { settingsAPI } from '@/lib/api';

const AdminSettings = () => {
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [testing, setTesting] = useState(false);
  
  const [printerConfig, setPrinterConfig] = useState({
    ip: '',
    port: 9100,
    width: 80,
    cut_paper: true,
    copies: 1,
    restaurant_name: 'Pizzaria'
  });

  useEffect(() => {
    loadSettings();
  }, []);

  const loadSettings = async () => {
    try {
      const response = await settingsAPI.getPrinter();
      setPrinterConfig(prev => ({ ...prev, ...response.data }));
    } catch (err) {
      console.error('Error loading settings:', err);
    } finally {
      setLoading(false);
    }
  };

  const handleSave = async () => {
    setSaving(true);
    try {
      await settingsAPI.updatePrinter(printerConfig);
      toast.success('Definições guardadas');
    } catch (err) {
      console.error('Error saving settings:', err);
      toast.error('Erro ao guardar definições');
    } finally {
      setSaving(false);
    }
  };

  const handleTestPrint = async () => {
    if (!printerConfig.ip) {
      toast.error('Configure o IP da impressora primeiro');
      return;
    }

    setTesting(true);
    try {
      await settingsAPI.testPrinter();
      toast.success('Teste de impressão enviado');
    } catch (err) {
      console.error('Error testing printer:', err);
      toast.error(err.response?.data?.detail || 'Erro ao testar impressora');
    } finally {
      setTesting(false);
    }
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
      <div className="max-w-2xl">
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <Printer className="h-5 w-5" />
              Impressora Térmica
            </CardTitle>
            <CardDescription>
              Configure a impressora térmica da cozinha para impressão automática de pedidos
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-6">
            {/* Restaurant Name */}
            <div className="space-y-2">
              <Label htmlFor="restaurant-name">Nome do Restaurante</Label>
              <Input
                id="restaurant-name"
                value={printerConfig.restaurant_name}
                onChange={(e) => setPrinterConfig(prev => ({ ...prev, restaurant_name: e.target.value }))}
                placeholder="Nome que aparece nos talões"
                data-testid="printer-restaurant-name"
              />
              <p className="text-xs text-muted-foreground">
                Este nome aparece no topo de cada talão impresso
              </p>
            </div>

            {/* IP & Port */}
            <div className="grid gap-4 md:grid-cols-2">
              <div className="space-y-2">
                <Label htmlFor="printer-ip">Endereço IP</Label>
                <Input
                  id="printer-ip"
                  value={printerConfig.ip}
                  onChange={(e) => setPrinterConfig(prev => ({ ...prev, ip: e.target.value }))}
                  placeholder="Ex: 192.168.1.100"
                  data-testid="printer-ip-input"
                />
              </div>
              <div className="space-y-2">
                <Label htmlFor="printer-port">Porta</Label>
                <Input
                  id="printer-port"
                  type="number"
                  value={printerConfig.port}
                  onChange={(e) => setPrinterConfig(prev => ({ ...prev, port: parseInt(e.target.value) || 9100 }))}
                  placeholder="9100"
                  data-testid="printer-port-input"
                />
              </div>
            </div>

            {/* Width & Copies */}
            <div className="grid gap-4 md:grid-cols-2">
              <div className="space-y-2">
                <Label htmlFor="printer-width">Largura do Papel</Label>
                <Select 
                  value={printerConfig.width.toString()}
                  onValueChange={(value) => setPrinterConfig(prev => ({ ...prev, width: parseInt(value) }))}
                >
                  <SelectTrigger data-testid="printer-width-select">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="58">58mm</SelectItem>
                    <SelectItem value="80">80mm</SelectItem>
                  </SelectContent>
                </Select>
              </div>
              <div className="space-y-2">
                <Label htmlFor="printer-copies">Número de Cópias</Label>
                <Input
                  id="printer-copies"
                  type="number"
                  min="1"
                  max="5"
                  value={printerConfig.copies}
                  onChange={(e) => setPrinterConfig(prev => ({ ...prev, copies: Math.min(5, Math.max(1, parseInt(e.target.value) || 1)) }))}
                  data-testid="printer-copies-input"
                />
              </div>
            </div>

            {/* Cut Paper */}
            <div className="flex items-center justify-between p-4 bg-secondary/50 rounded-lg">
              <div>
                <Label htmlFor="cut-paper" className="font-medium">Cortar Papel Automaticamente</Label>
                <p className="text-sm text-muted-foreground">
                  Corta o papel após cada impressão (se a impressora suportar)
                </p>
              </div>
              <Switch
                id="cut-paper"
                checked={printerConfig.cut_paper}
                onCheckedChange={(checked) => setPrinterConfig(prev => ({ ...prev, cut_paper: checked }))}
                data-testid="printer-cut-switch"
              />
            </div>

            {/* Info Box */}
            <div className="p-4 bg-blue-50 dark:bg-blue-900/20 rounded-lg">
              <h4 className="font-medium text-blue-900 dark:text-blue-100 mb-2">
                Configuração da Impressora
              </h4>
              <ul className="text-sm text-blue-800 dark:text-blue-200 space-y-1 list-disc list-inside">
                <li>A impressora deve estar na mesma rede que o servidor</li>
                <li>Configure um IP fixo na impressora para evitar mudanças</li>
                <li>A porta padrão para impressoras ESC/POS é 9100</li>
                <li>Impressoras compatíveis: Epson, Star, Bixolon, etc.</li>
              </ul>
            </div>

            {/* Actions */}
            <div className="flex gap-4 pt-4">
              <Button onClick={handleSave} disabled={saving} data-testid="save-printer-settings">
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
              <Button 
                variant="outline" 
                onClick={handleTestPrint} 
                disabled={testing || !printerConfig.ip}
                data-testid="test-printer-btn"
              >
                {testing ? (
                  <>
                    <Loader2 className="h-4 w-4 mr-2 animate-spin" />
                    A testar...
                  </>
                ) : (
                  <>
                    <TestTube className="h-4 w-4 mr-2" />
                    Imprimir Teste
                  </>
                )}
              </Button>
            </div>
          </CardContent>
        </Card>
      </div>
    </AdminLayout>
  );
};

export default AdminSettings;
