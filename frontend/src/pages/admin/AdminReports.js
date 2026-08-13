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
import { Input } from '@/components/ui/input';
import { toast } from 'sonner';
import AdminLayout from '@/components/AdminLayout';
import { reportsAPI } from '@/lib/api';

const paymentMethodIcons = {
  dinheiro: Banknote,
  cartao: CreditCard,
  mbway: Smartphone,
  multibanco: Wallet,
  // Nomes tal como vêm do Vendus (fonte de verdade da receita)
  Dinheiro: Banknote,
  Multibanco: Wallet,
  'MB WAY': Smartphone,
  'MBWay': Smartphone,
  Cartão: CreditCard,
  'Cartão de Crédito': CreditCard,
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
  const [schedCfg, setSchedCfg] = useState(null);
  const [schedStatus, setSchedStatus] = useState(null);
  const [busySched, setBusySched] = useState(false);
  const [testing, setTesting] = useState(false);
  const [cfgForm, setCfgForm] = useState({ api_key: '', report_email: '', sender_email: '' });
  const [savingCfg, setSavingCfg] = useState(false);
  const [selectedDate, setSelectedDate] = useState(() => {
    const now = new Date();
    return now.toISOString().split('T')[0];
  });
  const [endDate, setEndDate] = useState(() => new Date().toISOString().split('T')[0]);

  const loadScheduler = useCallback(async () => {
    try {
      const [c, s] = await Promise.all([reportsAPI.getConfig(), reportsAPI.schedulerStatus()]);
      setSchedCfg(c.data);
      setSchedStatus(s.data);
      setCfgForm((f) => ({
        ...f,
        report_email: f.report_email || c.data.report_email || '',
        sender_email: f.sender_email || c.data.sender_email || '',
      }));
    } catch { /* ignore */ }
  }, []);

  const saveCfg = async () => {
    if (!cfgForm.report_email) { toast.error('Indica o email de destino'); return; }
    setSavingCfg(true);
    try {
      await reportsAPI.saveResendConfig(cfgForm);
      toast.success('Configuração guardada');
      setCfgForm((f) => ({ ...f, api_key: '' }));
      loadScheduler();
    } catch (e) {
      toast.error(e.response?.data?.detail || 'Erro ao guardar a configuração');
    } finally {
      setSavingCfg(false);
    }
  };

  const toggleScheduler = async (enable) => {
    setBusySched(true);
    try {
      await (enable ? reportsAPI.schedulerEnable() : reportsAPI.schedulerDisable());
      toast.success(enable ? 'Relatório automático ativado (00:00)' : 'Relatório automático desativado');
      loadScheduler();
    } catch (e) {
      toast.error(e.response?.data?.detail || 'Erro ao alterar o agendamento');
    } finally {
      setBusySched(false);
    }
  };

  const sendTestNow = async () => {
    setTesting(true);
    try {
      const r = await reportsAPI.testNow();
      if (r.data.success) toast.success(r.data.message || 'Relatório de teste enviado');
      else toast.error(r.data.error || r.data.message || 'Falha ao enviar');
    } catch (e) {
      toast.error(e.response?.data?.detail || 'Erro ao enviar o teste');
    } finally {
      setTesting(false);
    }
  };

  const loadReport = useCallback(async () => {
    setLoading(true);
    try {
      const end = endDate < selectedDate ? selectedDate : endDate;
      const response = await reportsAPI.getData(selectedDate, end);
      setReportData(response.data);
    } catch (err) {
      console.error('Error loading report:', err);
      toast.error('Erro ao carregar relatório');
    } finally {
      setLoading(false);
    }
  }, [selectedDate, endDate]);

  useEffect(() => {
    loadReport();
  }, [loadReport]);

  useEffect(() => {
    loadScheduler();
  }, [loadScheduler]);

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
      const d = date.toISOString().split('T')[0];
      setSelectedDate(d);
      setEndDate(d); // setas = um dia; intervalos usam os inputs De/Até
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
          <span className="text-muted-foreground text-sm">até</span>
          <div className="flex items-center gap-2 px-4 py-2 rounded-lg border bg-card justify-center">
            <CalendarDays className="h-4 w-4 text-muted-foreground" />
            <input
              type="date"
              value={endDate}
              min={selectedDate}
              max={new Date().toISOString().split('T')[0]}
              onChange={(e) => setEndDate(e.target.value)}
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

      {/* Configurar email do relatório (Resend) */}
      <Card className="mb-6">
        <CardHeader className="pb-3">
          <CardTitle className="text-base flex items-center gap-2">
            <Mail className="h-4 w-4" /> Configurar email do relatório (Resend)
          </CardTitle>
        </CardHeader>
        <CardContent className="space-y-3">
          <div className="grid gap-3 sm:grid-cols-2">
            <div className="space-y-1">
              <label className="text-xs font-medium text-muted-foreground">Chave do Resend (API key)</label>
              <Input
                type="password"
                autoComplete="off"
                placeholder={schedCfg?.resend_configured ? '•••••• (já guardada — preenche só para trocar)' : 're_...'}
                value={cfgForm.api_key}
                onChange={(e) => setCfgForm({ ...cfgForm, api_key: e.target.value })}
              />
            </div>
            <div className="space-y-1">
              <label className="text-xs font-medium text-muted-foreground">Email de destino (quem recebe)</label>
              <Input
                type="email"
                placeholder="ex.: dono@lenhaebrasa.com"
                value={cfgForm.report_email}
                onChange={(e) => setCfgForm({ ...cfgForm, report_email: e.target.value })}
              />
            </div>
            <div className="space-y-1 sm:col-span-2">
              <label className="text-xs font-medium text-muted-foreground">Remetente (opcional)</label>
              <Input
                type="email"
                placeholder="onboarding@resend.dev"
                value={cfgForm.sender_email}
                onChange={(e) => setCfgForm({ ...cfgForm, sender_email: e.target.value })}
              />
            </div>
          </div>
          <p className="text-xs text-muted-foreground">
            A chave é a API key do Resend (começa por <code>re_</code>). Se deixares o remetente vazio, usa <code>onboarding@resend.dev</code>, que só entrega no email da própria conta Resend — para enviar para outro email, verifica um domínio no Resend e usa um remetente desse domínio.
          </p>
          <Button onClick={saveCfg} disabled={savingCfg}>
            {savingCfg ? <Loader2 className="h-4 w-4 mr-2 animate-spin" /> : <CheckCircle className="h-4 w-4 mr-2" />}
            Guardar configuração
          </Button>
        </CardContent>
      </Card>

      {/* Envio automático diário */}
      <Card className="mb-6">
        <CardHeader className="pb-3">
          <CardTitle className="text-base flex items-center gap-2">
            <Clock className="h-4 w-4" /> Relatório automático (todos os dias às 00:00)
          </CardTitle>
        </CardHeader>
        <CardContent className="space-y-3">
          <div className="flex flex-wrap items-center gap-x-6 gap-y-1 text-sm">
            <span className="flex items-center gap-1.5">
              Email (Resend):
              {schedCfg?.resend_configured
                ? <Badge className="bg-green-600 text-white border-0">configurado</Badge>
                : <Badge variant="destructive">falta a chave</Badge>}
            </span>
            <span>Destinatário: <span className="font-medium">{schedCfg?.report_email || '—'}</span></span>
            <span className="flex items-center gap-1.5">
              Automático:
              {schedStatus?.enabled
                ? <Badge className="bg-green-600 text-white border-0">ligado</Badge>
                : <Badge variant="secondary">desligado</Badge>}
            </span>
            {schedStatus?.enabled && schedStatus?.next_run && (
              <span className="text-muted-foreground">próximo: {new Date(schedStatus.next_run).toLocaleString('pt-PT')}</span>
            )}
          </div>
          {!schedCfg?.resend_configured && (
            <p className="text-xs text-muted-foreground">
              Primeiro preenche a chave da Resend e o email de destino no cartão acima e clica em Guardar. Depois liga o automático aqui.
            </p>
          )}
          <div className="flex flex-wrap gap-2">
            {schedStatus?.enabled ? (
              <Button variant="outline" onClick={() => toggleScheduler(false)} disabled={busySched}>
                {busySched ? <Loader2 className="h-4 w-4 mr-2 animate-spin" /> : <XCircle className="h-4 w-4 mr-2" />}
                Desativar automático
              </Button>
            ) : (
              <Button onClick={() => toggleScheduler(true)} disabled={busySched || !schedCfg?.resend_configured}>
                {busySched ? <Loader2 className="h-4 w-4 mr-2 animate-spin" /> : <CheckCircle className="h-4 w-4 mr-2" />}
                Ativar automático (00:00)
              </Button>
            )}
            <Button variant="outline" onClick={sendTestNow} disabled={testing || !schedCfg?.resend_configured}>
              {testing ? <Loader2 className="h-4 w-4 mr-2 animate-spin" /> : <Send className="h-4 w-4 mr-2" />}
              Enviar teste agora
            </Button>
          </div>
        </CardContent>
      </Card>

      {/* Date label */}
      <p className="text-sm text-muted-foreground mb-6 capitalize">
        {selectedDate !== endDate
          ? `${formatDate(selectedDate)} até ${formatDate(endDate)}`
          : formatDate(selectedDate)}
      </p>

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
                        <div className="flex items-center gap-2">
                          <span className="text-sm text-muted-foreground">€ {(product.revenue || 0).toFixed(2)}</span>
                          <Badge variant="secondary">{product.quantity}x</Badge>
                        </div>
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

          {/* Aberturas de gaveta (auditoria) */}
          <Card className="mt-6">
            <CardHeader className="pb-3">
              <CardTitle className="text-lg flex items-center gap-2">
                <Wallet className="h-5 w-5" />
                Aberturas de gaveta
              </CardTitle>
            </CardHeader>
            <CardContent>
              {(reportData?.drawer_opens || []).length === 0 ? (
                <p className="text-sm text-muted-foreground text-center py-6">
                  Nenhuma abertura de gaveta registada neste dia
                </p>
              ) : (
                <div className="space-y-2">
                  {reportData.drawer_opens.map((d, idx) => (
                    <div key={idx} className="flex items-center gap-3 p-2 rounded-lg hover:bg-secondary/50">
                      <span className="font-mono text-sm text-muted-foreground w-12">{d.time}</span>
                      <span className="flex-1 font-medium truncate">{d.operator}</span>
                      <Badge variant={d.had_session ? 'secondary' : 'outline'}>
                        {d.had_session ? 'Caixa aberta' : 'Caixa fechada'}
                      </Badge>
                    </div>
                  ))}
                </div>
              )}
            </CardContent>
          </Card>

          {/* Faturas emitidas */}
          <Card className="mt-6">
            <CardHeader className="pb-3">
              <CardTitle className="text-lg flex items-center gap-2">
                <Receipt className="h-5 w-5" />
                Faturas emitidas
              </CardTitle>
            </CardHeader>
            <CardContent>
              {(reportData?.invoices || []).length === 0 ? (
                <p className="text-sm text-muted-foreground text-center py-6">
                  Nenhuma fatura neste período
                </p>
              ) : (
                <div className="space-y-1">
                  {reportData.invoices.map((inv, idx) => (
                    <div key={idx} className="flex items-center gap-3 p-2 rounded-lg hover:bg-secondary/50 text-sm">
                      <span className="font-mono text-muted-foreground w-12">{inv.time}</span>
                      <span className="flex-1 truncate">{inv.number || inv.label}</span>
                      <span className="text-muted-foreground truncate max-w-[120px]">{inv.method}</span>
                      <span className={`font-medium tabular-nums ${inv.amount < 0 ? 'text-red-600' : ''}`}>
                        € {inv.amount.toFixed(2)}
                      </span>
                    </div>
                  ))}
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
