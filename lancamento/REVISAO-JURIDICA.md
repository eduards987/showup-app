# Revisão jurídica dos Termos e da Privacidade

Revisão feita em 29/10/2026 com base na LGPD, no Código de Defesa do Consumidor (CDC), no Marco Civil da Internet e no Decreto 7.962/2013 (comércio eletrônico).
**Não é parecer jurídico.** Ela deixa os textos mais completos e lista o que um advogado precisa confirmar antes do lançamento.

## 1. O que foi corrigido nas páginas

**Bloqueava a publicação:** as três páginas e a página inicial estavam com os textos de exemplo ("Seu nome ou razão social", `seu@email.com`).
Os campos `{{...}}` voltaram, e agora o `preencher-site.py` e a trava do `firebase deploy` recusam texto de exemplo.

**Política de Privacidade:**
- Bases legais de cada tratamento (art. 7º e 9º da LGPD): contrato, obrigação legal, legítimo interesse, defesa de direitos e consentimento (só para as notificações).
- O **profissional** aparece como destinatário dos dados do cliente (nome, contato, agendamentos, comparecimento). Antes não aparecia.
- Transferência internacional (art. 33): Render, MongoDB Atlas, Stripe, Expo, Google e Microsoft ficam fora do Brasil.
- Lista completa dos direitos do art. 18, incluindo oposição, informação sobre compartilhamento e reclamação à ANPD. Prazo de resposta de 15 dias.
- Prazos de guarda: registros fiscais em geral 5 anos e registros de acesso 6 meses (Marco Civil, art. 15).
- Dados técnicos (IP, data e hora), aviso de incidente de segurança, cookies e armazenamento no navegador, e o e-mail como canal do titular e da ANPD.

**Termos de Uso:**
- Nova seção 5, **Responsabilidades do profissional**: informar a política de falta, marcar comparecimento com verdade (marcar falta falsa é fraude), obrigações fiscais e LGPD.
- Cliente: canal para **contestar uma cobrança de falta** em até 30 dias, e a garantia de que a taxa de falta nunca passa do valor do serviço (o servidor já recusa).
- Quem agenda pelo link sem conta: maioridade (ou autorização) e cartão próprio ou autorizado.
- **Direito de arrependimento** de 7 dias na primeira contratação de plano (CDC, art. 49).
- **Aviso de 30 dias** antes de mudar o preço de um plano, com cancelamento sem custo.
- Os Termos dizem que cancelar o plano volta ao Free **na hora**, que é o que o código faz.

## 2. Perguntas para o advogado

1. **Tipo de pessoa e CNPJ.** Operar como pessoa física ou MEI? Intermediação de pagamentos e software podem não caber no MEI. Defina antes de preencher `{{RESPONSAVEL}}` e `{{DOCUMENTO}}`.
2. **Endereço no site.** O Decreto 7.962/2013 (art. 2º) pede nome, CPF/CNPJ, **endereço físico** e eletrônico em quem vende pela internet. As páginas ainda não têm endereço.
   Se não quiser expor o endereço de casa, pergunte sobre um endereço comercial ou fiscal.
3. **Agente de pequeno porte (LGPD).** Se o ShowUp se enquadrar (Resolução CD/ANPD nº 2/2022), fica dispensado de indicar encarregado, mas precisa do canal de atendimento, que a política já indica.
   Confirme o enquadramento e se o volume de dados de pagamento muda isso.
4. **Responsabilidade da plataforma.** O CDC costuma tornar a plataforma responsável junto com o profissional. A cláusula 8 já ressalva os direitos do consumidor; confirme se basta.
5. **Taxa de falta.** É cláusula penal: precisa ser proporcional e informada antes. Confirme se o limite atual (até 100% do serviço) é aceitável ou se convém um teto menor (ex.: 50%).
6. **Cancelamento do cliente.** Hoje o cliente cancela sem custo a qualquer momento antes da confirmação. Se os profissionais quiserem cobrar cancelamento em cima da hora, isso precisa de regra nos Termos e no código.
7. **Cancelamento imediato do plano** sem devolução proporcional do período já pago: confirme se é aceitável ou se é melhor manter o plano até o fim do período.
8. **Intermediação de pagamento.** Com o Stripe Connect, o ShowUp recebe e repassa valores. Confirme se isso exige algo junto ao Banco Central (subcredenciamento) ou se o Stripe cobre.
9. **Clientes de fora do Brasil.** O app aceita EUR e GBP e tem página em inglês e espanhol. Oferecer o serviço a quem está na União Europeia pode atrair o GDPR (art. 3º, 2), inclusive a exigência de um representante na UE.
   Se a ideia é só o Brasil por agora, o mais seguro é tirar EUR e GBP até ter essa resposta.
10. **Termos só em português.** O app é trilíngue, mas os Termos não. Pergunte se é preciso traduzi-los para quem usa o app em outro idioma.
11. **Impostos.** Nota fiscal das taxas e mensalidades (ISS hoje e IBS/CBS com a reforma tributária). Isso é mais para o contador.

## 3. O que você precisa fazer para as promessas dos textos serem verdade

- [ ] **Registros de acesso por 6 meses** (Marco Civil, art. 15). A política diz que guardamos IP, data e hora por 6 meses. Confirme se os logs do Render guardam isso por esse tempo.
  Se não guardam, é preciso gravar esses registros (por exemplo, numa coleção do MongoDB com expiração de 6 meses). Hoje o código não faz isso.
- [ ] **Responder pedidos em até 15 dias** (exclusão por e-mail, acesso aos dados, contestação de cobrança). Use um e-mail que você lê.
- [ ] **Reembolso do arrependimento e das contestações:** é manual, pelo painel do Stripe.
- [ ] **Aviso de 30 dias** antes de mudar preço de plano: precisa ser enviado (notificação e e-mail).
- [ ] Depois de preencher os dados: `py lancamento\preencher-site.py --verificar` e só então `firebase deploy`.
