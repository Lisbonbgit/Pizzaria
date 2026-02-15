import React, { useState, useEffect, useCallback } from 'react';
import { 
  Loader2, 
  Plus, 
  Pencil, 
  Trash2, 
  QrCode,
  Download,
  Eye,
  EyeOff
} from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Switch } from '@/components/ui/switch';
import { Badge } from '@/components/ui/badge';
import { Card, CardContent } from '@/components/ui/card';
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter } from '@/components/ui/dialog';
import { AlertDialog, AlertDialogAction, AlertDialogCancel, AlertDialogContent, AlertDialogDescription, AlertDialogFooter, AlertDialogHeader, AlertDialogTitle } from '@/components/ui/alert-dialog';
import { toast } from 'sonner';
import AdminLayout from '@/components/AdminLayout';
import { tablesAPI } from '@/lib/api';

const AdminTables = () => {
  const [tables, setTables] = useState([]);
  const [loading, setLoading] = useState(true);
  
  // Table Modal
  const [tableModalOpen, setTableModalOpen] = useState(false);
  const [editingTable, setEditingTable] = useState(null);
  const [tableForm, setTableForm] = useState({ number: 1, name: '', active: true });
  
  // QR Modal
  const [qrModalOpen, setQrModalOpen] = useState(false);
  const [qrData, setQrData] = useState(null);
  const [loadingQR, setLoadingQR] = useState(false);
  
  // Delete confirmation
  const [deleteDialogOpen, setDeleteDialogOpen] = useState(false);
  const [deleteTarget, setDeleteTarget] = useState(null);

  const loadTables = useCallback(async () => {
    try {
      const response = await tablesAPI.list();
      setTables(response.data);
    } catch (err) {
      console.error('Error loading tables:', err);
      toast.error('Erro ao carregar mesas');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    loadTables();
  }, [loadTables]);

  const openTableModal = (table = null) => {
    if (table) {
      setEditingTable(table);
      setTableForm({ number: table.number, name: table.name || '', active: table.active });
    } else {
      setEditingTable(null);
      const maxNumber = tables.length > 0 ? Math.max(...tables.map(t => t.number)) : 0;
      setTableForm({ number: maxNumber + 1, name: '', active: true });
    }
    setTableModalOpen(true);
  };

  const handleSaveTable = async () => {
    if (tableForm.number <= 0) {
      toast.error('Número da mesa deve ser maior que 0');
      return;
    }

    try {
      if (editingTable) {
        await tablesAPI.update(editingTable.id, tableForm);
        toast.success('Mesa atualizada');
      } else {
        await tablesAPI.create(tableForm);
        toast.success('Mesa criada');
      }
      setTableModalOpen(false);
      loadTables();
    } catch (err) {
      console.error('Error saving table:', err);
      if (err.response?.data?.detail) {
        toast.error(err.response.data.detail);
      } else {
        toast.error('Erro ao guardar mesa');
      }
    }
  };

  const confirmDeleteTable = (table) => {
    setDeleteTarget(table);
    setDeleteDialogOpen(true);
  };

  const handleDeleteTable = async () => {
    try {
      await tablesAPI.delete(deleteTarget.id);
      toast.success('Mesa eliminada');
      setDeleteDialogOpen(false);
      loadTables();
    } catch (err) {
      console.error('Error deleting table:', err);
      toast.error('Erro ao eliminar mesa');
    }
  };

  const toggleTableStatus = async (table) => {
    try {
      await tablesAPI.update(table.id, { active: !table.active });
      toast.success(table.active ? 'Mesa desativada' : 'Mesa ativada');
      loadTables();
    } catch (err) {
      console.error('Error toggling table status:', err);
      toast.error('Erro ao alterar estado da mesa');
    }
  };

  const showQRCode = async (table) => {
    setLoadingQR(true);
    setQrModalOpen(true);
    
    try {
      const baseUrl = window.location.origin;
      const response = await tablesAPI.getQRCode(table.id, baseUrl);
      setQrData(response.data);
    } catch (err) {
      console.error('Error getting QR code:', err);
      toast.error('Erro ao gerar QR Code');
      setQrModalOpen(false);
    } finally {
      setLoadingQR(false);
    }
  };

  const downloadQRCode = () => {
    if (!qrData?.qr_code) return;
    
    const link = document.createElement('a');
    link.href = qrData.qr_code;
    link.download = `mesa-${qrData.table_number}-qrcode.png`;
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
    toast.success('QR Code descarregado');
  };

  if (loading) {
    return (
      <AdminLayout title="Mesas">
        <div className="flex items-center justify-center h-64">
          <Loader2 className="h-8 w-8 animate-spin text-primary" />
        </div>
      </AdminLayout>
    );
  }

  return (
    <AdminLayout title="Mesas">
      <div className="flex justify-between items-center mb-6">
        <p className="text-muted-foreground">{tables.length} mesas</p>
        <Button onClick={() => openTableModal()} data-testid="add-table-btn">
          <Plus className="h-4 w-4 mr-2" />
          Nova Mesa
        </Button>
      </div>

      <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
        {tables.map((table) => (
          <Card key={table.id} data-testid={`table-card-${table.id}`}>
            <CardContent className="p-4">
              <div className="flex items-center justify-between mb-4">
                <div className="flex items-center gap-3">
                  <div className="w-12 h-12 rounded-lg bg-primary/10 flex items-center justify-center">
                    <span className="font-heading text-xl font-bold text-primary">
                      {table.number}
                    </span>
                  </div>
                  <div>
                    <h3 className="font-semibold">{table.name || `Mesa ${table.number}`}</h3>
                    {!table.active && (
                      <Badge variant="secondary">Inativa</Badge>
                    )}
                  </div>
                </div>
              </div>
              <div className="flex gap-2">
                <Button 
                  variant="outline" 
                  size="sm"
                  className="flex-1"
                  onClick={() => showQRCode(table)}
                >
                  <QrCode className="h-4 w-4 mr-1" />
                  QR Code
                </Button>
                <Button variant="outline" size="sm" onClick={() => openTableModal(table)}>
                  <Pencil className="h-4 w-4" />
                </Button>
                <Button 
                  variant="outline" 
                  size="sm"
                  onClick={() => toggleTableStatus(table)}
                >
                  {table.active ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
                </Button>
                <Button 
                  variant="outline" 
                  size="sm"
                  onClick={() => confirmDeleteTable(table)}
                >
                  <Trash2 className="h-4 w-4 text-destructive" />
                </Button>
              </div>
            </CardContent>
          </Card>
        ))}
      </div>

      {/* Table Modal */}
      <Dialog open={tableModalOpen} onOpenChange={setTableModalOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>
              {editingTable ? 'Editar Mesa' : 'Nova Mesa'}
            </DialogTitle>
          </DialogHeader>
          <div className="space-y-4 py-4">
            <div className="space-y-2">
              <Label htmlFor="table-number">Número da Mesa</Label>
              <Input
                id="table-number"
                type="number"
                min="1"
                value={tableForm.number}
                onChange={(e) => setTableForm(prev => ({ ...prev, number: parseInt(e.target.value) || 1 }))}
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="table-name">Nome (opcional)</Label>
              <Input
                id="table-name"
                value={tableForm.name}
                onChange={(e) => setTableForm(prev => ({ ...prev, name: e.target.value }))}
                placeholder="Ex: Mesa da Janela"
              />
            </div>
            <div className="flex items-center gap-2">
              <Switch
                id="table-active"
                checked={tableForm.active}
                onCheckedChange={(checked) => setTableForm(prev => ({ ...prev, active: checked }))}
              />
              <Label htmlFor="table-active">Ativa</Label>
            </div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setTableModalOpen(false)}>Cancelar</Button>
            <Button onClick={handleSaveTable}>Guardar</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* QR Code Modal */}
      <Dialog open={qrModalOpen} onOpenChange={setQrModalOpen}>
        <DialogContent className="max-w-sm">
          <DialogHeader>
            <DialogTitle>QR Code da Mesa {qrData?.table_number}</DialogTitle>
          </DialogHeader>
          <div className="py-4">
            {loadingQR ? (
              <div className="flex items-center justify-center h-64">
                <Loader2 className="h-8 w-8 animate-spin text-primary" />
              </div>
            ) : qrData ? (
              <div className="text-center">
                <div className="qr-container inline-block mb-4">
                  <img
                    src={qrData.qr_code}
                    alt={`QR Code Mesa ${qrData.table_number}`}
                    className="w-64 h-64"
                  />
                </div>
                <p className="text-sm text-muted-foreground mb-4 break-all">
                  {qrData.url}
                </p>
                <Button onClick={downloadQRCode} className="w-full">
                  <Download className="h-4 w-4 mr-2" />
                  Descarregar QR Code
                </Button>
              </div>
            ) : null}
          </div>
        </DialogContent>
      </Dialog>

      {/* Delete Confirmation */}
      <AlertDialog open={deleteDialogOpen} onOpenChange={setDeleteDialogOpen}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Confirmar eliminação</AlertDialogTitle>
            <AlertDialogDescription>
              Tem a certeza que deseja eliminar a Mesa {deleteTarget?.number}?
              Esta ação não pode ser desfeita.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Cancelar</AlertDialogCancel>
            <AlertDialogAction 
              onClick={handleDeleteTable}
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

export default AdminTables;
