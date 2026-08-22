import React, { useState, useEffect, useCallback, useMemo } from 'react';
import { Loader2, Link2, CheckCircle, AlertTriangle, Save } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { toast } from 'sonner';
import AdminLayout from '@/components/AdminLayout';
import { vendusLinkAPI } from '@/lib/api';

// Valor especial do seletor para "sem ligação" (o Radix Select não aceita value="").
const NONE_VALUE = '__none__';

const AdminVendusLink = () => {
  const [suggestions, setSuggestions] = useState([]);
  const [officialCount, setOfficialCount] = useState(0);
  // product_id -> vendus_id (number) | null
  const [links, setLinks] = useState({});
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [saving, setSaving] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await vendusLinkAPI.suggestions();
      const list = res.data?.suggestions || [];
      setSuggestions(list);
      setOfficialCount(res.data?.official_count || 0);
      const initialLinks = {};
      list.forEach((s) => {
        // Pré-selecciona a ligação já gravada; sem essa, a sugestão por nome.
        initialLinks[s.product_id] = s.current_vendus_id ?? s.match?.id ?? null;
      });
      setLinks(initialLinks);
    } catch (err) {
      console.error('Error loading vendus link suggestions:', err);
      setError('Erro ao carregar as sugestões de ligação ao Vendus');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  // Artigos oficiais distintos, obtidos de todos os "match" das sugestões.
  const officialArticles = useMemo(() => {
    const byId = new Map();
    suggestions.forEach((s) => {
      if (s.match && s.match.id != null && !byId.has(s.match.id)) {
        byId.set(s.match.id, s.match);
      }
    });
    return Array.from(byId.values()).sort((a, b) =>
      String(a.title || '').localeCompare(String(b.title || ''), 'pt-PT')
    );
  }, [suggestions]);

  const articleById = useMemo(() => {
    const map = new Map();
    officialArticles.forEach((a) => map.set(a.id, a));
    return map;
  }, [officialArticles]);

  const handleChange = (productId, value) => {
    setLinks((prev) => ({
      ...prev,
      [productId]: value === NONE_VALUE ? null : Number(value),
    }));
  };

  const handleSave = async () => {
    setSaving(true);
    try {
      const payload = suggestions.map((s) => ({
        product_id: s.product_id,
        vendus_id: links[s.product_id] ?? null,
      }));
      const res = await vendusLinkAPI.save(payload);
      toast.success(`Ligações guardadas (${res.data?.updated ?? payload.length})`);
    } catch (err) {
      console.error('Error saving vendus links:', err);
      toast.error(err.response?.data?.detail || 'Erro ao guardar as ligações');
    } finally {
      setSaving(false);
    }
  };

  if (loading) {
    return (
      <AdminLayout title="Ligar ao Vendus">
        <div className="flex items-center justify-center h-64">
          <Loader2 className="h-8 w-8 animate-spin text-primary" />
        </div>
      </AdminLayout>
    );
  }

  if (error) {
    return (
      <AdminLayout title="Ligar ao Vendus">
        <Card>
          <CardContent className="p-6 text-center">
            <p className="text-sm text-muted-foreground mb-4">{error}</p>
            <Button variant="outline" onClick={load}>Tentar novamente</Button>
          </CardContent>
        </Card>
      </AdminLayout>
    );
  }

  return (
    <AdminLayout title="Ligar ao Vendus">
      <div className="flex flex-col sm:flex-row items-start sm:items-center justify-between gap-4 mb-6">
        <p className="text-sm text-muted-foreground">
          {suggestions.length} produto{suggestions.length !== 1 ? 's' : ''} da app · {officialCount} artigo{officialCount !== 1 ? 's' : ''} oficial{officialCount !== 1 ? 'ais' : ''} no Vendus
        </p>
        <Button onClick={handleSave} disabled={saving}>
          {saving ? (
            <>
              <Loader2 className="h-4 w-4 mr-2 animate-spin" />
              A guardar...
            </>
          ) : (
            <>
              <Save className="h-4 w-4 mr-2" />
              Guardar ligações
            </>
          )}
        </Button>
      </div>

      <Card>
        <CardHeader className="pb-3">
          <CardTitle className="text-base flex items-center gap-2">
            <Link2 className="h-4 w-4" /> Ligação produto (app) ↔ artigo (Vendus)
          </CardTitle>
        </CardHeader>
        <CardContent>
          {suggestions.length === 0 ? (
            <p className="text-sm text-muted-foreground text-center py-6">
              Sem produtos para ligar
            </p>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="text-left text-muted-foreground border-b">
                    <th className="py-2 pr-3 font-medium">Produto (app)</th>
                    <th className="py-2 pr-3 font-medium">Preço app</th>
                    <th className="py-2 pr-3 font-medium">Artigo Vendus</th>
                    <th className="py-2 pr-3 font-medium">Preço Vendus</th>
                    <th className="py-2 pr-3 font-medium">Estado</th>
                  </tr>
                </thead>
                <tbody>
                  {suggestions.map((s) => {
                    const selectedId = links[s.product_id] ?? null;
                    const selectedArticle = selectedId != null ? articleById.get(selectedId) : null;
                    const isNone = selectedId == null;
                    const priceMismatch = !isNone && selectedArticle
                      && Number(s.app_price) !== Number(selectedArticle.price);
                    const highlight = isNone || priceMismatch;
                    return (
                      <tr
                        key={s.product_id}
                        className={`border-b last:border-0 ${highlight ? 'bg-red-50' : ''}`}
                      >
                        <td className="py-2 pr-3 font-medium">{s.product_name}</td>
                        <td className="py-2 pr-3 tabular-nums">€ {Number(s.app_price || 0).toFixed(2)}</td>
                        <td className="py-2 pr-3">
                          <Select
                            value={selectedId != null ? String(selectedId) : NONE_VALUE}
                            onValueChange={(v) => handleChange(s.product_id, v)}
                          >
                            <SelectTrigger className="w-64">
                              <SelectValue placeholder="— sem ligação —" />
                            </SelectTrigger>
                            <SelectContent>
                              <SelectItem value={NONE_VALUE}>— sem ligação —</SelectItem>
                              {officialArticles.map((a) => (
                                <SelectItem key={a.id} value={String(a.id)}>
                                  {a.title}{a.reference ? ` (${a.reference})` : ''}
                                </SelectItem>
                              ))}
                            </SelectContent>
                          </Select>
                        </td>
                        <td className="py-2 pr-3 tabular-nums">
                          {selectedArticle ? `€ ${Number(selectedArticle.price || 0).toFixed(2)}` : '—'}
                        </td>
                        <td className="py-2 pr-3">
                          {isNone ? (
                            <Badge variant="destructive" className="flex items-center gap-1 w-fit whitespace-nowrap">
                              <AlertTriangle className="h-3 w-3" /> Sem ligação
                            </Badge>
                          ) : priceMismatch ? (
                            <Badge variant="destructive" className="flex items-center gap-1 w-fit whitespace-nowrap">
                              <AlertTriangle className="h-3 w-3" /> Preço diferente
                            </Badge>
                          ) : (
                            <Badge className="bg-green-600 text-white border-0 flex items-center gap-1 w-fit whitespace-nowrap">
                              <CheckCircle className="h-3 w-3" /> OK
                            </Badge>
                          )}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}
        </CardContent>
      </Card>
    </AdminLayout>
  );
};

export default AdminVendusLink;
