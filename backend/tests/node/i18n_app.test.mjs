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
import * as rc from "./lib/recebimento.ts";
import * as tu from "./lib/tutorial.ts";
import * as ec from "./lib/estado-consulta.ts";

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
assert.ok(aj.resumoJanelaAgenda([{ weekday: 0 }]).texto.includes("A reserva no cartão vale 7 dias"), "padrão: Stripe");
assert.ok(aj.resumoJanelaAgenda([{ weekday: 0 }], 5).texto.includes("A reserva no cartão vale 5 dias"), "Mercado Pago: 5 dias");
const REC = { metodo: "stripe", mercadopago_disponivel: true, mercadopago_conectado: false, desconto_mercadopago_bps: 300, reserva_dias: 7, reserva_dias_stripe: 7, reserva_dias_mercadopago: 5 };
assert.ok(rc.explicarOpcoes(REC).mercadopago.includes("fica 3 pontos menor") && rc.explicarOpcoes(REC).mercadopago.includes("vale 5 dias"));
assert.ok(rc.explicarOpcoes(REC).stripe.includes("vale 7 dias"));
assert.ok(rc.explicarOpcoes({ ...REC, desconto_mercadopago_bps: 250 }).mercadopago.includes("2.5 pontos"), "o desconto vem do servidor");
assert.strictEqual(rc.mensagemDoRetorno(undefined), null);
assert.ok(rc.mensagemDoRetorno("ok").startsWith("Mercado Pago conectado"));
assert.ok(rc.mensagemDoRetorno("conta_em_uso").includes("outro profissional"));
assert.ok(rc.mensagemDoRetorno("qualquer_outra").startsWith("Não foi possível conectar"));
assert.strictEqual(tu.passosDoProfissional().length, 5);
assert.deepStrictEqual(tu.passosDoProfissional().map((p) => p.titulo), ["Cadastre seus serviços", "Abra seus horários", "Escolha onde receber", "Compartilhe seu link", "Confirme depois do atendimento"]);
assert.ok(tu.passosDoProfissional().every((p) => p.icone && p.texto && p.exemplos.length >= 2));
assert.strictEqual(tu.passosDoCliente().length, 5);
assert.ok(tu.passosDoCliente().every((p) => p.icone && p.texto && p.exemplos.length >= 2));
assert.strictEqual(tu.passosDoTutorial("cliente")[0].titulo, "Encontre o profissional");
assert.strictEqual(tu.passosDoTutorial("profissional")[0].titulo, "Cadastre seus serviços");
assert.strictEqual(tu.destinoAoTerminar("profissional"), "/(app)/novo-servico"); assert.strictEqual(tu.destinoAoTerminar("cliente"), "/(app)/search");
assert.strictEqual(tu.textoDoUltimoBotao("cliente"), "Buscar profissionais");

// ---- aviso de conversão: só quando a moeda do preço NÃO é uma das moedas em que o Stripe deposita
assert.strictEqual(m.avisoDeConversao("BRL"), null); assert.strictEqual(m.avisoDeConversao(""), null);
assert.ok(m.avisoDeConversao("USD").startsWith("O valor cobrado em USD é convertido para reais") && m.avisoDeConversao("USD").includes("tem 4 pontos percentuais a mais") && !m.avisoDeConversao("USD").includes("não cobra nada a mais"));
assert.ok(m.avisoDeConversao("USD", ["BRL"], 250).includes("tem 2.5 pontos percentuais a mais"), "o adicional vem do servidor");
assert.strictEqual(m.avisoDeConversao("USD", ["BRL", "USD"]), null, "moeda liberada pelo Stripe: sem aviso");
assert.ok(m.avisoDeConversao("EUR", ["BRL", "USD"]).includes("EUR"));

// ---- inglês
core.setIdiomaAtual("en");
assert.ok(m.avisoDeConversao("USD").startsWith("The amount charged in USD is converted to reais") && m.avisoDeConversao("USD").endsWith("is 4 percentage points higher."));
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
assert.ok(aj.resumoJanelaAgenda([{ weekday: 5 }], 5).texto.includes("The card hold lasts 5 days"));
assert.strictEqual(tu.passosDoProfissional()[0].titulo, "Add your services"); assert.strictEqual(tu.passosDoProfissional()[4].exemplos[1], "No-show");
assert.strictEqual(tu.passosDoCliente()[3].titulo, "The amount is only held"); assert.strictEqual(tu.textoDoUltimoBotao("cliente"), "Find professionals");
assert.ok(rc.explicarOpcoes(REC).mercadopago.includes("3 points lower") && rc.mensagemDoRetorno("ok").startsWith("Mercado Pago connected"));
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
// ---- estado das telas que buscam dados: sem internet é ERRO, nunca "vazio"
assert.strictEqual(ec.estadoDaConsulta({ data: undefined, isError: false }), "carregando");
assert.strictEqual(ec.estadoDaConsulta({ data: undefined, isError: true }), "erro", "sem dados e com erro: não pode dizer 'nada aqui'");
assert.strictEqual(ec.estadoDaConsulta({ data: [], isError: false }), "vazio");
assert.strictEqual(ec.estadoDaConsulta({ data: [1], isError: true }), "pronto", "dados já carregados ficam na tela se a atualização falhar");
assert.strictEqual(ec.estadoDaConsulta({ data: [], isError: true }), "vazio");
assert.strictEqual(ec.estadoDaConsulta({ data: { itens: [] }, isError: false }, (d) => d.itens.length === 0), "vazio");
assert.strictEqual(ec.estadoDaConsulta({ data: { x: 1 }, isError: false }), "pronto");
{
  const H = (id, ini, fim) => ({ id, horario_inicio: ini, horario_fim: fim });
  const agora = Date.parse("2026-10-21T13:00:00Z");
  const lista = [
    H("velho", "2026-09-01T12:00:00Z", "2026-09-01T13:00:00Z"),
    H("ontem", "2026-10-20T12:00:00Z", "2026-10-20T13:00:00Z"),
    H("depois", "2026-10-23T12:00:00Z", "2026-10-23T13:00:00Z"),
    H("agora", "2026-10-21T12:30:00Z", "2026-10-21T13:30:00Z"),       // começou e não terminou: ainda é "próximo"
    H("amanha", "2026-10-22T12:00:00Z", "2026-10-22T13:00:00Z"),
  ];
  const { proximos, anteriores } = ec.separarAgendamentos(lista, agora);
  assert.deepStrictEqual(proximos.map((a) => a.id), ["agora", "amanha", "depois"], "próximos: o mais perto primeiro");
  assert.deepStrictEqual(anteriores.map((a) => a.id), ["ontem", "velho"], "anteriores: o mais recente primeiro");
  assert.strictEqual(lista[0].id, "velho", "não altera a lista recebida");
}

console.log("i18n do app: OK");
