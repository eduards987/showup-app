// Cliente only: professional profile + services list.

import Ionicons from "@react-native-vector-icons/ionicons";
import { useQuery } from "@tanstack/react-query";
import { useLocalSearchParams, useRouter } from "expo-router";
import {
  ActivityIndicator,
  Pressable,
  ScrollView,
  Text,
  View,
} from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import { api } from "@/src/lib/api";
import { formatMoney } from "@/src/lib/format";
import { ProfissionalDetail } from "@/src/lib/types";
import { makeStyles, radius, spacing, useTheme } from "@/src/theme";

const useStyles = makeStyles((c) => ({
  root: { flex: 1, backgroundColor: c.surface },
  headerRow: {
    flexDirection: "row",
    alignItems: "center",
    paddingHorizontal: spacing.lg,
    paddingVertical: spacing.md,
    gap: spacing.sm,
  },
  backBtn: { padding: spacing.sm },
  hero: { alignItems: "center", paddingTop: spacing.lg, paddingBottom: spacing.xl },
  avatar: {
    width: 88,
    height: 88,
    borderRadius: radius.pill,
    backgroundColor: c.brandTertiary,
    alignItems: "center",
    justifyContent: "center",
  },
  avatarText: { color: c.brandPrimary, fontWeight: "800", fontSize: 32 },
  name: { fontSize: 22, fontWeight: "700", color: c.onSurface, marginTop: spacing.md },
  sub: { fontSize: 13, color: c.muted, marginTop: 4 },
  sectionTitle: {
    fontSize: 12,
    fontWeight: "800",
    color: c.muted,
    letterSpacing: 1,
    marginHorizontal: spacing.xl,
    marginBottom: spacing.md,
    marginTop: spacing.xl,
  },
  servicoCard: {
    marginHorizontal: spacing.xl,
    marginBottom: spacing.md,
    padding: spacing.lg,
    backgroundColor: c.surfaceSecondary,
    borderRadius: radius.lg,
    borderWidth: 1,
    borderColor: c.border,
  },
  servicoRow: { flexDirection: "row", justifyContent: "space-between", alignItems: "flex-start" },
  servicoName: { fontSize: 16, fontWeight: "700", color: c.onSurfaceSecondary, flex: 1 },
  servicoValue: { fontSize: 16, fontWeight: "700", color: c.brandPrimary },
  servicoMeta: { fontSize: 13, color: c.muted, marginTop: 4 },
  servicoDesc: { fontSize: 13, color: c.onSurfaceTertiary, marginTop: spacing.sm, lineHeight: 18 },
  noShow: {
    marginTop: spacing.sm,
    fontSize: 12,
    color: c.warning,
    fontWeight: "600",
  },
}));

export default function ProfissionalDetalhe() {
  const styles = useStyles();
  const { colors } = useTheme();
  const insets = useSafeAreaInsets();
  const router = useRouter();
  const { id } = useLocalSearchParams<{ id: string }>();

  const q = useQuery({
    queryKey: ["profissional", id],
    queryFn: () => api<ProfissionalDetail>(`/api/profissionais/${id}`),
    enabled: !!id,
  });

  if (q.isLoading) {
    return (
      <View style={[styles.root, { paddingTop: insets.top }]}>
        <ActivityIndicator style={{ marginTop: spacing.xxl }} color={colors.brandPrimary} />
      </View>
    );
  }
  if (!q.data) return null;

  const initials = q.data.name.split(" ").map((s) => s[0]).slice(0, 2).join("").toUpperCase();

  return (
    <View style={[styles.root, { paddingTop: insets.top }]}>
      <View style={styles.headerRow}>
        <Pressable testID="back-btn" onPress={() => router.back()} style={styles.backBtn}>
          <Ionicons name="chevron-back" size={24} color={colors.onSurface} />
        </Pressable>
      </View>
      <ScrollView contentContainerStyle={{ paddingBottom: spacing.xxl }}>
        <View style={styles.hero}>
          <View style={styles.avatar}>
            <Text style={styles.avatarText}>{initials}</Text>
          </View>
          <Text style={styles.name}>{q.data.name}</Text>
          <Text style={styles.sub}>{q.data.servicos.length} serviço(s)</Text>
        </View>

        <Text style={styles.sectionTitle}>SERVIÇOS DISPONÍVEIS</Text>

        {q.data.servicos.map((s) => (
          <Pressable
            key={s.servico_id}
            testID={`servico-${s.servico_id}`}
            onPress={() => router.push(`/(app)/book/${s.servico_id}`)}
            style={styles.servicoCard}
          >
            <View style={styles.servicoRow}>
              <Text style={styles.servicoName}>{s.nome}</Text>
              <Text style={styles.servicoValue}>{formatMoney(s.valor_centavos, s.moeda)}</Text>
            </View>
            <Text style={styles.servicoMeta}>{s.duracao_min} min</Text>
            {s.descricao ? <Text style={styles.servicoDesc}>{s.descricao}</Text> : null}
            <Text style={styles.noShow}>
              Taxa de no-show: {formatMoney(s.taxa_no_show_centavos, s.moeda)}
            </Text>
          </Pressable>
        ))}
      </ScrollView>
    </View>
  );
}
