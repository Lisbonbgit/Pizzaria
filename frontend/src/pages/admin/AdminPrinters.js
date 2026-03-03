import React, { useState, useEffect, useCallback } from 'react';
import { 
  Loader2, 
  Plus, 
  Pencil, 
  Trash2, 
  Printer,
  TestTube,
  Eye,
  EyeOff,
  Wifi,
  WifiOff,
  Copy,
  RefreshCw,
  CheckCircle,
  XCircle,
  Clock
} from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Switch } from '@/components/ui/switch';
import { Badge } from '@/components/ui/badge';
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from '@/components/ui/card';
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter } from '@/components/ui/dialog';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { AlertDialog, AlertDialogAction, AlertDialogCancel, AlertDialogContent, AlertDialogDescription, AlertDialogFooter, AlertDialogHeader, AlertDialogTitle } from '@/components/ui/alert-dialog';
import { toast } from 'sonner';
import AdminLayout from '@/components/AdminLayout';
import api from '@/lib/api';

const AdminPrinters = () => {
  const [printers, setPrinters] = useState([]);
  const [printJobs, setPrintJobs] = useState([]);
  const [agentConfig, setAgentConfig] = useState(null);
  const [loading, setLoading] = useState(true);
  const [activeTab, setActiveTab] = useState('printers');
  
  // Printer Modal
  const [printerModalOpen, setPrinterModalOpen] = useState(false);
  const [editingPrinter, setEditingPrinter] = useState(null);
  const [printerForm, setPrinterForm] = useState({
    name: '',
    ip: '',
    port: 9100,
    width: 80,
    cut_paper: true,
    active: true,
    printer_type: 'kitchen'
  });
  const [testingPrinter, setTestingPrinter] = useState(null);
  
  // Delete confirmation
  const [deleteDialogOpen, setDeleteDialogOpen] = useState(false);
  const [deleteTarget, setDeleteTarget] = useState(null);

  const loadData = useCallback(async () => {
    try {
      const [printersRes, jobsRes, agentRes] = await Promise.all([
        api.get('/printers'),
        api.get('/print-jobs?status=failed'),
        api.get('/settings/print-agent')
      ]);
      setPrinters(printersRes.data);
      setPrintJobs(jobsRes.data);
      setAgentConfig(agentRes.data);
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

  // Printer handlers
  const openPrinterModal = (printer = null) => {
    if (printer) {
      setEditingPrinter(printer);
      setPrinterForm({
        name: printer.name,
        ip: printer.ip,
        port: printer.port,
        width: printer.width,
        cut_paper: printer.cut_paper,
        active: printer.active,
        printer_type: printer.printer_type || 'kitchen'
      });
    } else {
      setEditingPrinter(null);
      setPrinterForm({
        name: '',
        ip: '',
        port: 9100,
        width: 80,
        cut_paper: true,
        active: true,
        printer_type: 'kitchen'
      });
    }
    setPrinterModalOpen(true);
  };

  const handleSavePrinter = async () => {
    if (!printerForm.name.trim() || !printerForm.ip.trim()) {
      toast.error('Nome e IP são obrigatórios');
      return;
    }

    try {
      if (editingPrinter) {
        await api.put(`/printers/${editingPrinter.id}`, printerForm);
        toast.success('Impressora atualizada');
      } else {
        await api.post('/printers', printerForm);
        toast.success('Impressora criada');
      }
      setPrinterModalOpen(false);
      loadData();
    } catch (err) {
      console.error('Error saving printer:', err);
      toast.error('Erro ao guardar impressora');
    }
  };

  const confirmDeletePrinter = (printer) => {
    setDeleteTarget(printer);
    setDeleteDialogOpen(true);
  };

  const handleDeletePrinter = async () => {
    try {
      await api.delete(`/printers/${deleteTarget.id}`);
      toast.success('Impressora eliminada');
      setDeleteDialogOpen(false);
      loadData();
    } catch (err) {
      console.error('Error deleting printer:', err);
      toast.error('Erro ao eliminar impressora');
    }
  };

  const togglePrinterStatus = async (printer) => {
    try {
      await api.put(`/printers/${printer.id}`, { active: !printer.active });
      toast.success(printer.active ? 'Impressora desativada' : 'Impressora ativada');
      loadData();
    } catch (err) {
      console.error('Error toggling printer:', err);
      toast.error('Erro ao alterar estado');
    }
  };

  const testPrinter = async (printer) => {
    setTestingPrinter(printer.id);
    try {
      await api.post(`/printers/${printer.id}/test`);
      toast.success('Teste de impressão agendado. O Print Agent irá processar.');
    } catch (err) {
      console.error('Error testing printer:', err);
      toast.error(err.response?.data?.detail || 'Erro ao testar impressora');
    } finally {
      setTestingPrinter(null);
    }
  };

  const copyApiKey = () => {
    if (agentConfig?.api_key) {
      navigator.clipboard.writeText(agentConfig.api_key);
      toast.success('API Key copiada');
    }
  };

  const regenerateApiKey = async () => {
    try {
      const response = await api.post('/settings/print-agent/regenerate');
      setAgentConfig({ api_key: response.data.api_key });
      toast.success('Nova API Key gerada');
    } catch (err) {
      console.error('Error regenerating key:', err);
      toast.error('Erro ao gerar nova chave');
    }
  };

  const getJobStatusIcon = (status) => {
    switch (status) {
      case 'printed':
        return <CheckCircle className="h-4 w-4 text-green-600" />;
      case 'failed':
        return <XCircle className="h-4 w-4 text-red-600" />;
      case 'printing':
        return <Loader2 className="h-4 w-4 text-blue-600 animate-spin" />;
      default:
        return <Clock className="h-4 w-4 text-yellow-600" />;
    }
  };

  if (loading) {
    return (
      <AdminLayout title="Impressoras">
        <div className="flex items-center justify-center h-64">
          <Loader2 className="h-8 w-8 animate-spin text-primary" />
        </div>
      </AdminLayout>
    );
  }

  return (
    <AdminLayout title="Impressoras">
      <Tabs value={activeTab} onValueChange={setActiveTab}>
        <TabsList className="mb-6">
          <TabsTrigger value="printers">Impressoras</TabsTrigger>
          <TabsTrigger value="agent">Print Agent</TabsTrigger>
          <TabsTrigger value="jobs">Fila de Impressão</TabsTrigger>
        </TabsList>

        {/* Printers Tab */}
        <TabsContent value="printers">
          <div className="flex justify-between items-center mb-6">
            <p className="text-muted-foreground">{printers.length} impressora(s) configurada(s)</p>
            <Button onClick={() => openPrinterModal()} data-testid="add-printer-btn">
              <Plus className="h-4 w-4 mr-2" />
              Nova Impressora
            </Button>
          </div>

          <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-3">
            {printers.map((printer) => (
              <Card key={printer.id} data-testid={`printer-card-${printer.id}`}>
                <CardContent className="p-4">
                  <div className="flex items-start justify-between mb-4">
                    <div className="flex items-center gap-3">
                      <div className={`w-12 h-12 rounded-lg flex items-center justify-center ${
                        printer.active ? 'bg-green-100 dark:bg-green-900/30' : 'bg-gray-100 dark:bg-gray-800'
                      }`}>
                        <Printer className={`h-6 w-6 ${
                          printer.active ? 'text-green-600' : 'text-gray-400'
                        }`} />
                      </div>
                      <div>
                        <h3 className="font-semibold">{printer.name}</h3>
                        <p className="text-sm text-muted-foreground">{printer.ip}:{printer.port}</p>
                      </div>
                    </div>
                    {printer.active ? (
                      <Badge variant="secondary" className="bg-green-100 text-green-800 dark:bg-green-900/30 dark:text-green-400">
                        <Wifi className="h-3 w-3 mr-1" />
                        Ativa
                      </Badge>
                    ) : (
                      <Badge variant="secondary">
                        <WifiOff className="h-3 w-3 mr-1" />
                        Inativa
                      </Badge>
                    )}
                  </div>
                  
                  <div className="text-sm text-muted-foreground mb-4">
                    <p>Tipo: <span className="font-medium">{printer.printer_type === 'cashier' ? 'Caixa' : 'Cozinha'}</span></p>
                    <p>Largura: {printer.width}mm</p>
                    <p>Cortar papel: {printer.cut_paper ? 'Sim' : 'Não'}</p>
                  </div>

                  <div className="flex gap-2">
                    <Button 
                      variant="outline" 
                      size="sm"
                      className="flex-1"
                      onClick={() => testPrinter(printer)}
                      disabled={testingPrinter === printer.id || !printer.active}
                    >
                      {testingPrinter === printer.id ? (
                        <Loader2 className="h-4 w-4 animate-spin" />
                      ) : (
                        <>
                          <TestTube className="h-4 w-4 mr-1" />
                          Testar
                        </>
                      )}
                    </Button>
                    <Button variant="outline" size="sm" onClick={() => openPrinterModal(printer)}>
                      <Pencil className="h-4 w-4" />
                    </Button>
                    <Button 
                      variant="outline" 
                      size="sm"
                      onClick={() => togglePrinterStatus(printer)}
                    >
                      {printer.active ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
                    </Button>
                    <Button 
                      variant="outline" 
                      size="sm"
                      onClick={() => confirmDeletePrinter(printer)}
                    >
                      <Trash2 className="h-4 w-4 text-destructive" />
                    </Button>
                  </div>
                </CardContent>
              </Card>
            ))}

            {printers.length === 0 && (
              <Card className="col-span-full">
                <CardContent className="py-12 text-center">
                  <Printer className="h-12 w-12 mx-auto text-muted-foreground mb-4" />
                  <p className="text-muted-foreground">Nenhuma impressora configurada</p>
                  <Button onClick={() => openPrinterModal()} className="mt-4">
                    <Plus className="h-4 w-4 mr-2" />
                    Adicionar Impressora
                  </Button>
                </CardContent>
              </Card>
            )}
          </div>
        </TabsContent>

        {/* Print Agent Tab */}
        <TabsContent value="agent">
          <div className="max-w-2xl">
            <Card>
              <CardHeader>
                <CardTitle className="flex items-center gap-2">
                  <Printer className="h-5 w-5" />
                  Print Agent Local
                </CardTitle>
                <CardDescription>
                  Configure o agente de impressão que faz a ponte entre o sistema na cloud e as impressoras locais.
                </CardDescription>
              </CardHeader>
              <CardContent className="space-y-6">
                {/* API Key */}
                <div className="space-y-3">
                  <Label>API Key do Print Agent</Label>
                  <div className="flex gap-2">
                    <Input
                      value={agentConfig?.api_key || ''}
                      readOnly
                      className="font-mono text-sm"
                    />
                    <Button variant="outline" onClick={copyApiKey}>
                      <Copy className="h-4 w-4" />
                    </Button>
                    <Button variant="outline" onClick={regenerateApiKey}>
                      <RefreshCw className="h-4 w-4" />
                    </Button>
                  </div>
                  <p className="text-xs text-muted-foreground">
                    Use esta chave para autenticar o Print Agent. Regenere se suspeitar de comprometimento.
                  </p>
                </div>

                {/* Instructions */}
                <div className="p-4 bg-blue-50 dark:bg-blue-900/20 rounded-lg">
                  <h4 className="font-medium text-blue-900 dark:text-blue-100 mb-3">
                    Como Instalar o Print Agent
                  </h4>
                  <ol className="text-sm text-blue-800 dark:text-blue-200 space-y-2 list-decimal list-inside">
                    <li>Descarregue os ficheiros do Print Agent</li>
                    <li>Instale Python 3.8+ no PC da pizzaria</li>
                    <li>Configure a API Key no ficheiro <code className="bg-blue-100 dark:bg-blue-800 px-1 rounded">print_agent.py</code></li>
                    <li>Execute <code className="bg-blue-100 dark:bg-blue-800 px-1 rounded">iniciar_agent.bat</code></li>
                    <li>O agent irá buscar pedidos automaticamente</li>
                  </ol>
                </div>

                {/* Download */}
                <div className="p-4 border rounded-lg">
                  <h4 className="font-medium mb-2">Descarregar Print Agent</h4>
                  <p className="text-sm text-muted-foreground mb-4">
                    Descarregue os ficheiros necessários para instalar o Print Agent no PC da pizzaria.
                  </p>
                  <Button variant="outline" asChild>
                    <a href="/api/agent/download" download>
                      Descarregar Ficheiros
                    </a>
                  </Button>
                </div>

                {/* Status */}
                <div className="p-4 bg-secondary/50 rounded-lg">
                  <h4 className="font-medium mb-2">Estado do Sistema</h4>
                  <div className="grid gap-2 text-sm">
                    <div className="flex justify-between">
                      <span className="text-muted-foreground">Impressoras Ativas:</span>
                      <span className="font-medium">{printers.filter(p => p.active).length}</span>
                    </div>
                    <div className="flex justify-between">
                      <span className="text-muted-foreground">Jobs Pendentes:</span>
                      <span className="font-medium">{printJobs.filter(j => j.status === 'pending').length}</span>
                    </div>
                    <div className="flex justify-between">
                      <span className="text-muted-foreground">Jobs com Erro:</span>
                      <span className="font-medium text-red-600">{printJobs.filter(j => j.status === 'failed').length}</span>
                    </div>
                  </div>
                </div>
              </CardContent>
            </Card>
          </div>
        </TabsContent>

        {/* Print Jobs Tab */}
        <TabsContent value="jobs">
          <div className="flex justify-between items-center mb-6">
            <p className="text-muted-foreground">Últimos jobs de impressão com erro</p>
            <Button variant="outline" onClick={loadData}>
              <RefreshCw className="h-4 w-4 mr-2" />
              Atualizar
            </Button>
          </div>

          {printJobs.length === 0 ? (
            <Card>
              <CardContent className="py-12 text-center">
                <CheckCircle className="h-12 w-12 mx-auto text-green-600 mb-4" />
                <p className="text-muted-foreground">Sem erros de impressão recentes</p>
              </CardContent>
            </Card>
          ) : (
            <div className="space-y-3">
              {printJobs.map((job) => (
                <Card key={job.id}>
                  <CardContent className="p-4">
                    <div className="flex items-center justify-between">
                      <div className="flex items-center gap-3">
                        {getJobStatusIcon(job.status)}
                        <div>
                          <p className="font-medium">
                            {job.order_id ? `Pedido` : 'Teste'} - {job.printer_name}
                          </p>
                          <p className="text-sm text-muted-foreground">
                            {new Date(job.created_at).toLocaleString('pt-PT')}
                          </p>
                          {job.error && (
                            <p className="text-sm text-red-600 mt-1">{job.error}</p>
                          )}
                        </div>
                      </div>
                      <div className="text-right">
                        <Badge variant={job.status === 'failed' ? 'destructive' : 'secondary'}>
                          {job.status === 'failed' ? 'Falhou' : 
                           job.status === 'printed' ? 'Impresso' :
                           job.status === 'printing' ? 'A imprimir' : 'Pendente'}
                        </Badge>
                        <p className="text-xs text-muted-foreground mt-1">
                          Tentativas: {job.attempts}
                        </p>
                      </div>
                    </div>
                  </CardContent>
                </Card>
              ))}
            </div>
          )}
        </TabsContent>
      </Tabs>

      {/* Printer Modal */}
      <Dialog open={printerModalOpen} onOpenChange={setPrinterModalOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>
              {editingPrinter ? 'Editar Impressora' : 'Nova Impressora'}
            </DialogTitle>
          </DialogHeader>
          <div className="space-y-4 py-4">
            <div className="space-y-2">
              <Label htmlFor="printer-name">Nome</Label>
              <Input
                id="printer-name"
                value={printerForm.name}
                onChange={(e) => setPrinterForm(prev => ({ ...prev, name: e.target.value }))}
                placeholder="Ex: Cozinha, Balcão"
              />
            </div>
            <div className="grid gap-4 md:grid-cols-2">
              <div className="space-y-2">
                <Label htmlFor="printer-ip">Endereço IP</Label>
                <Input
                  id="printer-ip"
                  value={printerForm.ip}
                  onChange={(e) => setPrinterForm(prev => ({ ...prev, ip: e.target.value }))}
                  placeholder="Ex: 192.168.1.100"
                />
              </div>
              <div className="space-y-2">
                <Label htmlFor="printer-port">Porta</Label>
                <Input
                  id="printer-port"
                  type="number"
                  value={printerForm.port}
                  onChange={(e) => setPrinterForm(prev => ({ ...prev, port: parseInt(e.target.value) || 9100 }))}
                  placeholder="9100"
                />
              </div>
            </div>
            <div className="space-y-2">
              <Label htmlFor="printer-width">Largura do Papel</Label>
              <Select 
                value={printerForm.width.toString()}
                onValueChange={(value) => setPrinterForm(prev => ({ ...prev, width: parseInt(value) }))}
              >
                <SelectTrigger>
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="58">58mm</SelectItem>
                  <SelectItem value="80">80mm</SelectItem>
                </SelectContent>
              </Select>
            </div>
            <div className="space-y-2">
              <Label htmlFor="printer-type">Tipo de Impressora</Label>
              <Select 
                value={printerForm.printer_type}
                onValueChange={(value) => setPrinterForm(prev => ({ ...prev, printer_type: value }))}
              >
                <SelectTrigger>
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="kitchen">Cozinha - Formato de preparação</SelectItem>
                  <SelectItem value="cashier">Caixa - Formato com preços</SelectItem>
                </SelectContent>
              </Select>
              <p className="text-xs text-muted-foreground">
                {printerForm.printer_type === 'kitchen' 
                  ? 'Mostra detalhes de preparação, observações em destaque' 
                  : 'Mostra preços unitários e total do pedido'}
              </p>
            </div>
            <div className="flex items-center justify-between p-3 bg-secondary/50 rounded-lg">
              <div>
                <Label htmlFor="cut-paper">Cortar Papel</Label>
                <p className="text-xs text-muted-foreground">Corta automaticamente após impressão</p>
              </div>
              <Switch
                id="cut-paper"
                checked={printerForm.cut_paper}
                onCheckedChange={(checked) => setPrinterForm(prev => ({ ...prev, cut_paper: checked }))}
              />
            </div>
            <div className="flex items-center justify-between p-3 bg-secondary/50 rounded-lg">
              <div>
                <Label htmlFor="printer-active">Ativa</Label>
                <p className="text-xs text-muted-foreground">Recebe pedidos para impressão</p>
              </div>
              <Switch
                id="printer-active"
                checked={printerForm.active}
                onCheckedChange={(checked) => setPrinterForm(prev => ({ ...prev, active: checked }))}
              />
            </div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setPrinterModalOpen(false)}>Cancelar</Button>
            <Button onClick={handleSavePrinter}>Guardar</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Delete Confirmation */}
      <AlertDialog open={deleteDialogOpen} onOpenChange={setDeleteDialogOpen}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Confirmar eliminação</AlertDialogTitle>
            <AlertDialogDescription>
              Tem a certeza que deseja eliminar a impressora "{deleteTarget?.name}"?
              Esta ação não pode ser desfeita.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Cancelar</AlertDialogCancel>
            <AlertDialogAction 
              onClick={handleDeletePrinter}
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

export default AdminPrinters;
