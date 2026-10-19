// Cliente only: search professionals + category filter.

import Ionicons from "@react-native-vector-icons/ionicons";
import { useQuery } from "@tanstack/react-query";
import { useRouter } from "expo-router";
import { useState } from "react";
import {
  ActivityIndicator,
  FlatList,
  Pressable,
  ScrollView,
  Text,
  TextInput,
  View,
} from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import { api } from "@/src/lib/api";
import { nomeDaCategoria, nomeDoGrupo } from "@/src/lib/categorias";
import { DropdownGrupos } from "@/src/components/dropdown";
import { ProfissionalPublic } from "@/src/lib/types";
import { makeStyles, radius, spacing, useTheme } from "@/src/theme";
import { t } from "@/src/i18n/core";
import { useIdioma } from "@/src/i18n";

const useStyles = makeStyles((c) => ({
  root: { flex: 1, backgroundColor: c.surface },
  header: { paddingHorizontal: spacing.xl, paddingTop: spacing.lg, paddingBottom: spacing.md },
  title: { fontSize: 24, fontWeight: "700", color: c.onSurface },
  subtitle: { fontSize: 14, color: c.muted, marginTop: spacing.xs },
  searchWrap: {
    marginHorizontal: spacing.xl,
    marginTop: spacing.md,
    height: 48,
    borderRadius: radius.md,
    backgroundColor: c.surfaceSecondary,
    borderWidth: 1,
    borderColor: c.border,
    flexDirection: "row",
    alignItems: "center",
    paddingHorizontal: spacing.md,
    gap: spacing.sm,
  },
  input: { flex: 1, fontSize: 15, color: c.onSurfaceSecondary },
  chip: {
    height: 36,
    paddingHorizontal: spacing.md,
    borderRadius: radius.pill,
    backgroundColor: c.surfaceSecondary,
    borderWidth: 1,
    borderColor: c.border,
    alignItems: "center",
    justifyContent: "center",
    flexShrink: 0,
  },
  chipActive: { backgroundColor: c.brandPrimary, borderColor: c.brandPrimary },
  chipText: { color: c.onSurfaceSecondary, fontSize: 13, fontWeight: "600" },
  chipTextActive: { color: c.onBrandPrimary },
  item: {
    marginHorizontal: spacing.xl,
    marginTop: spacing.md,
    padding: spacing.lg,
    backgroundColor: c.surfaceSecondary,
    borderRadius: radius.lg,
    borderWidth: 1,
    borderColor: c.border,
    flexDirection: "row",
    alignItems: "center",
    gap: spacing.md,
  },
  avatar: {
    width: 48,
    height: 48,
    borderRadius: radius.pill,
    backgroundColor: c.brandTertiary,
    alignItems: "center",
    justifyContent: "center",
  },
  avatarText: { color: c.brandPrimary, fontWeight: "700", fontSize: 18 },
  itemName: { fontSize: 16, fontWeight: "700", color: c.onSurfaceSecondary },
  itemMeta: { fontSize: 13, color: c.muted, marginTop: 2 },
  catRow: { flexDirection: "row", flexWrap: "wrap", gap: 4, marginTop: 4 },
  catTag: {
    paddingHorizontal: 8,
    paddingVertical: 2,
    borderRadius: radius.pill,
    backgroundColor: c.brandTertiary,
  },
  catTagText: { color: c.onBrandTertiary, fontSize: 10, fontWeight: "700" },
  empty: {
    marginHorizontal: spacing.xl,
    padding: spacing.xl,
    backgroundColor: c.surfaceTertiary,
    borderRadius: radius.lg,
    alignItems: "center",
    gap: spacing.xs,
    marginTop: spacing.xl,
  },
  emptyTitle: { fontSize: 15, fontWeight: "700", color: c.onSurfaceTertiary },
  emptyBody: { fontSize: 13, color: c.muted, textAlign: "center" },
}));

export default function Search() {
  useIdioma();
  const styles = useStyles();
  const { colors } = useTheme();
  const insets = useSafeAreaInsets();
  const router = useRouter();
  const [q, setQ] = useState("");
  const [cat, setCat] = useState<string | null>(null);

  // A lista de categorias vem do servidor (a mesma da tela do profissional): uma cópia fixa aqui ficaria desatualizada.
  const catsQ = useQuery({ queryKey: ["categorias-list"], queryFn: () => api<{ categorias: string[]; grupos?: { grupo: string; categorias: string[] }[] }>("/api/categorias"), staleTime: Infinity });
  const secoesCats = (catsQ.data?.grupos ?? [{ grupo: "", categorias: catsQ.data?.categorias ?? [] }]).map((g) => ({
    titulo: g.grupo ? nomeDoGrupo(g.grupo) : "",
    opcoes: g.categorias.map((c) => ({ valor: c, rotulo: nomeDaCategoria(c) })),
  }));
  const listQ = useQuery({
    queryKey: ["profissionais", q, cat],
    queryFn: () => {
      const params = new URLSearchParams();
      if (q) params.set("q", q);
      if (cat) params.set("categoria", cat);
      const s = params.toString();
      return api<ProfissionalPublic[]>(`/api/profissionais${s ? `?${s}` : ""}`);
    },
  });

  return (
    <View style={[styles.root, { paddingTop: insets.top }]}>
      <View style={styles.header}>
        <Text style={styles.title}>{t("Buscar profissionais")}</Text>
        <Text style={styles.subtitle}>{t("Filtre por categoria ou nome.")}</Text>
      </View>
      <View style={styles.searchWrap}>
        <Ionicons name="search" size={18} color={colors.muted} />
        <TextInput
          testID="search-input"
          value={q}
          onChangeText={setQ}
          placeholder={t("Nome do profissional")}
          placeholderTextColor={colors.muted}
          style={styles.input}
          autoCorrect={false}
        />
      </View>

      <View style={{ paddingHorizontal: spacing.xl, paddingVertical: spacing.md }}>
        <DropdownGrupos
          testID="seletor-categoria-busca"
          icone="pricetags-outline"
          titulo={t("Categoria")}
          valor={cat ?? ""}
          secoes={[{ titulo: "", opcoes: [{ valor: "", rotulo: t("Todos") }] }, ...secoesCats]}
          onChange={(v) => setCat(v === "" ? null : v)}
        />
      </View>

      {listQ.isLoading ? (
        <ActivityIndicator style={{ marginTop: spacing.xl }} color={colors.brandPrimary} />
      ) : (listQ.data?.length ?? 0) === 0 ? (
        <View style={styles.empty} testID="search-empty">
          <Ionicons name="people-outline" size={28} color={colors.muted} />
          <Text style={styles.emptyTitle}>{t("Nenhum profissional")}</Text>
          <Text style={styles.emptyBody}>
            {cat ? t("Tente outra categoria.") : t("Nenhum profissional com serviços ativos.")}
          </Text>
        </View>
      ) : (
        <FlatList
          data={listQ.data ?? []}
          keyExtractor={(p) => p.user_id}
          contentContainerStyle={{ paddingBottom: spacing.xxl }}
          renderItem={({ item }) => (
            <Pressable
              testID={`profissional-${item.user_id}`}
              onPress={() => router.push(`/(app)/profissional/${item.user_id}`)}
              style={styles.item}
            >
              <View style={styles.avatar}>
                <Text style={styles.avatarText}>
                  {item.name.split(" ").map((s) => s[0]).slice(0, 2).join("").toUpperCase()}
                </Text>
              </View>
              <View style={{ flex: 1 }}>
                <Text style={styles.itemName}>{item.name}</Text>
                <Text style={styles.itemMeta}>{item.servicos_count}{" "}{t("serviço(s) disponíveis")}</Text>
                {item.categorias.length > 0 ? (
                  <View style={styles.catRow}>
                    {item.categorias.map((c) => (
                      <View key={c} style={styles.catTag}>
                        <Text style={styles.catTagText}>{nomeDaCategoria(c).toUpperCase()}</Text>
                      </View>
                    ))}
                  </View>
                ) : null}
              </View>
              <Ionicons name="chevron-forward" size={18} color={colors.muted} />
            </Pressable>
          )}
        />
      )}
    </View>
  );
}
