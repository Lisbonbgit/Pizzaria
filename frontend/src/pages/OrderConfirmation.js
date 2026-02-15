import React, { useState, useEffect } from 'react';
import { useParams, Link } from 'react-router-dom';
import { CheckCircle, Clock, Loader2, AlertCircle, ArrowLeft } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { Card, CardContent } from '@/components/ui/card';
import { ordersAPI } from '@/lib/api';

const OrderConfirmation = () => {
  const { orderId } = useParams();
  const [order, setOrder] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  useEffect(() => {
    const loadOrder = async () => {
      try {
        const response = await ordersAPI.get(orderId);
        setOrder(response.data);
      } catch (err) {
        console.error('Error loading order:', err);
        setError('Pedido não encontrado');
      } finally {
        setLoading(false);
      }
    };

    loadOrder();
  }, [orderId]);

  const getStatusInfo = (status) => {
    const statusMap = {
      received: { label: 'Recebido', icon: CheckCircle, color: 'text-blue-600' },
      preparing: { label: 'Em Preparação', icon: Clock, color: 'text-yellow-600' },
      ready: { label: 'Pronto', icon: CheckCircle, color: 'text-green-600' },
      delivered: { label: 'Entregue', icon: CheckCircle, color: 'text-gray-600' },
      cancelled: { label: 'Cancelado', icon: AlertCircle, color: 'text-red-600' }
    };
    return statusMap[status] || statusMap.received;
  };

  if (loading) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-background">
        <div className="text-center">
          <Loader2 className="h-8 w-8 animate-spin mx-auto text-primary" />
          <p className="mt-4 text-muted-foreground">A carregar pedido...</p>
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
          <Link to="/">
            <Button className="mt-4">Voltar ao Menu</Button>
          </Link>
        </div>
      </div>
    );
  }

  const statusInfo = getStatusInfo(order.status);
  const StatusIcon = statusInfo.icon;

  return (
    <div className="min-h-screen bg-background p-4 md:p-6">
      <div className="max-w-lg mx-auto">
        {/* Back link */}
        <Link to="/" className="inline-flex items-center text-sm text-muted-foreground hover:text-foreground mb-6">
          <ArrowLeft className="h-4 w-4 mr-1" />
          Novo Pedido
        </Link>

        {/* Success Message */}
        <div className="text-center mb-8 animate-fade-in">
          <div className="w-20 h-20 rounded-full bg-green-100 dark:bg-green-900/30 flex items-center justify-center mx-auto mb-4">
            <CheckCircle className="h-10 w-10 text-green-600" />
          </div>
          <h1 className="font-heading text-3xl font-bold">Pedido Enviado!</h1>
          <p className="text-muted-foreground mt-2">
            O seu pedido foi enviado para a cozinha
          </p>
        </div>

        {/* Order Info Card */}
        <Card className="mb-6 animate-slide-up" data-testid="order-confirmation-card">
          <CardContent className="p-6">
            {/* Order Number & Status */}
            <div className="flex justify-between items-start mb-6">
              <div>
                <p className="text-sm text-muted-foreground uppercase tracking-wide">Pedido</p>
                <p className="font-heading text-3xl font-bold">#{order.order_number}</p>
              </div>
              <div className="text-right">
                <p className="text-sm text-muted-foreground uppercase tracking-wide">Mesa</p>
                <Badge variant="outline" className="text-xl font-bold mt-1">
                  {order.table_number}
                </Badge>
              </div>
            </div>

            {/* Status */}
            <div className="flex items-center gap-3 p-4 bg-secondary/50 rounded-lg mb-6">
              <StatusIcon className={`h-6 w-6 ${statusInfo.color}`} />
              <div>
                <p className="text-sm text-muted-foreground">Estado</p>
                <p className="font-semibold">{statusInfo.label}</p>
              </div>
            </div>

            {/* Items */}
            <div className="space-y-3 mb-6">
              <p className="text-sm text-muted-foreground uppercase tracking-wide">Itens</p>
              {order.items.map((item, index) => (
                <div key={index} className="flex justify-between items-start py-2 border-b border-border last:border-0">
                  <div className="flex-1">
                    <p className="font-medium">
                      {item.quantity}x {item.product_name}
                    </p>
                    {item.variation && (
                      <p className="text-sm text-muted-foreground">{item.variation.name}</p>
                    )}
                    {item.extras?.length > 0 && (
                      <p className="text-sm text-muted-foreground">
                        + {item.extras.map(e => e.name).join(', ')}
                      </p>
                    )}
                    {item.notes && (
                      <p className="text-sm text-muted-foreground italic">"{item.notes}"</p>
                    )}
                  </div>
                  <p className="font-semibold">€ {item.total_price.toFixed(2)}</p>
                </div>
              ))}
            </div>

            {/* Order Notes */}
            {order.notes && (
              <div className="mb-6 p-3 bg-yellow-50 dark:bg-yellow-900/20 rounded-lg">
                <p className="text-sm text-muted-foreground">Observações</p>
                <p className="font-medium">{order.notes}</p>
              </div>
            )}

            {/* Total */}
            <div className="flex justify-between items-center pt-4 border-t">
              <span className="text-lg">Total</span>
              <span className="font-heading text-2xl font-bold">€ {order.total.toFixed(2)}</span>
            </div>

            {/* Time */}
            <p className="text-sm text-muted-foreground text-center mt-4">
              {new Date(order.created_at).toLocaleString('pt-PT', {
                day: '2-digit',
                month: '2-digit',
                year: 'numeric',
                hour: '2-digit',
                minute: '2-digit'
              })}
            </p>
          </CardContent>
        </Card>

        {/* Action */}
        <div className="text-center">
          <Link to="/">
            <Button size="lg" variant="outline" className="rounded-full">
              Fazer Novo Pedido
            </Button>
          </Link>
        </div>
      </div>
    </div>
  );
};

export default OrderConfirmation;
