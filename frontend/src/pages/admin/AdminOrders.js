import React, { useState, useEffect, useCallback } from 'react';
import { 
  Loader2, 
  Search, 
  RefreshCw,
  Printer,
  Eye,
  CheckCircle,
  Clock,
  XCircle
} from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Badge } from '@/components/ui/badge';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Dialog, DialogContent, DialogHeader, DialogTitle } from '@/components/ui/dialog';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { toast } from 'sonner';
import AdminLayout from '@/components/AdminLayout';
import { ordersAPI } from '@/lib/api';

const statusOptions = [
  { value: 'received', label: 'Recebido' },
  { value: 'preparing', label: 'Em Preparação' },
  { value: 'ready', label: 'Pronto' },
  { value: 'delivered', label: 'Entregue' },
  { value: 'cancelled', label: 'Cancelado' }
];

const AdminOrders = () => {
  const [orders, setOrders] = useState([]);
  const [loading, setLoading] = useState(true);
  const [searchTerm, setSearchTerm] = useState('');
  const [statusFilter, setStatusFilter] = useState('all');
  const [selectedOrder, setSelectedOrder] = useState(null);
  const [detailModalOpen, setDetailModalOpen] = useState(false);

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

  const handleReprint = async (orderId) => {
    try {
      await ordersAPI.reprint(orderId);
      toast.success('Impressão agendada');
    } catch (err) {
      console.error('Error reprinting:', err);
      toast.error('Erro ao reimprimir');
    }
  };

  const handleMarkPaid = async (orderId) => {
    try {
      await ordersAPI.markPaid(orderId);
      toast.success('Marcado como pago');
      loadOrders();
    } catch (err) {
      console.error('Error marking paid:', err);
      toast.error('Erro ao marcar como pago');
    }
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
                      <div className="flex items-center gap-2 mb-1">
                        <Badge variant="outline">Mesa {order.table_number}</Badge>
                        {getStatusBadge(order.status)}
                        <div className="flex items-center gap-1" title={`Impressão: ${order.print_status}`}>
                          {getPrintStatusIcon(order.print_status)}
                        </div>
                        {order.paid && (
                          <Badge variant="secondary" className="bg-green-100 text-green-800">
                            Pago
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
                      onClick={() => handleReprint(order.id)}
                    >
                      <Printer className="h-4 w-4 mr-1" />
                      Reimprimir
                    </Button>
                    {!order.paid && (
                      <Button 
                        variant="outline" 
                        size="sm"
                        onClick={() => handleMarkPaid(order.id)}
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
    </AdminLayout>
  );
};

export default AdminOrders;
