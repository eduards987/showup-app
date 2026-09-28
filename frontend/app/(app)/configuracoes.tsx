// Profissional only: manage weekly availability + categorias.

import Ionicons from "@react-native-vector-icons/ionicons";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useRouter } from "expo-router";
import { useEffect, useState } from "react";
import {
  ActivityIndicator,
  Alert,
  Pressable,
  ScrollView,
  Text,
  TextInput,
  View,
} from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import { api } from "@/src/lib/api";
import { useAuth } from "@/src/lib/auth";
import { TIMEZONE_LABELS } from "@/src/lib/format";
import { openExternalCheckout } from "@/src/lib/open-external-checkout";
import { makeStyles, radius, spacing, useTheme } from "@/src/theme";

type Slot = { weekday: number; hora_inicio: string; hora_fim: string };

const WEEKDAYS = ["Seg", "Ter", "Qua", "Qui", "Sex", "Sáb", "Dom"];
const CATEGORIAS_LABELS: Record<string, string> = {
  fitness: "Fitness",
  terapia: "Terapia",
  consultoria: "Consultoria",
  estetica: "Estética",
  coaching: "Coaching",
  nutricao: "Nutrição",
};

const useStyles = makeStyles((c) => ({
  root: { flex: 1, backgroundColor: c.surface },
  headerRow: { flexDirection: "row", alignItems: "center", paddingHorizontal: spacing.lg, paddingVertical: spacing.md },
  backBtn: { padding: spacing.sm },
  title: { fontSize: 24, fontWeight: "700", color: c.onSurface, paddingHorizontal: spacing.xl },
  subtitle: { fontSize: 14, color: c.muted, paddingHorizontal: spacing.xl, marginTop: 4, marginBottom: spacing.lg },
  sectionTitle: {
    fontSize: 12,
    fontWeight: "800",
    color: c.muted,
    letterSpacing: 1,
    marginHorizontal: spacing.xl,
    marginTop: spacing.lg,
    marginBottom: spacing.md,
  },
  chipsRow: {
    flexDirection: "row",
    flexWrap: "wrap",
    gap: spacing.sm,
    paddingHorizontal: spacing.xl,
    marginBottom: spacing.md,
  },
  chip: {
    paddingHorizontal: spacing.md,
    paddingVertical: spacing.sm,
    borderRadius: radius.pill,
    backgroundColor: c.surfaceTertiary,
    borderWidth: 1,
    borderColor: c.border,
  },
  chipActive: { backgroundColor: c.brandPrimary, borderColor: c.brandPrimary },
  chipText: { color: c.onSurfaceTertiary, fontSize: 13, fontWeight: "600" },
  chipTextActive: { color: c.onBrandPrimary },
  slotRow: {
    marginHorizontal: spacing.xl,
    marginBottom: spacing.sm,
    padding: spacing.md,
    borderRadius: radius.md,
    backgroundColor: c.surfaceSecondary,
    borderWidth: 1,
    borderColor: c.border,
    flexDirection: "row",
    alignItems: "center",
    gap: spacing.sm,
  },
  slotDay: {
    width: 52,
    fontSize: 14,
    fontWeight: "700",
    color: c.onSurfaceSecondary,
  },
  timeInput: {
    flex: 1,
    height: 40,
    borderRadius: radius.md,
    backgroundColor: c.surface,
    borderWidth: 1,
    borderColor: c.border,
    paddingHorizontal: spacing.sm,
    fontSize: 14,
    color: c.onSurfaceSecondary,
    textAlign: "center",
  },
  trash: { padding: spacing.sm },
  addSlotBtn: {
    marginHorizontal: spacing.xl,
    marginTop: spacing.sm,
    height: 44,
    borderRadius: radius.md,
    borderWidth: 1,
    borderColor: c.brandPrimary,
    borderStyle: "dashed",
    alignItems: "center",
    justifyContent: "center",
    flexDirection: "row",
    gap: spacing.sm,
  },
  addSlotText: { color: c.brandPrimary, fontSize: 13, fontWeight: "700" },
  ctaWrap: { padding: spacing.lg, borderTopWidth: 1, borderTopColor: c.border, backgroundColor: c.surface },
  cta: {
    height: 52,
    borderRadius: radius.md,
    backgroundColor: c.brandPrimary,
    alignItems: "center",
    justifyContent: "center",
  },
  ctaDisabled: { opacity: 0.4 },
  ctaText: { color: c.onBrandPrimary, fontSize: 15, fontWeight: "700" },
  saved: {
    marginHorizontal: spacing.xl,
    padding: spacing.md,
    borderRadius: radius.md,
    backgroundColor: c.brandTertiary,
    marginBottom: spacing.md,
  },
  savedText: { fontSize: 13, color: c.onBrandTertiary, fontWeight: "600" },
  connectCard: {
    marginHorizontal: spacing.xl,
    padding: spacing.lg,
    backgroundColor: c.surfaceSecondary,
    borderRadius: radius.lg,
    borderWidth: 1,
    borderColor: c.border,
    gap: spacing.sm,
  },
  connectRow: { flexDirection: "row", alignItems: "center", gap: spacing.sm },
  connectTitle: { fontSize: 14, fontWeight: "700", color: c.onSurfaceSecondary },
  connectBody: { fontSize: 13, color: c.muted, lineHeight: 18 },
  dangerRow: { flexDirection: "row", alignItems: "center", justifyContent: "center", gap: spacing.sm },
  dangerText: { fontSize: 15, fontWeight: "600", color: c.error },
  dangerNote: { fontSize: 12, color: c.muted, lineHeight: 17, marginTop: spacing.sm, textAlign: "center" },
  connectBtn: {
    marginTop: spacing.sm,
    height: 42,
    borderRadius: radius.md,
    backgroundColor: c.brand,
    alignItems: "center",
    justifyContent: "center",
    flexDirection: "row",
    gap: 6,
  },
  connectBtnText: { color: c.onBrand, fontSize: 13, fontWeight: "700" },
}));

export default function Configuracoes() {
  const styles = useStyles();
  const { colors } = useTheme();
  const insets = useSafeAreaInsets();
  const router = useRouter();
  const auth = useAuth();
  const qc = useQueryClient();

  const excluirContaM = useMutation({
    mutationFn: () => api("/api/me", { method: "DELETE" }),
    onSuccess: () => {
      auth.signOut();
    },
  });

  const confirmarExclusao = () => {
    Alert.alert(
      "Excluir sua conta",
      "Isso é permanente — seus dados pessoais serão apagados e você não vai conseguir desfazer isso depois. Tem certeza?",
      [
        { text: "Cancelar", style: "cancel" },
        {
          text: "Excluir conta",
          style: "destructive",
          onPress: () => {
            excluirContaM.mutate(undefined, {
              onError: (e: any) => {
                Alert.alert("Não foi possível excluir", e?.message ?? "Tente novamente.");
              },
            });
          },
        },
      ],
    );
  };

  const [selectedCats, setSelectedCats] = useState<string[]>(
    auth.status === "authenticated" ? (auth.user.categorias ?? []) : [],
  );
  const [selectedTz, setSelectedTz] = useState<string>(
    auth.status === "authenticated" ? (auth.user.timezone ?? "America/Sao_Paulo") : "America/Sao_Paulo",
  );
  const [selectedMoeda, setSelectedMoeda] = useState<string>(
    auth.status === "authenticated" ? (auth.user.moeda ?? "BRL") : "BRL",
  );
  const [slots, setSlots] = useState<Slot[]>([]);
  const [saved, setSaved] = useState(false);

  const catsQ = useQuery({
    queryKey: ["categorias-list"],
    queryFn: () => api<{ categorias: string[] }>("/api/categorias"),
  });

  const timezonesQ = useQuery({
    queryKey: ["timezones-list"],
    queryFn: () => api<{ timezones: string[] }>("/api/timezones"),
  });

  const moedasQ = useQuery({
    queryKey: ["moedas-list"],
    queryFn: () => api<{ moedas: string[] }>("/api/moedas"),
  });

  const dispQ = useQuery({
    queryKey: ["me-disp"],
    queryFn: async () => {
      if (auth.status !== "authenticated") return { slots: [] };
      return api<{ slots: Slot[] }>(
        `/api/profissionais/${auth.user.user_id}/disponibilidade`,
      );
    },
    enabled: auth.status === "authenticated",
  });
  useEffect(() => {
    if (dispQ.data?.slots) setSlots(dispQ.data.slots);
  }, [dispQ.data]);

  const connectQ = useQuery({
    queryKey: ["connect-status"],
    queryFn: () => api<{ account_id?: string; charges_enabled: boolean; payouts_enabled: boolean; details_submitted: boolean }>("/api/me/connect"),
    enabled: auth.status === "authenticated" && auth.user.role === "profissional",
  });

  const saveCatsM = useMutation({
    mutationFn: (categorias: string[]) =>
      api("/api/me/categorias", {
        method: "PUT",
        body: JSON.stringify({ categorias }),
      }),
    onSuccess: () => {
      auth.refresh();
      setSaved(true);
      setTimeout(() => setSaved(false), 2000);
    },
  });

  const saveTzM = useMutation({
    mutationFn: (timezone: string) =>
      api("/api/me/timezone", {
        method: "PUT",
        body: JSON.stringify({ timezone }),
      }),
    onSuccess: () => {
      auth.refresh();
      // Os horários já cadastrados em disponibilidade não mudam de valor,
      // mas o instante UTC que eles representam muda — os slots calculados
      // pro cliente vão refletir o novo fuso na próxima consulta.
      setSaved(true);
      setTimeout(() => setSaved(false), 2000);
    },
  });

  const saveMoedaM = useMutation({
    mutationFn: (moeda: string) =>
      api("/api/me/moeda", {
        method: "PUT",
        body: JSON.stringify({ moeda }),
      }),
    onSuccess: () => {
      auth.refresh();
      // Só afeta serviços criados DAQUI PRA FRENTE — os que já existem
      // guardam a moeda que tinham no momento da criação (ver PRD).
      setSaved(true);
      setTimeout(() => setSaved(false), 2000);
    },
  });

  const saveDispM = useMutation({
    mutationFn: (list: Slot[]) =>
      api("/api/me/disponibilidade", {
        method: "PUT",
        body: JSON.stringify({ slots: list }),
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["me-disp"] });
      setSaved(true);
      setTimeout(() => setSaved(false), 2000);
    },
  });

  const connectM = useMutation({
    mutationFn: () =>
      openExternalCheckout("/(app)/perfil", (returnUrl, refreshUrl) =>
        api<{ url: string }>(
          `/api/me/connect/onboarding?return_url=${encodeURIComponent(returnUrl)}&refresh_url=${encodeURIComponent(refreshUrl)}`,
          { method: "POST" },
        ).then((r) => r.url),
      ),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["connect-status"] }),
  });

  const cats = catsQ.data?.categorias ?? [];
  const toggleCat = (c: string) => {
    setSelectedCats((prev) =>
      prev.includes(c) ? prev.filter((x) => x !== c) : prev.length >= 3 ? prev : [...prev, c],
    );
  };

  const addSlot = () =>
    setSlots((s) => [...s, { weekday: 0, hora_inicio: "09:00", hora_fim: "18:00" }]);
  const updateSlot = (i: number, patch: Partial<Slot>) =>
    setSlots((s) => s.map((x, idx) => (idx === i ? { ...x, ...patch } : x)));
  const rmSlot = (i: number) => setSlots((s) => s.filter((_, idx) => idx !== i));

  return (
    <View style={[styles.root, { paddingTop: insets.top }]}>
      <View style={styles.headerRow}>
        <Pressable onPress={() => router.back()} style={styles.backBtn}>
          <Ionicons name="chevron-back" size={24} color={colors.onSurface} />
        </Pressable>
      </View>
      <Text style={styles.title}>Meu perfil profissional</Text>
      <Text style={styles.subtitle}>
        Defina categorias, disponibilidade e ative repasses automáticos.
      </Text>

      <ScrollView contentContainerStyle={{ paddingBottom: spacing.xxl }}>
        {saved ? (
          <View style={styles.saved}>
            <Text style={styles.savedText}>Salvo ✓</Text>
          </View>
        ) : null}

        <Text style={styles.sectionTitle}>CATEGORIAS (até 3)</Text>
        <View style={styles.chipsRow}>
          {cats.map((c) => {
            const active = selectedCats.includes(c);
            return (
              <Pressable
                key={c}
                testID={`cat-${c}`}
                onPress={() => toggleCat(c)}
                style={[styles.chip, active && styles.chipActive]}
              >
                <Text style={[styles.chipText, active && styles.chipTextActive]}>
                  {CATEGORIAS_LABELS[c] ?? c}
                </Text>
              </Pressable>
            );
          })}
        </View>
        <View style={{ paddingHorizontal: spacing.xl, marginBottom: spacing.md }}>
          <Pressable
            testID="save-cats"
            disabled={selectedCats.length === 0 || saveCatsM.isPending}
            onPress={() => saveCatsM.mutate(selectedCats)}
            style={[
              styles.cta,
              { height: 44 },
              (selectedCats.length === 0 || saveCatsM.isPending) && styles.ctaDisabled,
            ]}
          >
            {saveCatsM.isPending ? (
              <ActivityIndicator color={colors.onBrandPrimary} />
            ) : (
              <Text style={styles.ctaText}>Salvar categorias</Text>
            )}
          </Pressable>
        </View>

        <Text style={styles.sectionTitle}>FUSO HORÁRIO</Text>
        <Text style={[styles.connectBody, { paddingHorizontal: spacing.xl, marginBottom: spacing.sm }]}>
          Os horários que você cadastra em disponibilidade usam este fuso como referência.
        </Text>
        <View style={styles.chipsRow}>
          {(timezonesQ.data?.timezones ?? []).map((tz) => {
            const active = selectedTz === tz;
            return (
              <Pressable
                key={tz}
                testID={`tz-${tz}`}
                onPress={() => setSelectedTz(tz)}
                style={[styles.chip, active && styles.chipActive]}
              >
                <Text style={[styles.chipText, active && styles.chipTextActive]}>
                  {TIMEZONE_LABELS[tz] ?? tz}
                </Text>
              </Pressable>
            );
          })}
        </View>
        <View style={{ paddingHorizontal: spacing.xl, marginBottom: spacing.md }}>
          <Pressable
            testID="save-tz"
            disabled={saveTzM.isPending}
            onPress={() => saveTzM.mutate(selectedTz)}
            style={[styles.cta, { height: 44 }, saveTzM.isPending && styles.ctaDisabled]}
          >
            {saveTzM.isPending ? (
              <ActivityIndicator color={colors.onBrandPrimary} />
            ) : (
              <Text style={styles.ctaText}>Salvar fuso horário</Text>
            )}
          </Pressable>
        </View>

        <Text style={styles.sectionTitle}>MOEDA</Text>
        <Text style={[styles.connectBody, { paddingHorizontal: spacing.xl, marginBottom: spacing.sm }]}>
          Moeda em que você recebe. Só afeta serviços criados a partir de agora.
        </Text>
        <View style={styles.chipsRow}>
          {(moedasQ.data?.moedas ?? []).map((m) => {
            const active = selectedMoeda === m;
            return (
              <Pressable
                key={m}
                testID={`moeda-${m}`}
                onPress={() => setSelectedMoeda(m)}
                style={[styles.chip, active && styles.chipActive]}
              >
                <Text style={[styles.chipText, active && styles.chipTextActive]}>{m}</Text>
              </Pressable>
            );
          })}
        </View>
        <View style={{ paddingHorizontal: spacing.xl, marginBottom: spacing.md }}>
          <Pressable
            testID="save-moeda"
            disabled={saveMoedaM.isPending}
            onPress={() => saveMoedaM.mutate(selectedMoeda)}
            style={[styles.cta, { height: 44 }, saveMoedaM.isPending && styles.ctaDisabled]}
          >
            {saveMoedaM.isPending ? (
              <ActivityIndicator color={colors.onBrandPrimary} />
            ) : (
              <Text style={styles.ctaText}>Salvar moeda</Text>
            )}
          </Pressable>
        </View>

        <Text style={styles.sectionTitle}>DISPONIBILIDADE SEMANAL</Text>
        {slots.length === 0 ? (
          <Text style={[styles.connectBody, { paddingHorizontal: spacing.xl, marginBottom: spacing.sm }]}>
            Nenhum horário. Clientes não poderão reservar até você adicionar.
          </Text>
        ) : null}
        {slots.map((s, i) => (
          <View key={i} style={styles.slotRow}>
            <Pressable
              testID={`slot-day-${i}`}
              onPress={() => updateSlot(i, { weekday: (s.weekday + 1) % 7 })}
              style={{ minWidth: 52 }}
            >
              <Text style={styles.slotDay}>{WEEKDAYS[s.weekday]}</Text>
            </Pressable>
            <TextInput
              testID={`slot-start-${i}`}
              style={styles.timeInput}
              value={s.hora_inicio}
              onChangeText={(t) => updateSlot(i, { hora_inicio: t })}
              placeholder="09:00"
              placeholderTextColor={colors.muted}
            />
            <Text style={{ color: colors.muted }}>→</Text>
            <TextInput
              testID={`slot-end-${i}`}
              style={styles.timeInput}
              value={s.hora_fim}
              onChangeText={(t) => updateSlot(i, { hora_fim: t })}
              placeholder="18:00"
              placeholderTextColor={colors.muted}
            />
            <Pressable testID={`slot-del-${i}`} onPress={() => rmSlot(i)} style={styles.trash}>
              <Ionicons name="trash-outline" size={18} color={colors.error} />
            </Pressable>
          </View>
        ))}
        <Pressable testID="add-slot" onPress={addSlot} style={styles.addSlotBtn}>
          <Ionicons name="add" size={18} color={colors.brandPrimary} />
          <Text style={styles.addSlotText}>Adicionar horário</Text>
        </Pressable>
        <View style={{ paddingHorizontal: spacing.xl, marginTop: spacing.md }}>
          <Pressable
            testID="save-disp"
            disabled={saveDispM.isPending}
            onPress={() => saveDispM.mutate(slots)}
            style={[styles.cta, { height: 44 }]}
          >
            {saveDispM.isPending ? (
              <ActivityIndicator color={colors.onBrandPrimary} />
            ) : (
              <Text style={styles.ctaText}>Salvar disponibilidade</Text>
            )}
          </Pressable>
        </View>

        <Text style={styles.sectionTitle}>REPASSE AUTOMÁTICO (STRIPE CONNECT)</Text>
        <View style={styles.connectCard}>
          <View style={styles.connectRow}>
            <Ionicons
              name={connectQ.data?.charges_enabled ? "checkmark-circle" : "alert-circle-outline"}
              size={22}
              color={connectQ.data?.charges_enabled ? colors.success : colors.warning}
            />
            <Text style={styles.connectTitle}>
              {connectQ.data?.charges_enabled ? "Conta conectada" : "Conta não conectada"}
            </Text>
          </View>
          <Text style={styles.connectBody}>
            Com Stripe Connect ativo, cada captura já debita a taxa da plataforma e transfere o
            restante para sua conta. Sem Connect, o repasse fica no ledger interno.
          </Text>
          {!connectQ.data?.charges_enabled ? (
            <Pressable
              testID="connect-onboarding"
              onPress={() => connectM.mutate()}
              disabled={connectM.isPending}
              style={styles.connectBtn}
            >
              {connectM.isPending ? (
                <ActivityIndicator color={colors.onBrand} />
              ) : (
                <>
                  <Ionicons name="link-outline" size={16} color={colors.onBrand} />
                  <Text style={styles.connectBtnText}>Conectar Stripe</Text>
                </>
              )}
            </Pressable>
          ) : null}
        </View>

        <Text style={styles.sectionTitle}>ZONA DE PERIGO</Text>
        <View style={styles.connectCard}>
          <Pressable
            testID="excluir-conta"
            onPress={confirmarExclusao}
            disabled={excluirContaM.isPending}
            style={styles.dangerRow}
          >
            {excluirContaM.isPending ? (
              <ActivityIndicator color={colors.error} />
            ) : (
              <>
                <Ionicons name="trash-outline" size={18} color={colors.error} />
                <Text style={styles.dangerText}>Excluir minha conta</Text>
              </>
            )}
          </Pressable>
          <Text style={styles.dangerNote}>
            Remove seus dados pessoais permanentemente. Agendamentos pendentes ou futuros
            precisam ser resolvidos antes.
          </Text>
        </View>
      </ScrollView>
    </View>
  );
}
