import { t } from "@/src/i18n/core";
// Mini tutorial animado: os passos de cada papel. Lógica PURA (sem React Native): testável no Node.
// A animação fica em src/components/tutorial.tsx. Quando aparece: logo DEPOIS do cadastro (a tela "Como você vai usar o
// ShowUp?" manda para o Início com ?tutorial=1) e quando a pessoa pede em Perfil. Mudou o fluxo do app? Atualize o passo aqui.

export type Papel = "profissional" | "cliente";

export type PassoTutorial = {
  icone: string;               // nome do Ionicons
  titulo: string;
  texto: string;
  // Exemplo animado do que a pessoa vai ver na tela (nomes de marca e números ficam iguais em todos os idiomas).
  exemplos: string[];
};

/** Parâmetro que a tela de cadastro passa para o Início abrir o tutorial. */
export const PARAM_TUTORIAL = "tutorial";

/** Para onde o último botão leva: o primeiro passo de verdade de cada papel. */
export function destinoAoTerminar(papel: Papel): string {
  return papel === "profissional" ? "/(app)/novo-servico" : "/(app)/search";
}

export function textoDoUltimoBotao(papel: Papel): string {
  return papel === "profissional" ? t("Cadastrar meu primeiro serviço") : t("Buscar profissionais");
}

export function passosDoTutorial(papel: Papel): PassoTutorial[] {
  return papel === "profissional" ? passosDoProfissional() : passosDoCliente();
}

export function passosDoProfissional(): PassoTutorial[] {
  return [
    {
      icone: "pricetags-outline",
      titulo: t("Cadastre seus serviços"),
      texto: t("Em Serviços, informe o nome, a duração, o preço e a taxa que o cliente paga se faltar sem avisar."),
      exemplos: [t("Corte · 45 min · R$ 60,00"), t("Taxa se faltar: R$ 20,00")],
    },
    {
      icone: "time-outline",
      titulo: t("Abra seus horários"),
      texto: t("Em Perfil > Configurações, escolha os dias e horários em que você atende. O cliente só vê esses horários."),
      exemplos: [t("Seg a Sex"), "09:00 → 18:00"],
    },
    {
      icone: "wallet-outline",
      titulo: t("Escolha onde receber"),
      texto: t("Conecte o Stripe ou o Mercado Pago. O dinheiro do atendimento cai direto na sua conta."),
      exemplos: ["Stripe", "Mercado Pago"],
    },
    {
      icone: "share-social-outline",
      titulo: t("Compartilhe seu link"),
      texto: t("Mande seu link de agendamento pelo WhatsApp ou Instagram. O cliente agenda sem instalar nada."),
      exemplos: [t("…/p/seu-nome"), t("Compartilhar")],
    },
    {
      icone: "checkmark-done-outline",
      titulo: t("Confirme depois do atendimento"),
      texto: t("O cartão do cliente fica só reservado. Depois do horário, diga se ele veio: o app cobra o valor inteiro ou só a taxa de falta."),
      exemplos: [t("Compareceu"), t("Não compareceu")],
    },
  ];
}

export function passosDoCliente(): PassoTutorial[] {
  return [
    {
      icone: "search-outline",
      titulo: t("Encontre o profissional"),
      texto: t("Busque pelo nome ou pela categoria e veja os serviços, a duração e o preço de cada um."),
      exemplos: [t("Personal trainer"), t("Corte · 45 min · R$ 60,00")],
    },
    {
      icone: "card-outline",
      titulo: t("Cadastre seu cartão"),
      texto: t("Em Perfil, salve um cartão uma vez só. Ele fica guardado com segurança pelo Stripe, nunca pelo ShowUp."),
      exemplos: ["Visa •••• 4242", t("Salvo com segurança")],
    },
    {
      icone: "calendar-outline",
      titulo: t("Escolha o dia e o horário"),
      texto: t("Toque no serviço e escolha um dos horários livres. A reserva sai na hora."),
      exemplos: [t("Qua, 22/10"), "10:00"],
    },
    {
      icone: "lock-closed-outline",
      titulo: t("O valor fica só reservado"),
      texto: t("Nada é cobrado na hora. Depois do atendimento o valor é cobrado. Se faltar sem avisar, você paga só a taxa de falta."),
      exemplos: [t("Reservado: R$ 60,00"), t("Cobrado só depois do atendimento")],
    },
    {
      icone: "close-circle-outline",
      titulo: t("Precisa desmarcar?"),
      texto: t("Cancele pelo app antes do horário e a reserva no seu cartão é liberada, sem custo."),
      exemplos: [t("Cancelar reserva"), t("Reserva liberada")],
    },
  ];
}
