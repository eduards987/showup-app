// Comportamento real da tradução do app (formatos, moedas, estados, mensagens). Roda com: node --experimental-strip-types
// pelo test_i18n_app.py, que monta a pasta temporária com os arquivos do app (os imports "@/src/..." viram relativos).
import assert from "node:assert";
import * as core from "./i18n/core.ts";
import * as f from "./lib/format.ts";
import * as m from "./lib/moedas.ts";
import * as cat from "./lib/categorias.ts";
import * as ae from "./lib/auth-email.ts";
import * as ce from "./lib/connect-estado.ts";
import * as ne from "./lib/notificacoes-erros.ts";
import * as aj from "./lib/agenda-janela.ts";

const em = (iso, tz) => [f.formatDateTime(iso, tz), f.formatDateOnly(iso, tz)];
const ISO = "2026-10-21T13:30:00Z";                         // quarta 21/10, 10:30 em São Paulo
const status = { charges_enabled: false, payouts_enabled: false, details_submitted: true, pendencias: [] };

// ---- detecção pelo aparelho
assert.strictEqual(core.normalizarIdioma("pt"), "pt-BR"); assert.strictEqual(core.normalizarIdioma("pt_BR"), "pt-BR");
assert.strictEqual(core.normalizarIdioma("EN-us"), "en"); assert.strictEqual(core.normalizarIdioma("es-MX"), "es");
assert.strictEqual(core.normalizarIdioma("fr"), null); assert.strictEqual(core.normalizarIdioma(undefined), null);
assert.strictEqual(core.detectarIdioma(["pt-BR"]), "pt-BR"); assert.strictEqual(core.detectarIdioma(["en-US"]), "en");
assert.strictEqual(core.detectarIdioma(["fr-FR", "es-ES"]), "es", "o primeiro idioma SUPORTADO da lista vale");
assert.strictEqual(core.detectarIdioma(["fr-FR"]), "en", "sem tradução -> inglês");
assert.strictEqual(core.detectarIdioma(["fr-BR"]), "pt-BR", "sem tradução, mas região Brasil -> português");
assert.strictEqual(core.detectarIdioma([]), "pt-BR"); assert.strictEqual(core.detectarIdioma([undefined, null, ""]), "pt-BR");
assert.strictEqual(core.interpolar("falta {{x}}", { n: 1 }), "falta {{x}}", "variável ausente não some");

// ---- português (padrão) continua exatamente como era
assert.deepStrictEqual(em(ISO), ["21 de out, 10:30", "qua, 21 de out"]);
assert.strictEqual(f.formatMoney(12000, "BRL").replace(/\s/g, " "), "R$ 120,00");
assert.strictEqual(m.rotuloDaMoeda("USD"), "USD · Dólar americano"); assert.strictEqual(cat.nomeDaCategoria("nutricao"), "Nutrição");
assert.strictEqual(f.rotuloConfirmacao("nao_compareceu"), "Não compareceu"); assert.strictEqual(ae.textosDoModo("criar").titulo, "Criar conta");
assert.deepStrictEqual(ce.resumirPendencias(["individual.address.city", "xyz.desconhecido", "individual.id_number"]), ["Endereço", "CPF", "Outras informações pedidas pelo Stripe"]);
assert.ok(aj.resumoJanelaAgenda([{ weekday: 0 }, { weekday: 1 }]).texto.includes("nos próximos 2 dias em que você atende (Seg, Ter)"));

// ---- aviso de conversão: só quando a moeda do preço NÃO é uma das moedas em que o Stripe deposita
assert.strictEqual(m.avisoDeConversao("BRL"), null); assert.strictEqual(m.avisoDeConversao(""), null);
assert.ok(m.avisoDeConversao("USD").startsWith("O valor cobrado em USD é convertido para reais") && m.avisoDeConversao("USD").includes("não cobra nada a mais pela conversão") && !/cobra uma taxa de convers/.test(m.avisoDeConversao("USD")));
assert.strictEqual(m.avisoDeConversao("USD", ["BRL", "USD"]), null, "moeda liberada pelo Stripe: sem aviso");
assert.ok(m.avisoDeConversao("EUR", ["BRL", "USD"]).includes("EUR"));

// ---- inglês
core.setIdiomaAtual("en");
assert.ok(m.avisoDeConversao("USD").startsWith("The amount charged in USD is converted to reais") && m.avisoDeConversao("USD").endsWith("its fee stays the same."));
assert.deepStrictEqual(em(ISO), ["Oct 21, 10:30", "Wed, Oct 21"]); assert.strictEqual(f.formatMoney(12000, "USD"), "$120.00");
assert.strictEqual(core.t("Salvar serviço"), "Save service"); assert.strictEqual(core.t("Testar {{trial_dias}} dias grátis", { trial_dias: 14 }), "Try 14 days free");
assert.strictEqual(core.t(" (atual)"), " (current)", "espaço do início é preservado");
assert.strictEqual(core.t("Seus clientes poderão agendar {{quando}}. ", { quando: "x" }), "Your clients will be able to book x. ", "espaço do fim é preservado");
assert.strictEqual(m.rotuloDaMoeda("BRL"), "BRL · Brazilian real"); assert.strictEqual(cat.nomeDaCategoria("estetica"), "Beauty");
assert.strictEqual(cat.nomeDaCategoria("odontologia"), "Dentist"); assert.strictEqual(cat.nomeDoGrupo("bem_estar"), "Wellness & sports"); assert.strictEqual(cat.nomeDaCategoria("codigo_novo"), "codigo_novo");
assert.strictEqual(f.infoHold("autorizado").label, "Card hold"); assert.strictEqual(ae.textosDoModo("entrar").botao, "Sign in");
assert.strictEqual(ce.descreverConnect({ ...status, estado: "em_analise" }).titulo, "Stripe is reviewing your account");
assert.deepStrictEqual(ce.resumirPendencias(["individual.address.city", "individual.id_number"]), ["Address", "CPF (Brazilian tax ID)"]);
assert.ok(aj.resumoJanelaAgenda([{ weekday: 5 }]).texto.includes("on the next day you work (Sat)"));
assert.strictEqual(ne.msgEmulador(), "Emulators don't receive notifications. Use a real phone.");
assert.strictEqual(ne.novoDiagnostico()[0].titulo, "Real phone (not an emulator)");
assert.strictEqual(core.t("Texto inventado sem tradução"), "Texto inventado sem tradução", "sem tradução cai em português, nunca quebra");

// ---- espanhol
core.setIdiomaAtual("es");
assert.ok(m.avisoDeConversao("USD").startsWith("El valor cobrado en USD es convertido a reales"));
assert.deepStrictEqual(em(ISO), ["21 oct, 10:30", "mié, 21 oct"]); assert.strictEqual(core.t("Sair"), "Cerrar sesión");
assert.strictEqual(m.rotuloDaMoeda("USD"), "USD · Dólar estadounidense"); assert.strictEqual(f.rotuloConfirmacao("sem_resposta"), "Sin respuesta"); assert.strictEqual(cat.nomeDaCategoria("banho_tosa"), "Peluquería canina"); assert.strictEqual(cat.nomeDoGrupo("saude"), "Salud");
assert.strictEqual(core.t("O login com {{provedor}} foi cancelado.", { provedor: "Google" }), "El inicio de sesión con Google fue cancelado.");

// ---- o idioma é global e reversível; quem escuta é avisado só quando muda
let avisos = 0; const sair = core.assinarIdioma(() => avisos++);
core.setIdiomaAtual("es"); assert.strictEqual(avisos, 0); core.setIdiomaAtual("pt-BR"); assert.strictEqual(avisos, 1); sair();
assert.strictEqual(core.t("Salvar serviço"), "Salvar serviço"); assert.deepStrictEqual(em(ISO), ["21 de out, 10:30", "qua, 21 de out"]);
assert.strictEqual(cat.nomeDaCategoria("odontologia"), "Dentista"); assert.strictEqual(cat.nomeDoGrupo("casa_auto"), "Casa e automóveis");
console.log("i18n do app: OK");
