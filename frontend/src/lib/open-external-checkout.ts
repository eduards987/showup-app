// Abre um fluxo hospedado no navegador (Stripe Checkout, Connect
// onboarding) e volta pro app quando o usuário termina. App é mobile-only
// (sem build web), então isso sempre usa o browser controlado nativo — sem
// nenhum branch de plataforma.

import * as Linking from "expo-linking";
import * as WebBrowser from "expo-web-browser";

/**
 * @param fetchUrl recebe (returnUrl, cancelUrl) já prontas pro deep link de
 *   volta, e deve retornar a URL do Stripe pra abrir (via chamada à API).
 * @param onReturn chamado depois que o navegador fecha e o app retoma —
 *   tipicamente pra invalidar/refazer a query que mostra o estado atualizado
 *   (ex: plano ativo, conta Connect pronta).
 */
export async function openExternalCheckout(
  path: string,
  fetchUrl: (returnUrl: string, cancelUrl: string) => Promise<string>,
  onReturn?: () => void,
): Promise<void> {
  const returnUrl = Linking.createURL(path);
  const url = await fetchUrl(returnUrl, returnUrl);

  // openAuthSessionAsync abre um browser controlado (SFSafariViewController /
  // Chrome Custom Tabs) e resolve sozinho quando o Stripe redireciona de
  // volta pro nosso esquema de deep link. Capturamos o resultado — antes
  // isso era ignorado, então uma falha ao abrir (ex: nenhum navegador
  // compatível com Custom Tabs disponível) desaparecia silenciosamente,
  // sem log nem erro nenhum pro usuário.
  const result = await WebBrowser.openAuthSessionAsync(url, returnUrl);
  if (result.type !== "success" && result.type !== "dismiss") {
    console.warn("[openExternalCheckout] navegador não abriu como esperado:", result);
    throw new Error(
      result.type === "cancel"
        ? "O navegador foi fechado antes de terminar."
        : `Não foi possível abrir o navegador (${result.type}).`,
    );
  }
  onReturn?.();
}
