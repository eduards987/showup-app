// Profissional only: create a new service.

import Ionicons from "@react-native-vector-icons/ionicons";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useRouter } from "expo-router";
import { useState } from "react";
import {
  ActivityIndicator,
  KeyboardAvoidingView,
  Platform,
  Pressable,
  ScrollView,
  Text,
  TextInput,
  View,
} from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import { api } from "@/src/lib/api";
import { makeStyles, radius, spacing, useTheme } from "@/src/theme";

const useStyles = makeStyles((c) => ({
  root: { flex: 1, backgroundColor: c.surface },
  headerRow: { flexDirection: "row", alignItems: "center", paddingHorizontal: spacing.lg, paddingVertical: spacing.md },
  backBtn: { padding: spacing.sm },
  title: { fontSize: 24, fontWeight: "700", color: c.onSurface, paddingHorizontal: spacing.xl },
  subtitle: {
    fontSize: 14,
    color: c.muted,
    paddingHorizontal: spacing.xl,
    marginTop: 4,
    marginBottom: spacing.lg,
  },
  field: { paddingHorizontal: spacing.xl, marginBottom: spacing.lg },
  label: { fontSize: 13, fontWeight: "700", color: c.onSurface, marginBottom: spacing.sm },
  input: {
    height: 48,
    borderRadius: radius.md,
    backgroundColor: c.surfaceSecondary,
    borderWidth: 1,
    borderColor: c.border,
    paddingHorizontal: spacing.md,
    fontSize: 15,
    color: c.onSurfaceSecondary,
  },
  textarea: {
    minHeight: 88,
    borderRadius: radius.md,
    backgroundColor: c.surfaceSecondary,
    borderWidth: 1,
    borderColor: c.border,
    paddingHorizontal: spacing.md,
    paddingVertical: spacing.md,
    fontSize: 15,
    color: c.onSurfaceSecondary,
    textAlignVertical: "top",
  },
  row2: { flexDirection: "row", gap: spacing.md, paddingHorizontal: spacing.xl, marginBottom: spacing.lg },
  cell: { flex: 1 },
  ctaWrap: { padding: spacing.lg, borderTopWidth: 1, borderTopColor: c.border, backgroundColor: c.surface },
  cta: {
    height: 54,
    borderRadius: radius.md,
    backgroundColor: c.brandPrimary,
    alignItems: "center",
    justifyContent: "center",
  },
  ctaDisabled: { opacity: 0.4 },
  ctaText: { color: c.onBrandPrimary, fontSize: 16, fontWeight: "700" },
  err: {
    marginHorizontal: spacing.xl,
    marginBottom: spacing.md,
    padding: spacing.md,
    borderRadius: radius.md,
    backgroundColor: c.error,
  },
  errText: { color: c.onError, fontSize: 13, fontWeight: "600" },
}));

function reaisToCentavos(input: string): number {
  const digits = input.replace(/[^\d]/g, "");
  return digits ? parseInt(digits, 10) : 0;
}

export default function NovoServico() {
  const styles = useStyles();
  const { colors } = useTheme();
  const insets = useSafeAreaInsets();
  const router = useRouter();
  const qc = useQueryClient();

  const [nome, setNome] = useState("");
  const [descricao, setDescricao] = useState("");
  const [valor, setValor] = useState(""); // centavos as digits
  const [taxa, setTaxa] = useState("");
  const [duracao, setDuracao] = useState("60");
  const [err, setErr] = useState<string | null>(null);

  const createM = useMutation({
    mutationFn: () =>
      api("/api/servicos", {
        method: "POST",
        body: JSON.stringify({
          nome: nome.trim(),
          descricao: descricao.trim() || null,
          valor_centavos: reaisToCentavos(valor),
          taxa_no_show_centavos: reaisToCentavos(taxa),
          duracao_min: parseInt(duracao, 10) || 60,
        }),
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["meus-servicos"] });
      router.back();
    },
    onError: (e: any) => setErr(e.message || "Falha ao salvar"),
  });

  const valid =
    nome.trim().length >= 2 &&
    reaisToCentavos(valor) > 0 &&
    reaisToCentavos(taxa) > 0 &&
    reaisToCentavos(taxa) <= reaisToCentavos(valor) &&
    parseInt(duracao, 10) > 0;

  return (
    <KeyboardAvoidingView
      behavior={Platform.OS === "ios" ? "padding" : undefined}
      style={{ flex: 1 }}
    >
      <View style={[styles.root, { paddingTop: insets.top }]}>
        <View style={styles.headerRow}>
          <Pressable onPress={() => router.back()} style={styles.backBtn}>
            <Ionicons name="chevron-back" size={24} color={colors.onSurface} />
          </Pressable>
        </View>
        <Text style={styles.title}>Novo serviço</Text>
        <Text style={styles.subtitle}>Defina o valor total e a taxa em caso de no-show.</Text>

        <ScrollView contentContainerStyle={{ paddingBottom: spacing.xl }}>
          <View style={styles.field}>
            <Text style={styles.label}>Nome</Text>
            <TextInput
              testID="nome-input"
              value={nome}
              onChangeText={setNome}
              placeholder="Sessão de personal training"
              placeholderTextColor={colors.muted}
              style={styles.input}
            />
          </View>
          <View style={styles.field}>
            <Text style={styles.label}>Descrição (opcional)</Text>
            <TextInput
              value={descricao}
              onChangeText={setDescricao}
              multiline
              placeholder="Detalhe o que está incluído..."
              placeholderTextColor={colors.muted}
              style={styles.textarea}
            />
          </View>
          <View style={styles.row2}>
            <View style={styles.cell}>
              <Text style={styles.label}>Valor (R$)</Text>
              <TextInput
                testID="valor-input"
                value={valor ? (reaisToCentavos(valor) / 100).toFixed(2) : ""}
                onChangeText={setValor}
                keyboardType="numeric"
                placeholder="120,00"
                placeholderTextColor={colors.muted}
                style={styles.input}
              />
            </View>
            <View style={styles.cell}>
              <Text style={styles.label}>Taxa no-show (R$)</Text>
              <TextInput
                testID="taxa-input"
                value={taxa ? (reaisToCentavos(taxa) / 100).toFixed(2) : ""}
                onChangeText={setTaxa}
                keyboardType="numeric"
                placeholder="40,00"
                placeholderTextColor={colors.muted}
                style={styles.input}
              />
            </View>
          </View>
          <View style={styles.field}>
            <Text style={styles.label}>Duração (min)</Text>
            <TextInput
              testID="duracao-input"
              value={duracao}
              onChangeText={setDuracao}
              keyboardType="numeric"
              placeholder="60"
              placeholderTextColor={colors.muted}
              style={styles.input}
            />
          </View>
          {err ? (
            <View style={styles.err}>
              <Text style={styles.errText}>{err}</Text>
            </View>
          ) : null}
        </ScrollView>
        <View style={[styles.ctaWrap, { paddingBottom: insets.bottom + spacing.md }]}>
          <Pressable
            testID="save-servico"
            onPress={() => {
              setErr(null);
              createM.mutate();
            }}
            disabled={!valid || createM.isPending}
            style={[styles.cta, (!valid || createM.isPending) && styles.ctaDisabled]}
          >
            {createM.isPending ? (
              <ActivityIndicator color={colors.onBrandPrimary} />
            ) : (
              <Text style={styles.ctaText}>Salvar serviço</Text>
            )}
          </Pressable>
        </View>
      </View>
    </KeyboardAvoidingView>
  );
}
