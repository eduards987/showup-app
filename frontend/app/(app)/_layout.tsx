import Ionicons from "@react-native-vector-icons/ionicons";
import { Redirect, Tabs } from "expo-router";

import { useAuth } from "@/src/lib/auth";
import { usePushRegistration } from "@/src/lib/use-push-registration";
import { useTheme } from "@/src/theme";

export default function AppLayout() {
  const auth = useAuth();
  const { colors } = useTheme();
  usePushRegistration();

  if (auth.status === "loading") return null;
  if (auth.status === "unauthenticated") return <Redirect href="/welcome" />;
  if (!auth.user.role) return <Redirect href="/role-select" />;

  const isCliente = auth.user.role === "cliente";

  return (
    <Tabs
      screenOptions={{
        headerShown: false,
        tabBarActiveTintColor: colors.brandPrimary,
        tabBarInactiveTintColor: colors.muted,
        tabBarStyle: {
          backgroundColor: colors.surfaceSecondary,
          borderTopColor: colors.border,
        },
        tabBarItemStyle: { alignSelf: "center" },
        tabBarLabelStyle: { fontSize: 11, fontWeight: "600" },
      }}
    >
      <Tabs.Screen
        name="home"
        options={{
          title: isCliente ? "Início" : "Agenda",
          tabBarIcon: ({ color, size }) => (
            <Ionicons name={isCliente ? "home-outline" : "calendar-outline"} color={color} size={size} />
          ),
        }}
      />
      <Tabs.Screen
        name="search"
        options={{
          href: isCliente ? "/search" : null,
          title: "Buscar",
          tabBarIcon: ({ color, size }) => (
            <Ionicons name="search-outline" color={color} size={size} />
          ),
        }}
      />
      <Tabs.Screen
        name="servicos"
        options={{
          href: !isCliente ? "/servicos" : null,
          title: "Serviços",
          tabBarIcon: ({ color, size }) => (
            <Ionicons name="briefcase-outline" color={color} size={size} />
          ),
        }}
      />
      <Tabs.Screen
        name="agendamentos"
        options={{
          title: "Reservas",
          tabBarIcon: ({ color, size }) => (
            <Ionicons name="list-outline" color={color} size={size} />
          ),
        }}
      />
      <Tabs.Screen
        name="perfil"
        options={{
          title: "Perfil",
          tabBarIcon: ({ color, size }) => (
            <Ionicons name="person-outline" color={color} size={size} />
          ),
        }}
      />
      {/* Non-tab routes registered to avoid layout warnings */}
      <Tabs.Screen name="profissional/[id]" options={{ href: null }} />
      <Tabs.Screen name="book/[servicoId]" options={{ href: null }} />
      <Tabs.Screen name="agendamento/[id]" options={{ href: null }} />
      <Tabs.Screen name="novo-servico" options={{ href: null }} />
      <Tabs.Screen name="configuracoes" options={{ href: null }} />
    </Tabs>
  );
}
