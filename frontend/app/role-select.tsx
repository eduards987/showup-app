// Role selection: one-time post-login branching between Cliente and Profissional.

import { Redirect, useRouter } from "expo-router";
import { useState } from "react";
import {
  ActivityIndicator,
  Alert,
  Pressable,
  Text,
  View,
} from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import { ApiError } from "@/src/lib/api";
import { Role, useAuth } from "@/src/lib/auth";
import { makeStyles, radius, spacing, useTheme } from "@/src/theme";
import { t } from "@/src/i18n/core";
import { PARAM_TUTORIAL } from "@/src/lib/tutorial";
import { useIdioma } from "@/src/i18n";

const useStyles = makeStyles((colors) => ({
  root: { flex: 1, backgroundColor: colors.surface },
  header: {
    paddingHorizontal: spacing.xl,
    paddingTop: spacing.xl,
    paddingBottom: spacing.lg,
  },
  hi: { fontSize: 14, color: colors.muted, marginBottom: spacing.xs },
  title: {
    fontSize: 26,
    fontWeight: "700",
    color: colors.onSurface,
    lineHeight: 32,
  },
  subtitle: {
    marginTop: spacing.sm,
    fontSize: 15,
    color: colors.muted,
    lineHeight: 22,
  },
  cards: { paddingHorizontal: spacing.xl, gap: spacing.md, marginTop: spacing.lg },
  card: {
    backgroundColor: colors.surfaceSecondary,
    borderRadius: radius.lg,
    borderWidth: 1,
    borderColor: colors.border,
    padding: spacing.lg,
    minHeight: 132,
    gap: spacing.sm,
  },
  cardSelected: {
    borderColor: colors.brandPrimary,
    borderWidth: 2,
    backgroundColor: colors.brandTertiary,
  },
  cardTitleRow: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
  },
  cardTitle: {
    fontSize: 18,
    fontWeight: "700",
    color: colors.onSurfaceSecondary,
  },
  iconBubble: {
    width: 40,
    height: 40,
    borderRadius: radius.pill,
    backgroundColor: colors.brandTertiary,
    alignItems: "center",
    justifyContent: "center",
  },
  iconBubbleSelected: { backgroundColor: colors.brandPrimary },
  iconText: { fontSize: 18, color: colors.brandPrimary, fontWeight: "700" },
  iconTextSelected: { color: colors.onBrandPrimary },
  cardDesc: {
    fontSize: 14,
    color: colors.muted,
    lineHeight: 20,
  },
  ctaWrap: {
    paddingHorizontal: spacing.xl,
    paddingTop: spacing.md,
  },
  cta: {
    height: 54,
    borderRadius: radius.md,
    backgroundColor: colors.brandPrimary,
    alignItems: "center",
    justifyContent: "center",
  },
  ctaDisabled: { opacity: 0.5 },
  ctaText: { color: colors.onBrandPrimary, fontSize: 16, fontWeight: "700" },
  spacer: { flex: 1 },
}));

export default function RoleSelect() {
  useIdioma();
  const auth = useAuth();
  const router = useRouter();
  const styles = useStyles();
  const { colors } = useTheme();
  const insets = useSafeAreaInsets();
  const [selected, setSelected] = useState<Role | null>(null);
  const [saving, setSaving] = useState(false);

  if (auth.status === "loading") return null;
  if (auth.status === "unauthenticated") return <Redirect href="/welcome" />;
  // Enquanto salva, quem leva ao Início é o handleContinue (com o tutorial); sem esta trava, a mudança do papel
  // redirecionava antes, sem o parâmetro, e o tutorial não abria.
  if (auth.user.role && !saving) return <Redirect href="/(app)/home" />;

  const options: { role: Role; title: string; desc: string; letter: string }[] = [
    {
      role: "cliente",
      title: t("Sou Cliente"),
      desc: t("Quero agendar sessões e serviços com prestadores."),
      letter: "C",
    },
    {
      role: "profissional",
      title: t("Sou Profissional"),
      desc: t("Quero receber agendamentos e proteger minha agenda contra no-shows."),
      letter: "P",
    },
  ];

  const handleContinue = async () => {
    if (!selected || saving) return;
    setSaving(true);
    try {
      await auth.setRole(selected);
      // Cadastro concluído: o Início abre o mini tutorial do papel escolhido (dá para pular).
      router.replace({ pathname: "/(app)/home", params: { [PARAM_TUTORIAL]: "1" } });
    } catch (err) {
      Alert.alert(t("Não foi possível salvar"), err instanceof ApiError ? err.message : t("Sem conexão com o servidor. Confira a internet e tente de novo."));
    } finally {
      setSaving(false);
    }
  };

  return (
    <View
      testID="role-select-screen"
      style={[
        styles.root,
        { paddingTop: insets.top, paddingBottom: insets.bottom },
      ]}
    >
      <View style={styles.header}>
        <Text style={styles.hi}>{t("Olá,")}{" "}{auth.user.name.split(" ")[0]}</Text>
        <Text style={styles.title}>{t("Como você vai usar o ShowUp?")}</Text>
        <Text style={styles.subtitle}>{t("Escolha o papel principal. Você poderá ajustar depois.")}</Text>
      </View>
      <View style={styles.cards}>
        {options.map((opt) => {
          const isSel = selected === opt.role;
          return (
            <Pressable
              key={opt.role}
              testID={`role-card-${opt.role}`}
              onPress={() => setSelected(opt.role)}
              style={({ pressed }) => [
                styles.card,
                isSel && styles.cardSelected,
                pressed && { opacity: 0.9 },
              ]}
            >
              <View style={styles.cardTitleRow}>
                <Text style={styles.cardTitle}>{opt.title}</Text>
                <View
                  style={[
                    styles.iconBubble,
                    isSel && styles.iconBubbleSelected,
                  ]}
                >
                  <Text
                    style={[
                      styles.iconText,
                      isSel && styles.iconTextSelected,
                    ]}
                  >
                    {opt.letter}
                  </Text>
                </View>
              </View>
              <Text style={styles.cardDesc}>{opt.desc}</Text>
            </Pressable>
          );
        })}
      </View>
      <View style={styles.spacer} />
      <View style={styles.ctaWrap}>
        <Pressable
          testID="role-continue-button"
          onPress={handleContinue}
          disabled={!selected || saving}
          style={({ pressed }) => [
            styles.cta,
            (!selected || saving) && styles.ctaDisabled,
            pressed && { opacity: 0.85 },
          ]}
        >
          {saving ? (
            <ActivityIndicator color={colors.onBrandPrimary} />
          ) : (
            <Text style={styles.ctaText}>{t("Continuar")}</Text>
          )}
        </Pressable>
      </View>
    </View>
  );
}
