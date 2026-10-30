// Avisos padrão das telas que buscam dados: carregando e "não foi possível carregar" (com Tentar de novo).
// Quando mostrar cada um: estadoDaConsulta em src/lib/estado-consulta.ts.

import Ionicons from "@react-native-vector-icons/ionicons";
import { ActivityIndicator, Pressable, Text, View } from "react-native";

import { useIdioma } from "@/src/i18n";
import { t } from "@/src/i18n/core";
import { makeStyles, radius, spacing, useTheme } from "@/src/theme";

const useStyles = makeStyles((c) => ({
  caixa: {
    marginHorizontal: spacing.xl,
    marginTop: spacing.md,
    padding: spacing.xl,
    backgroundColor: c.surfaceTertiary,
    borderRadius: radius.lg,
    alignItems: "center",
    gap: spacing.xs,
  },
  titulo: { fontSize: 15, fontWeight: "700", color: c.onSurfaceTertiary, textAlign: "center" },
  texto: { fontSize: 13, color: c.muted, textAlign: "center" },
  botao: {
    marginTop: spacing.sm,
    paddingHorizontal: spacing.lg,
    paddingVertical: spacing.sm,
    borderRadius: radius.md,
    backgroundColor: c.brandPrimary,
  },
  botaoTexto: { color: c.onBrandPrimary, fontSize: 14, fontWeight: "700" },
}));

export function ErroAoCarregar({ onTentar, testID = "erro-carregar" }: { onTentar: () => void; testID?: string }) {
  useIdioma();
  const styles = useStyles();
  const { colors } = useTheme();
  return (
    <View style={styles.caixa} testID={testID}>
      <Ionicons name="cloud-offline-outline" size={28} color={colors.muted} />
      <Text style={styles.titulo}>{t("Não foi possível carregar")}</Text>
      <Text style={styles.texto}>{t("Confira a internet e tente de novo.")}</Text>
      <Pressable testID={`${testID}-tentar`} onPress={onTentar} style={styles.botao} accessibilityRole="button">
        <Text style={styles.botaoTexto}>{t("Tentar de novo")}</Text>
      </Pressable>
    </View>
  );
}

export function Carregando() {
  const { colors } = useTheme();
  return <ActivityIndicator color={colors.brandPrimary} style={{ marginTop: spacing.xl }} />;
}
