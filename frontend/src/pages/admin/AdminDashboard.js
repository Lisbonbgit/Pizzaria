import React, { useState, useEffect } from 'react';
import { Loader2, TrendingUp, ClipboardList, Euro, Users } from 'lucide-react';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import AdminLayout from '@/components/AdminLayout';
import { dashboardAPI, ordersAPI } from '@/lib/api';

const AdminDashboard = () => {
  const [stats, setStats] = useState(null);
  const [recentOrders, setRecentOrders] = useState([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    loadDashboard();
  }, []);

  const loadDashboard = async () => {
    try {
      const [statsRes, ordersRes] = await Promise.all([
        dashboardAPI.getStats(),
        ordersAPI.list()
      ]);
      setStats(statsRes.data);
      setRecentOrders(ordersRes.data.slice(0, 5));
    } catch (err) {
      console.error('Error loading dashboard:', err);
    } finally {
      setLoading(false);
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

  if (loading) {
    return (
      <AdminLayout title="Dashboard">
        <div className="flex items-center justify-center h-64">
          <Loader2 className="h-8 w-8 animate-spin text-primary" />
        </div>
      </AdminLayout>
    );
  }

  return (
    <AdminLayout title="Dashboard">
      {/* Stats Cards */}
      <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-4 mb-8">
        <Card data-testid="stat-orders">
          <CardHeader className="flex flex-row items-center justify-between pb-2">
            <CardTitle className="text-sm font-medium text-muted-foreground">
              Pedidos Hoje
            </CardTitle>
            <ClipboardList className="h-5 w-5 text-muted-foreground" />
          </CardHeader>
          <CardContent>
            <div className="text-3xl font-bold">{stats?.total_orders_today || 0}</div>
          </CardContent>
        </Card>

        <Card data-testid="stat-revenue">
          <CardHeader className="flex flex-row items-center justify-between pb-2">
            <CardTitle className="text-sm font-medium text-muted-foreground">
              Faturação Hoje
            </CardTitle>
            <Euro className="h-5 w-5 text-muted-foreground" />
          </CardHeader>
          <CardContent>
            <div className="text-3xl font-bold">
              € {(stats?.total_revenue_today || 0).toFixed(2)}
            </div>
          </CardContent>
        </Card>

        <Card data-testid="stat-pending">
          <CardHeader className="flex flex-row items-center justify-between pb-2">
            <CardTitle className="text-sm font-medium text-muted-foreground">
              Pendentes
            </CardTitle>
            <TrendingUp className="h-5 w-5 text-muted-foreground" />
          </CardHeader>
          <CardContent>
            <div className="text-3xl font-bold">
              {(stats?.orders_by_status?.received || 0) + (stats?.orders_by_status?.preparing || 0)}
            </div>
          </CardContent>
        </Card>

        <Card data-testid="stat-tables">
          <CardHeader className="flex flex-row items-center justify-between pb-2">
            <CardTitle className="text-sm font-medium text-muted-foreground">
              Mesas com Pedidos
            </CardTitle>
            <Users className="h-5 w-5 text-muted-foreground" />
          </CardHeader>
          <CardContent>
            <div className="text-3xl font-bold">
              {stats?.orders_by_table?.length || 0}
            </div>
          </CardContent>
        </Card>
      </div>

      {/* Recent Orders & Tables */}
      <div className="grid gap-6 lg:grid-cols-2">
        {/* Recent Orders */}
        <Card>
          <CardHeader>
            <CardTitle>Pedidos Recentes</CardTitle>
          </CardHeader>
          <CardContent>
            {recentOrders.length === 0 ? (
              <p className="text-muted-foreground text-center py-8">
                Nenhum pedido ainda
              </p>
            ) : (
              <div className="space-y-4">
                {recentOrders.map((order) => (
                  <div 
                    key={order.id} 
                    className="flex items-center justify-between p-3 bg-secondary/50 rounded-lg"
                    data-testid={`recent-order-${order.id}`}
                  >
                    <div>
                      <p className="font-semibold">Pedido #{order.order_number}</p>
                      <p className="text-sm text-muted-foreground">
                        Mesa {order.table_number} • {order.items.length} itens
                      </p>
                    </div>
                    <div className="text-right">
                      {getStatusBadge(order.status)}
                      <p className="text-sm font-semibold mt-1">
                        € {order.total.toFixed(2)}
                      </p>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </CardContent>
        </Card>

        {/* Orders by Table */}
        <Card>
          <CardHeader>
            <CardTitle>Pedidos por Mesa</CardTitle>
          </CardHeader>
          <CardContent>
            {!stats?.orders_by_table?.length ? (
              <p className="text-muted-foreground text-center py-8">
                Nenhum pedido hoje
              </p>
            ) : (
              <div className="space-y-3">
                {stats.orders_by_table.map((table) => (
                  <div 
                    key={table.table_number}
                    className="flex items-center justify-between p-3 bg-secondary/50 rounded-lg"
                  >
                    <div className="flex items-center gap-3">
                      <Badge variant="outline" className="text-lg font-bold">
                        {table.table_number}
                      </Badge>
                      <span className="text-sm text-muted-foreground">
                        {table.count} pedido{table.count !== 1 ? 's' : ''}
                      </span>
                    </div>
                    <span className="font-semibold">€ {table.total.toFixed(2)}</span>
                  </div>
                ))}
              </div>
            )}
          </CardContent>
        </Card>
      </div>
    </AdminLayout>
  );
};

export default AdminDashboard;
