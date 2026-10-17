// Roda sozinho ANTES de todo `firebase deploy` (ver "predeploy" no firebase.json).
// Cancela a publicação se alguma página ainda tem campo em branco ({{RESPONSAVEL}} etc.),
// para o site nunca ir ao ar com os Termos e a Privacidade incompletos.
// Para preencher: python lancamento/preencher-site.py --responsavel "..." --email "..." (--documento "..." | --sem-documento)
const fs = require("fs");
const path = require("path");

const pasta = path.join(__dirname, "public");
const problemas = [];
for (const arquivo of fs.readdirSync(pasta).filter((f) => f.endsWith(".html"))) {
  const texto = fs.readFileSync(path.join(pasta, arquivo), "utf8");
  const campos = [...new Set(texto.match(/\{\{[A-Z_]+\}\}/g) || [])];
  if (campos.length) problemas.push(`  - ${arquivo}: ${campos.join(", ")}`);
}
if (problemas.length) {
  console.error("\nPUBLICAÇÃO CANCELADA: há páginas com campos em branco.\n" + problemas.join("\n"));
  console.error('\nPreencha com:  py lancamento\\preencher-site.py --responsavel "Seu Nome" --email "contato@..." --sem-documento');
  console.error("(use --documento \"CPF 000.000.000-00\" no lugar de --sem-documento se quiser mostrar o documento)\n");
  process.exit(1);
}
console.log("Site sem campos em branco: pode publicar.");
