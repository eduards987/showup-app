// Perfil: user info, save card (cliente), sign out.

import Ionicons from "@react-native-vector-icons/ionicons";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import * as Clipboard from "expo-clipboard";
import { useRouter } from "expo-router";
import { useState } from "react";
import {
  ActivityIndicator,
  Linking,
  Pressable,
  ScrollView,
  Share,
  Text,
  View,
} from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import { CardSetupButton } from "@/src/components/card-setup-button";
import { ExcluirContaCard } from "@/src/components/excluir-conta";
import { NotificacoesCard } from "@/src/components/notificacoes-card";
import { api } from "@/src/lib/api";
import { useAuth } from "@/src/lib/auth";
import { URL_PRIVACIDADE, URL_SITE, URL_TERMOS } from "@/src/lib/legal";
import { CardInfo } from "@/src/lib/types";
import { makeStyles, radius, spacing, useTheme } from "@/src/theme";

// Página pública de agendamento (fora do app, funciona sem instalar nada), hospedada no Firebase. O link bonito
// (/p/eduardo-cerqueira) vem do servidor; este endereço antigo só é usado se o servidor não responder.
const BOOKING_PAGE_BASE = `${URL_SITE}/agendar`;

const useStyles = makeStyles((c) => ({
  root: { flex: 1, backgroundColor: c.surface },
  header: { paddingHorizontal: spacing.xl, paddingVertical: spacing.lg },
  title: { fontSize: 24, fontWeight: "700", color: c.onSurface },
  identity: {
    marginHorizontal: spacing.xl,
    padding: spacing.lg,
    backgroundColor: c.surfaceSecondary,
    borderRadius: radius.lg,
    borderWidth: 1,
    borderColor: c.border,
    flexDirection: "row",
    alignItems: "center",
    gap: spacing.md,
  },
  avatar: {
    width: 52,
    height: 52,
    borderRadius: radius.pill,
    backgroundColor: c.brandTertiary,
    alignItems: "center",
    justifyContent: "center",
  },
  avatarText: { color: c.brandPrimary, fontWeight: "800", fontSize: 20 },
  name: { fontSize: 16, fontWeight: "700", color: c.onSurfaceSecondary },
  email: { fontSize: 13, color: c.muted, marginTop: 2 },
  roleTag: {
    marginTop: spacing.xs,
    alignSelf: "flex-start",
    paddingHorizontal: spacing.sm,
    paddingVertical: 2,
    borderRadius: radius.pill,
    backgroundColor: c.brandPrimary,
  },
  roleText: { color: c.onBrandPrimary, fontSize: 11, fontWeight: "700" },
  sectionTitle: {
    marginHorizontal: spacing.xl,
    marginTop: spacing.xl,
    marginBottom: spacing.md,
    fontSize: 12,
    fontWeight: "800",
    color: c.muted,
    letterSpacing: 1,
  },
  card: {
    marginHorizontal: spacing.xl,
    padding: spacing.lg,
    backgroundColor: c.surfaceSecondary,
    borderRadius: radius.lg,
    borderWidth: 1,
    borderColor: c.border,
    gap: spacing.sm,
  },
  cardRow: { flexDirection: "row", alignItems: "center", justifyContent: "space-between" },
  cardLabel: { fontSize: 14, color: c.onSurfaceSecondary, fontWeight: "600" },
  cardMeta: { fontSize: 13, color: c.muted },
  cta: {
    height: 48,
    borderRadius: radius.md,
    backgroundColor: c.brandPrimary,
    alignItems: "center",
    justifyContent: "center",
    flexDirection: "row",
    gap: spacing.sm,
    marginTop: spacing.sm,
  },
  ctaText: { color: c.onBrandPrimary, fontSize: 15, fontWeight: "700" },
  logout: {
    marginHorizontal: spacing.xl,
    marginTop: spacing.xxl,
    height: 48,
    borderRadius: radius.md,
    borderWidth: 1,
    borderColor: c.border,
    alignItems: "center",
    justifyContent: "center",
  },
  logoutText: { color: c.error, fontSize: 15, fontWeight: "600" },
  note: {
    marginHorizontal: spacing.xl,
    marginTop: spacing.md,
    fontSize: 11,
    color: c.muted,
    textAlign: "center",
    lineHeight: 16,
  },
  note2: {
    fontSize: 12,
    color: c.muted,
    lineHeight: 17,
    marginBottom: spacing.sm,
  },
  linkText: {
    fontSize: 12,
    color: c.onSurfaceSecondary,
    backgroundColor: c.surfaceSecondary,
    borderRadius: radius.sm,
    paddingHorizontal: spacing.sm,
    paddingVertical: spacing.xs,
    fontFamily: "monospace",
  },
  linkActions: {
    flexDirection: "row",
    gap: spacing.sm,
    marginTop: spacing.sm,
  },
  linkActionBtn: {
    flex: 1,
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "center",
    gap: spacing.xs,
    backgroundColor: c.brandTertiary,
    borderRadius: radius.md,
    paddingVertical: spacing.sm,
  },
  linkActionText: {
    fontSize: 13,
    fontWeight: "600",
    color: c.brandPrimary,
  },
  errorText: {
    color: c.onError,
    fontSize: 12,
    marginTop: spacing.sm,
    textAlign: "center",
  },
}));

export default function Perfil() {
  const styles = useStyles();
  const { colors } = useTheme();
  const insets = useSafeAreaInsets();
  const router = useRouter();
  const auth = useAuth();
  const qc = useQueryClient();
  const [linkCopiado, setLinkCopiado] = useState(false);

  const isCliente = auth.status === "authenticated" && auth.user.role === "cliente";

  // Link de agendamento do profissional, no formato legível (/p/eduardo-cerqueira). Vem do servidor, então trocar o
  // domínio do site não exige recompilar o app.
  const linkQ = useQuery({
    // o id do usuário na chave: quem entra numa conta diferente no mesmo celular nunca vê o link da conta anterior
    queryKey: ["link-publico", auth.status === "authenticated" ? auth.user.user_id : null],
    queryFn: () => api<{ slug: string; url: string }>("/api/me/link-publico"),
    enabled: auth.status === "authenticated" && !isCliente,
    staleTime: Infinity,
  });

  const cardQ = useQuery({
    queryKey: ["card"],
    queryFn: () => api<CardInfo>("/api/me/card"),
    enabled: isCliente,
  });

  if (auth.status !== "authenticated") return null;
  const user = auth.user;
  const initials = user.name.split(" ").map((s) => s[0]).slice(0, 2).join("").toUpperCase();
  const bookingLink = linkQ.data?.url ?? `${BOOKING_PAGE_BASE}?prof=${user.user_id}`;

  const copiarLink = async () => {
    await Clipboard.setStringAsync(bookingLink);
    setLinkCopiado(true);
    setTimeout(() => setLinkCopiado(false), 2000);
  };
  const compartilharLink = () => {
    // Share.share() abre o menu nativo do celular — WhatsApp aparece como
    // uma das opções ali, sem precisar de nenhuma integração automática.
    Share.share({
      message: `Agende seu horário com ${user.name} pelo ShowUp: ${bookingLink}`,
    });
  };

  return (
    <View style={[styles.root, { paddingTop: insets.top }]}>
      <ScrollView contentContainerStyle={{ paddingBottom: insets.bottom + spacing.xxl }}>
        <View style={styles.header}>
          <Text style={styles.title}>Perfil</Text>
        </View>
        <View style={styles.identity}>
          <View style={styles.avatar}>
            <Text style={styles.avatarText}>{initials}</Text>
          </View>
          <View style={{ flex: 1 }}>
            <Text style={styles.name}>{user.name}</Text>
            <Text style={styles.email}>{user.email}</Text>
            <View style={styles.roleTag}>
              <Text style={styles.roleText}>
                {user.role === "cliente" ? "CLIENTE" : "PROFISSIONAL"}
              </Text>
            </View>
          </View>
        </View>

        {isCliente ? (
          <>
            <Text style={styles.sectionTitle}>MÉTODO DE PAGAMENTO</Text>
            <View style={styles.card}>
              {cardQ.data?.has_card ? (
                <>
                  <View style={styles.cardRow}>
                    <Ionicons name="card" size={20} color={colors.brandPrimary} />
                    <Text style={styles.cardLabel}>
                      {cardQ.data.brand?.toUpperCase()} •••• {cardQ.data.last4}
                    </Text>
                  </View>
                  <Text style={styles.cardMeta}>
                    Expira {cardQ.data.exp_month}/{cardQ.data.exp_year}
                  </Text>
                  <Text style={styles.note}>
                    Cartão salvo com segurança pelo Stripe — nunca passa pelos nossos servidores.
                  </Text>
                </>
              ) : (
                <>
                  <Text style={styles.cardLabel}>Nenhum cartão cadastrado</Text>
                  <Text style={styles.cardMeta}>
                    Precisamos de um cartão para pré-autorizar o hold no ato do agendamento.
                  </Text>
                  <CardSetupButton
                    onSaved={() => {
                      qc.invalidateQueries({ queryKey: ["card"] });
                      auth.refresh();
                    }}
                  />
                </>
              )}
            </View>
          </>
        ) : null}

        {!isCliente ? (
          <>
            <Text style={styles.sectionTitle}>CONFIGURAÇÕES DO PROFISSIONAL</Text>
            <Pressable
              testID="open-configuracoes"
              onPress={() => router.push("/(app)/configuracoes")}
              style={styles.card}
            >
              <View style={styles.cardRow}>
                <Ionicons name="settings-outline" size={20} color={colors.brandPrimary} />
                <Text style={styles.cardLabel}>Categorias, disponibilidade e Stripe Connect</Text>
                <Ionicons name="chevron-forward" size={18} color={colors.muted} />
              </View>
            </Pressable>
            <Pressable
              testID="open-planos"
              onPress={() => router.push("/(app)/planos")}
              style={styles.card}
            >
              <View style={styles.cardRow}>
                <Ionicons name="pricetag-outline" size={20} color={colors.brandPrimary} />
                <Text style={styles.cardLabel}>Plano e taxa por agendamento</Text>
                <Ionicons name="chevron-forward" size={18} color={colors.muted} />
              </View>
            </Pressable>

            <Text style={styles.sectionTitle}>NOTIFICAÇÕES</Text>
            <NotificacoesCard />

            <Text style={styles.sectionTitle}>SEU LINK DE AGENDAMENTO</Text>
            <View style={styles.card}>
              <View style={styles.cardRow}>
                <Ionicons name="link-outline" size={20} color={colors.brandPrimary} />
                <Text style={styles.cardLabel}>Compartilhe pra agendar sem app</Text>
              </View>
              <Text style={styles.note2}>
                Envie esse link pro cliente pelo WhatsApp — ele agenda e paga (Pix) sem
                precisar instalar nada.
              </Text>
              <Text style={styles.linkText} numberOfLines={1}>
                {bookingLink}
              </Text>
              <View style={styles.linkActions}>
                <Pressable testID="copiar-link" onPress={copiarLink} style={styles.linkActionBtn}>
                  <Ionicons
                    name={linkCopiado ? "checkmark" : "copy-outline"}
                    size={16}
                    color={colors.brandPrimary}
                  />
                  <Text style={styles.linkActionText}>{linkCopiado ? "Copiado!" : "Copiar"}</Text>
                </Pressable>
                <Pressable testID="compartilhar-link" onPress={compartilharLink} style={styles.linkActionBtn}>
                  <Ionicons name="share-social-outline" size={16} color={colors.brandPrimary} />
                  <Text style={styles.linkActionText}>Compartilhar</Text>
                </Pressable>
              </View>
            </View>
          </>
        ) : null}

        <Text style={styles.sectionTitle}>SOBRE</Text>
        <Pressable testID="abrir-termos" onPress={() => Linking.openURL(URL_TERMOS)} style={styles.card}>
          <View style={styles.cardRow}>
            <Ionicons name="document-text-outline" size={20} color={colors.brandPrimary} />
            <Text style={styles.cardLabel}>Termos de uso</Text>
            <Ionicons name="open-outline" size={18} color={colors.muted} />
          </View>
        </Pressable>
        <Pressable testID="abrir-privacidade" onPress={() => Linking.openURL(URL_PRIVACIDADE)} style={styles.card}>
          <View style={styles.cardRow}>
            <Ionicons name="shield-checkmark-outline" size={20} color={colors.brandPrimary} />
            <Text style={styles.cardLabel}>Política de privacidade</Text>
            <Ionicons name="open-outline" size={18} color={colors.muted} />
          </View>
        </Pressable>

        <Pressable
          testID="logout-button"
          onPress={auth.signOut}
          style={styles.logout}
        >
          <Text style={styles.logoutText}>Sair</Text>
        </Pressable>

        <Text style={styles.sectionTitle}>ZONA DE PERIGO</Text>
        <ExcluirContaCard />
      </ScrollView>
    </View>
  );
}
