// Small helpers used across screens.

export function formatMoney(centavos: number, moeda: string = "BRL"): string {
  const v = centavos / 100;
  try {
    // Locale indefinido de propósito: deixa o dispositivo decidir convenção
    // de formatação (separador decimal, posição do símbolo), só a MOEDA
    // vem do dado (serviço/agendamento) — é isso que torna isto correto
    // pra qualquer país, em vez de assumir pt-BR/BRL como antes.
    return v.toLocaleString(undefined, { style: "currency", currency: moeda });
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

const MESES = ["jan", "fev", "mar", "abr", "mai", "jun", "jul", "ago", "set", "out", "nov", "dez"];
const DIAS_SEMANA = ["dom", "seg", "ter", "qua", "qui", "sex", "sáb"];

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

export function formatDateTime(iso: string, timezone?: string): string {
  const p = partesNoFuso(iso, timezone);
  return `${pad2(p.dia)} de ${MESES[p.mes]}, ${pad2(p.hora)}:${pad2(p.minuto)}`;
}

export function formatDateOnly(iso: string, timezone?: string): string {
  const p = partesNoFuso(iso, timezone);
  return `${DIAS_SEMANA[p.diaSemana]}, ${pad2(p.dia)} de ${MESES[p.mes]}`;
}

export function formatTimeOnly(iso: string, timezone?: string): string {
  const p = partesNoFuso(iso, timezone);
  return `${pad2(p.hora)}:${pad2(p.minuto)}`;
}

export const HOLD_STATUS_LABELS: Record<string, { label: string; kind: "info" | "success" | "warning" | "error" }> = {
  autorizado: { label: "Hold autorizado", kind: "info" },
  capturado_total: { label: "Capturado (100%)", kind: "success" },
  capturado_taxa: { label: "Taxa de no-show", kind: "warning" },
  expirado: { label: "Hold expirado", kind: "error" },
  cancelado: { label: "Cancelado", kind: "error" },
};

export const CONFIRMACAO_LABELS: Record<string, string> = {
  pendente: "Aguardando",
  compareceu: "Compareceu",
  nao_compareceu: "Não compareceu",
  sem_resposta: "Sem resposta",
};

export const TIMEZONE_LABELS: Record<string, string> = {
  "America/Sao_Paulo": "Brasília (UTC-3)",
  "America/Manaus": "Manaus (UTC-4)",
  "America/Rio_Branco": "Rio Branco (UTC-5)",
  "America/Noronha": "Fernando de Noronha (UTC-2)",
};
