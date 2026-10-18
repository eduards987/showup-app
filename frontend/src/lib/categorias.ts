// Nome de cada categoria no idioma atual. O CÓDIGO (fitness, terapia...) é o que fica gravado e filtra a busca; só o rótulo muda.
import { t } from "@/src/i18n/core";

export function nomeDaCategoria(codigo: string): string {
  switch (codigo) {
    case "fitness": return t("Fitness");
    case "terapia": return t("Terapia");
    case "consultoria": return t("Consultoria");
    case "estetica": return t("Estética");
    case "coaching": return t("Coaching");
    case "nutricao": return t("Nutrição");
    default: return codigo;
  }
}
