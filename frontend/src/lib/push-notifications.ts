// Push notification registration — Expo push token lifecycle.
//
// Only professionals need this today (the backend only ever pushes to
// profissional_id — see server.py::_enviar_pushes_confirmacao). The hook
// that calls registerForPushNotifications() gates on role, this module
// stays role-agnostic so it's reusable if client-side pushes are added
// later.

import Constants from "expo-constants";
import * as Device from "expo-device";
import * as Notifications from "expo-notifications";
import { Platform } from "react-native";

import { api, ApiError } from "@/src/lib/api";
import {
  EstadoPasso,
  explicarFalhaDoToken,
  IdPasso,
  MSG_EMULADOR,
  MSG_PERMISSAO,
  MSG_SEM_PROJECT_ID,
  MSG_SEM_RECURSO_NO_SERVIDOR,
  novoDiagnostico,
  ORDEM_PASSOS,
  PassoDiagnostico,
} from "@/src/lib/notificacoes-erros";

// Foreground behavior: show the alert + play sound even while the app is
// open. Without this handler, Expo silently swallows foreground pushes.
Notifications.setNotificationHandler({
  handleNotification: async () => ({
    shouldShowAlert: true,
    shouldPlaySound: true,
    shouldSetBadge: false,
    shouldShowBanner: true,
    shouldShowList: true,
  }),
});

export type PushNotificationData = {
  type?: "confirmacao_pendente" | "confirmacao_urgente" | "novo_agendamento" | "proximo_atendimento" | "teste";
  agendamento_id?: string;
};

export type RegistroPush = { token: string | null; erro: string | null };

/**
 * Pede permissão, obtém o token Expo e o envia ao backend. Em vez de falhar calado, devolve o MOTIVO em português
 * (`erro`), para a tela poder mostrar. Seguro de chamar a cada login: /me/push-token só atualiza.
 */
export async function registrarComDiagnostico(): Promise<RegistroPush> {
  if (!Device.isDevice) {
    return { token: null, erro: MSG_EMULADOR };
  }

  const { status: existing } = await Notifications.getPermissionsAsync();
  let status = existing;
  if (existing !== "granted") {
    const req = await Notifications.requestPermissionsAsync();
    status = req.status;
  }
  if (status !== "granted") {
    return { token: null, erro: MSG_PERMISSAO };
  }

  if (Platform.OS === "android") {
    // Precisa existir ANTES do envio, ou a Expo cai para prioridade default
    // silenciosamente — ver channelId em backend/expo_push.py.
    await Notifications.setNotificationChannelAsync("default", {
      name: "default",
      importance: Notifications.AndroidImportance.HIGH,
      vibrationPattern: [0, 250, 250, 250],
    });
  }

  const projectId =
    Constants.expoConfig?.extra?.eas?.projectId ?? Constants.easConfig?.projectId;
  if (!projectId) {
    return { token: null, erro: MSG_SEM_PROJECT_ID };
  }

  try {
    const { data: expoPushToken } = await Notifications.getExpoPushTokenAsync({ projectId });
    await api("/api/me/push-token", {
      method: "PUT",
      body: JSON.stringify({ expo_push_token: expoPushToken, platform: Platform.OS }),
    });
    return { token: expoPushToken, erro: null };
  } catch (e) {
    return { token: null, erro: explicarFalhaDoToken(e instanceof Error ? e.message : String(e)) };
  }
}

/** Versão silenciosa, usada no login: registra o aparelho e só avisa no console se falhar. */
export async function registerForPushNotifications(): Promise<string | null> {
  const r = await registrarComDiagnostico();
  if (r.erro) console.warn("[push]", r.erro);
  return r.token;
}

/**
 * Botão "Enviar notificação de teste": percorre as etapas uma a uma e devolve a lista com o resultado de cada uma
 * (`aoMudar` é chamado a cada passo, para a tela mostrar o andamento). Assim, quando a notificação não chega, a lista
 * mostra EXATAMENTE em que etapa parou.
 */
export async function diagnosticarNotificacoes(
  aoMudar?: (passos: PassoDiagnostico[]) => void,
): Promise<{ passos: PassoDiagnostico[]; token: string | null }> {
  const passos = novoDiagnostico();
  let token: string | null = null;
  const marcar = (id: IdPasso, estado: EstadoPasso, detalhe?: string) => {
    const p = passos.find((x) => x.id === id)!;
    p.estado = estado;
    p.detalhe = detalhe;
    aoMudar?.(passos.map((x) => ({ ...x })));
  };
  const pularDaqui = (id: IdPasso) => {
    for (const outro of ORDEM_PASSOS.slice(ORDEM_PASSOS.indexOf(id) + 1)) marcar(outro, "pulado");
  };
  const falhar = (id: IdPasso, detalhe: string) => {
    marcar(id, "falhou", detalhe);
    pularDaqui(id);
    return { passos, token };
  };

  marcar("aparelho", "executando");
  if (!Device.isDevice) return falhar("aparelho", MSG_EMULADOR);
  marcar("aparelho", "ok");

  marcar("permissao", "executando");
  let { status } = await Notifications.getPermissionsAsync();
  if (status !== "granted") status = (await Notifications.requestPermissionsAsync()).status;
  if (status !== "granted") return falhar("permissao", MSG_PERMISSAO);
  marcar("permissao", "ok");

  marcar("token", "executando");
  if (Platform.OS === "android") {
    await Notifications.setNotificationChannelAsync("default", {
      name: "default",
      importance: Notifications.AndroidImportance.HIGH,
      vibrationPattern: [0, 250, 250, 250],
    });
  }
  const projectId = Constants.expoConfig?.extra?.eas?.projectId ?? Constants.easConfig?.projectId;
  if (!projectId) return falhar("token", MSG_SEM_PROJECT_ID);
  let obtido: string;
  try {
    obtido = (await Notifications.getExpoPushTokenAsync({ projectId })).data;
  } catch (e) {
    return falhar("token", explicarFalhaDoToken(e instanceof Error ? e.message : String(e)));
  }
  token = obtido;
  marcar("token", "ok", `${obtido.slice(0, 18)}…${obtido.slice(-4)}`);

  marcar("registro", "executando");
  try {
    await api("/api/me/push-token", { method: "PUT", body: JSON.stringify({ expo_push_token: obtido, platform: Platform.OS }) });
  } catch (e) {
    return falhar("registro", explicarFalhaDoToken(e instanceof Error ? e.message : String(e)));
  }
  marcar("registro", "ok");

  marcar("envio", "executando");
  marcar("entrega", "aguardando");
  try {
    const r = await api<{ enviado: boolean; recibo: string; mensagem: string; etapa?: string | null }>("/api/me/notificacoes/teste", {
      method: "POST",
    });
    if (r.etapa === "ticket") return falhar("envio", r.mensagem);
    marcar("envio", "ok");
    marcar("entrega", r.recibo === "ok" ? "ok" : r.recibo === "pendente" ? "pendente" : "falhou", r.mensagem);
  } catch (e) {
    if (e instanceof ApiError && e.status === 404) return falhar("envio", MSG_SEM_RECURSO_NO_SERVIDOR);
    return falhar("envio", e instanceof ApiError ? e.message : "Sem conexão com o servidor. Confira a internet e tente de novo.");
  }
  return { passos, token };
}

/** Best-effort — chamado no signOut para não deixar push chegando para quem
 * já saiu da conta neste aparelho. */
export async function unregisterPushToken(): Promise<void> {
  try {
    await api("/api/me/push-token", { method: "DELETE" });
  } catch {
    // Sem sessão válida (já deslogado) é o caso comum aqui — ignora.
  }
}
