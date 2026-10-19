// Compara o cálculo de fuso do APP (fusos.ts) com a base oficial (amostras geradas pelo Python/zoneinfo). Uso: node --experimental-strip-types fusos.test.mjs amostras.json
import assert from "node:assert";
import fs from "node:fs";
import * as core from "./i18n/core.ts";
import * as f from "./lib/format.ts";
import * as z from "./lib/fusos.ts";

const amostras = JSON.parse(fs.readFileSync(process.argv[2], "utf8"));
const erros = [];
for (const [zona, ms, esperado] of amostras) {
  const obtido = z.offsetMinutos(zona, ms);
  if (obtido !== esperado) erros.push(`${zona} em ${new Date(ms).toISOString()}: app=${obtido} oficial=${esperado}`);
}
const porFuso = {};
for (const e of erros) porFuso[e.split(" ")[0]] = (porFuso[e.split(" ")[0]] ?? 0) + 1;
assert.strictEqual(erros.length, 0, `${erros.length} diferenças de ${amostras.length} amostras, por fuso: ${JSON.stringify(porFuso)}. Primeiras:\n  ` + erros.slice(0, 8).join("\n  "));

// ---- horário de verão PERMANENTE (Colúmbia Britânica, Alberta, Manitoba): em 2026 entram no verão e não voltam, segundo a base oficial
for (const [zona, padrao] of [["America/Vancouver", -480], ["America/Edmonton", -420], ["America/Winnipeg", -360]]) {
  assert.strictEqual(z.offsetMinutos(zona, Date.UTC(2025, 11, 15, 12)), padrao, `${zona}: dezembro de 2025 ainda é horário padrão`);
  assert.strictEqual(z.offsetMinutos(zona, Date.UTC(2026, 6, 15, 12)), padrao + 60, `${zona}: verão de 2026`);
  assert.strictEqual(z.offsetMinutos(zona, Date.UTC(2026, 11, 15, 12)), padrao + 60, `${zona}: NÃO volta ao padrão no inverno de 2026`);
  assert.strictEqual(z.offsetMinutos(zona, Date.UTC(2027, 0, 15, 12)), padrao + 60, `${zona}: janeiro de 2027`);
}
assert.strictEqual(z.offsetMinutos("America/Toronto", Date.UTC(2026, 11, 15, 12)), -300, "Toronto continua voltando ao horário padrão");

// ---- rótulos e hora exibida (português)
assert.strictEqual(z.textoDoOffset(-180), "UTC-3"); assert.strictEqual(z.textoDoOffset(330), "UTC+5:30"); assert.strictEqual(z.textoDoOffset(0), "UTC");
assert.strictEqual(z.textoDoOffset(-210), "UTC-3:30"); assert.strictEqual(z.textoDoOffset(345), "UTC+5:45"); assert.strictEqual(z.textoDoOffset(60), "UTC+1");
const verao = Date.UTC(2026, 6, 15, 13, 0), inverno = Date.UTC(2026, 0, 15, 13, 0);
assert.strictEqual(z.rotuloDoFuso("America/New_York", verao), "Nova York (UTC-4)"); assert.strictEqual(z.rotuloDoFuso("America/New_York", inverno), "Nova York (UTC-5)");
assert.strictEqual(z.rotuloDoFuso("America/Sao_Paulo", verao), "Brasília (UTC-3)"); assert.strictEqual(z.rotuloDoFuso("Asia/Kolkata", verao), "Índia (Nova Délhi) (UTC+5:30)");
assert.strictEqual(z.rotuloDoFuso("Fuso/Inexistente", verao), "Fuso/Inexistente (UTC-3)", "fuso desconhecido: nome cru e Brasília, sem quebrar");
const iso = (ms) => new Date(ms).toISOString();
assert.strictEqual(f.formatDateTime(iso(verao), "America/New_York"), "15 de jul, 09:00"); assert.strictEqual(f.formatDateTime(iso(inverno), "America/New_York"), "15 de jan, 08:00");
assert.strictEqual(f.formatDateTime(iso(Date.UTC(2026, 0, 14, 22, 0)), "Australia/Sydney"), "15 de jan, 09:00", "Sydney em janeiro (verão): +11, e o dia muda");
assert.strictEqual(f.formatDateTime("2026-10-21T13:30:00Z", "America/Sao_Paulo"), "21 de out, 10:30"); assert.strictEqual(f.formatDateTime("2026-10-21T13:30:00Z"), "21 de out, 10:30", "sem fuso: Brasília");
assert.strictEqual(f.formatDateTime("2026-10-21T13:30:00Z", "Fuso/Inexistente"), "21 de out, 10:30");
core.setIdiomaAtual("en"); assert.strictEqual(z.nomeDoFuso("America/New_York"), "New York"); assert.strictEqual(z.nomeDoGrupoFuso("europa"), "Europe");
core.setIdiomaAtual("es"); assert.strictEqual(z.nomeDoFuso("Europe/Madrid"), "Madrid"); assert.strictEqual(z.nomeDoFuso("Europe/London"), "Londres"); assert.strictEqual(z.nomeDoGrupoFuso("america_sul"), "Sudamérica");
console.log(`fusos: OK (${amostras.length} amostras conferidas com a base oficial)`);
