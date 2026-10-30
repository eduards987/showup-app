// Bloco "Notificações" das configurações do profissional: explica quais avisos ele recebe e tem o botão de teste, que
// percorre as etapas (celular, permissão, código do aparelho, registro, envio, entrega) e mostra ✓ ou ✗ em cada uma.
// Quando a notificação não chega, a lista diz exatamente onde parou e o que fazer.

import Ionicons from "@react-native-vector-icons/ionicons";
import * as Clipboard from "expo-clipboard";
import { useState } from "react";
import { ActivityIndicator, Pressable, Text, View } from "react-native";

import { acaoFinal, EstadoPasso, PassoDiagnostico } from "@/src/lib/notificacoes-erros";
import { diagnosticarNotificacoes } from "@/src/lib/push-notifications";
import { makeStyles, radius, spacing, useTheme } from "@/src/theme";
import { t } from "@/src/i18n/core";
import { useIdioma } from "@/src/i18n";

const useStyles = makeStyles((c) => ({
  card: {
    marginHorizontal: spacing.xl,
    padding: spacing.lg,
    backgroundColor: c.surfaceSecondary,
    borderRadius: radius.lg,
    borderWidth: 1,
    borderColor: c.border,
    gap: spacing.sm,
  },
  row: { flexDirection: "row", alignItems: "center", gap: spacing.sm },
  titulo: { fontSize: 14, fontWeight: "700", color: c.onSurfaceSecondary, flexShrink: 1 },
  corpo: { fontSize: 13, color: c.muted, lineHeight: 18 },
  item: { fontSize: 13, color: c.onSurfaceSecondary, lineHeight: 18 },
  btn: {
    marginTop: spacing.sm,
    height: 42,
    borderRadius: radius.md,
    backgroundColor: c.brand,
    alignItems: "center",
    justifyContent: "center",
    flexDirection: "row",
    gap: 6,
  },
  btnText: { color: c.onBrand, fontSize: 13, fontWeight: "700" },
  btnSecundario: { alignSelf: "flex-start", paddingVertical: spacing.xs },
  btnSecundarioTexto: { fontSize: 12, color: c.onSurface, textDecorationLine: "underline" },
  passos: { marginTop: spacing.sm, gap: spacing.xs },
  passoLinha: { flexDirection: "row", alignItems: "flex-start", gap: spacing.sm },
  passoIcone: { width: 20, alignItems: "center", paddingTop: 1 },
  passoTitulo: { fontSize: 13, color: c.onSurfaceSecondary, lineHeight: 18 },
  passoDetalhe: { fontSize: 12, color: c.muted, lineHeight: 17 },
  resultado: { fontSize: 13, lineHeight: 18, fontWeight: "600", marginTop: spacing.xs },
}));

export function NotificacoesCard() {
  useIdioma();
  const styles = useStyles();
  const { colors } = useTheme();
  const [carregando, setCarregando] = useState(false);
  const [passos, setPassos] = useState<PassoDiagnostico[] | null>(null);
  const [token, setToken] = useState<string | null>(null);
  const [copiado, setCopiado] = useState(false);

  const testar = async () => {
    setCarregando(true);
    setCopiado(false);
    setPassos(null);
    try {
      const r = await diagnosticarNotificacoes(setPassos);
      setPassos(r.passos);
      setToken(r.token);
    } catch {
      setPassos([{ id: "envio", titulo: t("Teste de notificação"), estado: "falhou", detalhe: t("Não foi possível fazer o teste agora. Tente de novo.") }]);
    } finally {
      setCarregando(false);
    }
  };

  const copiarToken = async () => {
    if (!token) return;
    await Clipboard.setStringAsync(token);
    setCopiado(true);
  };

  const icone = (estado: EstadoPasso) => {
    if (estado === "executando") return <ActivityIndicator size="small" color={colors.muted} />;
    const nome = {
      ok: "checkmark-circle", falhou: "close-circle", pendente: "time-outline", pulado: "remove-circle-outline", aguardando: "ellipse-outline",
    }[estado] as "checkmark-circle";
    const cor = estado === "ok" ? colors.success : estado === "falhou" ? colors.error : colors.muted;
    return <Ionicons name={nome} size={18} color={cor} />;
  };

  const conclusao = passos && !carregando ? acaoFinal(passos) : null;

  return (
    <View style={styles.card} testID="notificacoes-card">
      <View style={styles.row}>
        <Ionicons name="notifications-outline" size={22} color={colors.onSurfaceSecondary} />
        <Text style={styles.titulo}>{t("Avisos no celular")}</Text>
      </View>
      <Text style={styles.corpo}>{t("Você recebe uma notificação:")}</Text>
      <Text style={styles.item}>{t("• quando entra um novo agendamento;")}</Text>
      <Text style={styles.item}>{t("• pouco antes do próximo atendimento;")}</Text>
      <Text style={styles.item}>{t("• quando precisa confirmar se o cliente compareceu.")}</Text>

      <Pressable testID="testar-notificacoes" onPress={testar} disabled={carregando} style={styles.btn}>
        {carregando ? (
          <ActivityIndicator color={colors.onBrand} />
        ) : (
          <>
            <Ionicons name="paper-plane-outline" size={16} color={colors.onBrand} />
            <Text style={styles.btnText}>{t("Enviar notificação de teste")}</Text>
          </>
        )}
      </Pressable>

      {passos ? (
        <View style={styles.passos} testID="passos-notificacao">
          {passos.map((p) => (
            <View key={p.id} style={styles.passoLinha}>
              <View style={styles.passoIcone}>{icone(p.estado)}</View>
              <View style={{ flex: 1 }}>
                <Text style={styles.passoTitulo}>{p.titulo}</Text>
                {p.estado === "ok" && p.detalhe ? <Text style={styles.passoDetalhe}>{p.detalhe}</Text> : null}
              </View>
            </View>
          ))}
        </View>
      ) : null}

      {conclusao ? (
        <Text testID="resultado-notificacao" style={[styles.resultado, { color: conclusao.ok ? colors.success : colors.error }]}>
          {conclusao.texto}
        </Text>
      ) : null}

      {token && !carregando ? (
        <Pressable testID="copiar-token" onPress={copiarToken} style={styles.btnSecundario}>
          <Text style={styles.btnSecundarioTexto}>
            {copiado ? "Copiado! Cole em expo.dev/notifications para testar direto na Expo." : t("Copiar o código do aparelho (para testar pela Expo)")}
          </Text>
        </Pressable>
      ) : null}
    </View>
  );
}
