// Lista suspensa (dropdown) reutilizável: mostra o valor escolhido num campo e abre uma lista para trocar.
// Usada para o idioma e para a moeda.
import Ionicons from "@react-native-vector-icons/ionicons";
import { useState } from "react";
import { FlatList, Modal, Pressable, Text } from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import { makeStyles, radius, spacing, useTheme } from "@/src/theme";

export type OpcaoDropdown<T extends string> = { valor: T; rotulo: string };

interface Props<T extends string> {
  /** Título da lista aberta (ex.: "Idioma"). */
  titulo: string;
  valor: T | null | undefined;
  opcoes: OpcaoDropdown<T>[];
  onChange: (novo: T) => void;
  /** "campo" = caixa larga (formulários); "pilula" = botão pequeno (cantos de tela). */
  variante?: "campo" | "pilula";
  /** Ícone à esquerda (nome do Ionicons). */
  icone?: "globe-outline" | "cash-outline";
  testID?: string;
  desabilitado?: boolean;
}

const useStyles = makeStyles((c) => ({
  campo: {
    minHeight: 48, borderRadius: radius.md, borderWidth: 1, borderColor: c.border, backgroundColor: c.surfaceSecondary,
    paddingHorizontal: spacing.md, flexDirection: "row", alignItems: "center", gap: spacing.sm,
  },
  pilula: {
    minHeight: 36, borderRadius: 999, borderWidth: 1, borderColor: c.border, backgroundColor: c.surfaceSecondary,
    paddingHorizontal: spacing.md, flexDirection: "row", alignItems: "center", gap: 6, alignSelf: "flex-start",
  },
  texto: { flex: 1, color: c.onSurface, fontSize: 15 },
  textoPilula: { color: c.onSurface, fontSize: 13, fontWeight: "600" },
  fundo: { flex: 1, backgroundColor: "rgba(0,0,0,0.45)", justifyContent: "flex-end" },
  folha: { backgroundColor: c.surface, borderTopLeftRadius: radius.lg, borderTopRightRadius: radius.lg, maxHeight: "70%", paddingTop: spacing.md },
  titulo: { fontSize: 16, fontWeight: "700", color: c.onSurface, paddingHorizontal: spacing.xl, paddingBottom: spacing.sm },
  item: { minHeight: 52, paddingHorizontal: spacing.xl, flexDirection: "row", alignItems: "center", gap: spacing.md, borderTopWidth: 1, borderTopColor: c.border },
  itemTexto: { flex: 1, color: c.onSurface, fontSize: 16 },
  itemAtivo: { color: c.brand, fontWeight: "700" },
}));

export function Dropdown<T extends string>({ titulo, valor, opcoes, onChange, variante = "campo", icone, testID, desabilitado }: Props<T>) {
  const styles = useStyles();
  const { colors } = useTheme();
  const insets = useSafeAreaInsets();
  const [aberto, setAberto] = useState(false);
  const atual = opcoes.find((o) => o.valor === valor);

  return (
    <>
      <Pressable
        testID={testID}
        accessibilityRole="button"
        accessibilityLabel={`${titulo}: ${atual?.rotulo ?? ""}`}
        disabled={desabilitado}
        onPress={() => setAberto(true)}
        style={[variante === "pilula" ? styles.pilula : styles.campo, desabilitado && { opacity: 0.5 }]}
      >
        {icone ? <Ionicons name={icone} size={variante === "pilula" ? 16 : 20} color={colors.onSurface} /> : null}
        <Text numberOfLines={1} style={variante === "pilula" ? styles.textoPilula : styles.texto}>{atual?.rotulo ?? valor ?? ""}</Text>
        <Ionicons name="chevron-down" size={variante === "pilula" ? 14 : 18} color={colors.muted} />
      </Pressable>

      <Modal visible={aberto} transparent animationType="fade" onRequestClose={() => setAberto(false)}>
        <Pressable style={styles.fundo} onPress={() => setAberto(false)} accessibilityLabel="fechar">
          {/* o toque dentro da folha não fecha */}
          <Pressable style={[styles.folha, { paddingBottom: insets.bottom + spacing.md }]} onPress={() => undefined}>
            <Text style={styles.titulo}>{titulo}</Text>
            <FlatList
              data={opcoes}
              keyExtractor={(o) => o.valor}
              renderItem={({ item }) => {
                const ativo = item.valor === valor;
                return (
                  <Pressable
                    testID={testID ? `${testID}-${item.valor}` : undefined}
                    accessibilityRole="button"
                    onPress={() => {
                      setAberto(false);
                      if (!ativo) onChange(item.valor);
                    }}
                    style={styles.item}
                  >
                    <Text style={[styles.itemTexto, ativo && styles.itemAtivo]}>{item.rotulo}</Text>
                    {ativo ? <Ionicons name="checkmark" size={20} color={colors.brand} /> : null}
                  </Pressable>
                );
              }}
            />
          </Pressable>
        </Pressable>
      </Modal>
    </>
  );
}

