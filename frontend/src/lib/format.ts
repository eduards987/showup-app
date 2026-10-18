// Small helpers used across screens.
import { getIdioma, type Idioma, localeAtual, t } from "@/src/i18n/core";

export function formatMoney(centavos: number, moeda: string = "BRL"): string {
  const v = centavos / 100;
  try {
    // O formato (separador decimal, posição do símbolo) segue o IDIOMA ESCOLHIDO no app; só a MOEDA vem do dado
    // (serviço/agendamento) — é isso que torna isto correto pra qualquer país.
    return v.toLocaleString(localeAtual(), { style: "currency", currency: moeda });
  } catch {
    // moeda fora do que o Intl reconhece — não deveria acontecer, já que o
    // backend só aceita moedas de MOEDAS_SUPORTADAS, mas nunca quebra a UI.
    return `${moeda} ${v.toFixed(2)}`;
  }
}

/** @deprecated use formatMoney(centavos, item.moeda) — todo item vindo do
 * backend (Servico, Agendamento) já carrega sua própria moeda. Mantido só
 * como rede de segurança pra código antigo que não passe a moeda. */
export function formatBRL(centavos: number): string {
  return formatMoney(centavos, "BRL");
}

// O motor JS do React Native (Hermes) tem um histórico conhecido de bugs
// com `Intl`/`toLocaleString` e fuso horário — passar `timeZone` explícito
// nem sempre funciona (ex: facebook/hermes#431), e em algumas versões ele
// ignora completamente a conversão e mostra tudo no fuso "errado". Por
// isso as três funções abaixo NÃO dependem do Intl pra converter fuso —
// calculam a hora/data manualmente a partir do offset fixo (em minutos)
// de cada fuso que o app suporta. Todos são fusos SEM horário de verão
// atualmente (o Brasil não observa DST desde 2019), então um offset fixo
// é seguro — se isso mudar no futuro, precisa revisar.
const OFFSET_MINUTOS: Record<string, number> = {
  "America/Sao_Paulo": -180,
  "America/Manaus": -240,
  "America/Rio_Branco": -300,
  "America/Noronha": -120,
};

const MESES: Record<Idioma, string[]> = {
  "pt-BR": ["jan", "fev", "mar", "abr", "mai", "jun", "jul", "ago", "set", "out", "nov", "dez"],
  en: ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"],
  es: ["ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "sep", "oct", "nov", "dic"],
};
const DIAS_SEMANA: Record<Idioma, string[]> = {
  "pt-BR": ["dom", "seg", "ter", "qua", "qui", "sex", "sáb"],
  en: ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"],
  es: ["dom", "lun", "mar", "mié", "jue", "vie", "sáb"],
};

function pad2(n: number): string {
  return String(n).padStart(2, "0");
}

/** Componentes de data/hora no fuso dado, sem passar pelo Intl — soma o
 * offset fixo em minutos sobre o instante UTC e lê os componentes com os
 * métodos `getUTC*` (que são aritmética pura, não dependem de locale/Intl
 * nem do fuso do dispositivo). `timezone` sem correspondência conhecida
 * cai no fuso do profissional ainda não ter sido carregado — usa
 * America/Sao_Paulo como piso razoável (é o default do backend também). */
function partesNoFuso(iso: string, timezone?: string) {
  const offset = OFFSET_MINUTOS[timezone ?? ""] ?? OFFSET_MINUTOS["America/Sao_Paulo"];
  const comOffset = new Date(new Date(iso).getTime() + offset * 60_000);
  return {
    ano: comOffset.getUTCFullYear(),
    mes: comOffset.getUTCMonth(),
    dia: comOffset.getUTCDate(),
    diaSemana: comOffset.getUTCDay(),
    hora: comOffset.getUTCHours(),
    minuto: comOffset.getUTCMinutes(),
  };
}

// A ordem muda por idioma: "15 de out, 09:00" (pt), "Oct 15, 09:00" (en), "15 oct, 09:00" (es).
export function formatDateTime(iso: string, timezone?: string): string {
  const p = partesNoFuso(iso, timezone);
  const idioma = getIdioma();
  const mes = MESES[idioma][p.mes];
  const hora = `${pad2(p.hora)}:${pad2(p.minuto)}`;
  if (idioma === "en") return `${mes} ${p.dia}, ${hora}`;
  if (idioma === "es") return `${pad2(p.dia)} ${mes}, ${hora}`;
  return `${pad2(p.dia)} de ${mes}, ${hora}`;
}

export function formatDateOnly(iso: string, timezone?: string): string {
  const p = partesNoFuso(iso, timezone);
  const idioma = getIdioma();
  const mes = MESES[idioma][p.mes];
  const dia = DIAS_SEMANA[idioma][p.diaSemana];
  if (idioma === "en") return `${dia}, ${mes} ${p.dia}`;
  if (idioma === "es") return `${dia}, ${pad2(p.dia)} ${mes}`;
  return `${dia}, ${pad2(p.dia)} de ${mes}`;
}

export function formatTimeOnly(iso: string, timezone?: string): string {
  const p = partesNoFuso(iso, timezone);
  return `${pad2(p.hora)}:${pad2(p.minuto)}`;
}

type KindStatus = "info" | "success" | "warning" | "error";

/** Rótulo e cor do estado da reserva no cartão, no idioma atual (é função, não constante: o idioma pode mudar com o app aberto). */
export function infoHold(status: string): { label: string; kind: KindStatus } {
  switch (status) {
    case "autorizado": return { label: t("Reserva no cartão"), kind: "info" };
    case "capturado_total": return { label: t("Cobrado (100%)"), kind: "success" };
    case "capturado_taxa": return { label: t("Taxa de falta"), kind: "warning" };
    case "expirado": return { label: t("Reserva expirada"), kind: "error" };
    case "cancelado": return { label: t("Cancelado"), kind: "error" };
    default: return { label: status, kind: "info" };
  }
}

export function rotuloConfirmacao(status: string): string {
  switch (status) {
    case "pendente": return t("Aguardando");
    case "compareceu": return t("Compareceu");
    case "nao_compareceu": return t("Não compareceu");
    case "sem_resposta": return t("Sem resposta");
    default: return status;
  }
}

export const TIMEZONE_LABELS: Record<string, string> = {
  "America/Sao_Paulo": "Brasília (UTC-3)",
  "America/Manaus": "Manaus (UTC-4)",
  "America/Rio_Branco": "Rio Branco (UTC-5)",
  "America/Noronha": "Fernando de Noronha (UTC-2)",
};
