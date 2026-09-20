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

export function formatDateTime(iso: string): string {
  const d = new Date(iso);
  return d.toLocaleString("pt-BR", {
    day: "2-digit",
    month: "short",
    hour: "2-digit",
    minute: "2-digit",
  });
}

export function formatDateOnly(iso: string): string {
  const d = new Date(iso);
  return d.toLocaleDateString("pt-BR", {
    weekday: "short",
    day: "2-digit",
    month: "short",
  });
}

export function formatTimeOnly(iso: string): string {
  const d = new Date(iso);
  return d.toLocaleTimeString("pt-BR", { hour: "2-digit", minute: "2-digit" });
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
