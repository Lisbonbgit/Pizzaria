import React, { useState, useEffect, useCallback } from 'react';
import { Loader2, Receipt, CheckCircle2, ShoppingBag } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from '@/components/ui/select';
import { toast } from 'sonner';
import AdminLayout from '@/components/AdminLayout';
import { tablesAPI, checkoutAPI } from '@/lib/api';

const eur = (v) => `€ ${Number(v || 0).toFixed(2)}`;

const AdminCheckout = () => {
  const [tables, setTables] = useState([]);
  const [methods, setMethods] = useState([]);
  const [methodsError, setMethodsError] = useState(false);
  const [tableNumber, setTableNumber] = useState('');
  const [bill, setBill] = useState(null);
  const [loadingBill, setLoadingBill] = useState(false);
  const [paymentId, setPaymentId] = useState('');
  const [nif, setNif] = useState('');
  const [closing, setClosing] = useState(false);
  const [receipt, setReceipt] = useState(null);

  useEffect(() => {
    tablesAPI.list().then((r) => setTables(r.data)).catch(() => toast.error('Erro ao carregar mesas'));
    checkoutAPI.paymentMethods()
      .then((r) => setMethods(r.data))
      .catch(() => setMethodsError(true));
  }, []);

  const loadBill = useCallback(async (num) => {
    if (!num) { setBill(null); return; }
    setLoadingBill(true);
    setReceipt(null);
    try {
      const r = await checkoutAPI.getBill(num);
      setBill(r.data);
    } catch {
      toast.error('Erro ao carregar a conta da mesa');
    } finally {
      setLoadingBill(false);
    }
  }, []);

  const onSelectTable = (num) => {
    setTableNumber(num);
    setPaymentId('');
    setNif('');
    loadBill(num);
  };

  const handleClose = async () => {
    if (!paymentId) { toast.error('Escolhe o método de pagamento'); return; }
    setClosing(true);
    try {
      const r = await checkoutAPI.closeTable(tableNumber, {
        payment_method_id: Number(paymentId),
        nif: nif.trim() || null,
      });
      setReceipt(r.data.vendus);
      toast.success(`Mesa ${tableNumber} fechada — ${r.data.vendus.number}`);
      loadBill(tableNumber);
    } catch (e) {
      toast.error(e.response?.data?.detail || 'Erro ao fechar a mesa');
    } finally {
      setClosing(false);
    }
  };

  const hasBill = bill && bill.orders > 0;

  return (
    <AdminLayout>
      <div className="max-w-3xl mx-auto space-y-6">
        <div className="flex items-center gap-3">
          <Receipt className="h-7 w-7 text-[#5a1a1a]" />
          <div>
            <h1 className="text-2xl font-bold">Fechar Mesa</h1>
            <p className="text-sm text-gray-500">Fatura a conta no Vendus e liberta a mesa</p>
          </div>
        </div>

        {/* Escolher mesa */}
        <Card>
          <CardHeader><CardTitle className="text-base">Mesa</CardTitle></CardHeader>
          <CardContent>
            <Select value={tableNumber} onValueChange={onSelectTable}>
              <SelectTrigger className="w-full sm:w-64">
                <SelectValue placeholder="Escolhe a mesa..." />
              </SelectTrigger>
              <SelectContent>
                {tables.map((t) => (
                  <SelectItem key={t.id} value={String(t.number)}>
                    Mesa {t.number}{t.name ? ` — ${t.name}` : ''}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </CardContent>
        </Card>

        {/* Conta */}
        {tableNumber && (
          <Card>
            <CardHeader><CardTitle className="text-base">Conta da Mesa {tableNumber}</CardTitle></CardHeader>
            <CardContent>
              {loadingBill ? (
                <div className="flex items-center gap-2 text-gray-500 py-4">
                  <Loader2 className="h-4 w-4 animate-spin" /> A carregar...
                </div>
              ) : !hasBill ? (
                <div className="flex items-center gap-2 text-gray-500 py-6 justify-center">
                  <ShoppingBag className="h-5 w-5" /> Sem conta em aberto nesta mesa.
                </div>
              ) : (
                <div className="space-y-2">
                  {bill.lines.map((l, i) => (
                    <div key={i} className="flex justify-between text-sm border-b last:border-0 py-1.5">
                      <span>{l.quantity}× {l.product_name}</span>
                      <span className="tabular-nums">{eur(l.total_price)}</span>
                    </div>
                  ))}
                  <div className="flex justify-between font-bold text-lg pt-2">
                    <span>Total</span>
                    <span className="tabular-nums">{eur(bill.total)}</span>
                  </div>
                </div>
              )}
            </CardContent>
          </Card>
        )}

        {/* Pagamento + fecho */}
        {hasBill && !receipt && (
          <Card>
            <CardHeader><CardTitle className="text-base">Pagamento</CardTitle></CardHeader>
            <CardContent className="space-y-4">
              <div>
                <Label>Método de pagamento</Label>
                {methodsError ? (
                  <p className="text-sm text-red-600 mt-1">
                    Não foi possível carregar os métodos do Vendus. Verifica a ligação/API key.
                  </p>
                ) : (
                  <Select value={paymentId} onValueChange={setPaymentId}>
                    <SelectTrigger className="w-full sm:w-64 mt-1">
                      <SelectValue placeholder="Escolhe..." />
                    </SelectTrigger>
                    <SelectContent>
                      {methods.map((m) => (
                        <SelectItem key={m.id} value={String(m.id)}>{m.title}</SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                )}
              </div>
              <div>
                <Label>NIF (opcional)</Label>
                <Input
                  className="w-full sm:w-64 mt-1"
                  placeholder="Contribuinte, se pedir fatura com NIF"
                  value={nif}
                  onChange={(e) => setNif(e.target.value)}
                />
              </div>
              <Button
                onClick={handleClose}
                disabled={closing || !paymentId}
                className="w-full sm:w-auto bg-[#5a1a1a] hover:bg-[#4a1414]"
              >
                {closing ? <Loader2 className="h-4 w-4 animate-spin mr-2" /> : <Receipt className="h-4 w-4 mr-2" />}
                Fechar mesa e faturar no Vendus ({eur(bill.total)})
              </Button>
            </CardContent>
          </Card>
        )}

        {/* Recibo emitido */}
        {receipt && (
          <Card className="border-green-500">
            <CardContent className="py-6">
              <div className="flex items-start gap-3">
                <CheckCircle2 className="h-8 w-8 text-green-600 shrink-0" />
                <div>
                  <p className="font-bold text-green-700">Fatura emitida no Vendus ✅</p>
                  <p className="text-sm text-gray-700 mt-1">Documento: <b>{receipt.number}</b></p>
                  <p className="text-sm text-gray-700">ATCUD: <b>{receipt.atcud}</b></p>
                  <p className="text-xs text-gray-400 mt-2">
                    (Em modo de testes o documento não tem valor fiscal — em produção é um recibo certificado.)
                  </p>
                </div>
              </div>
            </CardContent>
          </Card>
        )}
      </div>
    </AdminLayout>
  );
};

export default AdminCheckout;
