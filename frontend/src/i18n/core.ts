// Núcleo de idiomas do app: PURO (sem React Native), para poder ser testado no Node e usado por qualquer arquivo.
//
// Como funciona: o texto em PORTUGUÊS é a chave. `t("Salvar")` devolve "Save" se o idioma for inglês e o dicionário tiver essa
// chave; se não tiver, devolve o próprio português (nunca aparece uma chave estranha na tela). Variáveis usam {{nome}}:
//   t("Faltam {{n}} dias", { n: 3 })  ->  "Faltam 3 dias"  /  "3 days left"
// O teste test_i18n_cobertura.py garante que TODO texto passado a t() existe em inglês e em espanhol.
import en from "@/src/i18n/en";
import es from "@/src/i18n/es";

export type Idioma = "pt-BR" | "en" | "es";

export const IDIOMA_PADRAO: Idioma = "pt-BR";

/** Nome de cada idioma NO PRÓPRIO idioma (é assim que a pessoa o reconhece, mesmo se o app estiver noutra língua). */
export const IDIOMAS: { codigo: Idioma; nome: string }[] = [
  { codigo: "pt-BR", nome: "Português (Brasil)" },
  { codigo: "en", nome: "English" },
  { codigo: "es", nome: "Español" },
];

/** "pt", "pt-PT", "pt_BR", "EN-us", "es-MX" -> idioma suportado; qualquer outra coisa -> null. */
export function normalizarIdioma(valor: unknown): Idioma | null {
  if (typeof valor !== "string") return null;
  const base = valor.trim().replace("_", "-").toLowerCase().split("-")[0];
  if (base === "pt") return "pt-BR";
  if (base === "en") return "en";
  if (base === "es") return "es";
  return null;
}

/**
 * Escolhe o idioma a partir dos idiomas do aparelho (do mais para o menos preferido). Usa a configuração do próprio celular,
 * sem pedir permissão de localização (GPS): o idioma que a pessoa escolheu no aparelho diz mais do que o lugar onde ela está.
 * Idioma sem tradução (francês, japonês...) cai em inglês, a língua mais comum entre quem viaja; sem informação, português.
 */
export function detectarIdioma(locales: (string | undefined | null)[]): Idioma {
  const lista = locales.filter((l): l is string => typeof l === "string" && l.trim() !== "");
  if (lista.length === 0) return IDIOMA_PADRAO;
  for (const loc of lista) {
    const achado = normalizarIdioma(loc);
    if (achado) return achado;
  }
  const regiao = lista[0].replace("_", "-").split("-")[1]?.toUpperCase();
  return regiao === "BR" ? "pt-BR" : "en";
}

/** Código que o `Intl` entende (datas, números, moeda) para cada idioma do app. */
export function localeIntl(idioma: Idioma): string {
  return idioma === "pt-BR" ? "pt-BR" : idioma === "es" ? "es" : "en-US";
}

export function interpolar(texto: string, params?: Record<string, string | number>): string {
  if (!params) return texto;
  return texto.replace(/\{\{\s*(\w+)\s*\}\}/g, (inteiro, nome: string) => (nome in params ? String(params[nome]) : inteiro));
}

const DICIONARIOS: Record<Idioma, Record<string, string>> = { "pt-BR": {}, en, es };

let idiomaAtual: Idioma = IDIOMA_PADRAO;
const ouvintes = new Set<() => void>();

export function getIdioma(): Idioma {
  return idiomaAtual;
}

export function setIdiomaAtual(novo: Idioma): void {
  if (novo === idiomaAtual) return;
  idiomaAtual = novo;
  ouvintes.forEach((f) => f());
}

export function assinarIdioma(f: () => void): () => void {
  ouvintes.add(f);
  return () => {
    ouvintes.delete(f);
  };
}

/** Traduz um texto escrito em português para o idioma atual. */
export function t(texto: string, params?: Record<string, string | number>): string {
  const traduzido = DICIONARIOS[idiomaAtual][texto];
  return interpolar(traduzido ?? texto, params);
}

export function localeAtual(): string {
  return localeIntl(idiomaAtual);
}
