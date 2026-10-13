// Planos: mostra Free/Profissional/Ultra com a taxa por agendamento de cada
// um, a CONTA do próprio profissional (quanto ele pagaria em cada plano com o
// movimento dos últimos 30 dias, e quanto o app recuperou em faltas), e deixa
// ele assinar (Payment Sheet nativo), testar o plano pago de graça ou cancelar
// (volta pro Free). Só faz sentido pra profissional — a rota é alcançável só
// pelo card em perfil.tsx, que já esconde isso de clientes.

import Ionicons from "@react-native-vector-icons/ionicons";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useStripe } from "@stripe/stripe-react-native";
import { useRouter } from "expo-router";
import { ActivityIndicator, Pressable, ScrollView, Text, View } from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import { api } from "@/src/lib/api";
import { useAuth } from "@/src/lib/auth";
import { formatDateOnly, formatMoney } from "@/src/lib/format";
import { makeStyles, radius, spacing, useTheme } from "@/src/theme";

type Plano = {
  id: string;
  nome: string;
  fee_percent: number;
  preco_centavos: number;
  disponivel: boolean;
};

type Comparacao = {
  id: string;
  nome: string;
  fee_percent: number;
  preco_centavos: number;
  disponivel: boolean;
  taxa_estimada_centavos: number;
  custo_total_centavos: number;
  economia_vs_atual_centavos: number;
  equilibrio_vs_free_centavos: number | null;
  equilibrio_vs_anterior_centavos: number | null;
};

type Resumo = {
  plano_atual: string;
  moeda: string;
  janela_dias: number;
  atendimentos_cobrados: number;
  servicos_cobrados_centavos: number;
  base_taxa_centavos: number;
  faltas_cobradas_qtd: number;
  faltas_cobradas_centavos: number;
  comparacao_disponivel: boolean;
  comparacao: Comparacao[];
  recomendado: string | null;
  trial_disponivel: boolean;
  trial_dias: number;
  trial_termina_em: string | null;
};

type SubscriptionIntent = {
  customer_id: string;
  ephemeral_key_secret: string;
  // Assinatura paga usa o PaymentIntent; teste grátis (nada a cobrar agora)
  // usa o SetupIntent, só pra salvar o cartão.
  payment_intent_client_secret: string | null;
  setup_intent_client_secret: string | null;
  trial_dias: number;
  subscription_id: string;
};

// Texto de cada plano. Sem a conta do backend (carregando, ou outra moeda) cai
// numa frase que não promete número nenhum; com ela, o ponto de equilíbrio real.
function descricaoPlano(p: Plano, comp: Comparacao | undefined, moeda: string): string {
  if (p.id === "free") return "Sem mensalidade. Você paga só a taxa por agendamento.";
  const vsFree = comp?.equilibrio_vs_free_centavos;
  if (!vsFree) {
    return p.id === "ultra"
      ? "Taxa mínima — pra quem tem volume alto de atendimentos."
      : "Taxa reduzida — pra quem já atende com frequência.";
  }
  let txt = `Compensa a partir de ${formatMoney(vsFree, moeda)}/mês em atendimentos, comparado ao Free.`;
  const vsAnterior = comp?.equilibrio_vs_anterior_centavos;
  if (vsAnterior && vsAnterior !== vsFree) {
    txt += ` Sobre o plano anterior, a partir de ${formatMoney(vsAnterior, moeda)}/mês.`;
  }
  return txt;
}

function plural(n: number, um: string, varios: string): string {
  return `${n} ${n === 1 ? um : varios}`;
}

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
  badgeRecomendado: {
    backgroundColor: c.surfaceTertiary ?? c.border,
    paddingHorizontal: spacing.sm,
    paddingVertical: 4,
    borderRadius: radius.pill,
  },
  badgeRecomendadoText: { color: c.brandPrimary, fontSize: 11, fontWeight: "700" },
  resumoCard: {
    borderWidth: 1,
    borderColor: c.border,
    borderRadius: radius.lg,
    padding: spacing.lg,
    backgroundColor: c.surfaceSecondary,
    gap: spacing.xs,
  },
  resumoTitulo: { fontSize: 16, fontWeight: "700", color: c.onSurface },
  resumoLinha: { fontSize: 14, color: c.onSurface },
  resumoSub: { fontSize: 13, color: c.muted, marginTop: spacing.sm },
  tabelaLinha: { flexDirection: "row", justifyContent: "space-between", alignItems: "baseline", paddingVertical: 4 },
  tabelaNome: { fontSize: 14, color: c.onSurface, fontWeight: "600" },
  tabelaValor: { fontSize: 14, color: c.onSurface, fontWeight: "700" },
  tabelaDelta: { fontSize: 12, color: c.muted },
  tabelaDeltaBom: { fontSize: 12, color: c.brandPrimary, fontWeight: "700" },
  veredito: { fontSize: 14, color: c.brandPrimary, fontWeight: "700", marginTop: spacing.sm },
  nota: { fontSize: 12, color: c.muted, marginTop: spacing.sm },
  trialInfo: { fontSize: 12, color: c.muted, marginTop: spacing.xs, textAlign: "center" },
  trialAtivo: { fontSize: 13, color: c.brandPrimary, fontWeight: "700", marginTop: spacing.xs },
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

  const resumoQ = useQuery({
    queryKey: ["plano-resumo"],
    queryFn: () => api<Resumo>("/api/me/plano/resumo"),
    enabled: auth.status === "authenticated",
  });
  const resumo = resumoQ.data;

  const planoAtual = auth.status === "authenticated" ? (auth.user.plano ?? "free") : "free";
  const moeda = auth.status === "authenticated" ? (auth.user.moeda ?? "BRL") : "BRL";
  const timezone = auth.status === "authenticated" ? auth.user.timezone : undefined;
  const trialDisponivel = resumo?.trial_disponivel === true;
  const comparacaoDe = (id: string) => resumo?.comparacao.find((c) => c.id === id);
  const recarregar = () => {
    auth.refresh();
    qc.invalidateQueries({ queryKey: ["planos-list"] });
    qc.invalidateQueries({ queryKey: ["plano-resumo"] });
  };

  const checkoutM = useMutation({
    mutationFn: async ({ planoId, trial }: { planoId: string; trial: boolean }) => {
      // Passo 1: prepara a assinatura no Stripe (ainda pendente) e pega tudo
      // que o Payment Sheet nativo precisa — mesmo padrão já usado pro cartão
      // de no-show, sem abrir navegador. No teste grátis não há nada a cobrar
      // agora: o sheet só salva o cartão (SetupIntent).
      const intent = await api<SubscriptionIntent>("/api/me/plano/subscription-intent", {
        method: "POST",
        body: JSON.stringify({ plano: planoId, usar_trial: trial }),
      });

      const base = {
        merchantDisplayName: "ShowUp",
        customerId: intent.customer_id,
        customerEphemeralKeySecret: intent.ephemeral_key_secret,
      };
      const { error: initError } = intent.setup_intent_client_secret
        ? await initPaymentSheet({
            ...base,
            setupIntentClientSecret: intent.setup_intent_client_secret,
            primaryButtonLabel: "Começar teste grátis",
          })
        : await initPaymentSheet({
            ...base,
            paymentIntentClientSecret: intent.payment_intent_client_secret ?? "",
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
    onSuccess: recarregar,
  });

  const cancelarM = useMutation({
    mutationFn: () => api("/api/me/plano/cancelar", { method: "POST" }),
    onSuccess: recarregar,
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

          {resumo ? (
            <View style={styles.resumoCard} testID="plano-resumo">
              <Text style={styles.resumoTitulo}>Seus últimos {resumo.janela_dias} dias</Text>

              {resumo.atendimentos_cobrados === 0 && resumo.faltas_cobradas_qtd === 0 ? (
                <Text style={styles.resumoLinha}>
                  Ainda não há atendimentos cobrados pelo app nesse período.
                  {resumo.comparacao_disponivel
                    ? " Quando houver, mostramos aqui quanto você pagaria em cada plano."
                    : ""}
                </Text>
              ) : (
                <>
                  <Text style={styles.resumoLinha}>
                    {plural(resumo.atendimentos_cobrados, "atendimento cobrado", "atendimentos cobrados")} pelo
                    app · {formatMoney(resumo.servicos_cobrados_centavos, resumo.moeda)}
                  </Text>
                  {resumo.faltas_cobradas_qtd > 0 ? (
                    <Text style={styles.resumoLinha}>
                      {plural(resumo.faltas_cobradas_qtd, "falta cobrada", "faltas cobradas")} ·{" "}
                      {formatMoney(resumo.faltas_cobradas_centavos, resumo.moeda)} que você teria perdido
                    </Text>
                  ) : null}
                </>
              )}

              {resumo.comparacao_disponivel && resumo.base_taxa_centavos > 0 ? (
                <>
                  <Text style={styles.resumoSub}>Quanto você pagaria (taxa + mensalidade)</Text>
                  {resumo.comparacao.map((c) => (
                    <View key={c.id} style={styles.tabelaLinha}>
                      <Text style={styles.tabelaNome}>
                        {c.nome}
                        {c.id === resumo.plano_atual ? " (atual)" : ""}
                      </Text>
                      <Text style={styles.tabelaValor}>
                        {formatMoney(c.custo_total_centavos, resumo.moeda)}{" "}
                        {c.id !== resumo.plano_atual && c.economia_vs_atual_centavos !== 0 ? (
                          <Text
                            style={c.economia_vs_atual_centavos > 0 ? styles.tabelaDeltaBom : styles.tabelaDelta}
                          >
                            {c.economia_vs_atual_centavos > 0
                              ? `economiza ${formatMoney(c.economia_vs_atual_centavos, resumo.moeda)}`
                              : `+${formatMoney(-c.economia_vs_atual_centavos, resumo.moeda)}`}
                          </Text>
                        ) : null}
                      </Text>
                    </View>
                  ))}
                  {resumo.recomendado ? (
                    <Text style={styles.veredito}>
                      Com esse movimento, o {comparacaoDe(resumo.recomendado)?.nome} teria custado{" "}
                      {formatMoney(comparacaoDe(resumo.recomendado)?.economia_vs_atual_centavos ?? 0, resumo.moeda)} a
                      menos.
                    </Text>
                  ) : (
                    <Text style={styles.veredito}>
                      Pro seu movimento, o plano atual já é o mais barato.
                    </Text>
                  )}
                  <Text style={styles.nota}>
                    Estimativa com base nos últimos {resumo.janela_dias} dias — não garante o mesmo valor
                    nos próximos. A taxa incide sobre o valor efetivamente cobrado em cada atendimento ou falta.
                  </Text>
                </>
              ) : null}
            </View>
          ) : null}

          {(planosQ.data?.planos ?? []).map((p) => {
            const isAtual = p.id === planoAtual;
            const isFree = p.id === "free";
            const emTeste = isAtual && !isFree && !!resumo?.trial_termina_em;
            return (
              <View key={p.id} style={[styles.card, isAtual && styles.cardActive]}>
                <View style={styles.cardHeaderRow}>
                  <Text style={styles.planoNome}>{p.nome}</Text>
                  {isAtual ? (
                    <View style={styles.badge}>
                      <Text style={styles.badgeText}>PLANO ATUAL</Text>
                    </View>
                  ) : p.id === resumo?.recomendado ? (
                    <View style={styles.badgeRecomendado}>
                      <Text style={styles.badgeRecomendadoText}>MELHOR PRA VOCÊ</Text>
                    </View>
                  ) : null}
                </View>

                <Text style={styles.preco}>
                  {p.preco_centavos === 0 ? "Grátis" : formatMoney(p.preco_centavos, moeda)}
                  {p.preco_centavos > 0 ? <Text style={styles.precoSufixo}> /mês</Text> : null}
                </Text>
                <Text style={styles.taxa}>{p.fee_percent}% por agendamento</Text>
                <Text style={styles.descricao}>{descricaoPlano(p, comparacaoDe(p.id), moeda)}</Text>

                {emTeste && resumo?.trial_termina_em ? (
                  <Text style={styles.trialAtivo} testID="trial-ativo">
                    Teste grátis até {formatDateOnly(resumo.trial_termina_em, timezone)}. Depois, {formatMoney(p.preco_centavos, moeda)}/mês —
                    cancele antes disso se não quiser continuar.
                  </Text>
                ) : null}

                {!isAtual && !isFree && p.disponivel ? (
                  <>
                    <Pressable
                      testID={`assinar-${p.id}`}
                      disabled={checkoutM.isPending}
                      onPress={() => checkoutM.mutate({ planoId: p.id, trial: trialDisponivel })}
                      style={[styles.cta, checkoutM.isPending && styles.ctaDisabled]}
                    >
                      {checkoutM.isPending ? (
                        <ActivityIndicator color={colors.onBrandPrimary} />
                      ) : (
                        <Text style={styles.ctaText}>
                          {trialDisponivel ? `Testar ${resumo?.trial_dias} dias grátis` : `Assinar ${p.nome}`}
                        </Text>
                      )}
                    </Pressable>
                    {trialDisponivel ? (
                      <Text style={styles.trialInfo}>
                        Sem cobrança por {resumo?.trial_dias} dias; depois {formatMoney(p.preco_centavos, moeda)}/mês. Cancele
                        antes e você não paga nada.
                      </Text>
                    ) : null}
                  </>
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
