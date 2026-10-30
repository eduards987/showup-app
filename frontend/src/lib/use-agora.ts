import { useEffect, useState } from "react";

/** "Agora" para as telas que separam passado de futuro. Atualiza sozinho (a cada minuto, por padrão), em vez de ler
 *  Date.now() no meio do desenho da tela: assim um agendamento passa para "anteriores" sem precisar sair e voltar. */
export function useAgora(intervaloMs = 60_000): number {
  const [agora, setAgora] = useState(() => Date.now());
  useEffect(() => {
    const id = setInterval(() => setAgora(Date.now()), intervaloMs);
    return () => clearInterval(id);
  }, [intervaloMs]);
  return agora;
}
