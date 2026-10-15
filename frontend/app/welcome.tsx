// Welcome screen: full-bleed image, gradient scrim, bottom card with Google Sign-In.

import { Image } from "expo-image";
import { LinearGradient } from "expo-linear-gradient";
import { Redirect } from "expo-router";
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

import { useAuth } from "@/src/lib/auth";
import { URL_PRIVACIDADE, URL_TERMOS } from "@/src/lib/legal";
import { makeStyles, radius, spacing, useTheme } from "@/src/theme";

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
  const auth = useAuth();
  const styles = useStyles();
  const { colors } = useTheme();
  const insets = useSafeAreaInsets();
  const [loading, setLoading] = useState(false);

  if (auth.status === "authenticated") return <Redirect href="/" />;

  const handleSignIn = async () => {
    setLoading(true);
    try {
      await auth.signIn();
    } finally {
      setLoading(false);
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
      <View style={{ flex: 1 }} />
      <View style={[styles.card, { paddingBottom: insets.bottom + spacing.xl }]}>
        <View style={styles.brandRow}>
          <View style={styles.brandDot} />
          <Text style={styles.brand}>SHOWUP</Text>
        </View>
        <Text style={styles.title}>Agendamentos com garantia.</Text>
        <Text style={styles.subtitle}>
          Pré-autorização de pagamento na hora do agendamento. Sem no-show,
          sem cobrança abusiva.
        </Text>
        <Pressable
          testID="google-signin-button"
          onPress={handleSignIn}
          disabled={loading}
          style={({ pressed }) => [
            styles.googleBtn,
            pressed && styles.googleBtnPressed,
          ]}
        >
          {loading ? (
            <ActivityIndicator color={colors.onSurfaceInverse} />
          ) : (
            <>
              <View style={styles.gLogo}>
                <Text style={styles.gLogoText}>G</Text>
              </View>
              <Text style={styles.googleText}>Continuar com Google</Text>
            </>
          )}
        </Pressable>
        <Text style={styles.legal}>
          Ao continuar você concorda com os{" "}
          <Text testID="link-termos" style={styles.legalLink} onPress={() => Linking.openURL(URL_TERMOS)}>
            termos de uso
          </Text>{" "}
          e a{" "}
          <Text testID="link-privacidade" style={styles.legalLink} onPress={() => Linking.openURL(URL_PRIVACIDADE)}>
            política de privacidade
          </Text>
          .
        </Text>
      </View>
    </View>
  );
}
