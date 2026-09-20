// AuthContext — login direto com o Google (SDK nativo), sem nenhum servidor
// de terceiros no meio. O SDK devolve um ID token que o backend valida
// direto com o Google; a partir daí a sessão é 100% nossa (session_token
// próprio, salvo no SecureStore).

import { GoogleSignin } from "@react-native-google-signin/google-signin";
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

let googleConfigured = false;
function ensureGoogleConfigured() {
  if (googleConfigured) return;
  const webClientId = process.env.EXPO_PUBLIC_GOOGLE_WEB_CLIENT_ID ?? "";
  if (!webClientId) {
    console.warn(
      "[auth] EXPO_PUBLIC_GOOGLE_WEB_CLIENT_ID não configurado — login do Google não vai funcionar.",
    );
    return;
  }
  // webClientId aqui é o Client ID tipo "Web application" do Google Cloud
  // Console (não o Android/iOS) — é o que o backend usa como "audience"
  // pra validar o ID token, então tem que ser exatamente o mesmo dos dois
  // lados.
  GoogleSignin.configure({ webClientId, offlineAccess: false });
  googleConfigured = true;
}

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [state, setState] = useState<AuthState>({ status: "loading", user: null });

  useEffect(() => {
    ensureGoogleConfigured();
  }, []);

  const applyAuth = useCallback((token: string | null, user: User | null) => {
    setAuthToken(token);
    if (user && token) {
      setState({ status: "authenticated", user });
    } else {
      setState({ status: "unauthenticated", user: null });
    }
  }, []);

  // Bootstrap: só carrega o token já salvo, se tiver. Não há mais deep
  // link nenhum pra tratar no fluxo de login (o SDK nativo do Google
  // devolve o resultado direto, sem sair do app).
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
    ensureGoogleConfigured();
    await GoogleSignin.hasPlayServices();
    const response = await GoogleSignin.signIn();
    if (response.type !== "success") return; // usuário cancelou o fluxo
    const idToken = response.data.idToken;
    if (!idToken) {
      console.warn("[auth] Google não retornou idToken");
      return;
    }
    const res = await api<{ session_token: string; user: User }>("/api/auth/session", {
      method: "POST",
      body: JSON.stringify({ id_token: idToken }),
    });
    await storage.secureSet(TOKEN_KEY, res.session_token);
    applyAuth(res.session_token, res.user);
  }, [applyAuth]);

  const signOut = useCallback(async () => {
    await unregisterPushToken(); // antes do logout: precisa do token de auth ainda válido
    try {
      await api("/api/auth/logout", { method: "POST" });
    } catch {}
    try {
      await GoogleSignin.signOut();
    } catch {}
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
