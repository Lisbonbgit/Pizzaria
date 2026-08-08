import React, { useCallback, useEffect, useRef, useState } from 'react';
import { format } from 'date-fns';
import { Loader2, RotateCcw, UserCircle } from 'lucide-react';
import { Avatar, AvatarFallback } from '@/components/ui/avatar';
import { Button } from '@/components/ui/button';
import PosLogin from '@/pages/pos/PosLogin';
import { posAPI } from '@/lib/api';

// Tela de bloqueio/descanso do POS (Task 6) — usada tanto no arranque
// (primeiro login) como no re-desbloqueio após 10 min de inatividade
// (o `PosApp` sobrepõe este ecrã em vez de desmontar a caixa/mesa por
// baixo). Fluxo: relógio + avatares dos utilizadores ativos
// (`GET /pos/users-public`, auth-duplo por device token, como no Vendus) →
// clicar num utilizador mostra o PIN dele (`PosLogin` adaptado) → em
// sucesso chama `onUnlock(user)`.
const PosLockScreen = ({ onUnlock }) => {
  const [users, setUsers] = useState([]);
  const [loadingUsers, setLoadingUsers] = useState(true);
  const [usersError, setUsersError] = useState(false);
  const [pickedUser, setPickedUser] = useState(null);
  const [now, setNow] = useState(() => new Date());
  const isMountedRef = useRef(true);

  const loadUsers = useCallback(async () => {
    setLoadingUsers(true);
    setUsersError(false);
    try {
      const res = await posAPI.usersPublic();
      if (!isMountedRef.current) return;
      setUsers(res.data || []);
    } catch (err) {
      console.error('Erro ao carregar utilizadores POS:', err);
      if (!isMountedRef.current) return;
      setUsersError(true);
    } finally {
      if (isMountedRef.current) {
        setLoadingUsers(false);
      }
    }
  }, []);

  useEffect(() => {
    isMountedRef.current = true;
    loadUsers();
    return () => {
      isMountedRef.current = false;
    };
  }, [loadUsers]);

  // Relógio grande, a atualizar segundo a segundo.
  useEffect(() => {
    const intervalId = setInterval(() => setNow(new Date()), 1000);
    return () => clearInterval(intervalId);
  }, []);

  const handleSuccess = useCallback((loggedInUser) => {
    setPickedUser(null);
    onUnlock(loggedInUser);
  }, [onUnlock]);

  if (pickedUser) {
    return (
      <div className="fixed inset-0 z-[100] pointer-events-auto">
        <PosLogin user={pickedUser} onBack={() => setPickedUser(null)} onSuccess={handleSuccess} />
      </div>
    );
  }

  return (
    <div className="fixed inset-0 z-[100] pointer-events-auto overflow-y-auto bg-[#5a1a1a] flex flex-col items-center justify-center p-6 text-white">
      <div className="text-6xl md:text-7xl font-bold tabular-nums tracking-wide mb-2">
        {format(now, 'HH:mm:ss')}
      </div>
      <p className="text-white/70 mb-10">Quem és?</p>

      {loadingUsers && <Loader2 className="h-10 w-10 animate-spin text-white/80" />}

      {!loadingUsers && usersError && (
        <div className="flex flex-col items-center gap-4 text-center">
          <p className="text-white/85">Não foi possível carregar os utilizadores POS.</p>
          <Button onClick={loadUsers} className="bg-white text-[#5a1a1a] hover:bg-white/90">
            <RotateCcw className="h-4 w-4" />
            Tentar novamente
          </Button>
        </div>
      )}

      {!loadingUsers && !usersError && users.length === 0 && (
        <p className="text-white/85 text-center max-w-sm">
          Não há utilizadores POS ativos. Cria um em Admin → POS.
        </p>
      )}

      {!loadingUsers && !usersError && users.length > 0 && (
        <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 gap-6 max-w-2xl w-full">
          {users.map((u) => (
            <button
              key={u.id}
              type="button"
              onClick={() => setPickedUser(u)}
              className="flex flex-col items-center gap-2 p-4 rounded-2xl hover:bg-white/10 active:scale-95 transition-colors touch-manipulation select-none"
            >
              <Avatar className="h-20 w-20 border-2 border-white/30">
                <AvatarFallback className="bg-white/15 text-white">
                  <UserCircle className="h-12 w-12" />
                </AvatarFallback>
              </Avatar>
              <span className="font-medium text-center break-words max-w-full">{u.name}</span>
            </button>
          ))}
        </div>
      )}
    </div>
  );
};

export default PosLockScreen;
