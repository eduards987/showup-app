// Profissional only: manage weekly availability + categorias.

import Ionicons from "@react-native-vector-icons/ionicons";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useLocalSearchParams, useRouter } from "expo-router";
import { useEffect, useState } from "react";
import {
  ActivityIndicator,
  Alert,
  AppState,
  Linking,
  Pressable,
  ScrollView,
  Text,
  TextInput,
  View,
} from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import { ConnectCard } from "@/src/components/connect-card";
import { RecebimentoCard } from "@/src/components/recebimento-card";
import { SeletorMoeda } from "@/src/components/seletor-moeda";
import { avisoDeConversao } from "@/src/lib/moedas";
import { resumoJanelaAgenda } from "@/src/lib/agenda-janela";
import { api, ApiError } from "@/src/lib/api";
import { nomeDaCategoria, nomeDoGrupo } from "@/src/lib/categorias";
import { nomeDoGrupoFuso, rotuloDoFuso } from "@/src/lib/fusos";
import { DropdownGrupos, DropdownMultiGrupos } from "@/src/components/dropdown";
import { useAuth } from "@/src/lib/auth";
import type { ConnectStatus } from "@/src/lib/connect-estado";
import { openExternalCheckout } from "@/src/lib/open-external-checkout";
import { mensagemDoRetorno, type MetodoRecebimento, type RecebimentoStatus } from "@/src/lib/recebimento";
import { makeStyles, radius, spacing, useTheme } from "@/src/theme";
import { t } from "@/src/i18n/core";
import { useIdioma } from "@/src/i18n";

type Slot = { weekday: number; hora_inicio: string; hora_fim: string };

const diasDaSemana = () => [t("Seg"), t("Ter"), t("Qua"), t("Qui"), t("Sex"), t("Sáb"), t("Dom")];
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
  useIdioma();
  const styles = useStyles();
  const { colors } = useTheme();
  const insets = useSafeAreaInsets();
  const router = useRouter();
  const auth = useAuth();
  const qc = useQueryClient();
  // Volta da autorização do Mercado Pago: showup://configuracoes?mercadopago=ok (ou o motivo de não ter dado certo).
  const { mercadopago: retornoMp } = useLocalSearchParams<{ mercadopago?: string }>();
  useEffect(() => {
    const msg = mensagemDoRetorno(retornoMp);
    if (msg) {
      qc.invalidateQueries({ queryKey: ["recebimento"] });
      auth.refresh();
      Alert.alert("Mercado Pago", msg);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [retornoMp]);

  // O onboarding do Connect abre no navegador do SISTEMA (fora do app —
  // ver o comentário em openExternalCheckout sobre por quê), então não
  // tem como saber exatamente quando o usuário termina lá. O jeito que
  // sobra: toda vez que o app volta pro primeiro plano, revalida o status
  // — se o profissional realmente completou o cadastro, a tela atualiza
  // sozinha na próxima vez que ele olhar pra ela, sem precisar puxar pra
  // atualizar manualmente.
  useEffect(() => {
    const sub = AppState.addEventListener("change", (nextState) => {
      if (nextState === "active") {
        qc.invalidateQueries({ queryKey: ["connect-status"] });
        qc.invalidateQueries({ queryKey: ["recebimento"] });
      }
    });
    return () => sub.remove();
  }, [qc]);

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
    queryFn: () => api<{ categorias: string[]; grupos?: { grupo: string; categorias: string[] }[]; maximo?: number }>("/api/categorias"),
  });

  const timezonesQ = useQuery({
    queryKey: ["timezones-list"],
    queryFn: () => api<{ timezones: string[]; grupos?: { grupo: string; timezones: string[] }[] }>("/api/timezones"),
  });

  const moedasQ = useQuery({
    queryKey: ["moedas-list"],
    queryFn: () => api<{ moedas: string[]; moedas_de_recebimento?: string[]; adicional_conversao_bps?: number }>("/api/moedas"),
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
  // Os horários do servidor entram na tela UMA vez. Antes, cada nova busca (ao voltar para a tela, por exemplo)
  // sobrescrevia o que a pessoa estava editando e ainda não tinha salvo.
  const [slotsCarregados, setSlotsCarregados] = useState(false);
  if (!slotsCarregados && dispQ.data?.slots) {
    setSlotsCarregados(true);
    setSlots(dispQ.data.slots);
  }

  const connectQ = useQuery({
    queryKey: ["connect-status"],
    queryFn: () => api<ConnectStatus>("/api/me/connect"),
    enabled: auth.status === "authenticated" && auth.user.role === "profissional",
  });

  const recebimentoQ = useQuery({
    queryKey: ["recebimento"],
    queryFn: () => api<RecebimentoStatus>("/api/me/recebimento"),
    enabled: auth.status === "authenticated" && auth.user.role === "profissional",
  });

  const escolherRecebimentoM = useMutation({
    mutationFn: (metodo: MetodoRecebimento) =>
      api<RecebimentoStatus>("/api/me/recebimento", { method: "PUT", body: JSON.stringify({ metodo }) }),
    onSuccess: (st) => {
      qc.setQueryData(["recebimento"], st);
      auth.refresh();
    },
    onError: (err: unknown) => {
      Alert.alert(t("Não foi possível trocar"), err instanceof ApiError ? err.message : t("Tente de novo."));
    },
  });

  // A autorização do Mercado Pago abre no navegador do sistema; o retorno cai em showup://configuracoes (ver o useEffect acima).
  const conectarMpM = useMutation({
    mutationFn: async () => {
      const r = await api<{ url: string }>("/api/me/mercadopago/conectar", { method: "POST" });
      await Linking.openURL(r.url);
    },
    onError: (err: unknown) => {
      Alert.alert(t("Não foi possível conectar"), err instanceof ApiError ? err.message : t("Não foi possível conectar o Mercado Pago. Tente de novo."));
    },
  });

  const desconectarMpM = useMutation({
    mutationFn: () => api("/api/me/mercadopago", { method: "DELETE" }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["recebimento"] });
      auth.refresh();
    },
    onError: (err: unknown) => {
      Alert.alert(t("Não foi possível desconectar"), err instanceof ApiError ? err.message : t("Tente de novo."));
    },
  });

  const confirmarDesconexao = () =>
    Alert.alert(t("Desconectar Mercado Pago?"), t("Os próximos agendamentos voltam a ser recebidos pelo Stripe."), [
      { text: t("Cancelar"), style: "cancel" },
      { text: t("Desconectar"), style: "destructive", onPress: () => desconectarMpM.mutate() },
    ]);

  const recebePeloMp = recebimentoQ.data?.metodo === "mercadopago";

  const avisarErroAoSalvar = (err: unknown) =>
    Alert.alert(t("Não foi possível salvar"), err instanceof ApiError ? err.message : t("Sem conexão com o servidor. Confira a internet e tente de novo."));

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
    onError: avisarErroAoSalvar,
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
    onError: avisarErroAoSalvar,
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
    onError: avisarErroAoSalvar,
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
    onError: avisarErroAoSalvar,
  });

  const connectM = useMutation({
    mutationFn: () =>
      openExternalCheckout(
        "/(app)/perfil",
        (returnUrl, refreshUrl) =>
          api<{ url: string }>(
            `/api/me/connect/onboarding?return_url=${encodeURIComponent(returnUrl)}&refresh_url=${encodeURIComponent(refreshUrl)}`,
            { method: "POST" },
          ).then((r) => r.url),
        undefined,
        true, // navegador do sistema — ver o comentário em openExternalCheckout
      ),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["connect-status"] }),
    onError: (err: unknown) => {
      // Antes essa falha ficava muda — o botão só voltava ao normal sem
      // dizer por quê. Mostra a mensagem real (do backend, se veio uma;
      // senão a mensagem genérica do erro), pra dar pra diagnosticar.
      const msg = err instanceof ApiError ? err.message : t("Não foi possível abrir o Stripe. Tente de novo.");
      Alert.alert(t("Não foi possível conectar"), msg);
    },
  });

  // O painel do Stripe é onde aparecem as "Tasks" que o Stripe cria depois do
  // cadastro (informações adicionais, revisão) — o onboarding não cobre isso.
  // Ao voltar pro app, o listener de AppState lá em cima revalida o estado.
  const painelM = useMutation({
    mutationFn: async () => {
      const r = await api<{ url: string }>("/api/me/connect/painel", { method: "POST" });
      await Linking.openURL(r.url);
    },
    onError: (err: unknown) => {
      const msg = err instanceof ApiError ? err.message : t("Não foi possível abrir o painel do Stripe. Tente de novo.");
      Alert.alert(t("Não foi possível abrir o painel"), msg);
    },
  });

  // Listas por grupo vêm do servidor (sem `grupos`, um servidor antigo: tudo numa seção só).
  const maxCats = catsQ.data?.maximo ?? 3;
  const secoesCats = (catsQ.data?.grupos ?? [{ grupo: "", categorias: catsQ.data?.categorias ?? [] }]).map((g) => ({
    titulo: g.grupo ? nomeDoGrupo(g.grupo) : "",
    opcoes: g.categorias.map((c) => ({ valor: c, rotulo: nomeDaCategoria(c) })),
  }));
  const secoesTz = (timezonesQ.data?.grupos ?? [{ grupo: "", timezones: timezonesQ.data?.timezones ?? [] }]).map((g) => ({
    titulo: g.grupo ? nomeDoGrupoFuso(g.grupo) : "",
    opcoes: g.timezones.map((tz) => ({ valor: tz, rotulo: rotuloDoFuso(tz) })),
  }));

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
      <Text style={styles.title}>{t("Meu perfil profissional")}</Text>
      <Text style={styles.subtitle}>{t("Defina categorias, disponibilidade e ative repasses automáticos.")}</Text>

      <ScrollView contentContainerStyle={{ paddingBottom: spacing.xxl }}>
        {saved ? (
          <View style={styles.saved}>
            <Text style={styles.savedText}>{t("Salvo ✓")}</Text>
          </View>
        ) : null}

        <Text style={styles.sectionTitle}>{t("CATEGORIAS (até {{max}})", { max: maxCats })}</Text>
        <View style={{ paddingHorizontal: spacing.xl, marginBottom: spacing.md }}>
          <DropdownMultiGrupos
            testID="seletor-categorias"
            icone="pricetags-outline"
            titulo={t("Categoria")}
            textoVazio={t("Escolher categorias")}
            valores={selectedCats}
            secoes={secoesCats}
            maximo={maxCats}
            onChange={setSelectedCats}
            textoMaximo={t("Você pode escolher até {{max}} categorias. Desmarque uma para escolher outra.", { max: maxCats })}
            rotuloContagem={(n) => t("{{n}} de {{max}} selecionadas", { n, max: maxCats })}
            textoConcluir={t("Concluir")}
          />
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
              <Text style={styles.ctaText}>{t("Salvar categorias")}</Text>
            )}
          </Pressable>
        </View>

        <Text style={styles.sectionTitle}>{t("FUSO HORÁRIO")}</Text>
        <Text style={[styles.connectBody, { paddingHorizontal: spacing.xl, marginBottom: spacing.sm }]}>{t("Os horários que você cadastra em disponibilidade usam este fuso como referência.")}</Text>
        <View style={{ paddingHorizontal: spacing.xl, marginBottom: spacing.md }}>
          <DropdownGrupos testID="seletor-fuso" icone="time-outline" titulo={t("Fuso horário")} valor={selectedTz} secoes={secoesTz} onChange={setSelectedTz} />
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
              <Text style={styles.ctaText}>{t("Salvar fuso horário")}</Text>
            )}
          </Pressable>
        </View>

        <Text style={styles.sectionTitle}>{t("MOEDA")}</Text>
        <Text style={[styles.connectBody, { paddingHorizontal: spacing.xl, marginBottom: spacing.sm }]}>{t("Moeda em que você recebe. Só afeta serviços criados a partir de agora.")}</Text>
        <View style={{ paddingHorizontal: spacing.xl, marginBottom: spacing.md }}>
          <SeletorMoeda valor={selectedMoeda} moedas={moedasQ.data?.moedas ?? [selectedMoeda]} onChange={setSelectedMoeda} />
          {avisoDeConversao(selectedMoeda, moedasQ.data?.moedas_de_recebimento, moedasQ.data?.adicional_conversao_bps) ? (
            <Text testID="aviso-conversao" style={[styles.connectBody, { marginTop: spacing.sm, color: colors.warning }]}>
              {avisoDeConversao(selectedMoeda, moedasQ.data?.moedas_de_recebimento, moedasQ.data?.adicional_conversao_bps)}
            </Text>
          ) : null}
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
              <Text style={styles.ctaText}>{t("Salvar moeda")}</Text>
            )}
          </Pressable>
        </View>

        <Text style={styles.sectionTitle}>{t("DISPONIBILIDADE SEMANAL")}</Text>
        <Text testID="resumo-janela-agenda" style={[styles.connectBody, { paddingHorizontal: spacing.xl, marginBottom: spacing.sm }]}>
          {resumoJanelaAgenda(slots, recebimentoQ.data?.reserva_dias ?? 7).texto}
        </Text>
        {slots.map((s, i) => (
          <View key={i} style={styles.slotRow}>
            <Pressable
              testID={`slot-day-${i}`}
              onPress={() => updateSlot(i, { weekday: (s.weekday + 1) % 7 })}
              style={{ minWidth: 52 }}
            >
              <Text style={styles.slotDay}>{diasDaSemana()[s.weekday]}</Text>
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
          <Text style={styles.addSlotText}>{t("Adicionar horário")}</Text>
        </Pressable>
        <View style={{ paddingHorizontal: spacing.xl, marginTop: spacing.md }}>
          <Pressable
            testID="save-disp"
            disabled={saveDispM.isPending || !slotsCarregados}
            onPress={() => saveDispM.mutate(slots)}
            style={[styles.cta, { height: 44 }, (saveDispM.isPending || !slotsCarregados) && styles.ctaDisabled]}
          >
            {saveDispM.isPending ? (
              <ActivityIndicator color={colors.onBrandPrimary} />
            ) : (
              <Text style={styles.ctaText}>{t("Salvar disponibilidade")}</Text>
            )}
          </Pressable>
        </View>

        {recebimentoQ.data?.mercadopago_disponivel ? (
          <>
            <Text style={styles.sectionTitle}>{t("ONDE VOCÊ RECEBE")}</Text>
            <RecebimentoCard
              status={recebimentoQ.data}
              ocupado={escolherRecebimentoM.isPending || conectarMpM.isPending || desconectarMpM.isPending}
              onEscolher={(m) => escolherRecebimentoM.mutate(m)}
              onConectarMercadoPago={() => conectarMpM.mutate()}
              onDesconectarMercadoPago={confirmarDesconexao}
            />
          </>
        ) : null}

        {!recebePeloMp ? (
          <>
            <Text style={styles.sectionTitle}>{t("REPASSE AUTOMÁTICO (STRIPE CONNECT)")}</Text>
            <ConnectCard
              status={connectQ.data}
              ocupado={connectM.isPending || painelM.isPending}
              recarregando={connectQ.isFetching}
              onConectar={() => connectM.mutate()}
              onPainel={() => painelM.mutate()}
              onRecarregar={() => connectQ.refetch()}
            />
          </>
        ) : null}
      </ScrollView>
    </View>
  );
}
