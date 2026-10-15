// Endereços das páginas legais (hospedadas no Firebase Hosting). Um lugar só:
// se o site ganhar domínio próprio, troca aqui (ou via EXPO_PUBLIC_WEB_URL).
const WEB = (process.env.EXPO_PUBLIC_WEB_URL ?? "https://showup-509120.web.app").replace(/\/$/, "");

export const URL_TERMOS = `${WEB}/termos`;
export const URL_PRIVACIDADE = `${WEB}/privacidade`;
export const URL_EXCLUSAO = `${WEB}/excluir-conta`;
