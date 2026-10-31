// usePushRegistration — mount this once, inside the authenticated area of
// the app (see app/(app)/_layout.tsx). Handles:
//   1. Registering the device's Expo push token once the user is an
//      authenticated profissional.
//   2. Listening for notification taps and deep-linking to the relevant
//      agendamento screen.
//
// Kept separate from AuthProvider on purpose: auth.tsx is about identity,
// this is about a device capability tied to identity. Mixing them would
// make auth.tsx responsible for notification wiring it doesn't need to know
// about.

import * as Notifications from "expo-notifications";
import { useRouter } from "expo-router";
import { useEffect, useRef } from "react";

import { useAuth } from "@/src/lib/auth";
import type { PushNotificationData } from "@/src/lib/push-notifications";
import { registerForPushNotifications } from "@/src/lib/push-notifications";

export function usePushRegistration() {
  const auth = useAuth();
  const router = useRouter();
  const registeredForUserId = useRef<string | null>(null);

  // 1. Registro do aparelho: profissional (novo agendamento, próximo atendimento) e cliente (confirmação e lembrete
  // do agendamento). Uma vez por conta, por sessão do app.
  const userId = auth.status === "authenticated" ? auth.user.user_id : null;
  const role = auth.status === "authenticated" ? auth.user.role : null;
  useEffect(() => {
    if (!userId || (role !== "profissional" && role !== "cliente")) return;
    if (registeredForUserId.current === userId) return;

    registeredForUserId.current = userId;
    registerForPushNotifications();
  }, [userId, role]);

  // 2. Tap handling — works whether the app was backgrounded or fully
  // killed (getLastNotificationResponseAsync covers the cold-start case).
  useEffect(() => {
    const navigateFromData = (data: PushNotificationData | undefined) => {
      if (data?.agendamento_id) {
        router.push({ pathname: "/agendamento/[id]", params: { id: data.agendamento_id } });
      }
    };

    Notifications.getLastNotificationResponseAsync().then((response) => {
      if (response) navigateFromData(response.notification.request.content.data as PushNotificationData);
    });

    const sub = Notifications.addNotificationResponseReceivedListener((response) => {
      navigateFromData(response.notification.request.content.data as PushNotificationData);
    });

    return () => sub.remove();
  }, [router]);
}
