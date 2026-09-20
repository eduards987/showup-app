// App é mobile-only (sem build web) — StripeProvider sempre envolve a
// árvore normalmente. O único guard que resta é "chave ainda não
// configurada", não plataforma.

import { StripeProvider } from "@stripe/stripe-react-native";
import type { ReactElement } from "react";

const STRIPE_PUBLISHABLE_KEY = process.env.EXPO_PUBLIC_STRIPE_PUBLISHABLE_KEY ?? "";

export function MaybeStripeProvider({ children }: { children: ReactElement }) {
  if (!STRIPE_PUBLISHABLE_KEY) return children;
  return <StripeProvider publishableKey={STRIPE_PUBLISHABLE_KEY}>{children}</StripeProvider>;
}
