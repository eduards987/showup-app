// Bloco "Onde receber": Stripe ou Mercado Pago (só Brasil). Mostra as duas opções com o que muda em cada uma e
// conecta a conta do Mercado Pago (autorização no navegador). Os textos vêm de src/lib/recebimento.ts.

import Ionicons from "@react-native-vector-icons/ionicons";
import { ActivityIndicator, Pressable, Text, View } from "react-native";

import { useIdioma } from "@/src/i18n";
import { t } from "@/src/i18n/core";
import { explicarOpcoes, MetodoRecebimento, RecebimentoStatus } from "@/src/lib/recebimento";
import { makeStyles, radius, spacing, useTheme } from "@/src/theme";

const useStyles = makeStyles((c) => ({
  wrap: { marginHorizontal: spacing.xl, gap: spacing.sm, marginBottom: spacing.md },
  opcao: {
    padding: spacing.lg,
    backgroundColor: c.surfaceSecondary,
    borderRadius: radius.lg,
    borderWidth: 1,
    borderColor: c.border,
    gap: 6,
  },
  opcaoAtiva: { borderColor: c.brandPrimary, borderWidth: 2 },
  row: { flexDirection: "row", alignItems: "center", gap: spacing.sm },
  titulo: { fontSize: 14, fontWeight: "700", color: c.onSurfaceSecondary, flexShrink: 1 },
  corpo: { fontSize: 13, color: c.muted, lineHeight: 18 },
  link: { fontSize: 13, color: c.error, fontWeight: "600", marginTop: spacing.xs },
}));

type Props = {
  status: RecebimentoStatus;
  ocupado: boolean;
  onEscolher: (metodo: MetodoRecebimento) => void;
  onConectarMercadoPago: () => void;
  onDesconectarMercadoPago: () => void;
};

export function RecebimentoCard({ status, ocupado, onEscolher, onConectarMercadoPago, onDesconectarMercadoPago }: Props) {
  useIdioma();
  const styles = useStyles();
  const { colors } = useTheme();
  const textos = explicarOpcoes(status);
  const opcoes: { metodo: MetodoRecebimento; titulo: string }[] = [
    { metodo: "stripe", titulo: "Stripe" },              // nome de marca: igual em todos os idiomas
    { metodo: "mercadopago", titulo: "Mercado Pago" },
  ];

  return (
    <View style={styles.wrap}>
      {opcoes.map(({ metodo, titulo }) => {
        const ativo = status.metodo === metodo;
        const escolher = () => {
          if (ativo || ocupado) return;
          if (metodo === "mercadopago" && !status.mercadopago_conectado) onConectarMercadoPago();
          else onEscolher(metodo);
        };
        return (
          <Pressable key={metodo} testID={`recebimento-${metodo}`} onPress={escolher} style={[styles.opcao, ativo && styles.opcaoAtiva]}>
            <View style={styles.row}>
              <Ionicons
                name={ativo ? "radio-button-on" : "radio-button-off"}
                size={18}
                color={ativo ? colors.brandPrimary : colors.muted}
              />
              <Text style={styles.titulo}>{titulo}</Text>
              {ocupado && !ativo ? <ActivityIndicator size="small" color={colors.brandPrimary} /> : null}
            </View>
            <Text style={styles.corpo}>{textos[metodo]}</Text>
            {metodo === "mercadopago" && !status.mercadopago_conectado ? (
              <Text style={styles.corpo}>{t("Toque para conectar sua conta do Mercado Pago.")}</Text>
            ) : null}
            {metodo === "mercadopago" && status.mercadopago_conectado ? (
              <Pressable testID="desconectar-mercadopago" disabled={ocupado} onPress={onDesconectarMercadoPago}>
                <Text style={styles.link}>{t("Desconectar Mercado Pago")}</Text>
              </Pressable>
            ) : null}
          </Pressable>
        );
      })}
    </View>
  );
}
