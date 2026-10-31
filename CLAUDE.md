# ShowUp — contexto para o Claude Code

O `README.md` descreve o projeto. Este arquivo tem o que **não pode ser quebrado**: comandos, decisões já tomadas e armadilhas que já custaram caro.

## Como trabalhar aqui
- Responda em **português**. O dono usa **Windows**: dê comandos como `py lancamento\arquivo.py` (barra invertida).
- Antes de mexer numa área, leia `memory/PRD.md` (histórico das decisões) e o guia dela em `lancamento/`.
- **Dinheiro é sempre inteiro em centavos** da moeda. Nunca use float para valor.
- **Toda proteção nova precisa de teste que FALHE quando o código quebra.** Depois de escrever o teste, estrague o código de propósito, veja o teste falhar e desfaça. Já pegamos defeitos reais assim.
- **Segredos:** `.env*` está no `.gitignore`. Nunca commite, nunca cole chave real em conversa ou em arquivo versionado.
- Mudou comportamento? Atualize `memory/PRD.md` e o guia de `lancamento/` da área.

## Estrutura
- `backend/` — API FastAPI + MongoDB (Motor) + Stripe. Roda no **Render**. Módulos puros e testáveis: `agenda.py`, `i18n_servidor.py`, `notificacoes.py`.
- `frontend/` — app Expo Router (React Native). Textos em `src/i18n/`, regras puras em `src/lib/` (`fusos.ts`, `categorias.ts`, `moedas.ts`, `selecao.ts`).
- `firebase-hosting/public/` — site, `agendar.html` (página de agendamento do cliente, trilíngue) e legais. Deploy: `firebase deploy`.
- `lancamento/` — guias e scripts de lançamento (`LANCAMENTO.md` é a lista viva do que falta).

## Testes
- Rode **de dentro de `backend/`** os arquivos listados em `.github/workflows/tests.yml`: `python -m pytest -q tests/test_xxx.py ...`. São todos offline (banco, Stripe e push falsos).
- `tests/test_iteration*.py` são de integração (chamam um servidor real e semeiam o banco) e **não** rodam offline: ignore.
- Vários testes executam o TypeScript do app de verdade e precisam de **Node 22.6+**. Sem Node eles são pulados; com `CI=true` eles **falham**. Não deixe passar em branco.
- Tipos do app: `npx tsc --noEmit` dentro de `frontend/`. Rode uma vez **antes** de mexer para saber se já passa limpo; se houver erros antigos, compare só o que mudou.

## Decisões que não podem ser quebradas
- **Ordem de publicação:** site (`firebase deploy`) → servidor (commit/push → Render) → app. Ao contrário, os links novos dão 404.
- **Idiomas (pt/en/es):** todo texto da tela passa por `t("texto em português")`, com tradução em `frontend/src/i18n/en.ts` e `es.ts`. A página `agendar.html` tem o próprio dicionário; mensagens de erro do servidor estão em `backend/i18n_servidor.py`. Push, Termos, Privacidade e a página inicial ficam em português. Os testes cobram tudo isso.
- **Categorias:** a lista e a ordem vivem em `CATEGORIAS_POR_GRUPO` (servidor). **Nunca renomeie um código** (`fitness`, `odontologia`...): está gravado nos perfis. O nome traduzido fica em `frontend/src/lib/categorias.ts`.
- **Fusos horários:** o servidor usa `ZoneInfo` (sempre certo). O **app NÃO usa `Intl` para fuso** (bugs do Hermes): `frontend/src/lib/fusos.ts` tem a regra de horário de verão de cada fuso. O `test_fusos.py` compara todos com o pacote `tzdata` (`tzdata>=2026.5`). Se ele falhar no futuro, algum governo mudou a regra: atualize `fusos.ts`. Já aconteceu (Colúmbia Britânica, Alberta e Manitoba em horário de verão permanente desde 2026).
- **Moedas:** BRL, USD, EUR, GBP, MXN, ARS, COP, CAD, AUD. **Sem moedas "sem centavos"** (CLP, JPY...): o app multiplica por 100 e o Stripe cobraria 100x. A conta Stripe do profissional é **sempre no Brasil** (`CONNECT_PAIS`): plataforma brasileira só paga conta brasileira. Cobrança por atendimento em moeda que o Stripe converte para real tem **adicional de 4 pontos** na taxa (`ADICIONAL_CONVERSAO_BPS`, gravado na reserva; o app mostra no aviso de moeda, lido de `/api/moedas`). Decidido em 29/10/2026; substitui o antigo "o ShowUp absorve a conversão".
- **Preço dos planos:** a fonte é `PLANOS` no `backend/server.py` (Free 10%, Profissional R$ 29,90 + 7%, Ultra R$ 69,90 + 5,5%, desde 29/10/2026). O app só mostra o que o servidor manda; nunca converta preço no app. O servidor **recusa** assinar se o Price do Stripe (`STRIPE_PRICE_ID_*`) não tiver o mesmo valor, em BRL, mensal e ativo (`_price_confere`). Mudou o preço: crie o Price novo no Stripe e troque o ID no Render no mesmo dia. `lancamento/calcular-precos.py` (`ATUAIS`) tem de bater com `PLANOS` (o teste confere); revise todo mês. Guia: `lancamento/PRECOS-DOS-PLANOS.md`. **Planejado, ainda não existe:** preço do plano por moeda (`precos_planos.py`, `precos-stripe.py`).
- **Mercado Pago (só Brasil):** segunda forma de o profissional receber (`recebimento: "mercadopago"`). A tarifa sai do valor DELE, então a taxa do ShowUp tem `DESCONTO_MERCADOPAGO_BPS` (3 pontos) a menos; a reserva vale **5 dias** (`HOLD_DIAS_MERCADOPAGO`, a agenda abre menos); só Visa/Master/Amex/Cabal (captura parcial); Pix sempre ligado (30 min); só reais. Cada agendamento grava `gateway`: confirmar/cancelar/expirar vão ao gateway em que a reserva foi feita. Tokens do profissional **sempre cifrados** (`cofre.py`, `MERCADOPAGO_TOKEN_KEY`); pagamento só muda depois de CONSULTAR o Mercado Pago (nunca pelo corpo do aviso). Valor em reais só na borda (`mercadopago_gateway.reais/centavos`). Guia: `lancamento/MERCADO-PAGO.md` (tem o teste obrigatório no sandbox). Decidido em 30/10/2026.
- **Plano e moeda:** o Stripe trava o cliente numa moeda. Hoje todo plano é cobrado em reais. **Planejado:** cobrar na moeda do dia da assinatura (`plano_moeda`; planos antigos = BRL).

## Armadilhas já encontradas
- **Stripe SDK v16:** `currency_options` e `metadata` **não são dict** (sem `.get`). Use colchetes. Teste sempre com objetos reais (`stripe.Price.construct_from`).
- **Stripe Brasil:** a conversão de moeda é **2%** (os 1% da internet são dos EUA). Cartão internacional soma mais 2%. Pior caso de uma assinatura: 7,99% + R$ 0,39.
- **Assinatura sem `currency`:** o Stripe cobra sempre a moeda padrão do Price (reais), mesmo com `currency_options`.
- **Senha do MongoDB:** ao trocar no Atlas, troque também na `MONGO_URL` do Render. Diagnóstico: `py lancamento\verificar-mongo.py`.
- **Páginas do site** têm campos `{{...}}`; o `firebase deploy` é travado se sobrar algum ou se houver texto de exemplo (`seu@email.com`...). Preencha com `py lancamento\preencher-site.py`, nunca à mão, e **não commite as páginas preenchidas** (o repositório guarda os `{{...}}`).
- **`agendar.html`:** tudo que vem do servidor entra no HTML só por `esc()` (o nome do serviço é escrito pelo profissional). O teste recusa `${...}` sem `esc()` ou `T("fixo")`.
- **Horário ocupado:** uma lista só, `STATUS_OCUPAM_HORARIO` (servidor), para horários livres, conflito (app e link) e o índice `uniq_vaga_ativa`. Estado novo de reserva que ocupa horário entra NELA.
- **Cancelamento:** o cliente só cancela ANTES do horário (o servidor recusa depois; senão quem falta escapa da taxa de falta). O profissional pode depois.
- **Avisos ao cliente** (`avisos_cliente.py`): confirmação + lembretes 24 h e 2 h, push ou e-mail, uma vez cada. Nunca e-mail para `@showup.cliente`/`@showup.excluido`.
- **Telas do app:** sem dados e com erro mostra `ErroAoCarregar` (nunca "vazio" nem `return null`); ação que cobra, cancela ou apaga pede confirmação e tem `onError`.
- **Promessas dos textos legais** (prazos, registros de acesso por 6 meses, arrependimento, aviso de 30 dias) estão em `lancamento/REVISAO-JURIDICA.md`. Mudou uma regra (cancelamento, taxa de falta, plano)? Confira se os Termos ainda dizem a verdade.

## O que ainda falta para lançar
A lista viva está em `lancamento/LANCAMENTO.md`. Resumo: domínio próprio (antes da Play Store), conta Google Play + teste fechado de 14 dias, Stripe em modo real (incluindo os Prices por moeda com `--real`), revisão jurídica dos Termos e da Privacidade (textos revisados em 29/10/2026, faltam o advogado e as perguntas de `lancamento/REVISAO-JURIDICA.md`), e trocar os Price IDs no Render e criar os Prices no modo real (faixas novas aplicadas em 29/10/2026; veja `lancamento/PRECOS-DOS-PLANOS.md`). Até decidir, `PLANOS_COMPRA_HABILITADA=0` deixa os planos pagos como "em breve".
