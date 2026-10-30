// All appointments (list) — role-aware.

import Ionicons from "@react-native-vector-icons/ionicons";
import { useQuery } from "@tanstack/react-query";
import { useRouter } from "expo-router";
import { Pressable, SectionList, Text, View } from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import { Carregando, ErroAoCarregar } from "@/src/components/estado-consulta";
import { api } from "@/src/lib/api";
import { estadoDaConsulta, separarAgendamentos } from "@/src/lib/estado-consulta";
import { useAgora } from "@/src/lib/use-agora";
import { useAuth } from "@/src/lib/auth";
import {
  infoHold,
  rotuloConfirmacao,
  formatMoney,
  formatDateTime,
} from "@/src/lib/format";
import { Agendamento } from "@/src/lib/types";
import { makeStyles, radius, spacing, useTheme } from "@/src/theme";
import { t } from "@/src/i18n/core";
import { useIdioma } from "@/src/i18n";

const useStyles = makeStyles((c) => ({
  root: { flex: 1, backgroundColor: c.surface },
  header: { paddingHorizontal: spacing.xl, paddingVertical: spacing.lg },
  title: { fontSize: 24, fontWeight: "700", color: c.onSurface },
  card: {
    marginHorizontal: spacing.xl,
    marginBottom: spacing.md,
    padding: spacing.lg,
    backgroundColor: c.surfaceSecondary,
    borderRadius: radius.lg,
    borderWidth: 1,
    borderColor: c.border,
    gap: 6,
  },
  row: { flexDirection: "row", justifyContent: "space-between", alignItems: "flex-start" },
  cardTitle: { fontSize: 16, fontWeight: "700", color: c.onSurfaceSecondary },
  cardMeta: { fontSize: 13, color: c.muted },
  cardValue: { fontSize: 15, fontWeight: "700", color: c.brandPrimary },
  badgeRow: { flexDirection: "row", gap: spacing.xs, marginTop: spacing.xs, flexWrap: "wrap" },
  badge: {
    paddingHorizontal: spacing.sm,
    paddingVertical: 2,
    borderRadius: radius.pill,
  },
  badgeText: { fontSize: 11, fontWeight: "700" },
  empty: {
    marginHorizontal: spacing.xl,
    padding: spacing.xl,
    backgroundColor: c.surfaceTertiary,
    borderRadius: radius.lg,
    alignItems: "center",
    gap: spacing.xs,
    marginTop: spacing.md,
  },
  emptyTitle: { fontSize: 15, fontWeight: "700", color: c.onSurfaceTertiary },
  emptyBody: { fontSize: 13, color: c.muted, textAlign: "center" },
  secao: { fontSize: 12, fontWeight: "700", color: c.muted, letterSpacing: 1, marginHorizontal: spacing.xl, marginTop: spacing.md, marginBottom: spacing.sm },
}));

const KIND_COLORS = {
  info: { bg: "#E4EFF6", fg: "#255170" },
  success: { bg: "#DCF7E3", fg: "#1B7C34" },
  warning: { bg: "#FFECD1", fg: "#8A5A00" },
  error: { bg: "#FFE0DE", fg: "#8A1F1A" },
};

export default function Agendamentos() {
  useIdioma();
  const styles = useStyles();
  const { colors } = useTheme();
  const insets = useSafeAreaInsets();
  const router = useRouter();
  const auth = useAuth();
  const isCliente = auth.status === "authenticated" && auth.user.role === "cliente";

  const q = useQuery({
    queryKey: ["agendamentos"],
    queryFn: () => api<Agendamento[]>("/api/agendamentos"),
  });
  const agora = useAgora();
  const estado = estadoDaConsulta(q);
  const { proximos, anteriores } = separarAgendamentos(q.data ?? [], agora);
  const secoes = [
    { titulo: t("PRÓXIMOS"), data: proximos },
    { titulo: t("ANTERIORES"), data: anteriores },
  ].filter((sec) => sec.data.length > 0);

  return (
    <View style={[styles.root, { paddingTop: insets.top }]}>
      <View style={styles.header}>
        <Text style={styles.title}>{isCliente ? t("Minhas reservas") : t("Meus atendimentos")}</Text>
      </View>
      {estado === "carregando" ? (
        <Carregando />
      ) : estado === "erro" ? (
        <ErroAoCarregar onTentar={() => q.refetch()} testID="agendamentos-erro" />
      ) : estado === "vazio" ? (
        <View style={styles.empty}>
          <Ionicons name="calendar-outline" size={28} color={colors.muted} />
          <Text style={styles.emptyTitle}>{t("Nada aqui ainda")}</Text>
          <Text style={styles.emptyBody}>{t("Suas reservas aparecerão nesta lista.")}</Text>
        </View>
      ) : (
        <SectionList
          sections={secoes}
          stickySectionHeadersEnabled={false}
          renderSectionHeader={({ section }) => <Text style={styles.secao}>{section.titulo}</Text>}
          keyExtractor={(a) => a.agendamento_id}
          onRefresh={() => q.refetch()}
          refreshing={q.isFetching}
          contentContainerStyle={{ paddingBottom: insets.bottom + spacing.xxl }}
          renderItem={({ item }) => {
            const holdMeta = infoHold(item.hold_status);
            const holdColor = KIND_COLORS[holdMeta.kind];
            return (
              <Pressable
                testID={`agd-${item.agendamento_id}`}
                onPress={() => router.push(`/(app)/agendamento/${item.agendamento_id}`)}
                style={styles.card}
              >
                <View style={styles.row}>
                  <View style={{ flex: 1 }}>
                    <Text style={styles.cardTitle}>
                      {isCliente ? item.profissional_nome : item.cliente_nome}
                    </Text>
                    <Text style={styles.cardMeta}>
                      {item.servico_nome} · {formatDateTime(item.horario_inicio, auth.user?.timezone)}
                    </Text>
                  </View>
                  <Text style={styles.cardValue}>{formatMoney(item.valor_total_centavos, item.moeda)}</Text>
                </View>
                <View style={styles.badgeRow}>
                  <View style={[styles.badge, { backgroundColor: holdColor.bg }]}>
                    <Text style={[styles.badgeText, { color: holdColor.fg }]}>
                      {holdMeta.label.toUpperCase()}
                    </Text>
                  </View>
                  <View style={[styles.badge, { backgroundColor: colors.surfaceTertiary }]}>
                    <Text style={[styles.badgeText, { color: colors.onSurfaceTertiary }]}>
                      {rotuloConfirmacao(item.status_confirmacao).toUpperCase()}
                    </Text>
                  </View>
                </View>
              </Pressable>
            );
          }}
        />
      )}
    </View>
  );
}
