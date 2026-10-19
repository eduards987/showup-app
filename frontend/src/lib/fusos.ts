// Fusos horários: regras de horário de verão e nomes. PURO (sem React Native), testado no Node contra a base oficial de fusos (IANA).
//
// POR QUE ISSO EXISTE: o motor do React Native (Hermes) tem bugs conhecidos com `Intl`/`toLocaleString` e fuso horário, então o app NÃO usa Intl
// para converter hora. Antes só havia fusos do Brasil (sem horário de verão: um deslocamento fixo bastava). Com fusos de outros países, o
// deslocamento muda duas vezes por ano; por isso cada fuso tem a sua REGRA e o deslocamento é calculado para o instante pedido.
// A tabela é gerada junto com a lista do servidor (GET /api/timezones). test_fusos.py compara TODOS os fusos com a base oficial nas datas de troca.
//
// Regras (vigentes desde 2023): none = sem horário de verão | us = EUA/Canadá (2º dom. de março -> 1º dom. de novembro) |
// eu = Europa (último dom. de março -> último dom. de outubro, 01:00 UTC) | au = Austrália (1º dom. de outubro -> 1º dom. de abril) |
// nz = Nova Zelândia (último dom. de setembro -> 1º dom. de abril) | cl = Chile (dom. >= 2 de setembro -> dom. >= 2 de abril, em UTC).
// Se algum governo mudar a regra, atualize aqui e rode test_fusos.py (ele usa o pacote tzdata do requirements).
import { t } from "@/src/i18n/core";

export type RegraVerao = "none" | "us" | "eu" | "au" | "nz" | "cl";
export type GrupoFuso = "brasil" | "america_sul" | "america_norte" | "europa" | "africa" | "asia" | "oceania";

const MIN = 60_000;

export const FUSOS: Record<string, { base: number; regra: RegraVerao; grupo: GrupoFuso; permanenteDesde?: number }> = {
  "America/Sao_Paulo": { base: -180, regra: "none", grupo: "brasil" },
  "America/Manaus": { base: -240, regra: "none", grupo: "brasil" },
  "America/Rio_Branco": { base: -300, regra: "none", grupo: "brasil" },
  "America/Noronha": { base: -120, regra: "none", grupo: "brasil" },
  "America/Argentina/Buenos_Aires": { base: -180, regra: "none", grupo: "america_sul" },
  "America/Santiago": { base: -240, regra: "cl", grupo: "america_sul" },
  "America/Montevideo": { base: -180, regra: "none", grupo: "america_sul" },
  "America/Asuncion": { base: -180, regra: "none", grupo: "america_sul" },
  "America/La_Paz": { base: -240, regra: "none", grupo: "america_sul" },
  "America/Bogota": { base: -300, regra: "none", grupo: "america_sul" },
  "America/Lima": { base: -300, regra: "none", grupo: "america_sul" },
  "America/Guayaquil": { base: -300, regra: "none", grupo: "america_sul" },
  "America/Caracas": { base: -240, regra: "none", grupo: "america_sul" },
  "America/Mexico_City": { base: -360, regra: "none", grupo: "america_norte" },
  "America/Cancun": { base: -300, regra: "none", grupo: "america_norte" },
  "America/Tijuana": { base: -480, regra: "us", grupo: "america_norte" },
  "America/Guatemala": { base: -360, regra: "none", grupo: "america_norte" },
  "America/El_Salvador": { base: -360, regra: "none", grupo: "america_norte" },
  "America/Tegucigalpa": { base: -360, regra: "none", grupo: "america_norte" },
  "America/Managua": { base: -360, regra: "none", grupo: "america_norte" },
  "America/Costa_Rica": { base: -360, regra: "none", grupo: "america_norte" },
  "America/Panama": { base: -300, regra: "none", grupo: "america_norte" },
  "America/Jamaica": { base: -300, regra: "none", grupo: "america_norte" },
  "America/Santo_Domingo": { base: -240, regra: "none", grupo: "america_norte" },
  "America/Puerto_Rico": { base: -240, regra: "none", grupo: "america_norte" },
  "America/New_York": { base: -300, regra: "us", grupo: "america_norte" },
  "America/Chicago": { base: -360, regra: "us", grupo: "america_norte" },
  "America/Denver": { base: -420, regra: "us", grupo: "america_norte" },
  "America/Phoenix": { base: -420, regra: "none", grupo: "america_norte" },
  "America/Los_Angeles": { base: -480, regra: "us", grupo: "america_norte" },
  "America/Anchorage": { base: -540, regra: "us", grupo: "america_norte" },
  "Pacific/Honolulu": { base: -600, regra: "none", grupo: "america_norte" },
  "America/Toronto": { base: -300, regra: "us", grupo: "america_norte" },
  "America/Vancouver": { base: -480, regra: "us", grupo: "america_norte", permanenteDesde: 2026 },
  "America/Edmonton": { base: -420, regra: "us", grupo: "america_norte", permanenteDesde: 2026 },
  "America/Winnipeg": { base: -360, regra: "us", grupo: "america_norte", permanenteDesde: 2026 },
  "America/Regina": { base: -360, regra: "none", grupo: "america_norte" },
  "America/Halifax": { base: -240, regra: "us", grupo: "america_norte" },
  "America/St_Johns": { base: -210, regra: "us", grupo: "america_norte" },
  "Europe/London": { base: 0, regra: "eu", grupo: "europa" },
  "Europe/Dublin": { base: 0, regra: "eu", grupo: "europa" },
  "Europe/Lisbon": { base: 0, regra: "eu", grupo: "europa" },
  "Atlantic/Azores": { base: -60, regra: "eu", grupo: "europa" },
  "Europe/Madrid": { base: 60, regra: "eu", grupo: "europa" },
  "Europe/Paris": { base: 60, regra: "eu", grupo: "europa" },
  "Europe/Berlin": { base: 60, regra: "eu", grupo: "europa" },
  "Europe/Rome": { base: 60, regra: "eu", grupo: "europa" },
  "Europe/Amsterdam": { base: 60, regra: "eu", grupo: "europa" },
  "Europe/Brussels": { base: 60, regra: "eu", grupo: "europa" },
  "Europe/Vienna": { base: 60, regra: "eu", grupo: "europa" },
  "Europe/Zurich": { base: 60, regra: "eu", grupo: "europa" },
  "Europe/Stockholm": { base: 60, regra: "eu", grupo: "europa" },
  "Europe/Oslo": { base: 60, regra: "eu", grupo: "europa" },
  "Europe/Copenhagen": { base: 60, regra: "eu", grupo: "europa" },
  "Europe/Warsaw": { base: 60, regra: "eu", grupo: "europa" },
  "Europe/Prague": { base: 60, regra: "eu", grupo: "europa" },
  "Europe/Budapest": { base: 60, regra: "eu", grupo: "europa" },
  "Europe/Athens": { base: 120, regra: "eu", grupo: "europa" },
  "Europe/Helsinki": { base: 120, regra: "eu", grupo: "europa" },
  "Europe/Bucharest": { base: 120, regra: "eu", grupo: "europa" },
  "Europe/Kyiv": { base: 120, regra: "eu", grupo: "europa" },
  "Europe/Istanbul": { base: 180, regra: "none", grupo: "europa" },
  "Europe/Moscow": { base: 180, regra: "none", grupo: "europa" },
  "Africa/Johannesburg": { base: 120, regra: "none", grupo: "africa" },
  "Africa/Lagos": { base: 60, regra: "none", grupo: "africa" },
  "Africa/Nairobi": { base: 180, regra: "none", grupo: "africa" },
  "Africa/Accra": { base: 0, regra: "none", grupo: "africa" },
  "Africa/Luanda": { base: 60, regra: "none", grupo: "africa" },
  "Africa/Maputo": { base: 120, regra: "none", grupo: "africa" },
  "Africa/Algiers": { base: 60, regra: "none", grupo: "africa" },
  "Africa/Addis_Ababa": { base: 180, regra: "none", grupo: "africa" },
  "Asia/Dubai": { base: 240, regra: "none", grupo: "asia" },
  "Asia/Riyadh": { base: 180, regra: "none", grupo: "asia" },
  "Asia/Tehran": { base: 210, regra: "none", grupo: "asia" },
  "Asia/Karachi": { base: 300, regra: "none", grupo: "asia" },
  "Asia/Kolkata": { base: 330, regra: "none", grupo: "asia" },
  "Asia/Colombo": { base: 330, regra: "none", grupo: "asia" },
  "Asia/Kathmandu": { base: 345, regra: "none", grupo: "asia" },
  "Asia/Dhaka": { base: 360, regra: "none", grupo: "asia" },
  "Asia/Bangkok": { base: 420, regra: "none", grupo: "asia" },
  "Asia/Jakarta": { base: 420, regra: "none", grupo: "asia" },
  "Asia/Ho_Chi_Minh": { base: 420, regra: "none", grupo: "asia" },
  "Asia/Shanghai": { base: 480, regra: "none", grupo: "asia" },
  "Asia/Hong_Kong": { base: 480, regra: "none", grupo: "asia" },
  "Asia/Singapore": { base: 480, regra: "none", grupo: "asia" },
  "Asia/Kuala_Lumpur": { base: 480, regra: "none", grupo: "asia" },
  "Asia/Manila": { base: 480, regra: "none", grupo: "asia" },
  "Asia/Taipei": { base: 480, regra: "none", grupo: "asia" },
  "Asia/Seoul": { base: 540, regra: "none", grupo: "asia" },
  "Asia/Tokyo": { base: 540, regra: "none", grupo: "asia" },
  "Australia/Perth": { base: 480, regra: "none", grupo: "oceania" },
  "Australia/Darwin": { base: 570, regra: "none", grupo: "oceania" },
  "Australia/Brisbane": { base: 600, regra: "none", grupo: "oceania" },
  "Australia/Adelaide": { base: 570, regra: "au", grupo: "oceania" },
  "Australia/Sydney": { base: 600, regra: "au", grupo: "oceania" },
  "Australia/Melbourne": { base: 600, regra: "au", grupo: "oceania" },
  "Australia/Hobart": { base: 600, regra: "au", grupo: "oceania" },
  "Pacific/Auckland": { base: 720, regra: "nz", grupo: "oceania" },
  "Pacific/Guam": { base: 600, regra: "none", grupo: "oceania" },
};

const FUSO_PADRAO = "America/Sao_Paulo";

/** Dia do mês do n-ésimo domingo (n = 1 é o primeiro). */
function domingoN(ano: number, mes: number, n: number): number {
  const dow = new Date(Date.UTC(ano, mes, 1)).getUTCDay();
  return 1 + ((7 - dow) % 7) + 7 * (n - 1);
}
function ultimoDomingo(ano: number, mes: number): number {
  const ultimo = new Date(Date.UTC(ano, mes + 1, 0));
  return ultimo.getUTCDate() - ultimo.getUTCDay();
}
/** Primeiro domingo que cai no dia `dia` ou depois dele. */
function domingoApos(ano: number, mes: number, dia: number): number {
  const dow = new Date(Date.UTC(ano, mes, dia)).getUTCDay();
  return dia + ((7 - dow) % 7);
}

/** Deslocamento do fuso em relação ao UTC, em minutos, NO INSTANTE `utcMs` (considera o horário de verão). Fuso desconhecido: Brasília. */
export function offsetMinutos(timezone: string, utcMs: number): number {
  const f = FUSOS[timezone] ?? FUSOS[FUSO_PADRAO];
  const base = f.base;
  if (f.regra === "none") return base;
  const ano = new Date(utcMs + base * MIN).getUTCFullYear();
  // Horário de verão PERMANENTE: a partir da troca de outono do ano indicado o fuso não volta mais ao horário padrão (Colúmbia Britânica, Alberta e
  // Manitoba, a partir de 2026, segundo a base oficial). Antes disso vale a regra normal.
  if (f.permanenteDesde !== undefined && utcMs >= Date.UTC(f.permanenteDesde, 10, domingoN(f.permanenteDesde, 10, 1), 2, 0) - (base + 60) * MIN) return base + 60;
  let verao: boolean;
  switch (f.regra) {
    case "us": {
      const ini = Date.UTC(ano, 2, domingoN(ano, 2, 2), 2, 0) - base * MIN;            // 02:00 padrão
      const fim = Date.UTC(ano, 10, domingoN(ano, 10, 1), 2, 0) - (base + 60) * MIN;   // 02:00 de verão
      verao = utcMs >= ini && utcMs < fim;
      break;
    }
    case "eu": {
      const ini = Date.UTC(ano, 2, ultimoDomingo(ano, 2), 1, 0);
      const fim = Date.UTC(ano, 9, ultimoDomingo(ano, 9), 1, 0);
      verao = utcMs >= ini && utcMs < fim;
      break;
    }
    case "au": {
      const fim = Date.UTC(ano, 3, domingoN(ano, 3, 1), 2, 0) - base * MIN;
      const ini = Date.UTC(ano, 9, domingoN(ano, 9, 1), 2, 0) - base * MIN;
      verao = utcMs < fim || utcMs >= ini;                                                // hemisfério sul: o verão atravessa o ano novo
      break;
    }
    case "nz": {
      const fim = Date.UTC(ano, 3, domingoN(ano, 3, 1), 2, 0) - base * MIN;
      const ini = Date.UTC(ano, 8, ultimoDomingo(ano, 8), 2, 0) - base * MIN;
      verao = utcMs < fim || utcMs >= ini;
      break;
    }
    case "cl": {
      const fim = Date.UTC(ano, 3, domingoApos(ano, 3, 2), 3, 0);
      const ini = Date.UTC(ano, 8, domingoApos(ano, 8, 2), 4, 0);
      verao = utcMs < fim || utcMs >= ini;
      break;
    }
  }
  return base + (verao ? 60 : 0);
}

/** -180 -> "UTC-3"; 330 -> "UTC+5:30"; 0 -> "UTC". */
export function textoDoOffset(minutos: number): string {
  if (minutos === 0) return "UTC";
  const abs = Math.abs(minutos);
  const m = abs % 60;
  return `UTC${minutos < 0 ? "-" : "+"}${Math.floor(abs / 60)}${m ? ":" + String(m).padStart(2, "0") : ""}`;
}

/** Nome do fuso (cidade de referência) no idioma atual. */
export function nomeDoFuso(timezone: string): string {
  switch (timezone) {
    case "America/Sao_Paulo": return t("Brasília");
    case "America/Manaus": return t("Manaus");
    case "America/Rio_Branco": return t("Rio Branco");
    case "America/Noronha": return t("Fernando de Noronha");
    case "America/Argentina/Buenos_Aires": return t("Buenos Aires");
    case "America/Santiago": return t("Santiago");
    case "America/Montevideo": return t("Montevidéu");
    case "America/Asuncion": return t("Assunção");
    case "America/La_Paz": return t("La Paz");
    case "America/Bogota": return t("Bogotá");
    case "America/Lima": return t("Lima");
    case "America/Guayaquil": return t("Guaiaquil");
    case "America/Caracas": return t("Caracas");
    case "America/Mexico_City": return t("Cidade do México");
    case "America/Cancun": return t("Cancún");
    case "America/Tijuana": return t("Tijuana");
    case "America/Guatemala": return t("Guatemala");
    case "America/El_Salvador": return t("El Salvador");
    case "America/Tegucigalpa": return t("Tegucigalpa");
    case "America/Managua": return t("Manágua");
    case "America/Costa_Rica": return t("San José (Costa Rica)");
    case "America/Panama": return t("Panamá");
    case "America/Jamaica": return t("Jamaica");
    case "America/Santo_Domingo": return t("Santo Domingo");
    case "America/Puerto_Rico": return t("Porto Rico");
    case "America/New_York": return t("Nova York");
    case "America/Chicago": return t("Chicago");
    case "America/Denver": return t("Denver");
    case "America/Phoenix": return t("Phoenix");
    case "America/Los_Angeles": return t("Los Angeles");
    case "America/Anchorage": return t("Anchorage");
    case "Pacific/Honolulu": return t("Havaí");
    case "America/Toronto": return t("Toronto");
    case "America/Vancouver": return t("Vancouver");
    case "America/Edmonton": return t("Edmonton");
    case "America/Winnipeg": return t("Winnipeg");
    case "America/Regina": return t("Regina");
    case "America/Halifax": return t("Halifax");
    case "America/St_Johns": return t("St. John's");
    case "Europe/London": return t("Londres");
    case "Europe/Dublin": return t("Dublin");
    case "Europe/Lisbon": return t("Lisboa");
    case "Atlantic/Azores": return t("Açores");
    case "Europe/Madrid": return t("Madri");
    case "Europe/Paris": return t("Paris");
    case "Europe/Berlin": return t("Berlim");
    case "Europe/Rome": return t("Roma");
    case "Europe/Amsterdam": return t("Amsterdã");
    case "Europe/Brussels": return t("Bruxelas");
    case "Europe/Vienna": return t("Viena");
    case "Europe/Zurich": return t("Zurique");
    case "Europe/Stockholm": return t("Estocolmo");
    case "Europe/Oslo": return t("Oslo");
    case "Europe/Copenhagen": return t("Copenhague");
    case "Europe/Warsaw": return t("Varsóvia");
    case "Europe/Prague": return t("Praga");
    case "Europe/Budapest": return t("Budapeste");
    case "Europe/Athens": return t("Atenas");
    case "Europe/Helsinki": return t("Helsinque");
    case "Europe/Bucharest": return t("Bucareste");
    case "Europe/Kyiv": return t("Kiev");
    case "Europe/Istanbul": return t("Istambul");
    case "Europe/Moscow": return t("Moscou");
    case "Africa/Johannesburg": return t("Joanesburgo");
    case "Africa/Lagos": return t("Lagos");
    case "Africa/Nairobi": return t("Nairóbi");
    case "Africa/Accra": return t("Acra");
    case "Africa/Luanda": return t("Luanda");
    case "Africa/Maputo": return t("Maputo");
    case "Africa/Algiers": return t("Argel");
    case "Africa/Addis_Ababa": return t("Adis Abeba");
    case "Asia/Dubai": return t("Dubai");
    case "Asia/Riyadh": return t("Riade");
    case "Asia/Tehran": return t("Teerã");
    case "Asia/Karachi": return t("Karachi");
    case "Asia/Kolkata": return t("Índia (Nova Délhi)");
    case "Asia/Colombo": return t("Colombo");
    case "Asia/Kathmandu": return t("Katmandu");
    case "Asia/Dhaka": return t("Daca");
    case "Asia/Bangkok": return t("Bangkok");
    case "Asia/Jakarta": return t("Jacarta");
    case "Asia/Ho_Chi_Minh": return t("Ho Chi Minh");
    case "Asia/Shanghai": return t("Xangai");
    case "Asia/Hong_Kong": return t("Hong Kong");
    case "Asia/Singapore": return t("Singapura");
    case "Asia/Kuala_Lumpur": return t("Kuala Lumpur");
    case "Asia/Manila": return t("Manila");
    case "Asia/Taipei": return t("Taipé");
    case "Asia/Seoul": return t("Seul");
    case "Asia/Tokyo": return t("Tóquio");
    case "Australia/Perth": return t("Perth");
    case "Australia/Darwin": return t("Darwin");
    case "Australia/Brisbane": return t("Brisbane");
    case "Australia/Adelaide": return t("Adelaide");
    case "Australia/Sydney": return t("Sydney");
    case "Australia/Melbourne": return t("Melbourne");
    case "Australia/Hobart": return t("Hobart");
    case "Pacific/Auckland": return t("Auckland");
    case "Pacific/Guam": return t("Guam");
    default: return timezone;
  }
}

export function nomeDoGrupoFuso(grupo: string): string {
  switch (grupo) {
    case "brasil": return t("Brasil");
    case "america_sul": return t("América do Sul");
    case "america_norte": return t("América do Norte e Central");
    case "europa": return t("Europa");
    case "africa": return t("África");
    case "asia": return t("Ásia e Oriente Médio");
    case "oceania": return t("Oceania");
    default: return grupo;
  }
}

/** "Nova York (UTC-4)": o deslocamento é o de HOJE (muda com o horário de verão). */
export function rotuloDoFuso(timezone: string, utcMs: number = Date.now()): string {
  return `${nomeDoFuso(timezone)} (${textoDoOffset(offsetMinutos(timezone, utcMs))})`;
}
