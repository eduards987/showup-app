// Lista suspensa (dropdown) reutilizável: mostra o valor escolhido num campo e abre uma lista para trocar.
// Usada para o idioma e para a moeda.
import { alternarComLimite } from "@/src/lib/selecao";
import Ionicons from "@react-native-vector-icons/ionicons";
import { useState } from "react";
import { FlatList, Modal, Pressable, SectionList, Text, View } from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import { makeStyles, radius, spacing, useTheme } from "@/src/theme";

export type OpcaoDropdown<T extends string> = { valor: T; rotulo: string };
export type SecaoDropdown<T extends string> = { titulo: string; opcoes: OpcaoDropdown<T>[] };
export type IconeDropdown = "globe-outline" | "cash-outline" | "time-outline" | "pricetags-outline";

interface Props<T extends string> {
  /** Título da lista aberta (ex.: "Idioma"). */
  titulo: string;
  valor: T | null | undefined;
  opcoes: OpcaoDropdown<T>[];
  onChange: (novo: T) => void;
  /** "campo" = caixa larga (formulários); "pilula" = botão pequeno (cantos de tela). */
  variante?: "campo" | "pilula";
  /** Ícone à esquerda (nome do Ionicons). */
  icone?: IconeDropdown;
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
  secao: { backgroundColor: c.surfaceSecondary, paddingHorizontal: spacing.xl, paddingVertical: spacing.sm },
  secaoTexto: { color: c.muted, fontSize: 12, fontWeight: "700", letterSpacing: 0.6 },
  rodape: { borderTopWidth: 1, borderTopColor: c.border, paddingHorizontal: spacing.xl, paddingTop: spacing.md, gap: spacing.sm },
  rodapeLinha: { flexDirection: "row", alignItems: "center", justifyContent: "space-between" },
  contagem: { color: c.onSurface, fontSize: 14, fontWeight: "600" },
  aviso: { color: c.warning, fontSize: 13 },
  concluir: { backgroundColor: c.brand, borderRadius: radius.md, paddingHorizontal: spacing.xl, minHeight: 44, alignItems: "center", justifyContent: "center" },
  concluirTexto: { color: c.onBrand, fontSize: 15, fontWeight: "700" },
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


/** Lista suspensa de ESCOLHA ÚNICA com os itens separados por grupo (título do grupo em destaque). Seção com título vazio não mostra cabeçalho. */
interface PropsGrupos<T extends string> {
  titulo: string;
  valor: T | null | undefined;
  secoes: SecaoDropdown<T>[];
  onChange: (novo: T) => void;
  icone?: IconeDropdown;
  testID?: string;
}

export function DropdownGrupos<T extends string>({ titulo, valor, secoes, onChange, icone, testID }: PropsGrupos<T>) {
  const styles = useStyles();
  const { colors } = useTheme();
  const insets = useSafeAreaInsets();
  const [aberto, setAberto] = useState(false);
  const atual = secoes.flatMap((s) => s.opcoes).find((o) => o.valor === valor);

  return (
    <>
      <Pressable testID={testID} accessibilityRole="button" accessibilityLabel={`${titulo}: ${atual?.rotulo ?? ""}`} onPress={() => setAberto(true)} style={styles.campo}>
        {icone ? <Ionicons name={icone} size={20} color={colors.onSurface} /> : null}
        <Text numberOfLines={1} style={styles.texto}>{atual?.rotulo ?? valor ?? ""}</Text>
        <Ionicons name="chevron-down" size={18} color={colors.muted} />
      </Pressable>
      <Modal visible={aberto} transparent animationType="fade" onRequestClose={() => setAberto(false)}>
        <Pressable style={styles.fundo} onPress={() => setAberto(false)} accessibilityLabel="fechar">
          <Pressable style={[styles.folha, { paddingBottom: insets.bottom + spacing.md }]} onPress={() => undefined}>
            <Text style={styles.titulo}>{titulo}</Text>
            <SectionList
              sections={secoes.map((s) => ({ title: s.titulo, data: s.opcoes }))}
              keyExtractor={(o) => o.valor}
              stickySectionHeadersEnabled
              initialNumToRender={20}
              renderSectionHeader={({ section }) =>
                section.title ? (
                  <View style={styles.secao}><Text style={styles.secaoTexto}>{section.title.toUpperCase()}</Text></View>
                ) : null
              }
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

/** Lista suspensa de ESCOLHA MÚLTIPLA, por grupo, com limite. No limite, as opções não marcadas ficam apagadas e um aviso explica como trocar. */
interface PropsMulti<T extends string> {
  titulo: string;
  textoVazio: string;
  valores: T[];
  secoes: SecaoDropdown<T>[];
  maximo: number;
  onChange: (novos: T[]) => void;
  textoMaximo: string;
  rotuloContagem: (n: number) => string;
  textoConcluir: string;
  icone?: IconeDropdown;
  testID?: string;
}

export function DropdownMultiGrupos<T extends string>({
  titulo, textoVazio, valores, secoes, maximo, onChange, textoMaximo, rotuloContagem, textoConcluir, icone, testID,
}: PropsMulti<T>) {
  const styles = useStyles();
  const { colors } = useTheme();
  const insets = useSafeAreaInsets();
  const [aberto, setAberto] = useState(false);
  const [tentouPassar, setTentouPassar] = useState(false);
  const todas = secoes.flatMap((s) => s.opcoes);
  const resumo = valores.map((v) => todas.find((o) => o.valor === v)?.rotulo ?? v).join(", ");
  const cheio = valores.length >= maximo;

  const alternar = (v: T) => {
    const r = alternarComLimite(valores, v, maximo);
    setTentouPassar(r.bloqueado);                  // no limite: não marca e mostra por que
    if (!r.bloqueado) onChange(r.valores);
  };

  return (
    <>
      <Pressable
        testID={testID}
        accessibilityRole="button"
        accessibilityLabel={`${titulo}: ${resumo || textoVazio}`}
        onPress={() => { setTentouPassar(false); setAberto(true); }}
        style={styles.campo}
      >
        {icone ? <Ionicons name={icone} size={20} color={colors.onSurface} /> : null}
        <Text numberOfLines={2} style={[styles.texto, !resumo && { color: colors.muted }]}>{resumo || textoVazio}</Text>
        <Ionicons name="chevron-down" size={18} color={colors.muted} />
      </Pressable>
      <Modal visible={aberto} transparent animationType="fade" onRequestClose={() => setAberto(false)}>
        <Pressable style={styles.fundo} onPress={() => setAberto(false)} accessibilityLabel="fechar">
          <Pressable style={[styles.folha, { paddingBottom: insets.bottom + spacing.md }]} onPress={() => undefined}>
            <Text style={styles.titulo}>{titulo}</Text>
            <SectionList
              sections={secoes.map((s) => ({ title: s.titulo, data: s.opcoes }))}
              keyExtractor={(o) => o.valor}
              stickySectionHeadersEnabled
              initialNumToRender={20}
              renderSectionHeader={({ section }) => (
                <View style={styles.secao}><Text style={styles.secaoTexto}>{section.title.toUpperCase()}</Text></View>
              )}
              renderItem={({ item }) => {
                const marcado = valores.includes(item.valor);
                const apagado = cheio && !marcado;
                return (
                  <Pressable
                    testID={testID ? `${testID}-${item.valor}` : undefined}
                    accessibilityRole="checkbox"
                    accessibilityState={{ checked: marcado, disabled: apagado }}
                    onPress={() => alternar(item.valor)}
                    style={[styles.item, apagado && { opacity: 0.45 }]}
                  >
                    <Ionicons name={marcado ? "checkbox" : "square-outline"} size={22} color={marcado ? colors.brand : colors.muted} />
                    <Text style={[styles.itemTexto, marcado && styles.itemAtivo]}>{item.rotulo}</Text>
                  </Pressable>
                );
              }}
            />
            <View style={styles.rodape}>
              {tentouPassar ? <Text testID={testID ? `${testID}-aviso` : undefined} style={styles.aviso}>{textoMaximo}</Text> : null}
              <View style={styles.rodapeLinha}>
                <Text style={styles.contagem}>{rotuloContagem(valores.length)}</Text>
                <Pressable testID={testID ? `${testID}-concluir` : undefined} accessibilityRole="button" onPress={() => setAberto(false)} style={styles.concluir}>
                  <Text style={styles.concluirTexto}>{textoConcluir}</Text>
                </Pressable>
              </View>
            </View>
          </Pressable>
        </Pressable>
      </Modal>
    </>
  );
}
