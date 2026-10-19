// Nome de cada categoria (e de cada grupo) no idioma atual. O CÓDIGO (fitness, odontologia...) é o que fica gravado no perfil e filtra a busca;
// só o rótulo muda. A lista de códigos e a ordem vêm do servidor (GET /api/categorias); aqui ficam os nomes. test_categorias.py confere que
// todo código do servidor tem nome aqui e tradução em inglês e espanhol.
import { t } from "@/src/i18n/core";

export function nomeDaCategoria(codigo: string): string {
  switch (codigo) {
    case "medicina": return t("Médico(a)");
    case "odontologia": return t("Dentista");
    case "psicologia": return t("Psicólogo(a)");
    case "terapia": return t("Terapia");
    case "fisioterapia": return t("Fisioterapeuta");
    case "fonoaudiologia": return t("Fonoaudiólogo(a)");
    case "nutricao": return t("Nutrição");
    case "acupuntura": return t("Acupuntura");
    case "estetica": return t("Estética");
    case "cabeleireiro": return t("Cabeleireiro(a)");
    case "barbearia": return t("Barbearia");
    case "unhas": return t("Manicure e unhas");
    case "maquiagem": return t("Maquiagem");
    case "depilacao": return t("Depilação");
    case "tatuagem": return t("Tatuagem e piercing");
    case "fitness": return t("Fitness");
    case "yoga_pilates": return t("Yoga e pilates");
    case "massagem": return t("Massagem");
    case "danca": return t("Dança");
    case "artes_marciais": return t("Artes marciais");
    case "esportes": return t("Aulas de esporte");
    case "aulas_particulares": return t("Aulas particulares");
    case "idiomas": return t("Aulas de idiomas");
    case "musica": return t("Aulas de música");
    case "consultoria": return t("Consultoria");
    case "coaching": return t("Coaching");
    case "advocacia": return t("Advocacia");
    case "contabilidade": return t("Contabilidade");
    case "fotografia": return t("Fotografia");
    case "imobiliario": return t("Corretor(a) de imóveis");
    case "veterinaria": return t("Veterinária");
    case "banho_tosa": return t("Banho e tosa");
    case "adestramento": return t("Adestramento");
    case "automotivo": return t("Oficina e estética automotiva");
    case "reparos": return t("Reparos e serviços técnicos");
    case "outros": return t("Outros");
    default: return codigo;
  }
}

export function nomeDoGrupo(codigo: string): string {
  switch (codigo) {
    case "saude": return t("Saúde");
    case "beleza": return t("Beleza e estética");
    case "bem_estar": return t("Bem-estar e esporte");
    case "educacao": return t("Educação");
    case "profissionais": return t("Serviços profissionais");
    case "pets": return t("Pets");
    case "casa_auto": return t("Casa e automóveis");
    case "outros": return t("Outros");
    default: return codigo;
  }
}
