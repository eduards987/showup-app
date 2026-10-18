// Moedas que o app aceita (a lista oficial vem do servidor, GET /api/moedas) e o nome de cada uma no idioma atual.
// Os nomes são função (não constante): o idioma pode mudar com o app aberto.
import { t } from "@/src/i18n/core";

export function nomeDaMoeda(codigo: string): string {
  switch (codigo) {
    case "BRL": return t("Real brasileiro");
    case "USD": return t("Dólar americano");
    case "EUR": return t("Euro");
    case "GBP": return t("Libra esterlina");
    case "MXN": return t("Peso mexicano");
    case "ARS": return t("Peso argentino");
    case "COP": return t("Peso colombiano");
    case "CAD": return t("Dólar canadense");
    case "AUD": return t("Dólar australiano");
    default: return codigo;
  }
}

/** Enquanto o servidor não informar, a conta Stripe (brasileira) só deposita em reais. */
export const MOEDAS_DE_RECEBIMENTO_PADRAO = ["BRL"];

/**
 * Aviso para o profissional que cobra numa moeda em que o Stripe NÃO deposita na conta dele: o Stripe converte para reais pela cotação do dia
 * (o valor em reais varia um pouco). DECISÃO: o ShowUp absorve a taxa de conversão do Stripe; o profissional não paga nada a mais e a taxa
 * do ShowUp não muda. Se um dia o profissional passar a pagar a conversão, ESTE texto precisa mudar junto.
 * `moedasDeRecebimento` vem do servidor (GET /api/moedas). Sem conversão: null.
 */
export function avisoDeConversao(moeda: string, moedasDeRecebimento: string[] = MOEDAS_DE_RECEBIMENTO_PADRAO): string | null {
  if (!moeda || moedasDeRecebimento.includes(moeda)) return null;
  return t("O valor cobrado em {{moeda}} é convertido para reais pelo Stripe, pela cotação do dia, então o que você recebe em reais pode variar um pouco. O ShowUp não cobra nada a mais pela conversão e a sua taxa continua a mesma.", { moeda });
}

/** "BRL · Real brasileiro" — o que aparece na lista suspensa. */
export function rotuloDaMoeda(codigo: string): string {
  const nome = nomeDaMoeda(codigo);
  return nome === codigo ? codigo : `${codigo} · ${nome}`;
}
