// Explica ao profissional até quando o cliente consegue agendar, a partir dos dias que ele cadastrou. Lógica PURA (sem React
// Native): testável no Node. A regra de verdade fica no servidor (backend/agenda.py); isto só descreve a regra.

export type SlotSemana = { weekday: number };

const NOMES = ["Seg", "Ter", "Qua", "Qui", "Sex", "Sáb", "Dom"];

export type ResumoJanela = { dias: number; nomes: string[]; texto: string };

export function resumoJanelaAgenda(slots: SlotSemana[]): ResumoJanela {
  const distintos = [...new Set(slots.map((s) => s.weekday))].filter((d) => d >= 0 && d <= 6).sort((a, b) => a - b);
  const nomes = distintos.map((d) => NOMES[d]);
  if (nomes.length === 0) {
    return { dias: 0, nomes, texto: "Nenhum horário. Clientes não poderão reservar até você adicionar." };
  }
  const n = nomes.length;
  const quando = n === 1 ? `no próximo dia em que você atende (${nomes[0]})` : `nos próximos ${n} dias em que você atende (${nomes.join(", ")})`;
  return {
    dias: n,
    nomes,
    texto:
      `Seus clientes poderão agendar ${quando}. ` +
      "A reserva no cartão vale 7 dias e você tem 24 h depois do atendimento para confirmar, por isso o último dia pode abrir só aos poucos.",
  };
}
