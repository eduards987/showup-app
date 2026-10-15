// Bloco "Repasse automático (Stripe Connect)": diz em que pé está a conta do
// profissional no Stripe e oferece o próximo passo (conectar, enviar o que
// falta, abrir o painel). Os textos e a ação de cada estado vêm de
// src/lib/connect-estado.ts.

import Ionicons from "@react-native-vector-icons/ionicons";
import { ActivityIndicator, Pressable, Text, View } from "react-native";

import { ConnectStatus, ConnectVisual, descreverConnect } from "@/src/lib/connect-estado";
import { makeStyles, radius, spacing, useTheme } from "@/src/theme";

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
  aviso: { fontSize: 12, color: c.muted, lineHeight: 17, fontStyle: "italic" },
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
}));

const ICONES = {
  ok: "checkmark-circle",
  atencao: "alert-circle-outline",
  espera: "time-outline",
  erro: "close-circle-outline",
} as const satisfies Record<ConnectVisual, string>;

type Props = {
  status: ConnectStatus | undefined;
  /** Alguma ação (conectar / abrir painel) em andamento. */
  ocupado: boolean;
  /** A consulta ao Stripe está sendo refeita (botão "Tentar de novo"). */
  recarregando: boolean;
  onConectar: () => void;
  onPainel: () => void;
  onRecarregar: () => void;
};

export function ConnectCard({ status, ocupado, recarregando, onConectar, onPainel, onRecarregar }: Props) {
  const styles = useStyles();
  const { colors } = useTheme();
  const d = descreverConnect(status);

  const cor: Record<ConnectVisual, string> = {
    ok: colors.success,
    atencao: colors.warning,
    espera: colors.muted,
    erro: colors.error,
  };
  const acionar = d.acao === "onboarding" ? onConectar : d.acao === "painel" ? onPainel : onRecarregar;
  const emAndamento = ocupado || (d.acao === "recarregar" && recarregando);

  return (
    <View style={styles.card} testID="connect-card">
      <View style={styles.row}>
        {status ? (
          <Ionicons name={ICONES[d.visual]} size={22} color={cor[d.visual]} />
        ) : (
          <ActivityIndicator color={colors.muted} />
        )}
        <Text style={styles.titulo}>{d.titulo}</Text>
      </View>

      {d.corpo ? <Text style={styles.corpo}>{d.corpo}</Text> : null}
      {d.pendencias.map((p) => (
        <Text key={p} style={styles.item}>
          • {p}
        </Text>
      ))}
      {d.aviso ? <Text style={styles.aviso}>{d.aviso}</Text> : null}

      {d.acao ? (
        <Pressable
          testID={d.acao === "onboarding" ? "connect-onboarding" : `connect-${d.acao}`}
          onPress={acionar}
          disabled={emAndamento}
          style={styles.btn}
        >
          {emAndamento ? (
            <ActivityIndicator color={colors.onBrand} />
          ) : (
            <>
              <Ionicons
                name={d.acao === "onboarding" ? "link-outline" : d.acao === "painel" ? "open-outline" : "refresh-outline"}
                size={16}
                color={colors.onBrand}
              />
              <Text style={styles.btnText}>{d.acaoLabel}</Text>
            </>
          )}
        </Pressable>
      ) : null}
    </View>
  );
}
