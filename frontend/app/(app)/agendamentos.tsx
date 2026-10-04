// All appointments (list) — role-aware.

import Ionicons from "@react-native-vector-icons/ionicons";
import { useQuery } from "@tanstack/react-query";
import { useRouter } from "expo-router";
import { FlatList, Pressable, Text, View } from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import { api } from "@/src/lib/api";
import { useAuth } from "@/src/lib/auth";
import {
  CONFIRMACAO_LABELS,
  HOLD_STATUS_LABELS,
  formatMoney,
  formatDateTime,
} from "@/src/lib/format";
import { Agendamento } from "@/src/lib/types";
import { makeStyles, radius, spacing, useTheme } from "@/src/theme";

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
}));

const KIND_COLORS = {
  info: { bg: "#E4EFF6", fg: "#255170" },
  success: { bg: "#DCF7E3", fg: "#1B7C34" },
  warning: { bg: "#FFECD1", fg: "#8A5A00" },
  error: { bg: "#FFE0DE", fg: "#8A1F1A" },
};

export default function Agendamentos() {
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

  return (
    <View style={[styles.root, { paddingTop: insets.top }]}>
      <View style={styles.header}>
        <Text style={styles.title}>{isCliente ? "Minhas reservas" : "Meus atendimentos"}</Text>
      </View>
      {(q.data?.length ?? 0) === 0 ? (
        <View style={styles.empty}>
          <Ionicons name="calendar-outline" size={28} color={colors.muted} />
          <Text style={styles.emptyTitle}>Nada aqui ainda</Text>
          <Text style={styles.emptyBody}>Suas reservas aparecerão nesta lista.</Text>
        </View>
      ) : (
        <FlatList
          data={q.data ?? []}
          keyExtractor={(a) => a.agendamento_id}
          onRefresh={() => q.refetch()}
          refreshing={q.isFetching}
          contentContainerStyle={{ paddingBottom: insets.bottom + spacing.xxl }}
          renderItem={({ item }) => {
            const holdMeta = HOLD_STATUS_LABELS[item.hold_status] ?? { label: item.hold_status, kind: "info" };
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
                      {CONFIRMACAO_LABELS[item.status_confirmacao].toUpperCase()}
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
