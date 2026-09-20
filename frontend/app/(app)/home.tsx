// Home tab: role-aware dashboard.

import Ionicons from "@react-native-vector-icons/ionicons";
import { useQuery } from "@tanstack/react-query";
import { Redirect, useRouter } from "expo-router";
import {
  ActivityIndicator,
  Pressable,
  RefreshControl,
  ScrollView,
  Text,
  View,
} from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import { api } from "@/src/lib/api";
import { useAuth } from "@/src/lib/auth";
import { CONFIRMACAO_LABELS, formatMoney, formatDateTime } from "@/src/lib/format";
import { Agendamento, CardInfo } from "@/src/lib/types";
import { makeStyles, radius, spacing, useTheme } from "@/src/theme";

const useStyles = makeStyles((c) => ({
  root: { flex: 1, backgroundColor: c.surface },
  header: {
    paddingHorizontal: spacing.xl,
    paddingVertical: spacing.lg,
    flexDirection: "row",
    justifyContent: "space-between",
    alignItems: "center",
  },
  hi: { fontSize: 14, color: c.muted },
  name: { fontSize: 24, fontWeight: "700", color: c.onSurface, marginTop: 2 },
  avatar: {
    width: 44,
    height: 44,
    borderRadius: radius.pill,
    backgroundColor: c.brandTertiary,
    alignItems: "center",
    justifyContent: "center",
  },
  avatarText: { color: c.brandPrimary, fontWeight: "700", fontSize: 16 },

  banner: {
    marginHorizontal: spacing.xl,
    padding: spacing.lg,
    borderRadius: radius.lg,
    backgroundColor: c.warning,
    flexDirection: "row",
    alignItems: "center",
    gap: spacing.md,
  },
  bannerText: { flex: 1, color: c.onWarning, fontSize: 13, lineHeight: 18, fontWeight: "500" },
  bannerCta: { color: c.onWarning, fontSize: 13, fontWeight: "800" },

  section: { paddingHorizontal: spacing.xl, marginTop: spacing.xl },
  sectionRow: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
    marginBottom: spacing.md,
  },
  sectionTitle: {
    fontSize: 12,
    fontWeight: "800",
    color: c.muted,
    letterSpacing: 1,
  },
  sectionLink: { color: c.brandPrimary, fontSize: 13, fontWeight: "700" },

  card: {
    backgroundColor: c.surfaceSecondary,
    borderRadius: radius.lg,
    borderWidth: 1,
    borderColor: c.border,
    padding: spacing.lg,
    marginBottom: spacing.md,
    gap: 6,
  },
  cardRow: { flexDirection: "row", justifyContent: "space-between", alignItems: "flex-start" },
  cardTitle: { fontSize: 16, fontWeight: "700", color: c.onSurfaceSecondary },
  cardMeta: { fontSize: 13, color: c.muted },
  cardValue: { fontSize: 15, fontWeight: "700", color: c.brandPrimary },
  badge: {
    alignSelf: "flex-start",
    paddingHorizontal: spacing.sm,
    paddingVertical: 2,
    borderRadius: radius.pill,
    backgroundColor: c.brandTertiary,
    marginTop: spacing.xs,
  },
  badgeText: { fontSize: 11, fontWeight: "700", color: c.onBrandTertiary },

  empty: {
    marginHorizontal: spacing.xl,
    padding: spacing.xl,
    backgroundColor: c.surfaceTertiary,
    borderRadius: radius.lg,
    alignItems: "center",
    gap: spacing.xs,
  },
  emptyTitle: { fontSize: 15, fontWeight: "700", color: c.onSurfaceTertiary },
  emptyBody: { fontSize: 13, color: c.muted, textAlign: "center" },

  cta: {
    marginHorizontal: spacing.xl,
    marginTop: spacing.md,
    height: 52,
    borderRadius: radius.md,
    backgroundColor: c.brandPrimary,
    alignItems: "center",
    justifyContent: "center",
    flexDirection: "row",
    gap: spacing.sm,
  },
  ctaText: { color: c.onBrandPrimary, fontSize: 15, fontWeight: "700" },
}));

export default function Home() {
  const auth = useAuth();
  const styles = useStyles();
  const { colors } = useTheme();
  const router = useRouter();
  const insets = useSafeAreaInsets();

  const isCliente = auth.status === "authenticated" && auth.user.role === "cliente";

  const agendamentosQ = useQuery({
    queryKey: ["agendamentos"],
    queryFn: () => api<Agendamento[]>("/api/agendamentos"),
    enabled: auth.status === "authenticated",
  });
  const cardQ = useQuery({
    queryKey: ["card"],
    queryFn: () => api<CardInfo>("/api/me/card"),
    enabled: isCliente,
  });
  const remindersQ = useQuery({
    queryKey: ["reminders"],
    queryFn: () => api<{ count: number; items: Agendamento[] }>("/api/reminders/janela?horas=6"),
    enabled: auth.status === "authenticated" && auth.user.role === "profissional",
    refetchInterval: 60_000,
  });

  if (auth.status !== "authenticated") return <Redirect href="/" />;
  if (!auth.user.role) return <Redirect href="/role-select" />;

  const user = auth.user;
  const initials = user.name.split(" ").map((s) => s[0]).slice(0, 2).join("").toUpperCase();

  const list = agendamentosQ.data ?? [];
  const upcoming = list
    .filter((a) => new Date(a.horario_inicio).getTime() > Date.now() - 60 * 60 * 1000)
    .slice(0, 5);
  const needsAction = !isCliente
    ? list.filter(
        (a) =>
          a.status_confirmacao === "pendente" &&
          a.hold_status === "autorizado" &&
          new Date(a.horario_fim).getTime() <= Date.now(),
      )
    : [];

  return (
    <View style={[styles.root, { paddingTop: insets.top }]}>
      <ScrollView
        testID="home-scroll"
        contentContainerStyle={{ paddingBottom: spacing.xxl }}
        refreshControl={
          <RefreshControl
            refreshing={agendamentosQ.isFetching || cardQ.isFetching}
            onRefresh={() => {
              agendamentosQ.refetch();
              cardQ.refetch();
            }}
            tintColor={colors.brandPrimary}
          />
        }
      >
        <View style={styles.header}>
          <View>
            <Text style={styles.hi}>Bem-vindo,</Text>
            <Text style={styles.name}>{user.name.split(" ")[0]}</Text>
          </View>
          <View style={styles.avatar} testID="home-avatar">
            <Text style={styles.avatarText}>{initials}</Text>
          </View>
        </View>

        {isCliente && cardQ.data && !cardQ.data.has_card ? (
          <Pressable
            testID="save-card-banner"
            onPress={() => router.push("/(app)/perfil")}
            style={styles.banner}
          >
            <Ionicons name="card-outline" size={22} color={colors.onWarning} />
            <Text style={styles.bannerText}>
              Cadastre um cartão para reservar profissionais.
            </Text>
            <Text style={styles.bannerCta}>Cadastrar →</Text>
          </Pressable>
        ) : null}

        {!isCliente && (remindersQ.data?.count ?? 0) > 0 ? (
          <Pressable
            testID="reminder-banner"
            onPress={() => router.push("/(app)/agendamentos")}
            style={[styles.banner, { backgroundColor: colors.error }]}
          >
            <Ionicons name="alarm-outline" size={22} color={colors.onError} />
            <Text style={[styles.bannerText, { color: colors.onError }]}>
              {remindersQ.data!.count} atendimento(s) com janela terminando em menos de 6h.
              Confirme antes que o hold expire.
            </Text>
            <Text style={[styles.bannerCta, { color: colors.onError }]}>Ver →</Text>
          </Pressable>
        ) : null}

        {!isCliente && needsAction.length > 0 ? (
          <View style={styles.section}>
            <View style={styles.sectionRow}>
              <Text style={styles.sectionTitle}>PRECISAM DE CONFIRMAÇÃO</Text>
            </View>
            {needsAction.map((a) => (
              <Pressable
                key={a.agendamento_id}
                testID={`needs-action-${a.agendamento_id}`}
                onPress={() => router.push(`/(app)/agendamento/${a.agendamento_id}`)}
                style={styles.card}
              >
                <View style={styles.cardRow}>
                  <View style={{ flex: 1 }}>
                    <Text style={styles.cardTitle}>{a.cliente_nome}</Text>
                    <Text style={styles.cardMeta}>
                      {a.servico_nome} · {formatDateTime(a.horario_inicio)}
                    </Text>
                  </View>
                  <Text style={styles.cardValue}>{formatMoney(a.valor_total_centavos, a.moeda)}</Text>
                </View>
                <View style={[styles.badge, { backgroundColor: colors.warning }]}>
                  <Text style={[styles.badgeText, { color: colors.onWarning }]}>
                    AGUARDANDO SUA CONFIRMAÇÃO
                  </Text>
                </View>
              </Pressable>
            ))}
          </View>
        ) : null}

        <View style={styles.section}>
          <View style={styles.sectionRow}>
            <Text style={styles.sectionTitle}>
              {isCliente ? "PRÓXIMOS AGENDAMENTOS" : "PRÓXIMOS ATENDIMENTOS"}
            </Text>
            <Pressable onPress={() => router.push("/(app)/agendamentos")}>
              <Text style={styles.sectionLink}>Ver todos</Text>
            </Pressable>
          </View>
        </View>

        {agendamentosQ.isLoading ? (
          <ActivityIndicator style={{ marginTop: spacing.md }} color={colors.brandPrimary} />
        ) : upcoming.length === 0 ? (
          <View style={styles.empty} testID="home-empty">
            <Ionicons name="calendar-clear-outline" size={28} color={colors.muted} />
            <Text style={styles.emptyTitle}>
              {isCliente ? "Nenhum agendamento" : "Agenda livre"}
            </Text>
            <Text style={styles.emptyBody}>
              {isCliente
                ? "Encontre profissionais na aba Buscar e reserve seu horário."
                : "Adicione serviços em Serviços e compartilhe seu perfil."}
            </Text>
          </View>
        ) : (
          <View style={{ paddingHorizontal: spacing.xl }}>
            {upcoming.map((a) => (
              <Pressable
                key={a.agendamento_id}
                testID={`agenda-card-${a.agendamento_id}`}
                onPress={() => router.push(`/(app)/agendamento/${a.agendamento_id}`)}
                style={styles.card}
              >
                <View style={styles.cardRow}>
                  <View style={{ flex: 1 }}>
                    <Text style={styles.cardTitle}>
                      {isCliente ? a.profissional_nome : a.cliente_nome}
                    </Text>
                    <Text style={styles.cardMeta}>
                      {a.servico_nome} · {formatDateTime(a.horario_inicio)}
                    </Text>
                  </View>
                  <Text style={styles.cardValue}>{formatMoney(a.valor_total_centavos, a.moeda)}</Text>
                </View>
                <View style={styles.badge}>
                  <Text style={styles.badgeText}>
                    {CONFIRMACAO_LABELS[a.status_confirmacao].toUpperCase()}
                  </Text>
                </View>
              </Pressable>
            ))}
          </View>
        )}

        <Pressable
          testID="home-cta"
          onPress={() =>
            isCliente ? router.push("/(app)/search") : router.push("/(app)/servicos")
          }
          style={styles.cta}
        >
          <Ionicons
            name={isCliente ? "search-outline" : "add-circle-outline"}
            size={20}
            color={colors.onBrandPrimary}
          />
          <Text style={styles.ctaText}>
            {isCliente ? "Buscar profissionais" : "Gerenciar serviços"}
          </Text>
        </Pressable>
      </ScrollView>
    </View>
  );
}
