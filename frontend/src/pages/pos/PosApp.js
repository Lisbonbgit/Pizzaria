import React, { useCallback, useEffect, useState } from 'react';
import { Loader2, RotateCcw } from 'lucide-react';
import { toast } from 'sonner';
import { Button } from '@/components/ui/button';
import PosLockScreen from '@/pages/pos/PosLockScreen';
import PosAbrirCaixa from '@/pages/pos/PosAbrirCaixa';
import PosHome from '@/pages/pos/PosHome';
import PosFecharCaixa from '@/pages/pos/PosFecharCaixa';
import PosBalcao from '@/pages/pos/PosBalcao';
import { posAPI } from '@/lib/api';

// Tempo de inatividade até a tela de descanso bloquear o ecrã (Task 6).
const IDLE_LIMIT_MS = 2 * 60 * 1000;

// Shell da janela do POS (`/pos`, fora do ProtectedRoute admin).
// Máquina de estados por useState, guiada pelo que existe no localStorage:
//   1. Sem pos_device_token  -> dispositivo não autorizado (sem login).
//   2. Sem pos_token/user    -> tela de bloqueio (escolher utilizador → PIN).
//   3. Caso contrário        -> porta da caixa: resolve a sessão atual
//      (posAPI.cashCurrent) e mostra Abrir Caixa ou a Home (PosHome, Task 5).
// Com sessão aberta, 2 min sem interação sobrepõe a mesma tela de bloqueio
// (Task 6) por cima do que estiver em ecrã, sem desmontar nada por baixo —
// não perde o estado da caixa/mesa nem faz logout do dispositivo.
const PosApp = () => {
  const [user, setUser] = useState(null);
  // undefined = ainda por resolver (1ª chamada em curso); null = caixa
  // fechada; objeto = sessão aberta.
  const [session, setSession] = useState(undefined);
  const [caixaLoading, setCaixaLoading] = useState(false);
  const [caixaError, setCaixaError] = useState(false);
  // Controla o fluxo "Fechar Caixa" (Task 7) — ecrã cheio, substitui a Home
  // enquanto ativo.
  const [showFecharCaixa, setShowFecharCaixa] = useState(false);
  // Controla o fluxo "Balcão" (Fase 2, Task 4) — ecrã cheio, substitui a
  // Home enquanto ativo, mesmo mecanismo do Fechar Caixa acima.
  const [showBalcao, setShowBalcao] = useState(false);
  // Tela de descanso (Task 6) — true depois de 2 min sem interação com uma
  // sessão aberta. É só um overlay: o resto do estado abaixo mantém-se.
  const [locked, setLocked] = useState(false);

  const deviceToken = localStorage.getItem('pos_device_token');
  const posToken = localStorage.getItem('pos_token');

  // Limpa a sessão POS (PIN) sem tocar na autorização do dispositivo.
  // Também repõe `showFecharCaixa`: sem isto, um novo login (depois de
  // terminar um fecho de caixa) podia reabrir o ecrã do Z assim que a
  // próxima caixa fosse aberta (o valor antigo `true` ficava pendurado).
  const logout = useCallback(() => {
    localStorage.removeItem('pos_token');
    setUser(null);
    setSession(undefined);
    setCaixaError(false);
    setShowFecharCaixa(false);
    setShowBalcao(false);
    setLocked(false);
  }, []);

  // Re-resolve a sessão de caixa atual. Chamado no arranque (após login) e
  // depois de abrir/fechar a caixa (esta e a Task 5).
  const refreshCaixa = useCallback(async () => {
    setCaixaLoading(true);
    setCaixaError(false);
    try {
      const res = await posAPI.cashCurrent();
      setSession(res.data || null);
    } catch (err) {
      console.error('Erro ao verificar o estado da caixa:', err);
      setCaixaError(true);
      toast.error('Não foi possível verificar o estado da caixa');
    } finally {
      setCaixaLoading(false);
    }
  }, []);

  useEffect(() => {
    if (posToken && user) {
      refreshCaixa();
    }
  }, [posToken, user, refreshCaixa]);

  // Timer de inatividade (Task 6): só corre com sessão aberta (sem isso a
  // tela de bloqueio já é o próprio ecrã de login, não há nada para
  // "bloquear"). Qualquer clique/toque/tecla reinicia os 2 min.
  useEffect(() => {
    if (!posToken || !user) return undefined;
    let timeoutId;
    const resetTimer = () => {
      clearTimeout(timeoutId);
      timeoutId = setTimeout(() => setLocked(true), IDLE_LIMIT_MS);
    };
    const events = ['mousedown', 'keydown', 'touchstart'];
    events.forEach((evt) => window.addEventListener(evt, resetTimer));
    resetTimer();
    return () => {
      clearTimeout(timeoutId);
      events.forEach((evt) => window.removeEventListener(evt, resetTimer));
    };
  }, [posToken, user]);

  if (!deviceToken) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-[#5a1a1a] p-6">
        <div className="max-w-md text-center text-white space-y-4">
          <h1 className="text-2xl font-bold">Dispositivo não autorizado</h1>
          <p className="text-white/85 text-lg leading-relaxed">
            Este dispositivo não está autorizado. Abre o POS pelo botão{' '}
            <span className="font-semibold">Iniciar POS</span> no painel (Admin → POS).
          </p>
        </div>
      </div>
    );
  }

  // Sem sessão POS — tela de bloqueio faz de ecrã de login (Task 6):
  // escolher utilizador → PIN, em vez do antigo teclado nu.
  if (!posToken || !user) {
    return <PosLockScreen onUnlock={(loggedInUser) => setUser(loggedInUser)} />;
  }

  // A partir daqui há sessão POS. O conteúdo abaixo (`content`) é exatamente
  // a mesma máquina de estados de antes (loader/erro/abrir caixa/fechar
  // caixa/balcão/home); com `locked`, sobrepõe-se a tela de bloqueio por
  // cima sem desmontar nada disto — mantém a caixa/mesa como estavam.
  let content;

  // Ainda a resolver a 1ª chamada a cashCurrent, ou um refresh a meio.
  if (caixaLoading || session === undefined) {
    content = (
      <div className="min-h-screen flex items-center justify-center bg-[#5a1a1a]">
        <Loader2 className="h-10 w-10 animate-spin text-white" />
      </div>
    );
  } else if (caixaError) {
    // cashCurrent falhou (rede, token expirado, etc.) — não deixar o ecrã em
    // branco: mostra erro + opção de tentar outra vez (ou sair, se o token
    // POS tiver expirado e o retry for ficar sempre a falhar).
    content = (
      <div className="min-h-screen flex flex-col items-center justify-center gap-4 bg-[#5a1a1a] p-6 text-white text-center">
        <p className="text-lg max-w-sm">Não foi possível verificar o estado da caixa.</p>
        <Button onClick={refreshCaixa} className="bg-white text-[#5a1a1a] hover:bg-white/90">
          <RotateCcw className="h-4 w-4" />
          Tentar novamente
        </Button>
        <Button
          variant="outline"
          size="sm"
          onClick={logout}
          className="border-white/40 bg-transparent text-white hover:bg-white/10 hover:text-white"
        >
          Sair
        </Button>
      </div>
    );
  } else if (!session) {
    content = <PosAbrirCaixa operator={user} onAberta={refreshCaixa} />;
  } else if (showFecharCaixa) {
    // Fluxo "Fechar Caixa" (Task 7) — substitui a Home enquanto ativo.
    // `onClosed` é chamado a partir do ecrã do Z ("Terminar"): reresolve o
    // estado da caixa (fica fechada) e faz logout — a próxima pessoa a usar o
    // POS faz login por PIN de novo (o `logout` acima já repõe
    // `showFecharCaixa`, por isso não é preciso fazê-lo aqui).
    content = (
      <PosFecharCaixa
        operator={user}
        onCancel={() => setShowFecharCaixa(false)}
        onClosed={async () => {
          await refreshCaixa();
          logout();
        }}
      />
    );
  } else if (showBalcao) {
    // Fluxo "Balcão" (Fase 2, Task 4) — substitui a Home enquanto ativo, tal
    // como o Fechar Caixa acima. `onClose` volta à Home (o próprio PosBalcao
    // desliga o botão de voltar enquanto um pedido está impresso mas por
    // faturar).
    content = <PosBalcao onClose={() => setShowBalcao(false)} />;
  } else {
    // Caixa aberta — Home real do POS (Task 5), com o checkout de mesa
    // (Task 6, `TableCheckout` partilhado com o admin via `posCheckout`) já
    // ligado.
    content = (
      <PosHome
        session={session}
        operator={user}
        onFecharCaixa={() => setShowFecharCaixa(true)}
        onBalcao={() => setShowBalcao(true)}
        refreshCaixa={refreshCaixa}
        onLogout={logout}
      />
    );
  }

  return (
    <>
      {content}
      {locked && (
        <PosLockScreen
          onUnlock={(loggedInUser) => {
            setUser(loggedInUser);
            setLocked(false);
          }}
        />
      )}
    </>
  );
};

export default PosApp;
