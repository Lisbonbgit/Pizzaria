import { clsx } from "clsx";
import { twMerge } from "tailwind-merge"

export function cn(...inputs) {
  return twMerge(clsx(inputs));
}

// Texto do erro do servidor (o "detail" em PT-PT) para mostrar ao utilizador.
// Só se for texto: o 422 do FastAPI traz uma lista de objetos, que não se mostra.
export const detalheErro = (err, padrao) => {
  const d = err?.response?.data?.detail;
  return typeof d === 'string' && d ? d : padrao;
};
