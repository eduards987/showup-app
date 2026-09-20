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

import { api } from "@/src/lib/api";

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
  type?: "confirmacao_pendente" | "confirmacao_urgente";
  agendamento_id?: string;
};

/**
 * Requests permission, obtains the Expo push token, and sends it to the
 * backend. Safe to call every app foreground/login — /me/push-token just
 * upserts. Returns null (and logs) on any failure instead of throwing, since
 * a push-registration failure should never block the rest of the app.
 */
export async function registerForPushNotifications(): Promise<string | null> {
  if (!Device.isDevice) {
    console.warn("[push] Simuladores/emuladores não recebem push remoto — pule em desenvolvimento.");
    return null;
  }

  const { status: existing } = await Notifications.getPermissionsAsync();
  let status = existing;
  if (existing !== "granted") {
    const req = await Notifications.requestPermissionsAsync();
    status = req.status;
  }
  if (status !== "granted") {
    console.warn("[push] Permissão de notificação negada pelo usuário.");
    return null;
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
    console.warn(
      "[push] extra.eas.projectId ausente no app.json — rode `eas init` e preencha antes do build de produção.",
    );
    return null;
  }

  try {
    const { data: expoPushToken } = await Notifications.getExpoPushTokenAsync({ projectId });
    await api("/api/me/push-token", {
      method: "PUT",
      body: JSON.stringify({ expo_push_token: expoPushToken, platform: Platform.OS }),
    });
    return expoPushToken;
  } catch (e) {
    console.warn("[push] Falha ao obter/registrar o token", e);
    return null;
  }
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
