import React, { useCallback, useEffect, useState } from 'react';
import { Loader2, RotateCcw } from 'lucide-react';
import { toast } from 'sonner';
import { Button } from '@/components/ui/button';
import PosLogin from '@/pages/pos/PosLogin';
import PosAbrirCaixa from '@/pages/pos/PosAbrirCaixa';
import PosHome from '@/pages/pos/PosHome';
import { posAPI } from '@/lib/api';

// Shell da janela do POS (`/pos`, fora do ProtectedRoute admin).
// Máquina de estados por useState, guiada pelo que existe no localStorage:
//   1. Sem pos_device_token  -> dispositivo não autorizado (sem login).
//   2. Sem pos_token/user    -> ecrã de login por PIN.
//   3. Caso contrário        -> porta da caixa: resolve a sessão atual
//      (posAPI.cashCurrent) e mostra Abrir Caixa ou a Home (PosHome, Task 5).
const PosApp = () => {
  const [user, setUser] = useState(null);
  // undefined = ainda por resolver (1ª chamada em curso); null = caixa
  // fechada; objeto = sessão aberta.
  const [session, setSession] = useState(undefined);
  const [caixaLoading, setCaixaLoading] = useState(false);
  const [caixaError, setCaixaError] = useState(false);

  const deviceToken = localStorage.getItem('pos_device_token');
  const posToken = localStorage.getItem('pos_token');

  // Limpa a sessão POS (PIN) sem tocar na autorização do dispositivo.
  const logout = useCallback(() => {
    localStorage.removeItem('pos_token');
    setUser(null);
    setSession(undefined);
    setCaixaError(false);
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

  if (!posToken || !user) {
    return <PosLogin onLogin={(loggedInUser) => setUser(loggedInUser)} />;
  }

  // Ainda a resolver a 1ª chamada a cashCurrent, ou um refresh a meio.
  if (caixaLoading || session === undefined) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-[#5a1a1a]">
        <Loader2 className="h-10 w-10 animate-spin text-white" />
      </div>
    );
  }

  // cashCurrent falhou (rede, token expirado, etc.) — não deixar o ecrã em
  // branco: mostra erro + opção de tentar outra vez (ou sair, se o token
  // POS tiver expirado e o retry for ficar sempre a falhar).
  if (caixaError) {
    return (
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
  }

  if (!session) {
    return <PosAbrirCaixa operator={user} onAberta={refreshCaixa} />;
  }

  // Caixa aberta — Home real do POS (Task 5). `onFecharCaixa` e `onOpenTable`
  // são placeholders por agora: o fecho de caixa é a Task 7 e o checkout de
  // mesa é a Task 6; aqui só avisamos com um toast.
  return (
    <PosHome
      session={session}
      operator={user}
      onFecharCaixa={() => toast.info('Fecho de caixa na próxima tarefa')}
      onOpenTable={() => toast.info('Checkout na próxima tarefa')}
      refreshCaixa={refreshCaixa}
      onLogout={logout}
    />
  );
};

export default PosApp;
