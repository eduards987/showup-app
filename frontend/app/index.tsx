// Root gate. This is the ONLY place auth navigation is decided.
// Follows Critical Rule 13 from the auth playbook.

import { Redirect } from "expo-router";
import { ActivityIndicator, StyleSheet, View } from "react-native";

import { useAuth } from "@/src/lib/auth";
import { useTheme } from "@/src/theme";

export default function Index() {
  const auth = useAuth();
  const { colors } = useTheme();

  if (auth.status === "loading") {
    return (
      <View
        testID="auth-loading-screen"
        style={[styles.center, { backgroundColor: colors.surface }]}
      >
        <ActivityIndicator size="large" color={colors.brandPrimary} />
      </View>
    );
  }

  if (auth.status === "unauthenticated") {
    return <Redirect href="/welcome" />;
  }

  if (!auth.user.role) {
    return <Redirect href="/role-select" />;
  }

  return <Redirect href="/(app)/home" />;
}

const styles = StyleSheet.create({
  center: { flex: 1, alignItems: "center", justifyContent: "center" },
});
