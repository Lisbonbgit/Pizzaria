import React, { useState, useEffect, useCallback } from 'react';
import {
  Loader2,
  Users,
  UserPlus,
  Trash2,
  Settings2,
  Monitor,
  ExternalLink
} from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Switch } from '@/components/ui/switch';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import {
  AlertDialog, AlertDialogAction, AlertDialogCancel, AlertDialogContent,
  AlertDialogDescription, AlertDialogFooter, AlertDialogHeader, AlertDialogTitle
} from '@/components/ui/alert-dialog';
import { toast } from 'sonner';
import AdminLayout from '@/components/AdminLayout';
import { adminPosAPI, checkoutAPI } from '@/lib/api';

const PIN_REGEX = /^\d{4}$/;

const AdminPos = () => {
  // Utilizadores
  const [users, setUsers] = useState([]);
  const [loadingUsers, setLoadingUsers] = useState(true);
  const [newUser, setNewUser] = useState({ name: '', pin: '' });
  const [creatingUser, setCreatingUser] = useState(false);
  const [deleteDialogOpen, setDeleteDialogOpen] = useState(false);
  const [deleteTarget, setDeleteTarget] = useState(null);

  // Definições
  const [settings, setSettings] = useState({
    require_open_cash: true,
    cash_payment_method_id: null,
    z_footer_text: '',
  });
  const [loadingSettings, setLoadingSettings] = useState(true);
  const [savingSettings, setSavingSettings] = useState(false);
  const [paymentMethods, setPaymentMethods] = useState([]);

  // Iniciar POS
  const [startingPos, setStartingPos] = useState(false);

  const loadUsers = useCallback(async () => {
    setLoadingUsers(true);
    try {
      const res = await adminPosAPI.listUsers();
      setUsers(res.data);
    } catch (err) {
      console.error('Error loading POS users:', err);
      toast.error('Erro ao carregar utilizadores do POS');
    } finally {
      setLoadingUsers(false);
    }
  }, []);

  const loadSettings = useCallback(async () => {
    setLoadingSettings(true);
    try {
      const res = await adminPosAPI.getSettings();
      setSettings({
        require_open_cash: res.data.require_open_cash ?? true,
        cash_payment_method_id: res.data.cash_payment_method_id ?? null,
        z_footer_text: res.data.z_footer_text ?? '',
      });
    } catch (err) {
      console.error('Error loading POS settings:', err);
      toast.error('Erro ao carregar definições do POS');
    } finally {
      setLoadingSettings(false);
    }
  }, []);

  const loadPaymentMethods = useCallback(async () => {
    try {
      const res = await checkoutAPI.paymentMethods();
      setPaymentMethods(res.data || []);
    } catch (err) {
      console.error('Error loading payment methods:', err);
      // Não bloqueia a página — a definição pode ficar por escolher.
    }
  }, []);

  useEffect(() => {
    loadUsers();
    loadSettings();
    loadPaymentMethods();
  }, [loadUsers, loadSettings, loadPaymentMethods]);

  const handleCreateUser = async () => {
    if (!newUser.name.trim()) {
      toast.error('Indica o nome do utilizador');
      return;
    }
    if (!PIN_REGEX.test(newUser.pin)) {
      toast.error('O PIN deve ter exatamente 4 dígitos');
      return;
    }
    setCreatingUser(true);
    try {
      await adminPosAPI.createUser({ name: newUser.name.trim(), pin: newUser.pin });
      toast.success('Utilizador do POS criado');
      setNewUser({ name: '', pin: '' });
      loadUsers();
    } catch (err) {
      console.error('Error creating POS user:', err);
      toast.error(err.response?.data?.detail || 'Erro ao criar utilizador');
    } finally {
      setCreatingUser(false);
    }
  };

  const toggleUserActive = async (user) => {
    try {
      await adminPosAPI.updateUser(user.id, { active: !user.active });
      toast.success(user.active ? 'Utilizador desativado' : 'Utilizador ativado');
      loadUsers();
    } catch (err) {
      console.error('Error toggling POS user:', err);
      toast.error(err.response?.data?.detail || 'Erro ao alterar o estado do utilizador');
    }
  };

  const confirmDeleteUser = (user) => {
    setDeleteTarget(user);
    setDeleteDialogOpen(true);
  };

  const handleDeleteUser = async () => {
    if (!deleteTarget) return;
    try {
      await adminPosAPI.deleteUser(deleteTarget.id);
      toast.success('Utilizador eliminado');
      setDeleteDialogOpen(false);
      setDeleteTarget(null);
      loadUsers();
    } catch (err) {
      console.error('Error deleting POS user:', err);
      toast.error(err.response?.data?.detail || 'Erro ao eliminar utilizador');
    }
  };

  const handleSaveSettings = async () => {
    setSavingSettings(true);
    try {
      // O PUT substitui sempre o objeto completo — nunca enviar um parcial.
      await adminPosAPI.saveSettings({
        require_open_cash: settings.require_open_cash,
        cash_payment_method_id: settings.cash_payment_method_id,
        z_footer_text: settings.z_footer_text,
      });
      toast.success('Definições guardadas');
    } catch (err) {
      console.error('Error saving POS settings:', err);
      toast.error(err.response?.data?.detail || 'Erro ao guardar definições');
    } finally {
      setSavingSettings(false);
    }
  };

  const handleStartPos = async () => {
    setStartingPos(true);
    try {
      const res = await adminPosAPI.createDeviceToken('terminal');
      localStorage.setItem('pos_device_token', res.data.token);
      window.open('/pos', '_blank');
    } catch (err) {
      console.error('Error starting POS:', err);
      toast.error(err.response?.data?.detail || 'Erro ao iniciar o POS');
    } finally {
      setStartingPos(false);
    }
  };

  return (
    <AdminLayout title="POS">
      <div className="space-y-6">
        {/* Utilizadores */}
        <Card>
          <CardHeader className="pb-3">
            <CardTitle className="text-lg flex items-center gap-2">
              <Users className="h-5 w-5" />
              Utilizadores do POS
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="flex flex-col sm:flex-row gap-2 sm:items-end">
              <div className="flex-1 space-y-1">
                <Label className="text-xs font-medium text-muted-foreground">Nome</Label>
                <Input
                  placeholder="ex.: Ana"
                  value={newUser.name}
                  onChange={(e) => setNewUser({ ...newUser, name: e.target.value })}
                />
              </div>
              <div className="w-full sm:w-32 space-y-1">
                <Label className="text-xs font-medium text-muted-foreground">PIN (4 dígitos)</Label>
                <Input
                  placeholder="0000"
                  inputMode="numeric"
                  maxLength={4}
                  value={newUser.pin}
                  onChange={(e) => setNewUser({ ...newUser, pin: e.target.value.replace(/\D/g, '').slice(0, 4) })}
                />
              </div>
              <Button onClick={handleCreateUser} disabled={creatingUser}>
                {creatingUser ? (
                  <Loader2 className="h-4 w-4 mr-2 animate-spin" />
                ) : (
                  <UserPlus className="h-4 w-4 mr-2" />
                )}
                Adicionar
              </Button>
            </div>

            {loadingUsers ? (
              <div className="flex items-center justify-center py-6">
                <Loader2 className="h-6 w-6 animate-spin text-primary" />
              </div>
            ) : users.length === 0 ? (
              <p className="text-sm text-muted-foreground text-center py-6">
                Nenhum utilizador do POS criado
              </p>
            ) : (
              <div className="space-y-2">
                {users.map((u) => (
                  <div key={u.id} className="flex items-center justify-between p-3 rounded-lg bg-secondary/50">
                    <div className="flex items-center gap-3">
                      <span className="font-medium">{u.name}</span>
                      {u.active ? (
                        <Badge className="bg-green-600 text-white border-0">Ativo</Badge>
                      ) : (
                        <Badge variant="secondary">Inativo</Badge>
                      )}
                    </div>
                    <div className="flex items-center gap-2">
                      <Button size="sm" variant="outline" onClick={() => toggleUserActive(u)}>
                        {u.active ? 'Desativar' : 'Ativar'}
                      </Button>
                      <Button
                        size="sm"
                        variant="outline"
                        className="text-destructive hover:text-destructive"
                        onClick={() => confirmDeleteUser(u)}
                      >
                        <Trash2 className="h-4 w-4" />
                      </Button>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </CardContent>
        </Card>

        {/* Definições */}
        <Card>
          <CardHeader className="pb-3">
            <CardTitle className="text-lg flex items-center gap-2">
              <Settings2 className="h-5 w-5" />
              Definições
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-4">
            {loadingSettings ? (
              <div className="flex items-center justify-center py-6">
                <Loader2 className="h-6 w-6 animate-spin text-primary" />
              </div>
            ) : (
              <>
                <div className="flex items-center justify-between rounded-lg border p-3">
                  <div>
                    <p className="text-sm font-medium">Exigir caixa aberta</p>
                    <p className="text-xs text-muted-foreground">
                      Sem caixa aberta, o POS não deixa fechar mesas.
                    </p>
                  </div>
                  <Switch
                    checked={settings.require_open_cash}
                    onCheckedChange={(v) => setSettings((s) => ({ ...s, require_open_cash: v }))}
                  />
                </div>

                <div className="space-y-1">
                  <Label className="text-xs font-medium text-muted-foreground">
                    Método de pagamento "Dinheiro" (Vendus)
                  </Label>
                  <Select
                    value={settings.cash_payment_method_id != null ? String(settings.cash_payment_method_id) : 'none'}
                    onValueChange={(v) =>
                      setSettings((s) => ({ ...s, cash_payment_method_id: v === 'none' ? null : Number(v) }))
                    }
                  >
                    <SelectTrigger>
                      <SelectValue placeholder="Selecionar método..." />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value="none">— Nenhum —</SelectItem>
                      {paymentMethods.map((m) => (
                        <SelectItem key={m.id} value={String(m.id)}>
                          {m.title || m.name}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </div>

                <div className="space-y-1">
                  <Label className="text-xs font-medium text-muted-foreground">
                    Texto de rodapé do fecho (Z)
                  </Label>
                  <Input
                    placeholder="ex.: Obrigado pela preferência!"
                    value={settings.z_footer_text}
                    onChange={(e) => setSettings((s) => ({ ...s, z_footer_text: e.target.value }))}
                  />
                </div>

                <Button onClick={handleSaveSettings} disabled={savingSettings}>
                  {savingSettings && <Loader2 className="h-4 w-4 mr-2 animate-spin" />}
                  Guardar definições
                </Button>
              </>
            )}
          </CardContent>
        </Card>

        {/* Iniciar POS */}
        <Card>
          <CardHeader className="pb-3">
            <CardTitle className="text-lg flex items-center gap-2">
              <Monitor className="h-5 w-5" />
              Iniciar POS
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-3">
            <p className="text-sm text-muted-foreground">
              Abre uma janela nova do POS neste dispositivo.
            </p>
            <Button onClick={handleStartPos} disabled={startingPos}>
              {startingPos ? (
                <Loader2 className="h-4 w-4 mr-2 animate-spin" />
              ) : (
                <ExternalLink className="h-4 w-4 mr-2" />
              )}
              Iniciar POS
            </Button>
          </CardContent>
        </Card>
      </div>

      <AlertDialog open={deleteDialogOpen} onOpenChange={setDeleteDialogOpen}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Confirmar eliminação</AlertDialogTitle>
            <AlertDialogDescription>
              Tens a certeza que queres eliminar o utilizador "{deleteTarget?.name}"? Esta ação não pode ser revertida.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Cancelar</AlertDialogCancel>
            <AlertDialogAction onClick={handleDeleteUser}>Eliminar</AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </AdminLayout>
  );
};

export default AdminPos;
