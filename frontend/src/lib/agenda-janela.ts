import { t } from "@/src/i18n/core";
// Explica ao profissional até quando o cliente consegue agendar, a partir dos dias que ele cadastrou. Lógica PURA (sem React
// Native): testável no Node. A regra de verdade fica no servidor (backend/agenda.py); isto só descreve a regra.

export type SlotSemana = { weekday: number };


export type ResumoJanela = { dias: number; nomes: string[]; texto: string };

export function resumoJanelaAgenda(slots: SlotSemana[]): ResumoJanela {
  const distintos = [...new Set(slots.map((s) => s.weekday))].filter((d) => d >= 0 && d <= 6).sort((a, b) => a - b);
  const todos = [t("Seg"), t("Ter"), t("Qua"), t("Qui"), t("Sex"), t("Sáb"), t("Dom")];
  const nomes = distintos.map((d) => todos[d]);
  if (nomes.length === 0) {
    return { dias: 0, nomes, texto: t("Nenhum horário. Clientes não poderão reservar até você adicionar.") };
  }
  const n = nomes.length;
  const quando = n === 1 ? t("no próximo dia em que você atende ({{v1}})", { v1: nomes[0] }) : t("nos próximos {{n}} dias em que você atende ({{v2}})", { n, v2: nomes.join(", ") });
  return {
    dias: n,
    nomes,
    texto:
      t("Seus clientes poderão agendar {{quando}}. ", { quando }) +
      t("A reserva no cartão vale 7 dias e você tem 24 h depois do atendimento para confirmar, por isso o último dia pode abrir só aos poucos."),
  };
}
