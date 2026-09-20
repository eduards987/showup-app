// Design tokens for ShowUp. Light theme only.

import { useMemo } from "react";
import { Appearance, StyleSheet, useColorScheme } from "react-native";

export type ColorScheme = "light" | "dark";

const light = {
  // Surfaces
  surface: "#F7F6F2",
  onSurface: "#1A1C1A",
  surfaceSecondary: "#FFFFFF",
  onSurfaceSecondary: "#1A1C1A",
  surfaceTertiary: "#EAE8E3",
  onSurfaceTertiary: "#424543",
  surfaceInverse: "#2C2E2D",
  onSurfaceInverse: "#FFFFFF",
  muted: "#8A8D8B",

  // Brand — azul-verde (logo ShowUp: monograma S/U + check)
  brand: "#4C97C1",
  onBrand: "#FFFFFF",
  brandPrimary: "#4C97C1",
  onBrandPrimary: "#FFFFFF",
  brandSecondary: "#7FB667",
  onBrandSecondary: "#FFFFFF",
  brandTertiary: "#E4EFF6",
  onBrandTertiary: "#255170",

  // Status
  success: "#34C759",
  onSuccess: "#FFFFFF",
  warning: "#FF9F0A",
  onWarning: "#FFFFFF",
  error: "#FF3B30",
  onError: "#FFFFFF",
  info: "#4A4C4B",
  onInfo: "#FFFFFF",

  // Lines
  border: "#E5E3DF",
  borderStrong: "#C2C0BC",
  divider: "#E5E3DF",
};

export type ThemeColors = typeof light;

export const defaultScheme = "light" satisfies ColorScheme;
export const themes: { light: ThemeColors; dark?: ThemeColors } = { light };

export function setColorScheme(scheme: ColorScheme | null) {
  Appearance.setColorScheme?.(scheme ?? "unspecified");
}

setColorScheme?.(themes.dark ? null : defaultScheme);

export function useTheme(): { scheme: ColorScheme; colors: ThemeColors } {
  const system = useColorScheme();
  // useColorScheme() pode devolver "unspecified" (comum no Android) além de
  // "light"/"dark"/null — nenhum desses é uma chave válida de `themes`, daí
  // a checagem explícita em vez de indexar `themes[system]` direto.
  const scheme: ColorScheme = (system === "light" || system === "dark") && themes[system] ? system : defaultScheme;
  return { scheme, colors: themes[scheme] ?? themes.light };
}

export function makeStyles<T extends StyleSheet.NamedStyles<T> | StyleSheet.NamedStyles<any>>(
  factory: (colors: ThemeColors) => T & StyleSheet.NamedStyles<any>,
): () => T {
  return function useStyles(): T {
    const { colors } = useTheme();
    return useMemo(() => StyleSheet.create(factory(colors)), [colors]);
  };
}

// Convenience export for module-level use only when scheme won't change.
export const colors = light;

// Spacing tokens matching design_guidelines.json
export const spacing = {
  xs: 4,
  sm: 8,
  md: 12,
  lg: 16,
  xl: 24,
  xxl: 32,
  xxxl: 48,
};

export const radius = {
  sm: 6,
  md: 12,
  lg: 20,
  pill: 999,
};
