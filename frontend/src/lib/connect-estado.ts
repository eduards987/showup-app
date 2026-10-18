import { t } from "@/src/i18n/core";
// Textos e ação de cada estado da conta conectada do Stripe. Lógica PURA (sem
// React Native) de propósito: dá pra testar com node e é o que decide o que o
// profissional lê quando o Stripe trava a conta dele.

export type ConnectEstado =
  | "nao_conectada"
  | "pendente_informacoes"
  | "em_analise"
  | "restrita"
  | "recusada"
  | "ativa"
  | "indisponivel";

export type ConnectStatus = {
  account_id?: string | null;
  charges_enabled: boolean;
  payouts_enabled: boolean;
  details_submitted: boolean;
  estado: ConnectEstado;
  pendencias: string[];
  motivo_bloqueio?: string | null;
};

/** O que o botão faz: refaz o cadastro, abre o painel do Stripe ou só reconsulta. */
export type ConnectAcao = "onboarding" | "painel" | "recarregar" | null;
export type ConnectVisual = "ok" | "atencao" | "espera" | "erro";

export type ConnectDescricao = {
  titulo: string;
  corpo: string;
  aviso: string | null;
  visual: ConnectVisual;
  acao: ConnectAcao;
  acaoLabel: string;
  pendencias: string[];
};

// Códigos de `requirements` do Stripe -> o que o profissional entende. Casa
// primeiro pelo código exato e depois pelo prefixo (individual.address.* etc.).
function rotuloExato(codigo: string): string | undefined {
  switch (codigo) {
    case "external_account": return t("Conta bancária para receber");
    case "business_type": return t("Tipo de conta");
    case "individual.id_number": return t("CPF");
    case "individual.phone": return t("Telefone");
    case "individual.email": return t("E-mail");
    case "individual.first_name":
    case "individual.last_name": return t("Nome completo");
    case "individual.verification.document": return t("Foto do documento de identidade");
    case "individual.verification.additional_document": return t("Documento adicional");
    default: return undefined;
  }
}
// Casa pelo prefixo (individual.address.* etc.) quando não há código exato; a ordem importa.
function rotuloPorPrefixo(codigo: string): string | undefined {
  if (codigo.startsWith("individual.dob")) return t("Data de nascimento");
  if (codigo.startsWith("individual.address")) return t("Endereço");
  if (codigo.startsWith("individual.verification")) return t("Verificação de identidade");
  if (codigo.startsWith("business_profile")) return t("Informações sobre o seu negócio");
  if (codigo.startsWith("tos_acceptance")) return t("Aceite dos termos do Stripe");
  return undefined;
}
const outrasPendencias = () => t("Outras informações pedidas pelo Stripe");

/** Resume os códigos do Stripe em rótulos legíveis, sem repetir. */
export function resumirPendencias(codigos: string[]): string[] {
  const rotulos: string[] = [];
  const outras = outrasPendencias();
  for (const codigo of codigos) {
    const rotulo = rotuloExato(codigo) ?? rotuloPorPrefixo(codigo) ?? outras;
    if (!rotulos.includes(rotulo)) rotulos.push(rotulo);
  }
  // "Outras" sempre por último
  return rotulos.sort((a, b) => Number(a === outras) - Number(b === outras));
}

const avisoNaoLiberada = () => t("Enquanto a conta não estiver liberada, novos agendamentos podem ficar indisponíveis.");

export function descreverConnect(s: ConnectStatus | undefined): ConnectDescricao {
  if (!s) {
    return { titulo: t("Verificando sua conta…"), corpo: "", aviso: null, visual: "espera", acao: null, acaoLabel: "", pendencias: [] };
  }
  const pendencias = resumirPendencias(s.pendencias ?? []);
  switch (s.estado) {
    case "ativa":
      return {
        titulo: t("Conta conectada"),
        corpo:
          t("Repasse automático ativo: a cada atendimento cobrado, a taxa do ShowUp é descontada e o restante vai direto para a sua conta."),
        aviso: null, visual: "ok", acao: null, acaoLabel: "", pendencias: [],
      };
    case "pendente_informacoes":
      return {
        titulo: t("O Stripe precisa de mais informações"),
        corpo: pendencias.length
          ? t("Para liberar seus repasses, falta enviar:")
          : t("Falta concluir o seu cadastro no Stripe para liberar os repasses."),
        aviso: avisoNaoLiberada(),
        visual: "atencao",
        acao: s.details_submitted ? "painel" : "onboarding",
        acaoLabel: s.details_submitted ? t("Enviar informações") : t("Continuar cadastro"),
        pendencias,
      };
    case "em_analise":
      return {
        titulo: t("O Stripe está analisando sua conta"),
        corpo:
          t("Isso pode levar alguns dias. Você não precisa fazer nada agora — assim que for liberada, os repasses começam sozinhos."),
        aviso: avisoNaoLiberada(), visual: "espera", acao: "painel", acaoLabel: t("Ver andamento no Stripe"), pendencias: [],
      };
    case "restrita":
      return {
        titulo: t("Repasses pausados pelo Stripe"),
        corpo: t("O Stripe pausou os repasses desta conta. Abra o painel para ver o motivo e o que fazer."),
        aviso: avisoNaoLiberada(), visual: "atencao", acao: "painel", acaoLabel: t("Abrir painel do Stripe"), pendencias,
      };
    case "recusada":
      return {
        titulo: t("O Stripe não habilitou esta conta"),
        corpo:
          t("O Stripe não conseguiu liberar esta conta para receber pagamentos. Abra o painel para ver o motivo ou fale com o suporte do Stripe."),
        aviso: avisoNaoLiberada(), visual: "erro", acao: "painel", acaoLabel: t("Ver motivo no Stripe"), pendencias: [],
      };
    case "indisponivel":
      return {
        titulo: t("Não conseguimos consultar o Stripe"),
        corpo: t("Isso costuma ser passageiro. Tente de novo em instantes."),
        aviso: null, visual: "atencao", acao: "recarregar", acaoLabel: t("Tentar de novo"), pendencias: [],
      };
    case "nao_conectada":
    default:
      return {
        titulo: t("Conta não conectada"),
        corpo:
          t("Conecte sua conta do Stripe para receber os pagamentos automaticamente. O cadastro leva poucos minutos: o Stripe pede seus dados e um documento, como exige a lei para quem recebe pagamentos."),
        aviso: avisoNaoLiberada(), visual: "atencao", acao: "onboarding", acaoLabel: t("Conectar Stripe"), pendencias: [],
      };
  }
}
