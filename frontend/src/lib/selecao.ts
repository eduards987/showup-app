// Regra da escolha múltipla com limite (categorias: até 3). PURA, testada no Node: marcar além do limite não marca e avisa; desmarcar sempre pode.
export function alternarComLimite<T>(valores: T[], item: T, maximo: number): { valores: T[]; bloqueado: boolean } {
  if (valores.includes(item)) return { valores: valores.filter((x) => x !== item), bloqueado: false };
  if (valores.length >= maximo) return { valores, bloqueado: true };
  return { valores: [...valores, item], bloqueado: false };
}
