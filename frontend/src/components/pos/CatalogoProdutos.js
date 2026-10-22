import React, { useEffect, useState } from 'react';
import { Button } from '@/components/ui/button';
import {
  Dialog, DialogContent, DialogHeader, DialogTitle,
} from '@/components/ui/dialog';
import { categoriaElegivel, candidatosMeia, nomeMeiaMeia, precoBaseMeia, precoNoTamanho } from '@/lib/meiaMeia';

const eur = (v) => `€ ${Number(v || 0).toFixed(2)}`;

// Catálogo do POS — separadores por categoria (estilo POS Vendus), grelha de
// produtos e a janela de tamanho (Média/Grande) e extras (Borda de Catupiry).
// Usado no Balcão e no "Adicionar produtos" da mesa, para os dois serem iguais.
//
//   groups  — [{cid, name, items: [produto]}], já filtrados e ordenados por quem usa
//   onAdd   — (produto, variação|null, extras[], segundaMetade|null) → o ecrã decide o que fazer
//   gridRef — opcional: ref do contentor que rola a grelha (a mesa precisa dele
//             para o scroll funcionar dentro de um Dialog dentro de outro)
export default function CatalogoProdutos({ groups, onAdd, gridRef }) {
  const [selectedCat, setSelectedCat] = useState(null);
  const [sizePick, setSizePick] = useState(null);
  const [pickVar, setPickVar] = useState(null);      // variação escolhida
  const [pickExtras, setPickExtras] = useState([]);  // extras escolhidos
  const [meiaOn, setMeiaOn] = useState(false);      // "Fazer meia-meia" ligado
  const [pickHalf, setPickHalf] = useState(null);   // 2.º sabor escolhido

  // Separador ativo por omissão: o primeiro grupo, assim que o catálogo chega.
  useEffect(() => {
    if (selectedCat == null && groups.length > 0) setSelectedCat(groups[0].cid);
  }, [groups, selectedCat]);

  const activeGroup = groups.find((g) => g.cid === selectedCat) || groups[0] || null;

  const grupoDe = (p) => groups.find((g) => g.items.some((x) => x.id === p.id));
  const podeMeia = (p) => {
    const g = grupoDe(p);
    return !!g && categoriaElegivel({ name: g.name })
      && g.items.some((x) => x.id !== p.id && x.available !== false);
  };
  const candidatos = sizePick && meiaOn
    ? candidatosMeia(sizePick, pickVar?.name || null, grupoDe(sizePick)?.items || [])
    : [];

  // Toque num produto: com tamanhos ou extras abre a janela; senão adiciona logo.
  const tocar = (p) => {
    const temVar = Array.isArray(p.variations) && p.variations.length > 0;
    const temExtras = Array.isArray(p.extras) && p.extras.length > 0;
    if (temVar || temExtras || podeMeia(p)) {
      setSizePick(p);
      setPickVar(null);
      setPickExtras([]);
      setMeiaOn(false);
      setPickHalf(null);
      return;
    }
    onAdd(p, null, [], null);
  };

  return (
    <>
      <div className="mb-4 flex shrink-0 gap-1.5 overflow-x-auto pb-1 [-ms-overflow-style:none] [scrollbar-width:none] [&::-webkit-scrollbar]:hidden">
        {groups.map((g) => (
          <button
            key={g.cid}
            type="button"
            onClick={() => setSelectedCat(g.cid)}
            className={[
              'shrink-0 whitespace-nowrap rounded-lg px-4 py-2.5 text-sm font-semibold transition-colors touch-manipulation',
              g.cid === selectedCat
                ? 'bg-[#5a1a1a] text-white shadow-sm'
                : 'bg-muted text-muted-foreground hover:bg-muted/70',
            ].join(' ')}
          >
            {g.name}
          </button>
        ))}
      </div>

      {activeGroup && (
        <div ref={gridRef} className={gridRef ? 'min-h-0 flex-1 overflow-y-auto' : undefined}>
          <div className="grid gap-2 [grid-template-columns:repeat(auto-fill,minmax(140px,1fr))]">
            {activeGroup.items.map((p) => (
              <button
                key={p.id}
                type="button"
                onClick={() => tocar(p)}
                className="flex min-h-[76px] flex-col items-start justify-between rounded-lg border border-border bg-white p-3 text-left transition-all touch-manipulation active:scale-[0.97] cursor-pointer hover:border-primary/40 hover:shadow-sm"
              >
                <span className="text-sm font-medium leading-snug line-clamp-2">{p.name}</span>
                <span className="mt-2 text-sm font-semibold text-[#5a1a1a] tabular-nums">{eur(p.base_price)}</span>
              </button>
            ))}
          </div>
        </div>
      )}

      {/* Opções do produto — tamanho e extras. Sem extras, tocar no tamanho
          adiciona logo (um só toque); com extras, escolhe-se tudo e confirma-se. */}
      <Dialog open={sizePick != null} onOpenChange={(v) => !v && setSizePick(null)}>
        <DialogContent className="max-h-[90vh] max-w-sm overflow-y-auto text-foreground">
          <DialogHeader>
            <DialogTitle className="pr-6 text-lg">
              {sizePick && pickHalf ? nomeMeiaMeia(sizePick.name, pickHalf.name) : (sizePick?.name || 'Produto')}
            </DialogTitle>
          </DialogHeader>

          {sizePick && podeMeia(sizePick) && (
            <Button type="button" variant={meiaOn ? 'default' : 'outline'}
              className={meiaOn ? 'w-full bg-[#5a1a1a] text-white hover:bg-[#4a1414]' : 'w-full'}
              onClick={() => { setMeiaOn((v) => !v); setPickHalf(null); }}>
              {meiaOn ? 'Meia-meia ✓ (toca para tirar)' : 'Fazer meia-meia'}
            </Button>
          )}

          {(sizePick?.variations || []).length > 0 && (
            <>
              <p className="text-sm text-muted-foreground">Escolhe o tamanho</p>
              <div className="grid gap-2">
                {(sizePick?.variations || []).map((v) => {
                  const confirma = (sizePick?.extras || []).length > 0 || meiaOn;
                  const escolhido = pickVar?.name === v.name;
                  return (
                    <button key={v.name} type="button"
                      onClick={() => {
                        if (pickHalf && precoNoTamanho(pickHalf, v.name) == null) setPickHalf(null);
                        if (confirma) { setPickVar(v); return; }
                        onAdd(sizePick, v, [], null); setSizePick(null);
                      }}
                      className={[
                        'flex items-center justify-between rounded-lg border px-4 py-3 text-left transition-all touch-manipulation active:scale-[0.98]',
                        escolhido ? 'border-[#5a1a1a] bg-[#5a1a1a]/[0.06] ring-1 ring-[#5a1a1a]'
                                  : 'border-border bg-white hover:border-primary/40 hover:shadow-sm',
                      ].join(' ')}>
                      <span className="text-sm font-medium">{v.name}</span>
                      <span className="text-sm font-semibold text-[#5a1a1a] tabular-nums">{eur(v.price)}</span>
                    </button>
                  );
                })}
              </div>
            </>
          )}

          {meiaOn && (
            <>
              <p className="mt-1 text-sm text-muted-foreground">
                {(sizePick?.variations || []).length > 0 && !pickVar ? 'Escolhe primeiro o tamanho'
                  : candidatos.length ? 'Outra metade'
                    : `Nenhum outro sabor disponível${pickVar ? ' neste tamanho' : ''}`}
              </p>
              <div className="grid max-h-56 gap-2 overflow-y-auto">
                {candidatos.map((p) => {
                  const on = pickHalf?.id === p.id;
                  return (
                    <button key={p.id} type="button" onClick={() => setPickHalf(on ? null : p)}
                      className={[
                        'flex items-center justify-between rounded-lg border px-4 py-3 text-left transition-all touch-manipulation active:scale-[0.98]',
                        on ? 'border-[#5a1a1a] bg-[#5a1a1a]/[0.06] ring-1 ring-[#5a1a1a]'
                           : 'border-border bg-white hover:border-primary/40',
                      ].join(' ')}>
                      <span className="text-sm font-medium">{on ? '✓ ' : ''}{p.name}</span>
                      <span className="text-sm font-semibold text-[#5a1a1a] tabular-nums">
                        {eur(precoNoTamanho(p, pickVar?.name || null))}
                      </span>
                    </button>
                  );
                })}
              </div>
            </>
          )}

          {(sizePick?.extras || []).length > 0 && (
            <>
              <p className="mt-1 text-sm text-muted-foreground">Extras</p>
              <div className="grid gap-2">
                {(sizePick?.extras || []).map((e) => {
                  const on = pickExtras.some((x) => x.name === e.name);
                  return (
                    <button key={e.name} type="button"
                      onClick={() => setPickExtras((prev) => on
                        ? prev.filter((x) => x.name !== e.name)
                        : [...prev, { name: e.name, price: Number(e.price) || 0 }])}
                      className={[
                        'flex items-center justify-between rounded-lg border px-4 py-3 text-left transition-all touch-manipulation active:scale-[0.98]',
                        on ? 'border-[#5a1a1a] bg-[#5a1a1a]/[0.06] ring-1 ring-[#5a1a1a]'
                           : 'border-border bg-white hover:border-primary/40',
                      ].join(' ')}>
                      <span className="text-sm font-medium">{on ? '✓ ' : ''}{e.name}</span>
                      <span className="text-sm font-semibold text-[#5a1a1a] tabular-nums">+ {eur(e.price)}</span>
                    </button>
                  );
                })}
              </div>
            </>
          )}

          {/* Sem tamanhos não há botão de tamanho para tocar: a pizza que só abriu
              a janela por causa da meia-meia também se adiciona inteira aqui. Com o
              tamanho já escolhido (ex.: meia-meia ligada e desligada) também.
              Sem sizePick (a janela a fechar) não há botão: tocar-lhe adicionava null. */}
          {sizePick && ((sizePick.extras || []).length > 0 || meiaOn || pickVar
            || !(sizePick.variations || []).length) && (() => {
            const falta = (sizePick?.variations || []).length > 0 && !pickVar
              ? 'Escolhe o tamanho' : (meiaOn && !pickHalf ? 'Escolhe a outra metade' : null);
            const base = pickHalf
              ? precoBaseMeia(sizePick, pickHalf, pickVar?.name || null)
              : ((pickVar ? Number(pickVar.price) : Number(sizePick?.base_price)) || 0);
            const total = base + pickExtras.reduce((t, x) => t + (Number(x.price) || 0), 0);
            return (
              <Button disabled={!!falta}
                onClick={() => { onAdd(sizePick, pickVar || null, pickExtras, meiaOn ? pickHalf : null); setSizePick(null); }}
                className="mt-2 h-12 w-full bg-[#5a1a1a] text-base font-semibold text-white hover:bg-[#4a1414]">
                {falta || `Adicionar — ${eur(total)}`}
              </Button>
            );
          })()}
        </DialogContent>
      </Dialog>
    </>
  );
}
