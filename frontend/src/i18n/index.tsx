// Parte "React" dos idiomas: detecta o idioma do aparelho, guarda a escolha da pessoa e avisa as telas quando ela muda.
// Tudo o que é lógica pura fica em core.ts (testável no Node).
import { createContext, ReactNode, useCallback, useContext, useEffect, useSyncExternalStore } from "react";

import {
  assinarIdioma,
  detectarIdioma,
  getIdioma,
  Idioma,
  IDIOMAS,
  normalizarIdioma,
  setIdiomaAtual,
  t,
} from "@/src/i18n/core";
import { storage } from "@/src/utils/storage";

export { IDIOMAS, t };
export type { Idioma };

const CHAVE_IDIOMA = "idioma-escolhido";

/** Idiomas configurados no aparelho, do mais para o menos preferido (ex.: ["pt-BR", "en-US"]). */
function idiomasDoAparelho(): string[] {
  try {
    const principal = Intl.DateTimeFormat().resolvedOptions().locale;
    return principal ? [principal] : [];
  } catch {
    return [];
  }
}

// O idioma do aparelho vale desde o primeiro quadro (sem piscar em português); a escolha guardada, se existir, entra logo depois.
setIdiomaAtual(detectarIdioma(idiomasDoAparelho()));

interface IdiomaCtx {
  idioma: Idioma;
  escolher: (novo: Idioma) => Promise<void>;
}
const Ctx = createContext<IdiomaCtx | null>(null);

export function IdiomaProvider({ children }: { children: ReactNode }) {
  const idioma = useSyncExternalStore(assinarIdioma, getIdioma, getIdioma);

  useEffect(() => {
    let vivo = true;
    storage.getItem(CHAVE_IDIOMA, "").then((salvo) => {
      const escolhido = normalizarIdioma(salvo);
      if (vivo && escolhido) setIdiomaAtual(escolhido);
    });
    return () => {
      vivo = false;
    };
  }, []);

  const escolher = useCallback(async (novo: Idioma) => {
    setIdiomaAtual(novo);
    await storage.setItem(CHAVE_IDIOMA, novo);
  }, []);

  return <Ctx.Provider value={{ idioma, escolher }}>{children}</Ctx.Provider>;
}

/** Faz a tela se redesenhar quando a pessoa troca de idioma. Devolve o idioma atual e a função para trocar. */
export function useIdioma(): IdiomaCtx {
  const ctx = useContext(Ctx);
  const idioma = useSyncExternalStore(assinarIdioma, getIdioma, getIdioma);
  if (!ctx) return { idioma, escolher: async (novo) => setIdiomaAtual(novo) };
  return { ...ctx, idioma };
}
