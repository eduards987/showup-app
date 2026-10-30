# Moedas, países e o custo do Stripe (leia antes de abrir para fora do Brasil)

## O que funciona
- **Cliente de qualquer país pagando em outra moeda:** o Stripe cobra em mais de 135 moedas e converte para real na conta brasileira.
  O app oferece 9 moedas (BRL, USD, EUR, GBP, MXN, ARS, COP, CAD, AUD). A moeda é **a do preço do serviço**, escolhida pelo profissional.
- **Idiomas:** português, inglês e espanhol, no app e na página de agendamento (veja `IDIOMAS.md`).

## O que NÃO funciona (e como está protegido)
- **Profissional fora do Brasil.** O Stripe só permite transferir entre contas na **mesma região** (as exceções são entre EUA, Canadá, Reino
  Unido, Europa e Suíça). Uma plataforma brasileira só paga contas conectadas **no Brasil**. Por isso a conta Stripe do profissional é sempre criada
  no país da plataforma (`CONNECT_PAIS`, padrão `BR`). Antes, o país era inferido da moeda (dólar virava conta nos EUA), o que quebraria o cadastro.
- **Moedas sem centavos (CLP, JPY, KRW, VND...).** O app guarda valores em centavos (x100); nessas moedas o Stripe espera o valor inteiro e
  cobraria **100 vezes** o digitado. Foram retiradas da lista (`test_moedas.py` impede que voltem).

## Dá para receber em dólar **e** em real na conta do Stripe?
**Resposta curta: com a conta brasileira, provavelmente não** (confirme com o suporte do Stripe).
- O Stripe deposita sempre na **moeda do país da conta**. O Stripe Brasil exige conta bancária **em reais** para receber o repasse.
- Existe a "liquidação em várias moedas" (saldo e repasse em mais de uma moeda, **uma conta bancária por moeda**, sem taxa de câmbio), mas só em alguns países.
  Uma lista recente de terceiros cita UE, Reino Unido, Suíça, Noruega, Liechtenstein, Emirados, Austrália, Hong Kong, Singapura e EUA, **sem o Brasil**.
  A lista oficial do Stripe não carregou na minha consulta, então a confirmação final é com o Stripe.
- **Decisão de 29/10/2026 (substitui a anterior): adicional de 4 pontos na taxa do ShowUp** quando o serviço é cobrado numa moeda que o Stripe converte (`ADICIONAL_CONVERSAO_BPS`).
  O aviso do app mostra o adicional. O texto abaixo descreve a decisão ANTIGA e fica como histórico.
- **Antes:** o ShowUp absorvia a conversão. Cobrar em dólar funciona: o Stripe converte para reais pela cotação do dia e a taxa de conversão fica no custo do ShowUp.
  O profissional não paga nada a mais e a taxa do ShowUp é a mesma; o app só avisa (em *Configurações > MOEDA* e em *Novo serviço*) que o valor em reais pode variar um pouco.
  **Confira com uma cobrança de teste em dólar:** no extrato do Stripe, veja o valor que chegou ao profissional e quem arcou com a taxa de conversão. Se o Stripe a descontar do
  repasse do profissional, o texto do aviso deixa de ser verdadeiro e precisa mudar.
- **Para testar se o Stripe libera:** no painel do Stripe, *Settings > Payouts > Manage currencies* (ou peça "multi-currency settlement" ao suporte para a conta brasileira).
  Se liberarem o dólar, acrescente `USD` em `MOEDAS_RECEBIMENTO` no Render (ex.: `BRL,USD`): o aviso some só para essa moeda, sem recompilar o app.
  **Só faça isso depois de o Stripe confirmar**, porque mudar a variável não muda o que o Stripe faz. E cada profissional ainda precisaria de uma conta bancária em dólar para receber dólar.

## Profissional em outro país (Chile, Paraguai...) recebendo na moeda dele
Hoje o ShowUp **não consegue pagar** profissional fora do Brasil (a conta Stripe dele é sempre no Brasil, veja acima). Para receber em peso chileno ou em guarani
sem converter para real, o dinheiro precisa passar por uma conta no próprio país. Caminhos possíveis (cada um exige decisão sua e conferência com o Stripe):
1. **Estrutura nos EUA** (empresa americana + conta Stripe lá) usando "repasses entre países" do Stripe, que cobra 0,25% por repasse e converte a cobrança na entrada.
   Resolve quem **recebe**, mas **não elimina a conversão** que você quer evitar.
2. **Um meio de pagamento local por país** (por exemplo, um gateway com presença no Chile e no Paraguai). É um projeto de integração por país.
3. **Lançar só no Brasil agora** e abrir país a país quando houver o meio de pagamento certo (recomendado).
Moedas sem centavos (CLP, PYG) só entram quando o valor inteiro for tratado corretamente no código (hoje o app multiplica tudo por 100).

## Planos na moeda de cada país
O preço do plano está em reais e o Stripe cobra a assinatura em reais. Para cobrar em outra moeda é preciso criar, no Stripe, um **preço do plano em cada moeda** e decidir
os valores (não dá para só converter pela cotação do dia). Quando você definir a tabela, eu ligo cada moeda ao seu preço. A porcentagem por agendamento continua igual em todos os países.

## O custo (conferir nas páginas de preços do Stripe antes de decidir)

> **Atualizado em 29/10/2026:** a conta completa (com o Connect: R$ 6 por profissional ativo + 0,25% + R$ 0,67 por repasse, e o Billing: 0,7%) e a proposta
> de novas faixas estão em `PRECOS-DOS-PLANOS.md`, com a calculadora `py lancamento\calcular-precos.py`. A conversão de moeda no Stripe Brasil é **a partir de 2%**.
> A tabela abaixo é a conta antiga, sem esses custos.
As cobranças usam repasse com destino (`transfer_data.destination` + `application_fee_amount`, sem `on_behalf_of`). Nesse modelo a **taxa de
processamento do Stripe sai da plataforma**, e a taxa do ShowUp (`application_fee`) é a sua receita. Valores públicos do Stripe Brasil:
**3,99% + R$ 0,39** por cartão nacional, **+2%** para cartão internacional, e conversão de moeda (cerca de **1%**, podendo chegar a 2%).

Exemplo: serviço de **R$ 120,00** cobrado por inteiro (taxas do ShowUp: Free 10%, Profissional 5%, Ultra 2%):

| Cenário | Custo Stripe | Free (10%) | Profissional (5%) | Ultra (2%) |
|---|---|---|---|---|
| Cartão nacional | R$ 5,18 | **+ R$ 6,82** | + R$ 0,82 | **− R$ 2,78** |
| Cartão internacional + conversão (1%) | R$ 8,78 | + R$ 3,22 | **− R$ 2,78** | **− R$ 6,38** |

*Sobra (ou falta) para o ShowUp depois de pagar o Stripe; conta simples, sem imposto.* Em **falta** (só a taxa de falta é cobrada, ex.: R$ 30) o valor fixo de
R$ 0,39 pesa mais: Profissional fica em − R$ 0,09 e Ultra em − R$ 0,99, mesmo em cartão nacional.

**Conclusão:** com as faixas atuais, o plano **Ultra gera prejuízo até no cartão nacional** e o **Profissional** perde no cartão internacional. Antes de abrir
para fora do Brasil (e antes de liberar os planos pagos), decida uma destas saídas:
1. **Piso na taxa:** cobrar `max(percentual do plano, custo do Stripe + margem)` (ou um valor fixo mínimo por agendamento).
2. **Repassar o custo ao profissional** (cobrar a taxa do Stripe dele, em vez de a plataforma pagar).
3. **Subir as faixas** (ex.: Free 10%, Profissional 7%, Ultra 5%) e manter o plano Ultra só se ainda sobrar margem.
4. Deixar `PLANOS_COMPRA_HABILITADA=0` no lançamento (planos pagos "em breve") e começar só com o Free, que cobre o custo.

Confira também no **extrato do Stripe** quem de fato paga as taxas nas cobranças de teste antes de fechar a conta.
