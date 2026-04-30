import React, { useState, useEffect, useCallback } from 'react';
import { 
  Loader2, 
  Search, 
  RefreshCw,
  Printer,
  Eye,
  CheckCircle,
  Clock,
  XCircle,
  CreditCard,
  Banknote,
  Smartphone,
  Wallet
} from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Badge } from '@/components/ui/badge';
import { Card, CardContent } from '@/components/ui/card';
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter } from '@/components/ui/dialog';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { Checkbox } from '@/components/ui/checkbox';
import { toast } from 'sonner';
import AdminLayout from '@/components/AdminLayout';
import { ordersAPI, printersAPI } from '@/lib/api';

const statusOptions = [
  { value: 'received', label: 'Recebido' },
  { value: 'preparing', label: 'Em Preparação' },
  { value: 'ready', label: 'Pronto' },
  { value: 'delivered', label: 'Entregue' },
  { value: 'cancelled', label: 'Cancelado' }
];

const paymentMethods = [
  { value: 'dinheiro', label: 'Dinheiro', icon: Banknote },
  { value: 'cartao', label: 'Cartão', icon: CreditCard },
  { value: 'mbway', label: 'MB WAY', icon: Smartphone },
  { value: 'multibanco', label: 'Multibanco', icon: Wallet },
];

const AdminOrders = () => {
  const [orders, setOrders] = useState([]);
  const [loading, setLoading] = useState(true);
  const [searchTerm, setSearchTerm] = useState('');
  const [statusFilter, setStatusFilter] = useState('all');
  const [selectedOrder, setSelectedOrder] = useState(null);
  const [detailModalOpen, setDetailModalOpen] = useState(false);
  
  // Payment method modal
  const [paymentModalOpen, setPaymentModalOpen] = useState(false);
  const [paymentOrderId, setPaymentOrderId] = useState(null);
  const [selectedPaymentMethod, setSelectedPaymentMethod] = useState(null);

  // Reprint modal
  const [reprintModalOpen, setReprintModalOpen] = useState(false);
  const [reprintOrderId, setReprintOrderId] = useState(null);
  const [printersList, setPrintersList] = useState([]);
  const [selectedPrinters, setSelectedPrinters] = useState([]);
  const [reprintLoading, setReprintLoading] = useState(false);

  const loadOrders = useCallback(async () => {
    try {
      const params = {};
      if (statusFilter !== 'all') {
        params.status = statusFilter;
      }
      const response = await ordersAPI.list(params);
      setOrders(response.data);
    } catch (err) {
      console.error('Error loading orders:', err);
      toast.error('Erro ao carregar pedidos');
    } finally {
      setLoading(false);
    }
  }, [statusFilter]);

  useEffect(() => {
    loadOrders();
  }, [loadOrders]);

  const handleStatusChange = async (orderId, newStatus) => {
    try {
      await ordersAPI.updateStatus(orderId, newStatus);
      toast.success('Estado atualizado');
      loadOrders();
    } catch (err) {
      console.error('Error updating status:', err);
      toast.error('Erro ao atualizar estado');
    }
  };

  const openReprintModal = async (orderId) => {
    setReprintOrderId(orderId);
    setSelectedPrinters([]);
    setReprintModalOpen(true);
    try {
      const res = await printersAPI.list();
      setPrintersList(res.data);
    } catch {
      toast.error('Erro ao carregar impressoras');
    }
  };

  const togglePrinterSelection = (printerId) => {
    setSelectedPrinters(prev => {
      if (prev.includes(printerId)) {
        return prev.filter(id => id !== printerId);
      }
      return [...prev, printerId];
    });
  };

  const handleConfirmReprint = async () => {
    if (selectedPrinters.length === 0) {
      toast.error('Selecione pelo menos uma impressora');
      return;
    }
    setReprintLoading(true);
    try {
      await ordersAPI.reprint(reprintOrderId, selectedPrinters);
      toast.success(`Impressão agendada para ${selectedPrinters.length} impressora(s)`);
      setReprintModalOpen(false);
    } catch (err) {
      console.error('Error reprinting:', err);
      toast.error('Erro ao reimprimir');
    } finally {
      setReprintLoading(false);
    }
  };

  const openPaymentModal = (orderId) => {
    setPaymentOrderId(orderId);
    setSelectedPaymentMethod(null);
    setPaymentModalOpen(true);
  };

  const handleConfirmPayment = async () => {
    if (!selectedPaymentMethod) {
      toast.error('Selecione um método de pagamento');
      return;
    }
    try {
      await ordersAPI.markPaid(paymentOrderId, selectedPaymentMethod);
      toast.success('Marcado como pago');
      setPaymentModalOpen(false);
      loadOrders();
    } catch (err) {
      console.error('Error marking paid:', err);
      toast.error('Erro ao marcar como pago');
    }
  };

  const getPaymentMethodLabel = (method) => {
    const found = paymentMethods.find(m => m.value === method);
    return found ? found.label : method || '—';
  };

  const getStatusBadge = (status) => {
    const statusMap = {
      received: { label: 'Recebido', className: 'status-received' },
      preparing: { label: 'Em Preparação', className: 'status-preparing' },
      ready: { label: 'Pronto', className: 'status-ready' },
      delivered: { label: 'Entregue', className: 'status-delivered' },
      cancelled: { label: 'Cancelado', className: 'status-cancelled' }
    };
    const info = statusMap[status] || statusMap.received;
    return <Badge className={info.className}>{info.label}</Badge>;
  };

  const getPrintStatusIcon = (status) => {
    switch (status) {
      case 'printed':
        return <CheckCircle className="h-4 w-4 text-green-600" />;
      case 'failed':
        return <XCircle className="h-4 w-4 text-red-600" />;
      default:
        return <Clock className="h-4 w-4 text-yellow-600" />;
    }
  };

  const filteredOrders = orders.filter(order => {
    if (searchTerm) {
      const search = searchTerm.toLowerCase();
      return (
        order.order_number.toString().includes(search) ||
        order.table_number.toString().includes(search)
      );
    }
    return true;
  });

  const viewOrderDetails = (order) => {
    setSelectedOrder(order);
    setDetailModalOpen(true);
  };

  if (loading) {
    return (
      <AdminLayout title="Pedidos">
        <div className="flex items-center justify-center h-64">
          <Loader2 className="h-8 w-8 animate-spin text-primary" />
        </div>
      </AdminLayout>
    );
  }

  return (
    <AdminLayout title="Pedidos">
      {/* Filters */}
      <div className="flex flex-col sm:flex-row gap-4 mb-6">
        <div className="relative flex-1">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
          <Input
            placeholder="Pesquisar por nº pedido ou mesa..."
            value={searchTerm}
            onChange={(e) => setSearchTerm(e.target.value)}
            className="pl-10"
            data-testid="orders-search-input"
          />
        </div>
        <Select value={statusFilter} onValueChange={setStatusFilter}>
          <SelectTrigger className="w-full sm:w-48" data-testid="orders-status-filter">
            <SelectValue placeholder="Filtrar por estado" />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="all">Todos os estados</SelectItem>
            {statusOptions.map(opt => (
              <SelectItem key={opt.value} value={opt.value}>{opt.label}</SelectItem>
            ))}
          </SelectContent>
        </Select>
        <Button variant="outline" onClick={loadOrders}>
          <RefreshCw className="h-4 w-4 mr-2" />
          Atualizar
        </Button>
      </div>

      {/* Orders List */}
      {filteredOrders.length === 0 ? (
        <Card>
          <CardContent className="py-12 text-center">
            <p className="text-muted-foreground">Nenhum pedido encontrado</p>
          </CardContent>
        </Card>
      ) : (
        <div className="space-y-4">
          {filteredOrders.map((order) => (
            <Card key={order.id} data-testid={`order-card-${order.id}`}>
              <CardContent className="p-4">
                <div className="flex flex-col lg:flex-row lg:items-center justify-between gap-4">
                  {/* Order Info */}
                  <div className="flex items-start gap-4">
                    <div className="text-center">
                      <p className="text-xs text-muted-foreground uppercase">Pedido</p>
                      <p className="font-heading text-2xl font-bold">#{order.order_number}</p>
                    </div>
                    <div>
                      <div className="flex items-center gap-2 mb-1 flex-wrap">
                        <Badge variant="outline">Mesa {order.table_number}</Badge>
                        {getStatusBadge(order.status)}
                        <div className="flex items-center gap-1" title={`Impressão: ${order.print_status}`}>
                          {getPrintStatusIcon(order.print_status)}
                        </div>
                        {order.paid && (
                          <Badge variant="secondary" className="bg-green-100 text-green-800">
                            Pago {order.payment_method ? `(${getPaymentMethodLabel(order.payment_method)})` : ''}
                          </Badge>
                        )}
                      </div>
                      <p className="text-sm text-muted-foreground">
                        {order.items.length} itens • € {order.total.toFixed(2)}
                      </p>
                      <p className="text-xs text-muted-foreground">
                        {new Date(order.created_at).toLocaleString('pt-PT')}
                      </p>
                    </div>
                  </div>

                  {/* Actions */}
                  <div className="flex flex-wrap items-center gap-2">
                    <Select 
                      value={order.status} 
                      onValueChange={(value) => handleStatusChange(order.id, value)}
                    >
                      <SelectTrigger className="w-40">
                        <SelectValue />
                      </SelectTrigger>
                      <SelectContent>
                        {statusOptions.map(opt => (
                          <SelectItem key={opt.value} value={opt.value}>{opt.label}</SelectItem>
                        ))}
                      </SelectContent>
                    </Select>
                    <Button 
                      variant="outline" 
                      size="sm"
                      onClick={() => viewOrderDetails(order)}
                    >
                      <Eye className="h-4 w-4 mr-1" />
                      Ver
                    </Button>
                    <Button 
                      variant="outline" 
                      size="sm"
                      onClick={() => openReprintModal(order.id)}
                    >
                      <Printer className="h-4 w-4 mr-1" />
                      Reimprimir
                    </Button>
                    {!order.paid && (
                      <Button 
                        variant="outline" 
                        size="sm"
                        onClick={() => openPaymentModal(order.id)}
                      >
                        <CheckCircle className="h-4 w-4 mr-1" />
                        Pago
                      </Button>
                    )}
                  </div>
                </div>
              </CardContent>
            </Card>
          ))}
        </div>
      )}

      {/* Payment Method Modal */}
      <Dialog open={paymentModalOpen} onOpenChange={setPaymentModalOpen}>
        <DialogContent className="max-w-sm">
          <DialogHeader>
            <DialogTitle className="font-heading text-xl">Método de Pagamento</DialogTitle>
          </DialogHeader>
          <div className="grid grid-cols-2 gap-3 py-4">
            {paymentMethods.map((method) => {
              const Icon = method.icon;
              const isSelected = selectedPaymentMethod === method.value;
              return (
                <button
                  key={method.value}
                  onClick={() => setSelectedPaymentMethod(method.value)}
                  className={`flex flex-col items-center gap-2 p-4 rounded-xl border-2 transition-all ${
                    isSelected
                      ? 'border-primary bg-primary/5 shadow-sm'
                      : 'border-border hover:border-primary/40 hover:bg-secondary/50'
                  }`}
                >
                  <Icon className={`h-8 w-8 ${isSelected ? 'text-primary' : 'text-muted-foreground'}`} />
                  <span className={`text-sm font-medium ${isSelected ? 'text-primary' : ''}`}>
                    {method.label}
                  </span>
                </button>
              );
            })}
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setPaymentModalOpen(false)}>
              Cancelar
            </Button>
            <Button onClick={handleConfirmPayment} disabled={!selectedPaymentMethod}>
              <CheckCircle className="h-4 w-4 mr-2" />
              Confirmar Pagamento
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Order Detail Modal */}
      <Dialog open={detailModalOpen} onOpenChange={setDetailModalOpen}>
        <DialogContent className="max-w-lg max-h-[90vh] overflow-y-auto">
          {selectedOrder && (
            <>
              <DialogHeader>
                <DialogTitle className="font-heading text-2xl">
                  Pedido #{selectedOrder.order_number}
                </DialogTitle>
              </DialogHeader>

              <div className="space-y-4">
                {/* Header Info */}
                <div className="flex justify-between items-center p-4 bg-secondary/50 rounded-lg">
                  <div>
                    <p className="text-sm text-muted-foreground">Mesa</p>
                    <p className="text-2xl font-bold">{selectedOrder.table_number}</p>
                  </div>
                  <div className="text-right">
                    {getStatusBadge(selectedOrder.status)}
                    <p className="text-sm text-muted-foreground mt-1">
                      {new Date(selectedOrder.created_at).toLocaleString('pt-PT')}
                    </p>
                  </div>
                </div>

                {/* Items */}
                <div>
                  <h4 className="font-semibold mb-3">Itens</h4>
                  <div className="space-y-3">
                    {selectedOrder.items.map((item, idx) => (
                      <div key={idx} className="p-3 border rounded-lg">
                        <div className="flex justify-between">
                          <span className="font-medium">{item.quantity}x {item.product_name}</span>
                          <span className="font-semibold">€ {item.total_price.toFixed(2)}</span>
                        </div>
                        {item.variation && (
                          <p className="text-sm text-muted-foreground">{item.variation.name}</p>
                        )}
                        {item.extras?.length > 0 && (
                          <p className="text-sm text-muted-foreground">
                            + {item.extras.map(e => e.name).join(', ')}
                          </p>
                        )}
                        {item.selected_complements?.length > 0 && (
                          <div className="mt-1 space-y-1">
                            {item.selected_complements.map((group, gIdx) => (
                              <div key={gIdx}>
                                <span className="text-xs font-semibold text-muted-foreground uppercase">{group.group_name}:</span>
                                <span className="text-sm text-muted-foreground ml-1">
                                  {group.items.map(i => {
                                    const price = i.price > 0 ? ` (+€${i.price.toFixed(2)})` : '';
                                    return `${i.name}${price}`;
                                  }).join(', ')}
                                </span>
                              </div>
                            ))}
                          </div>
                        )}
                        {item.selected_preference && (
                          <p className="text-sm text-primary font-medium mt-1">{item.selected_preference}</p>
                        )}
                        {item.notes && (
                          <p className="text-sm italic text-muted-foreground">"{item.notes}"</p>
                        )}
                      </div>
                    ))}
                  </div>
                </div>

                {/* Order Notes */}
                {selectedOrder.notes && (
                  <div className="p-3 bg-yellow-50 dark:bg-yellow-900/20 rounded-lg">
                    <p className="text-sm font-semibold">Observações:</p>
                    <p>{selectedOrder.notes}</p>
                  </div>
                )}

                {/* Total */}
                <div className="flex justify-between items-center pt-4 border-t">
                  <span className="text-lg">Total</span>
                  <span className="text-2xl font-bold">€ {selectedOrder.total.toFixed(2)}</span>
                </div>

                {/* Payment info */}
                {selectedOrder.paid && (
                  <div className="flex items-center gap-2 text-sm">
                    <CheckCircle className="h-4 w-4 text-green-600" />
                    <span>Pago — {getPaymentMethodLabel(selectedOrder.payment_method)}</span>
                  </div>
                )}

                {/* Print Status */}
                <div className="flex items-center gap-2 text-sm">
                  {getPrintStatusIcon(selectedOrder.print_status)}
                  <span>
                    Impressão: {
                      selectedOrder.print_status === 'printed' ? 'Impresso' :
                      selectedOrder.print_status === 'failed' ? 'Falhou' : 'Pendente'
                    }
                  </span>
                </div>
              </div>
            </>
          )}
        </DialogContent>
      </Dialog>

      {/* Reprint Modal */}
      <Dialog open={reprintModalOpen} onOpenChange={setReprintModalOpen}>
        <DialogContent className="max-w-sm">
          <DialogHeader>
            <DialogTitle className="font-heading text-xl flex items-center gap-2">
              <Printer className="h-5 w-5" />
              Reimprimir Pedido
            </DialogTitle>
          </DialogHeader>
          <p className="text-sm text-muted-foreground">Selecione as impressoras para reimpressão:</p>
          <div className="space-y-3 py-4">
            {printersList.length === 0 ? (
              <p className="text-sm text-muted-foreground text-center py-4">Nenhuma impressora configurada</p>
            ) : (
              printersList.map((printer) => {
                const isSelected = selectedPrinters.includes(printer.id);
                return (
                  <div
                    key={printer.id}
                    onClick={() => togglePrinterSelection(printer.id)}
                    className={`flex items-center gap-3 p-4 rounded-xl border-2 cursor-pointer transition-all ${
                      isSelected
                        ? 'border-primary bg-primary/5'
                        : 'border-border hover:border-primary/40 hover:bg-secondary/50'
                    }`}
                  >
                    <Checkbox checked={isSelected} />
                    <div className="flex-1">
                      <p className={`font-medium ${isSelected ? 'text-primary' : ''}`}>{printer.name}</p>
                      <p className="text-xs text-muted-foreground">
                        {printer.ip}:{printer.port} • {printer.printer_type === 'cashier' ? 'Caixa' : 'Cozinha'}
                      </p>
                    </div>
                    <Printer className={`h-5 w-5 ${isSelected ? 'text-primary' : 'text-muted-foreground'}`} />
                  </div>
                );
              })
            )}
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setReprintModalOpen(false)}>
              Cancelar
            </Button>
            <Button 
              onClick={handleConfirmReprint} 
              disabled={selectedPrinters.length === 0 || reprintLoading}
            >
              {reprintLoading ? (
                <Loader2 className="h-4 w-4 mr-2 animate-spin" />
              ) : (
                <Printer className="h-4 w-4 mr-2" />
              )}
              Reimprimir ({selectedPrinters.length})
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </AdminLayout>
  );
};

export default AdminOrders;
