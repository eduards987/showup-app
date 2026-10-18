// Welcome screen: full-bleed image, gradient scrim, bottom card with Google Sign-In.

import Ionicons from "@react-native-vector-icons/ionicons";
import { useQuery } from "@tanstack/react-query";
import { Image } from "expo-image";
import { LinearGradient } from "expo-linear-gradient";
import { Redirect, useRouter } from "expo-router";
import { useState } from "react";
import {
  ActivityIndicator,
  Linking,
  Pressable,
  StyleSheet,
  Text,
  View,
} from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import { api } from "@/src/lib/api";
import { useAuth } from "@/src/lib/auth";
import type { Metodos } from "@/src/lib/auth-email";
import { URL_PRIVACIDADE, URL_TERMOS } from "@/src/lib/legal";
import { makeStyles, radius, spacing, useTheme } from "@/src/theme";
import { SeletorIdioma } from "@/src/components/seletor-idioma";
import { t } from "@/src/i18n/core";
import { useIdioma } from "@/src/i18n";

const WELCOME_BG =
  "https://images.unsplash.com/photo-1698486617282-2c9a0e3193f7?crop=entropy&cs=srgb&fm=jpg&ixid=M3w4NjA1OTV8MHwxfHNlYXJjaHwxfHxhYnN0cmFjdCUyMHdlbGxuZXNzJTIwc2NoZWR1bGluZyUyMGJhY2tncm91bmR8ZW58MHx8fHwxNzg5NTc1NzM5fDA&ixlib=rb-4.1.0&q=85";

const useStyles = makeStyles((colors) => ({
  root: { flex: 1, backgroundColor: colors.surface },
  bg: StyleSheet.absoluteFill,
  card: {
    backgroundColor: colors.surfaceSecondary,
    borderTopLeftRadius: radius.lg,
    borderTopRightRadius: radius.lg,
    paddingHorizontal: spacing.xl,
    paddingTop: spacing.xl,
    gap: spacing.md,
  },
  brandRow: {
    flexDirection: "row",
    alignItems: "center",
    gap: spacing.sm,
    marginBottom: spacing.sm,
  },
  brandDot: {
    width: 12,
    height: 12,
    borderRadius: radius.pill,
    backgroundColor: colors.brandPrimary,
  },
  brand: {
    fontSize: 14,
    fontWeight: "600",
    color: colors.onSurfaceSecondary,
    letterSpacing: 1,
  },
  title: {
    fontSize: 28,
    fontWeight: "700",
    color: colors.onSurfaceSecondary,
    lineHeight: 34,
  },
  subtitle: {
    fontSize: 15,
    color: colors.muted,
    lineHeight: 22,
  },
  googleBtn: {
    marginTop: spacing.lg,
    height: 54,
    borderRadius: radius.md,
    backgroundColor: colors.onSurface,
    alignItems: "center",
    justifyContent: "center",
    flexDirection: "row",
    gap: spacing.md,
  },
  googleBtnPressed: { opacity: 0.85 },
  googleText: {
    color: colors.onSurfaceInverse,
    fontSize: 16,
    fontWeight: "600",
  },
  gLogo: {
    width: 22,
    height: 22,
    borderRadius: radius.pill,
    backgroundColor: "#FFFFFF",
    alignItems: "center",
    justifyContent: "center",
  },
  gLogoText: { color: "#4285F4", fontWeight: "700", fontSize: 14 },
  outlineBtn: {
    height: 54,
    borderRadius: radius.md,
    borderWidth: 1,
    borderColor: colors.border,
    backgroundColor: colors.surface,
    alignItems: "center",
    justifyContent: "center",
    flexDirection: "row",
    gap: spacing.md,
  },
  outlineText: { color: colors.onSurface, fontSize: 16, fontWeight: "600" },
  msLogo: { width: 20, height: 20, flexDirection: "row", flexWrap: "wrap", gap: 2 },
  msQuad: { width: 9, height: 9 },
  erro: { fontSize: 13, color: colors.error, textAlign: "center", lineHeight: 18 },
  legal: {
    marginTop: spacing.md,
    fontSize: 12,
    color: colors.muted,
    textAlign: "center",
    lineHeight: 18,
  },
  legalLink: { textDecorationLine: "underline", color: colors.onSurface },
}));

export default function Welcome() {
  useIdioma();
  const auth = useAuth();
  const styles = useStyles();
  const { colors } = useTheme();
  const insets = useSafeAreaInsets();
  const router = useRouter();
  const [loading, setLoading] = useState<"google" | "microsoft" | null>(null);
  const [erro, setErro] = useState<string | null>(null);

  // Quais jeitos de entrar o servidor consegue atender (Microsoft e e-mail dependem de configuração
  // dele). Enquanto não responde — ou se o servidor estiver dormindo — só o Google aparece.
  const metodosQ = useQuery({
    queryKey: ["auth-metodos"],
    queryFn: () => api<Metodos>("/api/auth/metodos"),
    retry: 2,
    staleTime: 5 * 60 * 1000,
  });
  const metodos = metodosQ.data;

  if (auth.status === "authenticated") return <Redirect href="/" />;

  const handleSignIn = async () => {
    setErro(null);
    setLoading("google");
    try {
      setErro(await auth.signIn());
    } catch {
      setErro(t("Não foi possível entrar com o Google. Tente de novo."));
    } finally {
      setLoading(null);
    }
  };

  const handleMicrosoft = async () => {
    setErro(null);
    setLoading("microsoft");
    try {
      setErro(await auth.signInMicrosoft());
    } catch {
      setErro(t("Não foi possível entrar com a Microsoft. Tente de novo."));
    } finally {
      setLoading(null);
    }
  };

  return (
    <View style={styles.root} testID="welcome-screen">
      <Image
        source={{ uri: WELCOME_BG }}
        style={styles.bg}
        contentFit="cover"
        transition={200}
      />
      <LinearGradient
        colors={["transparent", "rgba(44,46,45,0.35)", colors.surface]}
        locations={[0, 0.55, 1]}
        style={styles.bg}
      />
      <View style={{ position: "absolute", top: insets.top + spacing.md, right: spacing.lg, zIndex: 2 }}>
        <SeletorIdioma variante="pilula" />
      </View>
      <View style={{ flex: 1 }} />
      <View style={[styles.card, { paddingBottom: insets.bottom + spacing.xl }]}>
        <View style={styles.brandRow}>
          <View style={styles.brandDot} />
          <Text style={styles.brand}>SHOWUP</Text>
        </View>
        <Text style={styles.title}>{t("Agendamentos com garantia.")}</Text>
        <Text style={styles.subtitle}>{t("Pré-autorização de pagamento na hora do agendamento. Sem no-show, sem cobrança abusiva.")}</Text>
        <Pressable
          testID="google-signin-button"
          onPress={handleSignIn}
          disabled={loading !== null}
          style={({ pressed }) => [
            styles.googleBtn,
            pressed && styles.googleBtnPressed,
          ]}
        >
          {loading === "google" ? (
            <ActivityIndicator color={colors.onSurfaceInverse} />
          ) : (
            <>
              <View style={styles.gLogo}>
                <Text style={styles.gLogoText}>G</Text>
              </View>
              <Text style={styles.googleText}>{t("Continuar com Google")}</Text>
            </>
          )}
        </Pressable>
        {metodos?.microsoft ? (
          <Pressable
            testID="microsoft-signin-button"
            onPress={handleMicrosoft}
            disabled={loading !== null}
            style={({ pressed }) => [styles.outlineBtn, pressed && styles.googleBtnPressed]}
          >
            {loading === "microsoft" ? (
              <ActivityIndicator color={colors.onSurface} />
            ) : (
              <>
                <View style={styles.msLogo}>
                  <View style={[styles.msQuad, { backgroundColor: "#F25022" }]} />
                  <View style={[styles.msQuad, { backgroundColor: "#7FBA00" }]} />
                  <View style={[styles.msQuad, { backgroundColor: "#00A4EF" }]} />
                  <View style={[styles.msQuad, { backgroundColor: "#FFB900" }]} />
                </View>
                <Text style={styles.outlineText}>{t("Continuar com Microsoft")}</Text>
              </>
            )}
          </Pressable>
        ) : null}
        {metodos?.email ? (
          <Pressable
            testID="email-signin-button"
            onPress={() => router.push("/entrar-email")}
            disabled={loading !== null}
            style={({ pressed }) => [styles.outlineBtn, pressed && styles.googleBtnPressed]}
          >
            <Ionicons name="mail-outline" size={20} color={colors.onSurface} />
            <Text style={styles.outlineText}>{t("Continuar com e-mail")}</Text>
          </Pressable>
        ) : null}
        {erro ? (
          <Text style={styles.erro} testID="login-erro">
            {erro}
          </Text>
        ) : null}
        <Text style={styles.legal}>{t("Ao continuar você concorda com os")}{" "}
          <Text testID="link-termos" style={styles.legalLink} onPress={() => Linking.openURL(URL_TERMOS)}>{t("termos de uso")}</Text>{" "}{t("e a")}{" "}
          <Text testID="link-privacidade" style={styles.legalLink} onPress={() => Linking.openURL(URL_PRIVACIDADE)}>{t("política de privacidade")}</Text>
          .
        </Text>
      </View>
    </View>
  );
}
