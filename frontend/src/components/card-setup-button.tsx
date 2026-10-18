// Coleta de cartão real via Stripe Payment Sheet — app é mobile-only, sem
// build web, então não precisamos de nenhum guard/fallback de plataforma
// aqui: sempre roda em iOS/Android.

import Ionicons from "@react-native-vector-icons/ionicons";
import { useStripe } from "@stripe/stripe-react-native";
import { useState } from "react";
import { ActivityIndicator, Pressable, Text } from "react-native";

import { api } from "@/src/lib/api";
import { makeStyles, useTheme } from "@/src/theme";
import { t } from "@/src/i18n/core";
import { useIdioma } from "@/src/i18n";

const useStyles = makeStyles((c) => ({
  cta: {
    flexDirection: "row",
    gap: 8,
    height: 44,
    borderRadius: 10,
    backgroundColor: c.brandPrimary,
    alignItems: "center",
    justifyContent: "center",
    marginTop: 12,
  },
  ctaText: { color: c.onBrandPrimary, fontSize: 14, fontWeight: "700" },
  errorText: { color: c.onError, fontSize: 12, marginTop: 8, textAlign: "center" },
}));

export function CardSetupButton({ onSaved }: { onSaved: () => void }) {
  useIdioma();
  const styles = useStyles();
  const { colors } = useTheme();
  const { initPaymentSheet, presentPaymentSheet } = useStripe();
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handlePress = async () => {
    setError(null);
    setLoading(true);
    try {
      const setup = await api<{
        customer_id: string;
        ephemeral_key_secret: string;
        setup_intent_client_secret: string;
      }>("/api/me/card/setup-intent", { method: "POST" });

      const { error: initError } = await initPaymentSheet({
        merchantDisplayName: "ShowUp",
        customerId: setup.customer_id,
        customerEphemeralKeySecret: setup.ephemeral_key_secret,
        setupIntentClientSecret: setup.setup_intent_client_secret,
      });
      if (initError) throw new Error(initError.message);

      const { error: presentError } = await presentPaymentSheet();
      if (presentError) {
        // Usuário cancelou ou o cartão foi recusado pelo próprio Payment
        // Sheet — não é um bug nosso, só não fecha com sucesso.
        if (presentError.code !== "Canceled") setError(presentError.message);
        return;
      }

      // client_secret tem o formato "seti_xxx_secret_yyy" — o ID do
      // SetupIntent é tudo antes de "_secret_".
      const setupIntentId = setup.setup_intent_client_secret.split("_secret_")[0];
      await api("/api/me/card/confirm", {
        method: "POST",
        body: JSON.stringify({ setup_intent_id: setupIntentId }),
      });
      onSaved();
    } catch (e: any) {
      setError(e?.message || t("Falha ao salvar cartão"));
    } finally {
      setLoading(false);
    }
  };

  return (
    <>
      <Pressable testID="save-card-btn" onPress={handlePress} disabled={loading} style={styles.cta}>
        {loading ? (
          <ActivityIndicator color={colors.onBrandPrimary} />
        ) : (
          <>
            <Ionicons name="add-circle-outline" size={18} color={colors.onBrandPrimary} />
            <Text style={styles.ctaText}>{t("Adicionar cartão")}</Text>
          </>
        )}
      </Pressable>
      {error ? <Text style={styles.errorText}>{error}</Text> : null}
    </>
  );
}
