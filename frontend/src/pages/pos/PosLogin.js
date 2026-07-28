import React, { useCallback, useState } from 'react';
import { Loader2 } from 'lucide-react';
import { toast } from 'sonner';
import { posAPI } from '@/lib/api';

const PIN_LENGTH = 4;

// Teclado numérico: 1-9, "limpar" (C), 0, OK.
const KEYS = ['1', '2', '3', '4', '5', '6', '7', '8', '9', 'limpar', '0', 'OK'];

// Ecrã de login do POS por PIN (teclado numérico, ecrã cheio, tablet).
// Ao 4º dígito submete automaticamente; o botão OK serve de alternativa manual.
const PosLogin = ({ onLogin }) => {
  const [pin, setPin] = useState('');
  const [loading, setLoading] = useState(false);

  const submit = useCallback(async (candidatePin) => {
    setLoading(true);
    try {
      const res = await posAPI.login(candidatePin);
      localStorage.setItem('pos_token', res.data.token);
      onLogin(res.data.user);
      setPin('');
    } catch (err) {
      console.error('Erro no login do POS:', err);
      toast.error('PIN inválido');
      setPin('');
    } finally {
      setLoading(false);
    }
  }, [onLogin]);

  const handleDigit = (digit) => {
    if (loading) return;
    setPin((prev) => {
      if (prev.length >= PIN_LENGTH) return prev;
      const next = prev + digit;
      if (next.length === PIN_LENGTH) {
        submit(next);
      }
      return next;
    });
  };

  const handleClear = () => {
    if (loading) return;
    setPin('');
  };

  const handleOk = () => {
    if (loading || pin.length !== PIN_LENGTH) return;
    submit(pin);
  };

  const handleKey = (key) => {
    if (key === 'limpar') return handleClear();
    if (key === 'OK') return handleOk();
    return handleDigit(key);
  };

  return (
    <div className="min-h-screen flex flex-col items-center justify-center bg-[#5a1a1a] p-6 text-white">
      <h1 className="text-2xl font-bold mb-2">POS</h1>
      <p className="text-white/70 mb-8">Introduz o teu PIN</p>

      <div className="flex gap-4 mb-10" aria-label={`PIN: ${pin.length} de ${PIN_LENGTH} dígitos`}>
        {Array.from({ length: PIN_LENGTH }).map((_, i) => (
          <div
            key={i}
            className={`h-5 w-5 rounded-full border-2 border-white transition-colors ${
              i < pin.length ? 'bg-white' : 'bg-transparent'
            }`}
          />
        ))}
      </div>

      <div className="grid grid-cols-3 gap-4 w-full max-w-xs">
        {KEYS.map((key) => {
          const isOk = key === 'OK';
          const isClear = key === 'limpar';
          const disabled = loading || (isOk && pin.length !== PIN_LENGTH);
          return (
            <button
              key={key}
              type="button"
              disabled={disabled}
              onClick={() => handleKey(key)}
              aria-label={isClear ? 'limpar' : key}
              className={`h-20 rounded-2xl text-2xl font-semibold flex items-center justify-center transition-colors active:scale-95 disabled:opacity-40 disabled:active:scale-100 touch-manipulation select-none ${
                isOk || isClear ? 'bg-white/10 hover:bg-white/20' : 'bg-white/15 hover:bg-white/25'
              }`}
            >
              {isClear ? 'C' : key}
            </button>
          );
        })}
      </div>

      <div className="mt-8 h-6 flex items-center gap-2 text-white/80">
        {loading && (
          <>
            <Loader2 className="h-5 w-5 animate-spin" />
            A verificar PIN...
          </>
        )}
      </div>
    </div>
  );
};

export default PosLogin;
