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
 * (o valor em reais varia um pouco). DECISÃO (29/10/2026): nessas moedas a taxa do ShowUp tem um ADICIONAL (ADICIONAL_CONVERSAO_BPS no
 * servidor) para cobrir a conversão e o cartão internacional. `moedasDeRecebimento` e `adicionalBps` vêm do servidor (GET /api/moedas).
 * Sem conversão: null.
 */
export const ADICIONAL_CONVERSAO_BPS_PADRAO = 400;

export function avisoDeConversao(
  moeda: string,
  moedasDeRecebimento: string[] = MOEDAS_DE_RECEBIMENTO_PADRAO,
  adicionalBps: number = ADICIONAL_CONVERSAO_BPS_PADRAO,
): string | null {
  if (!moeda || moedasDeRecebimento.includes(moeda)) return null;
  // sem Intl/toLocaleString (Hermes): 400 -> "4", 250 -> "2.5"
  const adicional = String(Math.round(adicionalBps) / 100);
  return t("O valor cobrado em {{moeda}} é convertido para reais pelo Stripe, pela cotação do dia, então o que você recebe em reais pode variar um pouco. Para cobrir a conversão e o cartão internacional, a taxa do ShowUp nos agendamentos nesta moeda tem {{adicional}} pontos percentuais a mais.", { moeda, adicional });
}

/** "BRL · Real brasileiro" — o que aparece na lista suspensa. */
export function rotuloDaMoeda(codigo: string): string {
  const nome = nomeDaMoeda(codigo);
  return nome === codigo ? codigo : `${codigo} · ${nome}`;
}
