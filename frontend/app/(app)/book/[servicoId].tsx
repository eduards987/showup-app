// Cliente only: booking confirmation flow — creates the hold.

import Ionicons from "@react-native-vector-icons/ionicons";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useLocalSearchParams, useRouter } from "expo-router";
import { useMemo, useState } from "react";
import {
  ActivityIndicator,
  Pressable,
  ScrollView,
  Text,
  View,
} from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import { api } from "@/src/lib/api";
import { useAuth } from "@/src/lib/auth";
import { formatMoney } from "@/src/lib/format";
import { rotuloDoFuso } from "@/src/lib/fusos";
import { Agendamento, Servico } from "@/src/lib/types";
import { makeStyles, radius, spacing, useTheme } from "@/src/theme";
import { t } from "@/src/i18n/core";
import { useIdioma } from "@/src/i18n";

type Slot = { iso: string; day_label: string; time_label: string };

const useStyles = makeStyles((c) => ({
  root: { flex: 1, backgroundColor: c.surface },
  headerRow: { flexDirection: "row", alignItems: "center", paddingHorizontal: spacing.lg, paddingVertical: spacing.md, gap: spacing.sm },
  backBtn: { padding: spacing.sm },
  title: { fontSize: 24, fontWeight: "700", color: c.onSurface, paddingHorizontal: spacing.xl },
  subtitle: { fontSize: 14, color: c.muted, paddingHorizontal: spacing.xl, marginTop: 4, marginBottom: spacing.lg },
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
  cardTitle: { fontSize: 15, fontWeight: "700", color: c.onSurfaceSecondary },
  cardMeta: { fontSize: 13, color: c.muted },
  rowBetween: { flexDirection: "row", justifyContent: "space-between", alignItems: "center", marginTop: 6 },
  row: { flexDirection: "row", gap: spacing.sm, flexWrap: "wrap" },
  sectionLabel: { fontSize: 15, fontWeight: "700", color: c.onSurface, marginHorizontal: spacing.xl, marginTop: spacing.md, marginBottom: spacing.sm },
  chip: {
    height: 36,
    paddingHorizontal: spacing.md,
    borderRadius: radius.pill,
    backgroundColor: c.surfaceTertiary,
    borderWidth: 1,
    borderColor: c.border,
    alignItems: "center",
    justifyContent: "center",
    flexShrink: 0,
  },
  chipActive: { backgroundColor: c.brandPrimary, borderColor: c.brandPrimary },
  chipText: { color: c.onSurfaceTertiary, fontSize: 13, fontWeight: "600" },
  chipTextActive: { color: c.onBrandPrimary },
  breakdown: {
    marginHorizontal: spacing.xl,
    padding: spacing.lg,
    backgroundColor: c.brandTertiary,
    borderRadius: radius.lg,
    gap: spacing.sm,
  },
  breakdownTitle: { fontSize: 12, fontWeight: "800", color: c.onBrandTertiary, letterSpacing: 1 },
  breakdownRow: { flexDirection: "row", justifyContent: "space-between" },
  breakdownLabel: { color: c.onBrandTertiary, fontSize: 13 },
  breakdownValue: { color: c.onBrandTertiary, fontSize: 13, fontWeight: "700" },
  totalRow: {
    flexDirection: "row",
    justifyContent: "space-between",
    borderTopWidth: 1,
    borderTopColor: c.borderStrong,
    paddingTop: spacing.sm,
    marginTop: spacing.xs,
  },
  totalLabel: { color: c.onBrandTertiary, fontSize: 15, fontWeight: "700" },
  totalValue: { color: c.onBrandTertiary, fontSize: 18, fontWeight: "800" },
  ctaWrap: { padding: spacing.lg, backgroundColor: c.surface, borderTopWidth: 1, borderTopColor: c.border },
  cta: {
    height: 54,
    borderRadius: radius.md,
    backgroundColor: c.brandPrimary,
    alignItems: "center",
    justifyContent: "center",
    flexDirection: "row",
    gap: spacing.sm,
  },
  ctaDisabled: { opacity: 0.4 },
  ctaText: { color: c.onBrandPrimary, fontSize: 16, fontWeight: "700" },
  errorBox: {
    marginHorizontal: spacing.xl,
    padding: spacing.md,
    borderRadius: radius.md,
    backgroundColor: c.error,
    marginBottom: spacing.md,
  },
  errorText: { color: c.onError, fontSize: 13, fontWeight: "600" },
  emptySlots: {
    marginHorizontal: spacing.xl,
    padding: spacing.lg,
    borderRadius: radius.lg,
    backgroundColor: c.surfaceTertiary,
    alignItems: "center",
  },
  emptySlotsText: { color: c.onSurfaceTertiary, fontSize: 13, fontWeight: "600", textAlign: "center" },
}));

export default function Book() {
  useIdioma();
  const styles = useStyles();
  const { colors } = useTheme();
  const insets = useSafeAreaInsets();
  const router = useRouter();
  const qc = useQueryClient();
  const auth = useAuth();
  const { servicoId } = useLocalSearchParams<{ servicoId: string }>();

  const [selectedDay, setSelectedDay] = useState<string | null>(null);
  const [selectedIso, setSelectedIso] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);

  // Resolve service (search cache first, then fetch professionals list).
  const svcQ = useQuery({
    queryKey: ["servico-detail", servicoId],
    queryFn: async () => {
      const caches = qc.getQueriesData<{ servicos: Servico[]; user_id: string; timezone?: string }>({ queryKey: ["profissional"] });
      for (const [, data] of caches) {
        const found = data?.servicos.find((s) => s.servico_id === servicoId);
        if (found) return { servico: found, profissional_id: data!.user_id, timezone: data!.timezone ?? "America/Sao_Paulo" };
      }
      const profs = await api<{ user_id: string }[]>("/api/profissionais");
      for (const p of profs) {
        const detail = await api<{ servicos: Servico[]; user_id: string; timezone?: string }>(`/api/profissionais/${p.user_id}`);
        const s = detail.servicos.find((s) => s.servico_id === servicoId);
        if (s) return { servico: s, profissional_id: detail.user_id, timezone: detail.timezone ?? "America/Sao_Paulo" };
      }
      throw new Error(t("Serviço não encontrado"));
    },
    enabled: !!servicoId,
  });

  const slotsQ = useQuery({
    queryKey: ["slots", svcQ.data?.profissional_id, servicoId],
    queryFn: () =>
      api<Slot[]>(
        `/api/profissionais/${svcQ.data!.profissional_id}/slots?servico_id=${servicoId}`,
      ),
    enabled: !!svcQ.data,
  });

  const grouped = useMemo(() => {
    const map = new Map<string, Slot[]>();
    (slotsQ.data ?? []).forEach((sl) => {
      if (!map.has(sl.day_label)) map.set(sl.day_label, []);
      map.get(sl.day_label)!.push(sl);
    });
    return map;
  }, [slotsQ.data]);

  const days = Array.from(grouped.keys());
  const activeDay = selectedDay ?? days[0] ?? null;
  const daySlots = activeDay ? grouped.get(activeDay) ?? [] : [];

  const bookM = useMutation({
    mutationFn: (payload: { servico_id: string; horario_inicio: string }) =>
      api<Agendamento>("/api/agendamentos", {
        method: "POST",
        body: JSON.stringify(payload),
      }),
    onSuccess: (ag) => {
      qc.invalidateQueries({ queryKey: ["agendamentos"] });
      router.replace(`/(app)/agendamento/${ag.agendamento_id}`);
    },
    onError: (e: any) => setErr(e.message || t("Falha ao reservar")),
  });

  if (svcQ.isLoading) {
    return (
      <View style={[styles.root, { paddingTop: insets.top }]}>
        <ActivityIndicator style={{ marginTop: spacing.xxl }} color={colors.brandPrimary} />
      </View>
    );
  }
  if (!svcQ.data) return null;
  const s = svcQ.data.servico;
  const hasCard = auth.status === "authenticated" && auth.user.has_card;

  return (
    <View style={[styles.root, { paddingTop: insets.top }]}>
      <View style={styles.headerRow}>
        <Pressable onPress={() => router.back()} style={styles.backBtn}>
          <Ionicons name="chevron-back" size={24} color={colors.onSurface} />
        </Pressable>
      </View>
      <Text style={styles.title}>{t("Confirmar reserva")}</Text>
      <Text style={styles.subtitle}>{s.nome}</Text>

      <ScrollView contentContainerStyle={{ paddingBottom: spacing.xxl }}>
        <View style={styles.card}>
          <Text style={styles.cardTitle}>{s.nome}</Text>
          <Text style={styles.cardMeta}>{s.duracao_min}{" "}{t("min")}</Text>
          <View style={styles.rowBetween}>
            <Text style={styles.cardMeta}>{t("Valor")}</Text>
            <Text style={{ fontWeight: "700", color: colors.brandPrimary }}>
              {formatMoney(s.valor_centavos, s.moeda)}
            </Text>
          </View>
        </View>

        <Text style={styles.sectionLabel}>{t("Escolha o dia")}</Text>
        {svcQ.data?.timezone ? (
          <Text style={[styles.cardMeta, { paddingHorizontal: spacing.xl, marginBottom: spacing.sm }]}>{t("Horários no fuso de")}{" "}{rotuloDoFuso(svcQ.data.timezone)}
          </Text>
        ) : null}
        {slotsQ.isLoading ? (
          <ActivityIndicator color={colors.brandPrimary} />
        ) : days.length === 0 ? (
          <View style={styles.emptySlots}>
            <Text style={styles.emptySlotsText}>{t("Este profissional ainda não tem disponibilidade cadastrada.")}</Text>
          </View>
        ) : (
          <>
            <ScrollView
              horizontal
              showsHorizontalScrollIndicator={false}
              contentContainerStyle={{
                paddingHorizontal: spacing.xl,
                gap: spacing.sm,
                paddingBottom: spacing.md,
              }}
            >
              {days.map((d) => {
                const active = d === activeDay;
                return (
                  <Pressable
                    key={d}
                    testID={`day-${d}`}
                    onPress={() => {
                      setSelectedDay(d);
                      setSelectedIso(null);
                    }}
                    style={[styles.chip, active && styles.chipActive]}
                  >
                    <Text style={[styles.chipText, active && styles.chipTextActive]}>{d}</Text>
                  </Pressable>
                );
              })}
            </ScrollView>

            <Text style={styles.sectionLabel}>{t("Horários")}</Text>
            <View style={[styles.row, { paddingHorizontal: spacing.xl, marginBottom: spacing.lg }]}>
              {daySlots.map((sl) => {
                const active = sl.iso === selectedIso;
                return (
                  <Pressable
                    key={sl.iso}
                    testID={`slot-${sl.iso}`}
                    onPress={() => setSelectedIso(sl.iso)}
                    style={[styles.chip, active && styles.chipActive]}
                  >
                    <Text style={[styles.chipText, active && styles.chipTextActive]}>
                      {sl.time_label}
                    </Text>
                  </Pressable>
                );
              })}
            </View>
          </>
        )}

        <View style={styles.breakdown}>
          <Text style={styles.breakdownTitle}>{t("RESUMO DO HOLD")}</Text>
          <View style={styles.breakdownRow}>
            <Text style={styles.breakdownLabel}>{t("Valor do serviço")}</Text>
            <Text style={styles.breakdownValue}>{formatMoney(s.valor_centavos, s.moeda)}</Text>
          </View>
          <View style={styles.breakdownRow}>
            <Text style={styles.breakdownLabel}>{t("Taxa em caso de no-show")}</Text>
            <Text style={styles.breakdownValue}>{formatMoney(s.taxa_no_show_centavos, s.moeda)}</Text>
          </View>
          <View style={styles.totalRow}>
            <Text style={styles.totalLabel}>{t("Pré-autorização")}</Text>
            <Text style={styles.totalValue}>{formatMoney(s.valor_centavos, s.moeda)}</Text>
          </View>
        </View>

        {err ? (
          <View style={styles.errorBox}>
            <Text style={styles.errorText}>{err}</Text>
          </View>
        ) : null}

        {!hasCard ? (
          <Pressable
            testID="need-card"
            onPress={() => router.push("/(app)/perfil")}
            style={[styles.card, { alignItems: "center" }]}
          >
            <Text style={{ fontSize: 13, color: colors.warning, fontWeight: "700" }}>{t("Cadastre um cartão em Perfil antes de reservar.")}</Text>
          </Pressable>
        ) : null}
      </ScrollView>

      <View style={[styles.ctaWrap, { paddingBottom: insets.bottom + spacing.md }]}>
        <Pressable
          testID="confirm-hold"
          disabled={!selectedIso || !hasCard || bookM.isPending}
          onPress={() => {
            setErr(null);
            if (selectedIso) {
              bookM.mutate({ servico_id: s.servico_id, horario_inicio: selectedIso });
            }
          }}
          style={[styles.cta, (!selectedIso || !hasCard || bookM.isPending) && styles.ctaDisabled]}
        >
          {bookM.isPending ? (
            <ActivityIndicator color={colors.onBrandPrimary} />
          ) : (
            <>
              <Ionicons name="lock-closed" size={18} color={colors.onBrandPrimary} />
              <Text style={styles.ctaText}>{t("Pré-autorizar")}{" "}{formatMoney(s.valor_centavos, s.moeda)}
              </Text>
            </>
          )}
        </Pressable>
      </View>
    </View>
  );
}
