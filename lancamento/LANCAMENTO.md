# Lançamento do ShowUp — o que falta, em ordem

**Para montar e testar tudo, siga `TESTAR-TUDO.md`; para publicar o código nos servidores, `DEPLOY.md`.** Marque cada item quando terminar. **Quem** diz de quem é a tarefa: *você* (só você consegue),
*eu* (já está no código/arquivos) ou *os dois*. Os tempos são estimativas.

## 0. Três decisões que só você toma

| # | Decisão | Minha recomendação |
|---|---------|--------------------|
| 1 | **Vender planos pagos dentro do app?** O Google Play costuma exigir o sistema de cobrança dele para vender acesso a funções do app; aqui a mensalidade é paga pelo Stripe. O Google anunciou mais flexibilidade em 2026, mas **não consegui confirmar o que vale hoje para o Brasil** (a página de ajuda lista o Brasil em programas de cobrança alternativa, que ainda exigem integrar a cobrança do Google ao lado). | **Primeira versão com `PLANOS_COMPRA_HABILITADA=0`**: os planos pagos aparecem como "em breve", ninguém é cobrado pelo app e o Free (taxa de 10%) funciona normal. Depois do lançamento você decide entre integrar a cobrança do Google, vender os planos só pelo site ou manter só a taxa por agendamento. Confira a política atual no Play Console (Política > Pagamentos) antes de religar. |
| 2 | **Exigir conta do Stripe liberada para agendar?** Sem isso, o dinheiro cobrado fica na conta da plataforma e o repasse vira acerto manual. | **`EXIGIR_RECEBIMENTO_ATIVO=1` em produção.** Em teste pode ficar `0`. |
| 3 | **Conta do Google Play: pessoal ou de organização?** Conta *pessoal* criada depois de 13/11/2023 precisa de teste fechado com **12 testadores por 14 dias seguidos** antes de ir para produção. Conta de *organização* não tem essa exigência, mas pede número D-U-N-S e verificação da empresa. | Se a Octa Labs for uma empresa sua (CNPJ), vale ver a conta de organização. Se não, siga com a pessoal e comece o teste fechado já. |

## 1. Hoje — segurança (você · ~30 min)

- [ ] **Trocar o `GOOGLE_CLIENT_SECRET`** (foi colado no chat). Google Cloud Console > Credenciais > seu cliente OAuth Web > criar novo segredo. Atualizar no Render.
- [ ] **Trocar também**: senha do usuário do MongoDB Atlas (e a `MONGO_URL`), `INTERNAL_SERVICE_TOKEN` (`openssl rand -hex 32`) e o `STRIPE_WEBHOOK_SECRET` — esses valores já apareceram nas conversas.
- [ ] **Apagar os zips antigos do projeto** que você baixou/compartilhou. Os anteriores a esta rodada traziam os arquivos `.env` dentro. Os novos não trazem.
- [ ] Conferir no GitHub (Settings > Security) se há alerta de segredo vazado, e se o repositório está **privado**.

## 2. Esta semana — deixar tudo publicável

- [ ] **Preencher os dados do site** (você, 5 min). Os Termos e a Privacidade têm três campos em branco: nome/razão social, CPF/CNPJ e um **e-mail que você lê de verdade** (a política publicada antes usava `privacidade@showup.app`, que só funciona se você for dono desse domínio). Da raiz do projeto:
  `python lancamento/preencher-site.py --responsavel "Seu Nome" --documento "CPF 000.000.000-00" --email "contato@..."`
- [ ] **Revisão jurídica dos Termos e da Privacidade** (você · um advogado ou contador de confiança). **Em 29/10/2026 os textos foram revisados** (LGPD, CDC, Marco Civil):
  leve ao advogado as perguntas de `REVISAO-JURIDICA.md` e cumpra a lista da seção 3 de lá (registros de acesso por 6 meses, endereço no site, prazos). Os termos são um rascunho meu, **não aconselhamento jurídico**. Pontos para olhar: reembolso, retenção de valores em contestação, foro e a promessa de atender pedidos de exclusão por e-mail **em até 15 dias** (você precisa conseguir cumprir).
- [ ] **Login por e-mail e Microsoft** (você, opcional mas recomendado para o lançamento): siga `LOGIN.md`. Só configure
  depois de publicar a Política de Privacidade nova (a antiga dizia que o app não guarda senhas).
- [ ] **Publicar o site** (você): `python lancamento/preencher-site.py --verificar` e, só se passar, `cd firebase-hosting` e `firebase deploy --only hosting --project showup-509120`. Conferir que `/termos`, `/privacidade` e `/excluir-conta` abrem.
- [ ] **Google Cloud Console > Tela de consentimento OAuth**: preencher nome, e-mail de suporte, link da política de privacidade e **publicar o app ("Em produção")**. Em "Teste", só quem está na lista de testadores consegue entrar.
- [ ] **Webhooks do Stripe** (você) — ver `CHAVES-PRODUCAO.md`, seção 4. Dois endpoints, um deles de Connect, e o evento `customer.subscription.trial_will_end`.
- [ ] **Pedidos de exclusão por e-mail são manuais**: quem agendou por link e não tem app só consegue pedir por e-mail. Defina como você apaga esses dados (nome e telefone no MongoDB) e em quanto tempo.

## 3. Caminho crítico — Google Play (você · começar já)

O teste fechado de 14 dias é o que mais atrasa. Antes dele, nada de produção.

- [ ] Criar a conta de desenvolvedor (taxa única de US$ 25) — `play.google.com/console`.
- [ ] Gerar o build de produção: `cd frontend && eas build --profile production --platform android` (gera `.aab`). Antes, criar as variáveis no EAS (ambiente **production**) — `CHAVES-PRODUCAO.md`, seção 3.
- [ ] Criar o app no Console, preencher a ficha (`PLAY-STORE.md` tem os textos e as respostas prontas) e subir o `.aab` na faixa de **teste fechado**. O primeiro envio de um app novo é manual pelo Console.
- [ ] Recrutar **pelo menos 12 testadores reais** e mantê-los inscritos por 14 dias seguidos (`TESTADORES.md`). Recrute 15–20: se alguém sair antes dos 14 dias, o relógio dessa pessoa zera.
- [ ] Depois dos 14 dias: pedir **acesso à produção** (o Google costuma responder em até ~7 dias).

## 4. Pagamentos em produção (você · ~1–2 h + espera do Stripe)

- [ ] **Ativar a conta da plataforma no Stripe** (dados da empresa/pessoa, conta bancária). Só depois disso as chaves `live` funcionam.
- [ ] Trocar as chaves de teste pelas de produção: `CHAVES-PRODUCAO.md`.
- [ ] **Cada profissional refaz o cadastro do Stripe em produção** (contas de teste não existem no modo real). Para o profissional, o app agora explica o que o Stripe está pedindo e abre o painel.
- [ ] Fazer **uma reserva real de valor baixo** (ex.: R$ 5) ponta a ponta antes de divulgar: reservar, confirmar comparecimento, conferir o repasse e a taxa no Dashboard.
- [ ] Revisar no Stripe as regras de nova tentativa de cobrança (Billing > Revenue recovery), se um dia religar os planos pagos.

## 4b. Mercado Pago (você · ~1 h + testes)

Segunda forma de o profissional receber, com Pix ligado. O código está pronto (30/10/2026); falta configurar e testar: `MERCADO-PAGO.md`.

- [ ] Criar a aplicação no Mercado Pago (marketplace), cadastrar a URL de retorno e o webhook.
- [ ] Colocar as 5 variáveis `MERCADOPAGO_*` no Render.
- [ ] Fazer o teste obrigatório no sandbox (reserva sem cobrar, taxa da falta, aviso do Pix) antes de produção.

## 5. Infraestrutura (você · ~30 min)

- [ ] **Render**: usar um plano pago (o gratuito dorme e a primeira chamada demora ~1 min). O keep-alive do GitHub é um paliativo.
- [ ] **MongoDB Atlas**: o cluster gratuito não tem backup. Antes de usuários reais, um cluster com backup automático.
- [ ] Conferir os alertas de e-mail do Render e do Atlas.

## 6. Depois do lançamento (backlog)

- Decidir os planos pagos no Android (cobrança do Google, venda pelo site ou só taxa) e, no iOS, as regras da Apple.
- Relatórios de faltas e link personalizado; depois lista de espera, pacotes/recorrência e lembrete ao cliente.
- Pix pelo Stripe, quando o Stripe liberar para a conta (`PIX_STRIPE_HABILITADO=1`). Pelo Mercado Pago o Pix já funciona.
- Imagem de fundo da tela inicial vem de uma URL do Unsplash: embutir no app é mais seguro.
- iOS: precisa de conta Apple Developer (paga) e passar a revisão da Apple.

## O que já está pronto no código

- Estados claros do Stripe no app (pendências, em análise, restrita, recusada) e botão para abrir o painel.
- Trava de agendamento por conta do Stripe liberada (`EXIGIR_RECEBIMENTO_ATIVO`) e aviso na página pública.
- Interruptor dos planos pagos (`PLANOS_COMPRA_HABILITADA`), taxa proporcional na falta, teste grátis com cartão confirmado.
- Aviso de cobrança do plano que falhou e de fim do teste grátis.
- Exclusão de conta dentro do app para **todos** os usuários, cancelando assinatura e apagando token de push, cartão e cadastro no Stripe.
- Termos, Privacidade e Exclusão de conta no site + links dentro do app + rodapé no link de agendamento.
- Testes automáticos a cada push no GitHub (`.github/workflows/tests.yml`).

---

# Auditoria de 17/10/2026: o que falta, em ordem de importância

Estado hoje: reserva pelo link e pelo app, pagamento com cartão (teste), avisos ao profissional (novo agendamento, próximo
atendimento, confirmação) e site com Termos, Privacidade e exclusão de conta. **Nada abaixo impede o uso em teste.**

## Bloqueia o lançamento para usuários reais
1. ~~**Agenda x validade da reserva.**~~ **Resolvido em 17/10/2026.** O cliente vê os próximos N dias em que o profissional atende (N = dias da
   semana cadastrados: seg a sex = 5, seg a dom = 7), e nenhum atendimento pode terminar depois de agora + 7 dias - 24 h - 2 h (prazo da reserva
   no cartão). O servidor recusa horários fora da regra nos 3 fluxos (app, link com cartão, link com Pix) antes de tocar no cartão. Se o Stripe
   informar uma validade menor que 7 dias, o prazo de confirmação encurta (ou a reserva é desfeita e recusada). Detalhes em `backend/agenda.py`.
2. ~~**Moeda.**~~ **Decidido: o app continua aberto a várias moedas e idiomas** (dropdown de moeda; português, inglês e espanhol). Corrigido: o **CLP saiu**
   da lista (o Stripe o trata sem centavos e cobraria 100x) e a conta Stripe do profissional passou a ser sempre no país da plataforma (Brasil). **Pendente: revisar as
   faixas de taxa**, porque o custo do Stripe (cartão internacional + conversão) supera a taxa do plano Ultra e do Profissional: veja `TAXAS-E-MOEDAS.md`.
   **Aplicado em 29/10/2026:** Free 10%, Profissional R$ 29,90 + 7%, Ultra R$ 69,90 + 5,5%, +4 pontos fora do real. Prices novos no Stripe de teste.
   **Falta:** trocar os 2 Price IDs no Render antes de publicar o servidor e criar os Prices no modo real (`PRECOS-DOS-PLANOS.md`, seção 6).
3. **Stripe em modo real.** Ativar a conta, trocar as chaves (`sk_`, `pk_`, `whsec_`, `price_`), refazer os 2 webhooks no modo real e ligar
   `EXIGIR_RECEBIMENTO_ATIVO=1`. Só depois de validar tudo em teste. Veja `CHAVES-PRODUCAO.md`. **A chave `pk_test_` está dentro de `agendar.html`**: trocar também lá.
4. **Segredos que apareceram em conversas.** Confirme que foram trocados: segredo do Google (feito), senha do MongoDB (feito), `INTERNAL_SERVICE_TOKEN`, segredos dos webhooks.
5. **Revisão jurídica** dos Termos e da Privacidade (cobrança de taxa de falta, prazos, LGPD). Os textos são um modelo, não parecer jurídico. Revisados em 29/10/2026: veja `REVISAO-JURIDICA.md`.
6. **Google Play.** Conta de desenvolvedor, ficha da loja, formulário de segurança de dados e **teste fechado com 12 testadores por 14 dias** (`PLAY-STORE.md`, `TESTADORES.md`). É o que mais atrasa: comece cedo.
7. **Build de produção** (`.aab`) no projeto Expo novo: variáveis de produção no EAS, keystore gerado pelo EAS e **cópia de segurança** dele.

## Fortemente recomendado antes de divulgar
8. **Domínio próprio** (`DOMINIO.md`), de preferência antes da ficha da Play.
9. **Servidor sempre acordado.** O Render gratuito dorme; lembretes e confirmações dependem dele. Plano pago antes de ter clientes.
10. **Backup do banco.** O plano gratuito do MongoDB Atlas não tem backup automático: planeje um plano pago ou exportações periódicas.
11. **Monitoramento.** Aviso quando o servidor cair (ex.: UptimeRobot, gratuito) e captura de erros (ex.: Sentry).
12. **Suporte.** Um e-mail que você lê e responde (a página de exclusão promete resposta em até 15 dias).

## Melhorias de produto (depois do lançamento)
- **Lembrete ao CLIENTE** (WhatsApp/SMS/e-mail, ~24 h antes): costuma reduzir faltas mais do que qualquer outra coisa.
- **Pré-visualização do link por profissional** no WhatsApp (nome dele na imagem): exige servidor gerando a página (Cloud Run/Functions).
- **Pix**, quando o Stripe liberar para a conta (`PIX_DISPONIVEL` na página de agendamento).
- Tela "o que você vai precisar" antes do cadastro no Stripe; avisos de fim do teste grátis dos planos pagos.
- iPhone (exige conta paga da Apple e builds de iOS).
