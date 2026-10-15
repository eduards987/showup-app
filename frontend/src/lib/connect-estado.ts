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
const PENDENCIAS_EXATAS: Record<string, string> = {
  external_account: "Conta bancária para receber",
  business_type: "Tipo de conta",
  "individual.id_number": "CPF",
  "individual.phone": "Telefone",
  "individual.email": "E-mail",
  "individual.first_name": "Nome completo",
  "individual.last_name": "Nome completo",
  "individual.verification.document": "Foto do documento de identidade",
  "individual.verification.additional_document": "Documento adicional",
};
const PENDENCIAS_PREFIXO: Array<[string, string]> = [
  ["individual.dob", "Data de nascimento"],
  ["individual.address", "Endereço"],
  ["individual.verification", "Verificação de identidade"],
  ["business_profile", "Informações sobre o seu negócio"],
  ["tos_acceptance", "Aceite dos termos do Stripe"],
];
const PENDENCIA_OUTRAS = "Outras informações pedidas pelo Stripe";

/** Resume os códigos do Stripe em rótulos legíveis, sem repetir. */
export function resumirPendencias(codigos: string[]): string[] {
  const rotulos: string[] = [];
  for (const codigo of codigos) {
    const rotulo =
      PENDENCIAS_EXATAS[codigo] ??
      PENDENCIAS_PREFIXO.find(([prefixo]) => codigo.startsWith(prefixo))?.[1] ??
      PENDENCIA_OUTRAS;
    if (!rotulos.includes(rotulo)) rotulos.push(rotulo);
  }
  // "Outras" sempre por último
  return rotulos.sort((a, b) => Number(a === PENDENCIA_OUTRAS) - Number(b === PENDENCIA_OUTRAS));
}

const AVISO_NAO_LIBERADA =
  "Enquanto a conta não estiver liberada, novos agendamentos podem ficar indisponíveis.";

export function descreverConnect(s: ConnectStatus | undefined): ConnectDescricao {
  if (!s) {
    return { titulo: "Verificando sua conta…", corpo: "", aviso: null, visual: "espera", acao: null, acaoLabel: "", pendencias: [] };
  }
  const pendencias = resumirPendencias(s.pendencias ?? []);
  switch (s.estado) {
    case "ativa":
      return {
        titulo: "Conta conectada",
        corpo:
          "Repasse automático ativo: a cada atendimento cobrado, a taxa do ShowUp é descontada e o restante vai direto para a sua conta.",
        aviso: null, visual: "ok", acao: null, acaoLabel: "", pendencias: [],
      };
    case "pendente_informacoes":
      return {
        titulo: "O Stripe precisa de mais informações",
        corpo: pendencias.length
          ? "Para liberar seus repasses, falta enviar:"
          : "Falta concluir o seu cadastro no Stripe para liberar os repasses.",
        aviso: AVISO_NAO_LIBERADA,
        visual: "atencao",
        acao: s.details_submitted ? "painel" : "onboarding",
        acaoLabel: s.details_submitted ? "Enviar informações" : "Continuar cadastro",
        pendencias,
      };
    case "em_analise":
      return {
        titulo: "O Stripe está analisando sua conta",
        corpo:
          "Isso pode levar alguns dias. Você não precisa fazer nada agora — assim que for liberada, os repasses começam sozinhos.",
        aviso: AVISO_NAO_LIBERADA, visual: "espera", acao: "painel", acaoLabel: "Ver andamento no Stripe", pendencias: [],
      };
    case "restrita":
      return {
        titulo: "Repasses pausados pelo Stripe",
        corpo: "O Stripe pausou os repasses desta conta. Abra o painel para ver o motivo e o que fazer.",
        aviso: AVISO_NAO_LIBERADA, visual: "atencao", acao: "painel", acaoLabel: "Abrir painel do Stripe", pendencias,
      };
    case "recusada":
      return {
        titulo: "O Stripe não habilitou esta conta",
        corpo:
          "O Stripe não conseguiu liberar esta conta para receber pagamentos. Abra o painel para ver o motivo ou fale com o suporte do Stripe.",
        aviso: AVISO_NAO_LIBERADA, visual: "erro", acao: "painel", acaoLabel: "Ver motivo no Stripe", pendencias: [],
      };
    case "indisponivel":
      return {
        titulo: "Não conseguimos consultar o Stripe",
        corpo: "Isso costuma ser passageiro. Tente de novo em instantes.",
        aviso: null, visual: "atencao", acao: "recarregar", acaoLabel: "Tentar de novo", pendencias: [],
      };
    case "nao_conectada":
    default:
      return {
        titulo: "Conta não conectada",
        corpo:
          "Conecte sua conta do Stripe para receber os pagamentos automaticamente. O cadastro leva poucos minutos: o Stripe pede seus dados e um documento, como exige a lei para quem recebe pagamentos.",
        aviso: AVISO_NAO_LIBERADA, visual: "atencao", acao: "onboarding", acaoLabel: "Conectar Stripe", pendencias: [],
      };
  }
}
