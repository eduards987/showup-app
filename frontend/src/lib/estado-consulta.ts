// O que a tela mostra enquanto busca dados do servidor. Lógica PURA (sem React Native): testável no Node.
// Regra: sem internet (ou servidor fora) a tela diz "não foi possível carregar", NUNCA "nada aqui ainda": o profissional
// acharia que a agenda está vazia. Dados já carregados continuam na tela mesmo se a atualização seguinte falhar.

export type EstadoConsulta = "carregando" | "erro" | "vazio" | "pronto";

export function estadoDaConsulta<T>(
  q: { data: T | undefined; isError: boolean },
  estaVazio: (dados: T) => boolean = (d) => Array.isArray(d) && d.length === 0,
): EstadoConsulta {
  if (q.data !== undefined && q.data !== null) return estaVazio(q.data) ? "vazio" : "pronto";
  return q.isError ? "erro" : "carregando";
}

type ComHorario = { horario_inicio: string; horario_fim: string };

/** Lista de agendamentos: primeiro os que ainda vão acontecer (o mais próximo no topo), depois os que já passaram
 *  (o mais recente no topo). Antes era uma lista só, do mais ANTIGO para o mais novo. */
export function separarAgendamentos<T extends ComHorario>(lista: T[], agoraMs: number): { proximos: T[]; anteriores: T[] } {
  const ms = (iso: string) => new Date(iso).getTime();
  const proximos = lista.filter((a) => ms(a.horario_fim) > agoraMs).sort((a, b) => ms(a.horario_inicio) - ms(b.horario_inicio));
  const anteriores = lista.filter((a) => ms(a.horario_fim) <= agoraMs).sort((a, b) => ms(b.horario_inicio) - ms(a.horario_inicio));
  return { proximos, anteriores };
}
