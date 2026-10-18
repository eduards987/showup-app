// Abre um fluxo hospedado no navegador (Stripe Checkout, Connect
// onboarding) e volta pro app quando o usuário termina. App é mobile-only
// (sem build web), então isso sempre roda num navegador nativo — nunca no
// web. Dois modos: embutido dentro do app (padrão) ou o navegador de
// verdade do celular, saindo do app (ver useSystemBrowser abaixo).

import * as Linking from "expo-linking";
import * as WebBrowser from "expo-web-browser";

import { URL_SITE } from "@/src/lib/legal";

// O AccountLink do Stripe (usado pro onboarding do Connect) só aceita
// return_url/refresh_url http(s) de verdade — recusa esquemas customizados
// tipo "showup://" com 400 "Not a valid URL" (confirmado testando; é uma
// limitação documentada do Stripe, não um bug nosso). Por isso passamos
// pro Stripe uma página-ponte hospedada (https), que só repassa de volta
// pro nosso deep link de verdade assim que carrega no navegador do
// celular — o expo-web-browser intercepta esse redirect final e fecha a
// sessão sozinho, exatamente como faria com o deep link direto.
const STRIPE_BOUNCE_URL = `${URL_SITE}/stripe-bounce`;

/**
 * @param fetchUrl recebe (returnUrl, cancelUrl) já prontas pro deep link de
 *   volta, e deve retornar a URL do Stripe pra abrir (via chamada à API).
 * @param onReturn chamado depois que o navegador fecha e o app retoma —
 *   tipicamente pra invalidar/refazer a query que mostra o estado atualizado
 *   (ex: plano ativo, conta Connect pronta).
 * @param useSystemBrowser abre o navegador de verdade do celular (o app
 *   Chrome/Samsung Internet/etc que o usuário já usa pra tudo, fora do
 *   nosso app) em vez do embutido. Só existe por causa de um bug
 *   reproduzido no onboarding hospedado do Stripe Connect: a etapa de
 *   "Date of birth" trava com "Sorry, something went wrong" dentro do
 *   navegador embutido no Android — a MESMA conta, o MESMO link,
 *   completa sem erro nenhum no navegador de verdade do computador.
 *   IMPORTANTE: WebBrowser.openBrowserAsync NÃO serve pra isso — a
 *   própria doc do Expo confirma que no Android ele SEMPRE abre via
 *   "custom Chrome tabs" por baixo, o mesmo mecanismo de
 *   openAuthSessionAsync só com outro nome; teria o mesmo bug. Quem
 *   realmente tira a página do contexto embutido do app é
 *   Linking.openURL — abre o navegador PADRÃO de verdade, como usuário
 *   tocando num link fora do app. Sacrifica fluidez (o app perde
 *   controle de quando a aba fecha — o usuário volta manualmente), mas é
 *   a única forma de evitar esse travamento enquanto o Stripe não
 *   corrige a própria página. Pagamento (Stripe Checkout) nunca teve
 *   esse problema — é só o onboarding do Connect — então o padrão
 *   continua sendo o navegador embutido.
 */
export async function openExternalCheckout(
  path: string,
  fetchUrl: (returnUrl: string, cancelUrl: string) => Promise<string>,
  onReturn?: () => void,
  useSystemBrowser = false,
): Promise<void> {
  const deepLink = Linking.createURL(path);
  const bounceUrl = `${STRIPE_BOUNCE_URL}?next=${encodeURIComponent(deepLink)}`;
  const url = await fetchUrl(bounceUrl, bounceUrl);

  if (useSystemBrowser) {
    // Linking.openURL sai do app de verdade — sem Promise que espera o
    // usuário voltar (isso nem existe fora do próprio app). onReturn
    // dispara logo depois de abrir, não quando o onboarding termina —
    // quem chama isso não pode contar com onReturn pra saber que o
    // usuário terminou. Ver o listener de AppState em configuracoes.tsx,
    // que cobre esse caso revalidando o status ao voltar pro app.
    await Linking.openURL(url);
    onReturn?.();
    return;
  }

  // openAuthSessionAsync continua de olho no deep link DIRETO (não na
  // página-ponte) — é ele que o SO intercepta de verdade quando a
  // ponte redireciona no final.
  const result = await WebBrowser.openAuthSessionAsync(url, deepLink);
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
