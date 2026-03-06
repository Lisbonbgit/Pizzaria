import React, { useState, useEffect, useCallback } from 'react';
import {
  Loader2,
  CalendarDays,
  Mail,
  Send,
  TrendingUp,
  ShoppingBag,
  Receipt,
  XCircle,
  CheckCircle,
  Clock,
  ChevronLeft,
  ChevronRight,
  BarChart3,
  Trophy,
  CreditCard,
  Banknote,
  Smartphone,
  Wallet
} from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { toast } from 'sonner';
import AdminLayout from '@/components/AdminLayout';
import { reportsAPI } from '@/lib/api';

const paymentMethodIcons = {
  dinheiro: Banknote,
  cartao: CreditCard,
  mbway: Smartphone,
  multibanco: Wallet,
};

const paymentMethodLabels = {
  dinheiro: 'Dinheiro',
  cartao: 'Cartão',
  mbway: 'MB WAY',
  multibanco: 'Multibanco',
  'não especificado': 'Não especificado',
};

const AdminReports = () => {
  const [reportData, setReportData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [sendingEmail, setSendingEmail] = useState(false);
  const [selectedDate, setSelectedDate] = useState(() => {
    const now = new Date();
    return now.toISOString().split('T')[0];
  });

  const loadReport = useCallback(async () => {
    setLoading(true);
    try {
      const response = await reportsAPI.getData(selectedDate);
      setReportData(response.data);
    } catch (err) {
      console.error('Error loading report:', err);
      toast.error('Erro ao carregar relatório');
    } finally {
      setLoading(false);
    }
  }, [selectedDate]);

  useEffect(() => {
    loadReport();
  }, [loadReport]);

  const handleSendEmail = async () => {
    setSendingEmail(true);
    try {
      const response = await reportsAPI.sendEmail(selectedDate);
      if (response.data.success) {
        toast.success(response.data.message || 'Relatório enviado com sucesso!');
      }
    } catch (err) {
      console.error('Error sending report:', err);
      const errorMsg = err.response?.data?.detail || 'Erro ao enviar relatório por email';
      toast.error(errorMsg);
    } finally {
      setSendingEmail(false);
    }
  };

  const changeDate = (days) => {
    const date = new Date(selectedDate);
    date.setDate(date.getDate() + days);
    const today = new Date();
    today.setHours(23, 59, 59, 999);
    if (date <= today) {
      setSelectedDate(date.toISOString().split('T')[0]);
    }
  };

  const isToday = selectedDate === new Date().toISOString().split('T')[0];

  const formatDate = (dateStr) => {
    const date = new Date(dateStr + 'T12:00:00');
    const options = { weekday: 'long', day: 'numeric', month: 'long', year: 'numeric' };
    return date.toLocaleDateString('pt-PT', options);
  };

  // Find the max orders for the peak hours bar chart
  const maxOrders = reportData?.peak_hours
    ? Math.max(...reportData.peak_hours.map(h => h.orders), 1)
    : 1;

  if (loading && !reportData) {
    return (
      <AdminLayout title="Relatórios">
        <div className="flex items-center justify-center h-64">
          <Loader2 className="h-8 w-8 animate-spin text-primary" />
        </div>
      </AdminLayout>
    );
  }

  const summary = reportData?.summary || {};

  return (
    <AdminLayout title="Relatórios">
      {/* Date Selector & Send Email */}
      <div className="flex flex-col sm:flex-row items-start sm:items-center justify-between gap-4 mb-6">
        <div className="flex items-center gap-2">
          <Button variant="outline" size="icon" onClick={() => changeDate(-1)}>
            <ChevronLeft className="h-4 w-4" />
          </Button>
          <div className="flex items-center gap-2 px-4 py-2 rounded-lg border bg-card min-w-[200px] justify-center">
            <CalendarDays className="h-4 w-4 text-muted-foreground" />
            <input
              type="date"
              value={selectedDate}
              onChange={(e) => setSelectedDate(e.target.value)}
              max={new Date().toISOString().split('T')[0]}
              className="bg-transparent border-0 outline-none font-medium text-sm cursor-pointer"
            />
          </div>
          <Button variant="outline" size="icon" onClick={() => changeDate(1)} disabled={isToday}>
            <ChevronRight className="h-4 w-4" />
          </Button>
          {isToday && (
            <Badge variant="secondary" className="ml-2">Hoje</Badge>
          )}
        </div>

        <Button onClick={handleSendEmail} disabled={sendingEmail}>
          {sendingEmail ? (
            <>
              <Loader2 className="h-4 w-4 mr-2 animate-spin" />
              A enviar...
            </>
          ) : (
            <>
              <Send className="h-4 w-4 mr-2" />
              Enviar relatório por email
            </>
          )}
        </Button>
      </div>

      {/* Date label */}
      <p className="text-sm text-muted-foreground mb-6 capitalize">{formatDate(selectedDate)}</p>

      {loading ? (
        <div className="flex items-center justify-center h-32">
          <Loader2 className="h-6 w-6 animate-spin text-primary" />
        </div>
      ) : (
        <div className="space-y-6">
          {/* Summary Cards */}
          <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-5 gap-4">
            <Card>
              <CardContent className="p-4">
                <div className="flex items-center justify-between mb-2">
                  <span className="text-sm text-muted-foreground">Total Pedidos</span>
                  <ShoppingBag className="h-4 w-4 text-muted-foreground" />
                </div>
                <p className="text-3xl font-bold">{summary.total_orders || 0}</p>
              </CardContent>
            </Card>

            <Card>
              <CardContent className="p-4">
                <div className="flex items-center justify-between mb-2">
                  <span className="text-sm text-muted-foreground">Receita Total</span>
                  <TrendingUp className="h-4 w-4 text-green-600" />
                </div>
                <p className="text-3xl font-bold text-green-600">€ {(summary.total_revenue || 0).toFixed(2)}</p>
              </CardContent>
            </Card>

            <Card>
              <CardContent className="p-4">
                <div className="flex items-center justify-between mb-2">
                  <span className="text-sm text-muted-foreground">Ticket Médio</span>
                  <Receipt className="h-4 w-4 text-blue-600" />
                </div>
                <p className="text-3xl font-bold text-blue-600">€ {(summary.avg_ticket || 0).toFixed(2)}</p>
              </CardContent>
            </Card>

            <Card>
              <CardContent className="p-4">
                <div className="flex items-center justify-between mb-2">
                  <span className="text-sm text-muted-foreground">Concluídos</span>
                  <CheckCircle className="h-4 w-4 text-green-600" />
                </div>
                <p className="text-3xl font-bold">{summary.delivered_orders || 0}</p>
              </CardContent>
            </Card>

            <Card>
              <CardContent className="p-4">
                <div className="flex items-center justify-between mb-2">
                  <span className="text-sm text-muted-foreground">Cancelados</span>
                  <XCircle className="h-4 w-4 text-red-600" />
                </div>
                <p className="text-3xl font-bold text-red-600">{summary.cancelled_orders || 0}</p>
              </CardContent>
            </Card>
          </div>

          {/* Two columns: Payment Methods + Top Products */}
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
            {/* Payment Methods */}
            <Card>
              <CardHeader className="pb-3">
                <CardTitle className="text-lg flex items-center gap-2">
                  <CreditCard className="h-5 w-5" />
                  Métodos de Pagamento
                </CardTitle>
              </CardHeader>
              <CardContent>
                {Object.keys(reportData?.payment_methods || {}).length === 0 ? (
                  <p className="text-sm text-muted-foreground text-center py-6">
                    Nenhum pagamento registado
                  </p>
                ) : (
                  <div className="space-y-3">
                    {Object.entries(reportData.payment_methods).map(([method, data]) => {
                      const Icon = paymentMethodIcons[method] || Wallet;
                      const label = paymentMethodLabels[method] || method;
                      return (
                        <div key={method} className="flex items-center justify-between p-3 rounded-lg bg-secondary/50">
                          <div className="flex items-center gap-3">
                            <div className="w-10 h-10 rounded-full bg-primary/10 flex items-center justify-center">
                              <Icon className="h-5 w-5 text-primary" />
                            </div>
                            <div>
                              <p className="font-medium">{label}</p>
                              <p className="text-sm text-muted-foreground">{data.count} pedido{data.count !== 1 ? 's' : ''}</p>
                            </div>
                          </div>
                          <span className="font-bold text-lg">€ {data.total.toFixed(2)}</span>
                        </div>
                      );
                    })}
                  </div>
                )}
              </CardContent>
            </Card>

            {/* Top Products */}
            <Card>
              <CardHeader className="pb-3">
                <CardTitle className="text-lg flex items-center gap-2">
                  <Trophy className="h-5 w-5" />
                  Produtos Mais Vendidos
                </CardTitle>
              </CardHeader>
              <CardContent>
                {(reportData?.top_products || []).length === 0 ? (
                  <p className="text-sm text-muted-foreground text-center py-6">
                    Nenhum produto vendido
                  </p>
                ) : (
                  <div className="space-y-2">
                    {reportData.top_products.map((product, idx) => (
                      <div key={product.name} className="flex items-center gap-3 p-2 rounded-lg hover:bg-secondary/50">
                        <span className={`w-7 h-7 rounded-full flex items-center justify-center text-sm font-bold ${
                          idx === 0 ? 'bg-yellow-100 text-yellow-700' :
                          idx === 1 ? 'bg-gray-100 text-gray-700' :
                          idx === 2 ? 'bg-orange-100 text-orange-700' :
                          'bg-secondary text-muted-foreground'
                        }`}>
                          {idx + 1}
                        </span>
                        <span className="flex-1 font-medium truncate">{product.name}</span>
                        <Badge variant="secondary">{product.quantity}x</Badge>
                      </div>
                    ))}
                  </div>
                )}
              </CardContent>
            </Card>
          </div>

          {/* Peak Hours */}
          <Card>
            <CardHeader className="pb-3">
              <CardTitle className="text-lg flex items-center gap-2">
                <BarChart3 className="h-5 w-5" />
                Horários de Pico
              </CardTitle>
            </CardHeader>
            <CardContent>
              {(reportData?.peak_hours || []).every(h => h.orders === 0) ? (
                <p className="text-sm text-muted-foreground text-center py-6">
                  Sem dados de pedidos para este dia
                </p>
              ) : (
                <div className="flex items-end gap-1 h-48 px-2">
                  {(reportData?.peak_hours || []).map((hour) => {
                    const height = hour.orders > 0 ? Math.max((hour.orders / maxOrders) * 100, 8) : 0;
                    const hasOrders = hour.orders > 0;
                    return (
                      <div key={hour.hour} className="flex-1 flex flex-col items-center gap-1 group">
                        {/* Value label */}
                        <span className={`text-xs font-medium transition-opacity ${
                          hasOrders ? 'opacity-100' : 'opacity-0 group-hover:opacity-50'
                        }`}>
                          {hour.orders}
                        </span>
                        {/* Bar */}
                        <div
                          className={`w-full rounded-t transition-all ${
                            hasOrders ? 'bg-primary hover:bg-primary/80' : 'bg-secondary'
                          }`}
                          style={{ height: `${height}%`, minHeight: hasOrders ? '4px' : '2px' }}
                          title={`${hour.label}: ${hour.orders} pedido${hour.orders !== 1 ? 's' : ''}`}
                        />
                        {/* Hour label */}
                        <span className="text-[10px] text-muted-foreground -rotate-45 origin-center mt-1">
                          {hour.label}
                        </span>
                      </div>
                    );
                  })}
                </div>
              )}
            </CardContent>
          </Card>
        </div>
      )}
    </AdminLayout>
  );
};

export default AdminReports;
