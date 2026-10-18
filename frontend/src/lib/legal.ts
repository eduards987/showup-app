// Endereço do site (hospedado no Firebase Hosting) e das páginas legais. Um lugar só: se o site ganhar domínio próprio,
// troca aqui (ou pela variável EXPO_PUBLIC_WEB_URL). Todo o app usa este valor; o link de agendamento do profissional vem do servidor.
const WEB = (process.env.EXPO_PUBLIC_WEB_URL ?? "https://showup-509120.web.app").replace(/\/$/, "");

export const URL_SITE = WEB;

export const URL_TERMOS = `${WEB}/termos`;
export const URL_PRIVACIDADE = `${WEB}/privacidade`;
export const URL_EXCLUSAO = `${WEB}/excluir-conta`;
