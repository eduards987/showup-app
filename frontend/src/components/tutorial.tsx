// Mini tutorial animado (profissional ou cliente): abre logo depois do cadastro e pode ser revisto no Perfil. Dá para
// pular a qualquer momento. Os passos vêm de src/lib/tutorial.ts. Animações com Reanimated (já no app): cada passo entra deslizando, os exemplos
// aparecem um depois do outro, o ícone "respira" e a barra de progresso anda. Quem pede menos movimento no celular
// (acessibilidade) vê tudo sem animação: o Reanimated respeita essa configuração do sistema.

import Ionicons from "@react-native-vector-icons/ionicons";
import { useEffect, useState } from "react";
import { Modal, Pressable, Text, View } from "react-native";
import Animated, {
  FadeInDown,
  FadeInRight,
  FadeOutLeft,
  useAnimatedStyle,
  useSharedValue,
  withRepeat,
  withSequence,
  withTiming,
} from "react-native-reanimated";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import { useIdioma } from "@/src/i18n";
import { t } from "@/src/i18n/core";
import { destinoAoTerminar, passosDoTutorial, textoDoUltimoBotao, type Papel } from "@/src/lib/tutorial";
import { makeStyles, radius, spacing, useTheme } from "@/src/theme";

const useStyles = makeStyles((c) => ({
  fundo: { flex: 1, backgroundColor: c.surface, paddingHorizontal: spacing.xl },
  topo: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", paddingVertical: spacing.md },
  contador: { fontSize: 13, color: c.muted, fontWeight: "600" },
  pular: { fontSize: 14, color: c.muted, fontWeight: "600", padding: spacing.sm },
  trilho: { height: 4, borderRadius: radius.pill, backgroundColor: c.brandTertiary, overflow: "hidden" },
  barra: { height: 4, borderRadius: radius.pill, backgroundColor: c.brandPrimary },
  meio: { flex: 1, justifyContent: "center", alignItems: "center", gap: spacing.lg },
  circulo: {
    width: 112,
    height: 112,
    borderRadius: 56,
    backgroundColor: c.brandTertiary,
    alignItems: "center",
    justifyContent: "center",
  },
  titulo: { fontSize: 22, fontWeight: "700", color: c.onSurface, textAlign: "center" },
  texto: { fontSize: 15, color: c.muted, textAlign: "center", lineHeight: 22 },
  exemplos: { gap: spacing.sm, alignSelf: "stretch", marginTop: spacing.sm },
  exemplo: {
    paddingVertical: spacing.md,
    paddingHorizontal: spacing.lg,
    borderRadius: radius.md,
    backgroundColor: c.surfaceSecondary,
    borderWidth: 1,
    borderColor: c.border,
    flexDirection: "row",
    alignItems: "center",
    gap: spacing.sm,
  },
  exemploTexto: { fontSize: 14, color: c.onSurfaceSecondary, fontWeight: "600", flexShrink: 1 },
  rodape: { flexDirection: "row", gap: spacing.md, paddingVertical: spacing.lg },
  voltar: {
    flex: 1,
    height: 52,
    borderRadius: radius.md,
    borderWidth: 1,
    borderColor: c.border,
    alignItems: "center",
    justifyContent: "center",
  },
  voltarTexto: { fontSize: 15, fontWeight: "700", color: c.onSurface },
  avancar: { flex: 2, height: 52, borderRadius: radius.md, backgroundColor: c.brandPrimary, alignItems: "center", justifyContent: "center" },
  avancarTexto: { fontSize: 15, fontWeight: "700", color: c.onBrandPrimary },
}));

function IconeRespirando({ nome }: { nome: string }) {
  const styles = useStyles();
  const { colors } = useTheme();
  const escala = useSharedValue(1);
  useEffect(() => {
    escala.value = withRepeat(withSequence(withTiming(1.08, { duration: 700 }), withTiming(1, { duration: 700 })), -1);
  }, [escala]);
  const estilo = useAnimatedStyle(() => ({ transform: [{ scale: escala.value }] }));
  return (
    <Animated.View style={[styles.circulo, estilo]}>
      <Ionicons name={nome as never} size={52} color={colors.brandPrimary} />
    </Animated.View>
  );
}

type Props = {
  papel: Papel;
  visivel: boolean;
  onFechar: () => void;
  /** No último passo: leva ao primeiro passo de verdade (profissional: novo serviço; cliente: busca). Recebe a rota. */
  onComecar?: (rota: string) => void;
};

export function Tutorial({ papel, visivel, onFechar, onComecar }: Props) {
  useIdioma();
  const styles = useStyles();
  const { colors } = useTheme();
  const insets = useSafeAreaInsets();
  const passos = passosDoTutorial(papel);
  const [i, setI] = useState(0);
  const progresso = useSharedValue(0);

  // Abriu de novo: volta ao primeiro passo (ajustado durante o desenho, como o React recomenda, não num efeito).
  const [visivelAntes, setVisivelAntes] = useState(visivel);
  if (visivel !== visivelAntes) {
    setVisivelAntes(visivel);
    if (visivel) setI(0);
  }
  useEffect(() => {
    progresso.value = withTiming((i + 1) / passos.length, { duration: 350 });
  }, [i, passos.length, progresso]);
  const estiloBarra = useAnimatedStyle(() => ({ width: `${progresso.value * 100}%` }));

  const passo = passos[i];
  const ultimo = i === passos.length - 1;
  const avancar = () => {
    if (!ultimo) {
      setI(i + 1);
      return;
    }
    onFechar();
    onComecar?.(destinoAoTerminar(papel));
  };

  return (
    <Modal visible={visivel} animationType="slide" onRequestClose={onFechar} statusBarTranslucent>
      <View testID={`tutorial-${papel}`} style={[styles.fundo, { paddingTop: insets.top, paddingBottom: insets.bottom }]}>
        <View style={styles.topo}>
          <Text style={styles.contador}>{t("Passo {{n}} de {{total}}", { n: i + 1, total: passos.length })}</Text>
          <Pressable testID="tutorial-pular" onPress={onFechar} hitSlop={12}>
            <Text style={styles.pular}>{t("Pular")}</Text>
          </Pressable>
        </View>
        <View style={styles.trilho}>
          <Animated.View style={[styles.barra, estiloBarra]} />
        </View>

        {/* key = passo atual: trocar de passo refaz as animações de entrada */}
        <Animated.View key={i} entering={FadeInRight.duration(320)} exiting={FadeOutLeft.duration(200)} style={styles.meio}>
          <IconeRespirando nome={passo.icone} />
          <Text style={styles.titulo}>{passo.titulo}</Text>
          <Text style={styles.texto}>{passo.texto}</Text>
          <View style={styles.exemplos}>
            {passo.exemplos.map((ex, n) => (
              <Animated.View key={ex} entering={FadeInDown.delay(250 + n * 220).duration(380)} style={styles.exemplo}>
                <Ionicons name="checkmark-circle" size={18} color={colors.brandPrimary} />
                <Text style={styles.exemploTexto}>{ex}</Text>
              </Animated.View>
            ))}
          </View>
        </Animated.View>

        <View style={styles.rodape}>
          {i > 0 ? (
            <Pressable testID="tutorial-voltar" onPress={() => setI(i - 1)} style={styles.voltar}>
              <Text style={styles.voltarTexto}>{t("Voltar")}</Text>
            </Pressable>
          ) : null}
          <Pressable testID="tutorial-avancar" onPress={avancar} style={styles.avancar}>
            <Text style={styles.avancarTexto}>{ultimo ? textoDoUltimoBotao(papel) : t("Próximo")}</Text>
          </Pressable>
        </View>
      </View>
    </Modal>
  );
}
