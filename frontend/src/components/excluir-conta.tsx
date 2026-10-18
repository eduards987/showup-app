// Excluir a própria conta. Vive no PERFIL (que todo tipo de conta acessa): a
// política do Google Play exige que qualquer conta criada no app possa ser
// excluída de dentro dele — e antes isso só existia na tela de configurações do
// profissional, então quem usava o app como cliente não tinha como.

import Ionicons from "@react-native-vector-icons/ionicons";
import { useMutation } from "@tanstack/react-query";
import { ActivityIndicator, Alert, Linking, Pressable, Text, View } from "react-native";

import { api, ApiError } from "@/src/lib/api";
import { useAuth } from "@/src/lib/auth";
import { URL_EXCLUSAO } from "@/src/lib/legal";
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
  row: { flexDirection: "row", alignItems: "center", justifyContent: "center", gap: spacing.sm },
  texto: { fontSize: 15, fontWeight: "600", color: c.error },
  nota: { fontSize: 12, color: c.muted, lineHeight: 17, marginTop: spacing.sm, textAlign: "center" },
  link: { textDecorationLine: "underline" },
}));

export function ExcluirContaCard() {
  useIdioma();
  const styles = useStyles();
  const { colors } = useTheme();
  const auth = useAuth();

  const excluirM = useMutation({
    mutationFn: () => api("/api/me", { method: "DELETE" }),
    onSuccess: () => {
      auth.signOut();
    },
    // A mensagem do servidor é útil aqui: "você tem agendamentos pendentes",
    // "não conseguimos cancelar a cobrança do seu plano agora"...
    onError: (e: unknown) => {
      Alert.alert(t("Não foi possível excluir"), e instanceof ApiError ? e.message : t("Tente novamente."));
    },
  });

  const confirmar = () => {
    Alert.alert(
      t("Excluir sua conta"),
      t("Isso é permanente — seus dados pessoais serão apagados e você não vai conseguir desfazer isso depois. Se você tem um plano pago ou teste grátis, a cobrança será cancelada. Tem certeza?"),
      [
        { text: t("Cancelar"), style: "cancel" },
        { text: t("Excluir conta"), style: "destructive", onPress: () => excluirM.mutate() },
      ],
    );
  };

  return (
    <View style={styles.card}>
      <Pressable testID="excluir-conta" onPress={confirmar} disabled={excluirM.isPending} style={styles.row}>
        {excluirM.isPending ? (
          <ActivityIndicator color={colors.error} />
        ) : (
          <>
            <Ionicons name="trash-outline" size={18} color={colors.error} />
            <Text style={styles.texto}>{t("Excluir minha conta")}</Text>
          </>
        )}
      </Pressable>
      <Text style={styles.nota}>{t("Remove seus dados pessoais permanentemente. Agendamentos pendentes ou futuros precisam ser resolvidos antes.")}{" "}
        <Text style={styles.link} onPress={() => Linking.openURL(URL_EXCLUSAO)}>{t("Saiba mais")}</Text>
      </Text>
    </View>
  );
}
