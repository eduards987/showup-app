// Appointment detail — profissional confirms compareceu/nao_compareceu, or cancels.

import Ionicons from "@react-native-vector-icons/ionicons";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useLocalSearchParams, useRouter } from "expo-router";
import { useState } from "react";
import {
  ActivityIndicator,
  Modal,
  Pressable,
  ScrollView,
  Text,
  View,
} from "react-native";
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
  headerRow: {
    flexDirection: "row",
    alignItems: "center",
    paddingHorizontal: spacing.lg,
    paddingVertical: spacing.md,
  },
  backBtn: { padding: spacing.sm },
  title: {
    fontSize: 24,
    fontWeight: "700",
    color: c.onSurface,
    paddingHorizontal: spacing.xl,
  },
  subtitle: {
    fontSize: 14,
    color: c.muted,
    paddingHorizontal: spacing.xl,
    marginTop: 4,
    marginBottom: spacing.lg,
  },
  card: {
    marginHorizontal: spacing.xl,
    marginBottom: spacing.md,
    padding: spacing.lg,
    backgroundColor: c.surfaceSecondary,
    borderRadius: radius.lg,
    borderWidth: 1,
    borderColor: c.border,
    gap: spacing.sm,
  },
  row: { flexDirection: "row", justifyContent: "space-between", alignItems: "center" },
  label: { fontSize: 13, color: c.muted },
  value: { fontSize: 14, fontWeight: "600", color: c.onSurfaceSecondary },
  bigValue: { fontSize: 22, fontWeight: "800", color: c.brandPrimary },
  badge: {
    alignSelf: "flex-start",
    paddingHorizontal: spacing.md,
    paddingVertical: 4,
    borderRadius: radius.pill,
  },
  badgeText: { fontSize: 12, fontWeight: "800" },
  actionsWrap: {
    padding: spacing.lg,
    backgroundColor: c.surface,
    borderTopWidth: 1,
    borderTopColor: c.border,
    gap: spacing.sm,
  },
  primary: {
    height: 52,
    borderRadius: radius.md,
    backgroundColor: c.brandPrimary,
    alignItems: "center",
    justifyContent: "center",
    flexDirection: "row",
    gap: spacing.sm,
  },
  primaryText: { color: c.onBrandPrimary, fontSize: 15, fontWeight: "700" },
  danger: {
    height: 52,
    borderRadius: radius.md,
    backgroundColor: c.surfaceSecondary,
    borderWidth: 1,
    borderColor: c.error,
    alignItems: "center",
    justifyContent: "center",
    flexDirection: "row",
    gap: spacing.sm,
  },
  dangerText: { color: c.error, fontSize: 15, fontWeight: "700" },
  ghost: {
    height: 48,
    borderRadius: radius.md,
    alignItems: "center",
    justifyContent: "center",
  },
  ghostText: { color: c.muted, fontSize: 14, fontWeight: "600" },

  // Modal
  modalBackdrop: { flex: 1, backgroundColor: "rgba(0,0,0,0.4)", justifyContent: "flex-end" },
  sheet: {
    backgroundColor: c.surfaceSecondary,
    borderTopLeftRadius: radius.lg,
    borderTopRightRadius: radius.lg,
    padding: spacing.xl,
    gap: spacing.md,
  },
  sheetTitle: { fontSize: 18, fontWeight: "700", color: c.onSurfaceSecondary },
  sheetBody: { fontSize: 14, color: c.muted, lineHeight: 20 },
}));

const KIND_COLORS = {
  info: { bg: "#E4EFF6", fg: "#255170" },
  success: { bg: "#DCF7E3", fg: "#1B7C34" },
  warning: { bg: "#FFECD1", fg: "#8A5A00" },
  error: { bg: "#FFE0DE", fg: "#8A1F1A" },
};

export default function AgendamentoDetalhe() {
  const styles = useStyles();
  const { colors } = useTheme();
  const insets = useSafeAreaInsets();
  const router = useRouter();
  const qc = useQueryClient();
  const auth = useAuth();
  const { id } = useLocalSearchParams<{ id: string }>();
  const [confirmNoShow, setConfirmNoShow] = useState(false);

  const q = useQuery({
    queryKey: ["agendamento", id],
    queryFn: () => api<Agendamento>(`/api/agendamentos/${id}`),
    enabled: !!id,
  });

  const confirmM = useMutation({
    mutationFn: (resultado: "compareceu" | "nao_compareceu") =>
      api<Agendamento>(`/api/agendamentos/${id}/confirmar`, {
        method: "POST",
        body: JSON.stringify({ resultado }),
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["agendamento", id] });
      qc.invalidateQueries({ queryKey: ["agendamentos"] });
      setConfirmNoShow(false);
    },
  });

  const cancelM = useMutation({
    mutationFn: () => api(`/api/agendamentos/${id}/cancelar`, { method: "POST" }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["agendamento", id] });
      qc.invalidateQueries({ queryKey: ["agendamentos"] });
    },
  });

  if (q.isLoading || !q.data) {
    return (
      <View style={[styles.root, { paddingTop: insets.top }]}>
        <ActivityIndicator style={{ marginTop: spacing.xxl }} color={colors.brandPrimary} />
      </View>
    );
  }
  const a = q.data;
  const isProf = auth.status === "authenticated" && auth.user.role === "profissional";
  const isCli = auth.status === "authenticated" && auth.user.role === "cliente";
  const holdMeta = HOLD_STATUS_LABELS[a.hold_status] ?? { label: a.hold_status, kind: "info" };
  const holdColor = KIND_COLORS[holdMeta.kind];
  const canConfirm =
    isProf && a.status_confirmacao === "pendente" && a.hold_status === "autorizado";
  const canCancel =
    a.hold_status === "autorizado" && a.status_confirmacao === "pendente";

  return (
    <View style={[styles.root, { paddingTop: insets.top }]}>
      <View style={styles.headerRow}>
        <Pressable onPress={() => router.back()} style={styles.backBtn}>
          <Ionicons name="chevron-back" size={24} color={colors.onSurface} />
        </Pressable>
      </View>
      <Text style={styles.title}>{a.servico_nome}</Text>
      <Text style={styles.subtitle}>
        {isCli ? `com ${a.profissional_nome}` : `Cliente: ${a.cliente_nome}`}
      </Text>

      <ScrollView contentContainerStyle={{ paddingBottom: spacing.xxl }}>
        <View style={styles.card}>
          <Text style={styles.label}>Horário</Text>
          <Text style={styles.value}>{formatDateTime(a.horario_inicio)}</Text>
        </View>

        <View style={styles.card}>
          <View style={styles.row}>
            <Text style={styles.label}>Valor pré-autorizado</Text>
            <Text style={styles.bigValue}>{formatMoney(a.valor_total_centavos, a.moeda)}</Text>
          </View>
          <View style={styles.row}>
            <Text style={styles.label}>Taxa em caso de no-show</Text>
            <Text style={styles.value}>{formatMoney(a.valor_no_show_centavos, a.moeda)}</Text>
          </View>
          {a.valor_capturado_centavos > 0 ? (
            <View style={styles.row}>
              <Text style={styles.label}>Valor capturado</Text>
              <Text style={[styles.value, { color: colors.success }]}>
                {formatMoney(a.valor_capturado_centavos, a.moeda)}
              </Text>
            </View>
          ) : null}
        </View>

        <View style={styles.card}>
          <Text style={styles.label}>Status do pagamento</Text>
          <View style={[styles.badge, { backgroundColor: holdColor.bg }]}>
            <Text style={[styles.badgeText, { color: holdColor.fg }]}>
              {holdMeta.label.toUpperCase()}
            </Text>
          </View>
          <Text style={styles.label}>Confirmação</Text>
          <Text style={styles.value}>{CONFIRMACAO_LABELS[a.status_confirmacao]}</Text>
          <Text style={[styles.label, { fontSize: 12, marginTop: spacing.sm }]}>
            Janela até {formatDateTime(a.janela_confirmacao_expira_em)}
          </Text>
        </View>
      </ScrollView>

      {(canConfirm || canCancel) && (
        <View style={[styles.actionsWrap, { paddingBottom: insets.bottom + spacing.md }]}>
          {canConfirm ? (
            <>
              <Pressable
                testID="confirm-attended"
                onPress={() => confirmM.mutate("compareceu")}
                disabled={confirmM.isPending}
                style={styles.primary}
              >
                {confirmM.isPending ? (
                  <ActivityIndicator color={colors.onBrandPrimary} />
                ) : (
                  <>
                    <Ionicons name="checkmark-circle" size={20} color={colors.onBrandPrimary} />
                    <Text style={styles.primaryText}>
                      Compareceu · Capturar {formatMoney(a.valor_total_centavos, a.moeda)}
                    </Text>
                  </>
                )}
              </Pressable>
              <Pressable
                testID="confirm-noshow"
                onPress={() => setConfirmNoShow(true)}
                disabled={confirmM.isPending}
                style={styles.danger}
              >
                <Ionicons name="close-circle" size={20} color={colors.error} />
                <Text style={styles.dangerText}>
                  Não compareceu · Cobrar taxa {formatMoney(a.valor_no_show_centavos, a.moeda)}
                </Text>
              </Pressable>
            </>
          ) : null}
          {canCancel && !canConfirm ? (
            <Pressable
              testID="cancel-hold"
              onPress={() => cancelM.mutate()}
              disabled={cancelM.isPending}
              style={styles.ghost}
            >
              <Text style={styles.ghostText}>Cancelar reserva</Text>
            </Pressable>
          ) : null}
        </View>
      )}

      <Modal transparent visible={confirmNoShow} animationType="slide" onRequestClose={() => setConfirmNoShow(false)}>
        <View style={styles.modalBackdrop}>
          <View style={[styles.sheet, { paddingBottom: insets.bottom + spacing.xl }]}>
            <Text style={styles.sheetTitle}>Confirmar no-show?</Text>
            <Text style={styles.sheetBody}>
              Isso cobra {formatMoney(a.valor_no_show_centavos, a.moeda)} do cartão do cliente. O restante
              do hold ({formatMoney(a.valor_total_centavos - a.valor_no_show_centavos, a.moeda)}) é liberado
              automaticamente. Ação irreversível.
            </Text>
            <Pressable
              testID="modal-confirm-noshow"
              onPress={() => confirmM.mutate("nao_compareceu")}
              disabled={confirmM.isPending}
              style={styles.danger}
            >
              {confirmM.isPending ? (
                <ActivityIndicator color={colors.error} />
              ) : (
                <Text style={styles.dangerText}>Confirmar no-show</Text>
              )}
            </Pressable>
            <Pressable onPress={() => setConfirmNoShow(false)} style={styles.ghost}>
              <Text style={styles.ghostText}>Cancelar</Text>
            </Pressable>
          </View>
        </View>
      </Modal>
    </View>
  );
}
