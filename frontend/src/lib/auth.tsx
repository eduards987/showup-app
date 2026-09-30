// AuthContext — login com o Google via navegador. O navegador abre a URL
// de autorização do Google, que redireciona pro NOSSO backend (HTTPS —
// obrigatório, Client ID tipo "Web" não aceita esquema customizado como
// redirect), o backend troca o código por um id_token, valida, monta a
// sessão, e manda o navegador de volta pro app via showup://auth-callback
// já com o nosso session_token pronto.
//
// Trocamos do SDK nativo (@react-native-google-signin) pra esse fluxo
// porque o SDK nativo depende de casar exatamente o certificado que
// assinou o APK com o que está cadastrado no Google Cloud — frágil (muda
// entre build local, EAS, Play Store) e bateu num bug ativo da biblioteca
// com a New Architecture do Expo SDK 57. Esse fluxo não depende de
// certificado nenhum, só do Client ID Web (que nunca muda).

import * as WebBrowser from "expo-web-browser";
import React, {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
} from "react";

import { api, ApiError, setAuthToken } from "@/src/lib/api";
import { unregisterPushToken } from "@/src/lib/push-notifications";
import { storage } from "@/src/utils/storage";

export type Role = "cliente" | "profissional";

export type User = {
  user_id: string;
  email: string;
  name: string;
  picture?: string | null;
  role?: Role | null;
  has_card?: boolean;
  categorias?: string[];
  stripe_account_id?: string | null;
  connect_ready?: boolean;
  timezone?: string;
  moeda?: string;
  plano?: string;
  created_at: string;
};

type AuthState =
  | { status: "loading"; user: null }
  | { status: "authenticated"; user: User }
  | { status: "unauthenticated"; user: null };

type AuthContextValue = AuthState & {
  signIn: () => Promise<void>;
  signOut: () => Promise<void>;
  setRole: (role: Role) => Promise<void>;
  refresh: () => Promise<void>;
};

const TOKEN_KEY = "hb_session_token";

const AuthContext = createContext<AuthContextValue | null>(null);

// webClientId aqui é o Client ID tipo "Web application" do Google Cloud
// Console — é o que o backend usa tanto pra montar a URL de autorização
// quanto pra validar o id_token depois (o "audience" tem que bater).
const googleWebClientId = process.env.EXPO_PUBLIC_GOOGLE_WEB_CLIENT_ID ?? "";
// Mesma URL cadastrada no backend (GOOGLE_OAUTH_REDIRECT_URI) e nas "URIs
// de redirecionamento autorizadas" do Client ID Web no Google Cloud
// Console — as três têm que ser idênticas, char por char.
const googleCallbackUrl = process.env.EXPO_PUBLIC_BACKEND_URL
  ? `${process.env.EXPO_PUBLIC_BACKEND_URL}/api/auth/google/callback`
  : "";
// Depois que o backend termina de processar o login, ele redireciona o
// navegador pra essa URL (nosso próprio scheme) — é o sinal que o
// WebBrowser.openAuthSessionAsync fica esperando pra saber que acabou e
// fechar a tela.
const APP_AUTH_CALLBACK = "showup://auth-callback";

// Guarda a Promise do "acorda o backend" (ver o useEffect abaixo) fora do
// componente, pra signIn() poder esperar por ela mesmo que tenha sido
// disparada em uma montagem anterior do AuthProvider.
let backendWakeUpPromise: Promise<unknown> | null = null;

function sleep(ms: number) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [state, setState] = useState<AuthState>({ status: "loading", user: null });

  useEffect(() => {
    if (!googleWebClientId || !googleCallbackUrl) {
      console.warn(
        "[auth] EXPO_PUBLIC_GOOGLE_WEB_CLIENT_ID ou EXPO_PUBLIC_BACKEND_URL " +
          "não configurado — login do Google não vai funcionar.",
      );
    }
    // "Acorda" o backend (plano gratuito do Render dorme depois de ~15min
    // sem uso) assim que o app abre, bem antes do usuário eventualmente
    // tocar em "Entrar com Google". Sem isso, se o backend estiver
    // dormindo justo na hora do login, é o PRÓPRIO GOOGLE que redireciona
    // o navegador do usuário pro nosso /auth/google/callback como parte
    // do fluxo OAuth — diferente de toda chamada de API do app (que usa
    // fetch(), nunca navega o navegador pra lugar nenhum), esse redirect
    // É uma navegação de verdade, então o usuário veria a tela genérica
    // de "acordando" do Render bem no meio do login. signIn() abaixo dá
    // uma folga curta pra essa chamada terminar antes de abrir o
    // navegador — não elimina o risco por completo (se o usuário for
    // rápido demais), mas cobre a maioria dos casos sem atrasar quem
    // chegou depois do backend já ter acordado.
    if (process.env.EXPO_PUBLIC_BACKEND_URL && !backendWakeUpPromise) {
      backendWakeUpPromise = fetch(`${process.env.EXPO_PUBLIC_BACKEND_URL}/api/`).catch(() => {});
    }
  }, []);

  const applyAuth = useCallback((token: string | null, user: User | null) => {
    setAuthToken(token);
    if (user && token) {
      setState({ status: "authenticated", user });
    } else {
      setState({ status: "unauthenticated", user: null });
    }
  }, []);

  // Bootstrap: só carrega o token já salvo, se tiver. O fluxo de login em
  // si acontece só dentro de signIn() — não tem nada assíncrono rodando
  // em segundo plano aqui.
  useEffect(() => {
    let cancelled = false;
    (async () => {
      const token = await storage.secureGet<string>(TOKEN_KEY, "");
      if (!token) {
        if (!cancelled) applyAuth(null, null);
        return;
      }
      setAuthToken(token);
      try {
        const me = await api<{ user: User }>("/api/auth/me");
        if (!cancelled) applyAuth(token, me.user);
      } catch (e) {
        if (e instanceof ApiError && e.status === 401) {
          await storage.secureRemove(TOKEN_KEY);
        }
        if (!cancelled) applyAuth(null, null);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [applyAuth]);

  const signIn = useCallback(async () => {
    if (!googleWebClientId || !googleCallbackUrl) return;
    // Dá até 3s pro "acorda o backend" do useEffect terminar antes de abrir
    // o navegador — não trava o login por muito tempo se o backend estiver
    // realmente dormindo (nesse caso, o usuário ainda pode ver a tela do
    // Render por alguns segundos, mas bem mais raro do que sem isso).
    if (backendWakeUpPromise) {
      await Promise.race([backendWakeUpPromise, sleep(3000)]);
    }
    const authUrl =
      "https://accounts.google.com/o/oauth2/v2/auth?" +
      new URLSearchParams({
        client_id: googleWebClientId,
        redirect_uri: googleCallbackUrl,
        response_type: "code",
        scope: "openid email profile",
        // "select_account" força o Google a sempre mostrar a tela de
        // escolher conta, em vez de logar direto na última usada — mais
        // previsível pra quem tem várias contas Google no aparelho.
        prompt: "select_account",
      }).toString();

    const result = await WebBrowser.openAuthSessionAsync(authUrl, APP_AUTH_CALLBACK);
    if (result.type !== "success") return; // usuário cancelou/fechou o navegador

    const returnedUrl = new URL(result.url);
    const error = returnedUrl.searchParams.get("error");
    if (error) {
      console.warn("[auth] Login com Google falhou:", error);
      return;
    }
    const sessionToken = returnedUrl.searchParams.get("token");
    if (!sessionToken) {
      console.warn("[auth] Callback do Google voltou sem token");
      return;
    }

    setAuthToken(sessionToken);
    const me = await api<{ user: User }>("/api/auth/me");
    await storage.secureSet(TOKEN_KEY, sessionToken);
    applyAuth(sessionToken, me.user);
  }, [applyAuth]);

  const signOut = useCallback(async () => {
    await unregisterPushToken(); // antes do logout: precisa do token de auth ainda válido
    try {
      await api("/api/auth/logout", { method: "POST" });
    } catch {}
    // Não há mais uma sessão do SDK nativo do Google pra encerrar — a
    // sessão inteira agora é só a nossa (token no SecureStore, já removido
    // abaixo). O navegador não guarda estado de sessão entre logins.
    await storage.secureRemove(TOKEN_KEY);
    applyAuth(null, null);
  }, [applyAuth]);

  const setRole = useCallback(async (role: Role) => {
    const res = await api<{ user: User }>("/api/auth/role", {
      method: "POST",
      body: JSON.stringify({ role }),
    });
    setState({ status: "authenticated", user: res.user });
  }, []);

  const refresh = useCallback(async () => {
    try {
      const me = await api<{ user: User }>("/api/auth/me");
      setState({ status: "authenticated", user: me.user });
    } catch (e) {
      if (e instanceof ApiError && e.status === 401) {
        await storage.secureRemove(TOKEN_KEY);
        applyAuth(null, null);
      }
    }
  }, [applyAuth]);

  const value = useMemo<AuthContextValue>(
    () => ({ ...state, signIn, signOut, setRole, refresh }),
    [state, signIn, signOut, setRole, refresh],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used within AuthProvider");
  return ctx;
}
