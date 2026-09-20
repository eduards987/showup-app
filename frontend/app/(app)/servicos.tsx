// Profissional only: manage services.

import Ionicons from "@react-native-vector-icons/ionicons";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useRouter } from "expo-router";
import { ActivityIndicator, FlatList, Pressable, Text, View } from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import { api } from "@/src/lib/api";
import { formatMoney } from "@/src/lib/format";
import { Servico } from "@/src/lib/types";
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
  title: { fontSize: 24, fontWeight: "700", color: c.onSurface },
  addBtn: {
    height: 40,
    paddingHorizontal: spacing.md,
    backgroundColor: c.brandPrimary,
    borderRadius: radius.md,
    flexDirection: "row",
    alignItems: "center",
    gap: 6,
  },
  addText: { color: c.onBrandPrimary, fontWeight: "700", fontSize: 13 },
  item: {
    marginHorizontal: spacing.xl,
    marginBottom: spacing.md,
    padding: spacing.lg,
    backgroundColor: c.surfaceSecondary,
    borderRadius: radius.lg,
    borderWidth: 1,
    borderColor: c.border,
  },
  row: { flexDirection: "row", justifyContent: "space-between", alignItems: "flex-start" },
  name: { fontSize: 16, fontWeight: "700", color: c.onSurfaceSecondary, flex: 1 },
  value: { fontSize: 16, fontWeight: "700", color: c.brandPrimary },
  meta: { fontSize: 13, color: c.muted, marginTop: 4 },
  desc: { fontSize: 13, color: c.onSurfaceTertiary, marginTop: spacing.sm, lineHeight: 18 },
  del: {
    marginTop: spacing.sm,
    alignSelf: "flex-start",
    flexDirection: "row",
    alignItems: "center",
    gap: 4,
  },
  delText: { color: c.error, fontSize: 13, fontWeight: "600" },
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
}));

export default function Servicos() {
  const styles = useStyles();
  const { colors } = useTheme();
  const insets = useSafeAreaInsets();
  const router = useRouter();
  const qc = useQueryClient();

  const q = useQuery({
    queryKey: ["meus-servicos"],
    queryFn: () => api<Servico[]>("/api/servicos"),
  });

  const delM = useMutation({
    mutationFn: (id: string) => api(`/api/servicos/${id}`, { method: "DELETE" }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["meus-servicos"] }),
  });

  return (
    <View style={[styles.root, { paddingTop: insets.top }]}>
      <View style={styles.header}>
        <Text style={styles.title}>Meus serviços</Text>
        <Pressable
          testID="add-servico"
          onPress={() => router.push("/(app)/novo-servico")}
          style={styles.addBtn}
        >
          <Ionicons name="add" size={18} color={colors.onBrandPrimary} />
          <Text style={styles.addText}>Novo</Text>
        </Pressable>
      </View>
      {q.isLoading ? (
        <ActivityIndicator style={{ marginTop: spacing.xl }} color={colors.brandPrimary} />
      ) : (q.data?.length ?? 0) === 0 ? (
        <View style={styles.empty}>
          <Ionicons name="briefcase-outline" size={28} color={colors.muted} />
          <Text style={styles.emptyTitle}>Nenhum serviço</Text>
          <Text style={styles.emptyBody}>
            Cadastre um serviço para começar a receber reservas com garantia.
          </Text>
        </View>
      ) : (
        <FlatList
          data={q.data ?? []}
          keyExtractor={(s) => s.servico_id}
          contentContainerStyle={{ paddingBottom: insets.bottom + spacing.xxl }}
          renderItem={({ item }) => (
            <View style={styles.item} testID={`servico-${item.servico_id}`}>
              <View style={styles.row}>
                <Text style={styles.name}>{item.nome}</Text>
                <Text style={styles.value}>{formatMoney(item.valor_centavos, item.moeda)}</Text>
              </View>
              <Text style={styles.meta}>
                {item.duracao_min} min · Taxa no-show {formatMoney(item.taxa_no_show_centavos, item.moeda)}
              </Text>
              {item.descricao ? <Text style={styles.desc}>{item.descricao}</Text> : null}
              <Pressable
                testID={`del-${item.servico_id}`}
                onPress={() => delM.mutate(item.servico_id)}
                style={styles.del}
              >
                <Ionicons name="trash-outline" size={14} color={colors.error} />
                <Text style={styles.delText}>Remover</Text>
              </Pressable>
            </View>
          )}
        />
      )}
    </View>
  );
}
