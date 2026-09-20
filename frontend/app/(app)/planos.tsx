// Planos: mostra Free/Profissional/Ultra com a taxa por agendamento de cada
// um, e deixa o profissional assinar (checkout hospedado no Stripe) ou
// cancelar (volta pro Free). Só faz sentido pra profissional — a rota é
// alcançável só pelo card em perfil.tsx, que já esconde isso de clientes.

import Ionicons from "@react-native-vector-icons/ionicons";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useStripe } from "@stripe/stripe-react-native";
import { useRouter } from "expo-router";
import { ActivityIndicator, Pressable, ScrollView, Text, View } from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import { api } from "@/src/lib/api";
import { useAuth } from "@/src/lib/auth";
import { formatMoney } from "@/src/lib/format";
import { makeStyles, radius, spacing, useTheme } from "@/src/theme";

type Plano = {
  id: string;
  nome: string;
  fee_percent: number;
  preco_centavos: number;
  disponivel: boolean;
};

const DESCRICOES: Record<string, string> = {
  free: "Comece sem custo fixo. Ideal pra testar o app.",
  profissional: "Taxa reduzida — compensa a partir de ~4-5 agendamentos por mês.",
  ultra: "Taxa mínima — pra quem já tem volume alto de atendimentos.",
};

const useStyles = makeStyles((c) => ({
  root: { flex: 1, backgroundColor: c.surface },
  headerRow: { flexDirection: "row", alignItems: "center", paddingHorizontal: spacing.lg, paddingVertical: spacing.md },
  backBtn: { padding: spacing.xs },
  title: { fontSize: 20, fontWeight: "700", color: c.onSurface, marginLeft: spacing.sm },
  scroll: { padding: spacing.lg, gap: spacing.md, paddingBottom: spacing.xxl },
  intro: { color: c.muted, fontSize: 14, marginBottom: spacing.sm },
  card: {
    borderWidth: 1,
    borderColor: c.border,
    borderRadius: radius.lg,
    padding: spacing.lg,
    backgroundColor: c.surfaceSecondary,
    gap: spacing.xs,
  },
  cardActive: { borderColor: c.brandPrimary, borderWidth: 2 },
  cardHeaderRow: { flexDirection: "row", justifyContent: "space-between", alignItems: "center" },
  planoNome: { fontSize: 18, fontWeight: "700", color: c.onSurface },
  badge: {
    backgroundColor: c.brandPrimary,
    paddingHorizontal: spacing.sm,
    paddingVertical: 4,
    borderRadius: radius.pill,
  },
  badgeText: { color: c.onBrandPrimary, fontSize: 11, fontWeight: "700" },
  preco: { fontSize: 24, fontWeight: "800", color: c.onSurface, marginTop: spacing.xs },
  precoSufixo: { fontSize: 13, fontWeight: "500", color: c.muted },
  taxa: { fontSize: 14, color: c.brandPrimary, fontWeight: "700", marginTop: spacing.xs },
  descricao: { fontSize: 13, color: c.muted, marginTop: spacing.xs },
  cta: {
    marginTop: spacing.md,
    height: 44,
    borderRadius: radius.md,
    backgroundColor: c.brandPrimary,
    alignItems: "center",
    justifyContent: "center",
  },
  ctaSecundario: { backgroundColor: c.surfaceTertiary ?? c.border },
  ctaDisabled: { opacity: 0.5 },
  ctaText: { color: c.onBrandPrimary, fontSize: 14, fontWeight: "700" },
  ctaTextSecundario: { color: c.onSurface },
  emBreve: { fontSize: 12, color: c.muted, fontStyle: "italic", marginTop: spacing.sm, textAlign: "center" },
  errorText: { color: c.onError, fontSize: 13, marginTop: spacing.sm },
}));

export default function Planos() {
  const styles = useStyles();
  const { colors } = useTheme();
  const insets = useSafeAreaInsets();
  const router = useRouter();
  const auth = useAuth();
  const qc = useQueryClient();
  const { initPaymentSheet, presentPaymentSheet } = useStripe();

  const planosQ = useQuery({
    queryKey: ["planos-list"],
    queryFn: () => api<{ planos: Plano[] }>("/api/planos"),
  });

  const planoAtual = auth.status === "authenticated" ? (auth.user.plano ?? "free") : "free";
  const moeda = auth.status === "authenticated" ? (auth.user.moeda ?? "BRL") : "BRL";

  const checkoutM = useMutation({
    mutationFn: async (planoId: string) => {
      // Passo 1: prepara a assinatura no Stripe (ainda pendente de
      // pagamento) e pega tudo que o Payment Sheet nativo precisa —
      // mesmo padrão já usado pro cartão de no-show, sem abrir navegador.
      const intent = await api<{
        customer_id: string;
        ephemeral_key_secret: string;
        payment_intent_client_secret: string;
        subscription_id: string;
      }>("/api/me/plano/subscription-intent", {
        method: "POST",
        body: JSON.stringify({ plano: planoId }),
      });

      const { error: initError } = await initPaymentSheet({
        merchantDisplayName: "ShowUp",
        customerId: intent.customer_id,
        customerEphemeralKeySecret: intent.ephemeral_key_secret,
        paymentIntentClientSecret: intent.payment_intent_client_secret,
      });
      if (initError) throw new Error(initError.message);

      const { error: presentError } = await presentPaymentSheet();
      if (presentError) {
        if (presentError.code === "Canceled") return; // usuário cancelou, não é erro
        throw new Error(presentError.message);
      }

      // Passo 2: confirma DE VERDADE com o backend (que confere direto com
      // o Stripe) antes de liberar a taxa reduzida — nunca confia só no
      // "sucesso" que o Payment Sheet reporta.
      await api("/api/me/plano/confirm", {
        method: "POST",
        body: JSON.stringify({ subscription_id: intent.subscription_id, plano: planoId }),
      });
    },
    onSuccess: () => {
      auth.refresh();
      qc.invalidateQueries({ queryKey: ["planos-list"] });
    },
  });

  const cancelarM = useMutation({
    mutationFn: () => api("/api/me/plano/cancelar", { method: "POST" }),
    onSuccess: () => {
      auth.refresh();
      qc.invalidateQueries({ queryKey: ["planos-list"] });
    },
  });

  const erro = (checkoutM.error as any)?.message || (cancelarM.error as any)?.message;

  return (
    <View style={[styles.root, { paddingTop: insets.top }]}>
      <View style={styles.headerRow}>
        <Pressable onPress={() => router.back()} style={styles.backBtn}>
          <Ionicons name="chevron-back" size={24} color={colors.onSurface} />
        </Pressable>
        <Text style={styles.title}>Plano</Text>
      </View>

      {planosQ.isLoading ? (
        <ActivityIndicator style={{ marginTop: spacing.xl }} color={colors.brandPrimary} />
      ) : (
        <ScrollView contentContainerStyle={styles.scroll}>
          <Text style={styles.intro}>
            A taxa por agendamento diminui conforme o plano sobe. Trocar de plano nunca afeta
            agendamentos já criados, só os próximos.
          </Text>

          {(planosQ.data?.planos ?? []).map((p) => {
            const isAtual = p.id === planoAtual;
            const isFree = p.id === "free";
            return (
              <View key={p.id} style={[styles.card, isAtual && styles.cardActive]}>
                <View style={styles.cardHeaderRow}>
                  <Text style={styles.planoNome}>{p.nome}</Text>
                  {isAtual ? (
                    <View style={styles.badge}>
                      <Text style={styles.badgeText}>PLANO ATUAL</Text>
                    </View>
                  ) : null}
                </View>

                <Text style={styles.preco}>
                  {p.preco_centavos === 0 ? "Grátis" : formatMoney(p.preco_centavos, moeda)}
                  {p.preco_centavos > 0 ? <Text style={styles.precoSufixo}> /mês</Text> : null}
                </Text>
                <Text style={styles.taxa}>{p.fee_percent}% por agendamento</Text>
                <Text style={styles.descricao}>{DESCRICOES[p.id] ?? ""}</Text>

                {!isAtual && !isFree && p.disponivel ? (
                  <Pressable
                    testID={`assinar-${p.id}`}
                    disabled={checkoutM.isPending}
                    onPress={() => checkoutM.mutate(p.id)}
                    style={[styles.cta, checkoutM.isPending && styles.ctaDisabled]}
                  >
                    {checkoutM.isPending ? (
                      <ActivityIndicator color={colors.onBrandPrimary} />
                    ) : (
                      <Text style={styles.ctaText}>Assinar {p.nome}</Text>
                    )}
                  </Pressable>
                ) : null}

                {!isAtual && !isFree && !p.disponivel ? (
                  <Text style={styles.emBreve}>Em breve</Text>
                ) : null}

                {!isAtual && isFree ? (
                  <Pressable
                    testID="cancelar-plano"
                    disabled={cancelarM.isPending}
                    onPress={() => cancelarM.mutate()}
                    style={[styles.cta, styles.ctaSecundario, cancelarM.isPending && styles.ctaDisabled]}
                  >
                    {cancelarM.isPending ? (
                      <ActivityIndicator color={colors.onSurface} />
                    ) : (
                      <Text style={[styles.ctaText, styles.ctaTextSecundario]}>
                        Cancelar assinatura e voltar ao Free
                      </Text>
                    )}
                  </Pressable>
                ) : null}
              </View>
            );
          })}

          {erro ? <Text style={styles.errorText}>{erro}</Text> : null}
        </ScrollView>
      )}
    </View>
  );
}
