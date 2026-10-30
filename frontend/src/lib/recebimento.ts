import { t } from "@/src/i18n/core";
// Onde o profissional recebe: Stripe ou Mercado Pago (só Brasil). Lógica PURA (sem React Native): testável no Node.
// A regra de verdade (taxa menor, reserva de 5 dias, só reais) fica no servidor; isto só explica as opções na tela.

export type MetodoRecebimento = "stripe" | "mercadopago";

export type RecebimentoStatus = {
  metodo: MetodoRecebimento;
  mercadopago_disponivel: boolean;
  mercadopago_conectado: boolean;
  desconto_mercadopago_bps: number;
  reserva_dias: number;
  reserva_dias_stripe: number;
  reserva_dias_mercadopago: number;
};

export function pontos(bps: number): string {
  return String(Math.round(bps) / 100);
}

export function explicarOpcoes(st: RecebimentoStatus): Record<MetodoRecebimento, string> {
  return {
    stripe: t("O ShowUp paga a tarifa do cartão. A reserva no cartão vale {{dias}} dias. Aceita outras moedas.", {
      dias: st.reserva_dias_stripe,
    }),
    mercadopago: t(
      "A tarifa do Mercado Pago sai do seu valor e a taxa do ShowUp fica {{pontos}} pontos menor. A reserva no cartão vale {{dias}} dias, então a agenda abre menos dias à frente. Só reais, com Pix.",
      { pontos: pontos(st.desconto_mercadopago_bps), dias: st.reserva_dias_mercadopago },
    ),
  };
}

/** Mensagem depois de voltar da tela de autorização do Mercado Pago (showup://configuracoes?mercadopago=...). */
export function mensagemDoRetorno(resultado: string | undefined): string | null {
  if (!resultado) return null;
  if (resultado === "ok") return t("Mercado Pago conectado. Os próximos agendamentos já caem na sua conta do Mercado Pago.");
  if (resultado === "conta_em_uso") return t("Essa conta do Mercado Pago já está ligada a outro profissional no ShowUp.");
  if (resultado === "cancelado") return t("Você não autorizou o ShowUp no Mercado Pago. Nada mudou.");
  return t("Não foi possível conectar o Mercado Pago. Tente de novo.");
}
