import React, { useCallback, useState } from 'react';
import { Button } from '@/components/ui/button';
import PosLogin from '@/pages/pos/PosLogin';

// Shell da janela do POS (`/pos`, fora do ProtectedRoute admin).
// Máquina de estados por useState, guiada pelo que existe no localStorage:
//   1. Sem pos_device_token  -> dispositivo não autorizado (sem login).
//   2. Sem pos_token/user    -> ecrã de login por PIN.
//   3. Caso contrário        -> área da caixa (placeholder; Task 4 substitui).
const PosApp = () => {
  const [user, setUser] = useState(null);

  const deviceToken = localStorage.getItem('pos_device_token');
  const posToken = localStorage.getItem('pos_token');

  // Limpa a sessão POS (PIN) sem tocar na autorização do dispositivo.
  // Usado pelo placeholder da caixa; a Task 4 vai reutilizá-lo.
  const logout = useCallback(() => {
    localStorage.removeItem('pos_token');
    setUser(null);
  }, []);

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

  return (
    <div className="min-h-screen flex flex-col items-center justify-center gap-4 bg-[#5a1a1a] p-6 text-white">
      <div className="text-xl font-semibold">Caixa (a seguir)</div>
      <p className="text-white/80">Operador: {user.name}</p>
      <Button
        variant="outline"
        size="sm"
        onClick={logout}
        className="mt-4 border-white/40 bg-transparent text-white hover:bg-white/10 hover:text-white"
      >
        Sair
      </Button>
    </div>
  );
};

export default PosApp;
