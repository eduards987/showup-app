# Preços dos planos e taxas por atendimento

Pesquisa e contas de 29/10/2026. Calculadora: `py lancamento\calcular-precos.py` (rode de novo todo mês, depois de conferir os custos do Stripe).
**Aplicado em 29/10/2026** (seção 4): `PLANOS` e `ADICIONAL_CONVERSAO_BPS` no `backend/server.py`, e Prices novos no Stripe de **teste**. Falta o Render e o modo real (seção 6).

## 1. O que o Stripe cobra da plataforma (stripe.com/br/pricing e /br/connect/pricing, lidos em 29/10/2026)

| Item | Custo | Observação |
|---|---|---|
| Cartão nacional | **3,99% + R$ 0,39** | por cobrança. A página do Connect cita "a partir de 3,99% + R$ 0,50": confirme com o Stripe qual vale para a sua conta. |
| Cartão internacional | **+ 2%** | sobre o valor já convertido |
| Conversão de moeda | **a partir de 2%** | quando a cobrança não é em reais |
| Connect: conta ativa | **R$ 6 por mês** | por profissional que recebeu repasse no mês |
| Connect: repasse | **0,25% + R$ 0,67** | por repasse enviado ao profissional |
| Billing (assinaturas) | **0,7%** | do valor das mensalidades |
| Contestação (chargeback) | **R$ 55** | por contestação recebida, mais R$ 55 se responder manualmente (devolvidos se ganhar) |
| Pix | 1,19% | só por convite (hoje desligado) |

**Dois custos novos que a conta antiga (`TAXAS-E-MOEDAS.md`) não tinha:** o Connect (R$ 6 + repasses) e o Billing.
O ShowUp paga tudo isso, porque as cobranças usam repasse com destino (`transfer_data.destination`).

**Atenção ao calendário de repasse.** Cada repasse custa R$ 0,67. Com repasse diário, um profissional ativo custaria cerca de R$ 13 a R$ 20 por mês só nisso.
A calculadora supõe repasse **semanal** (4 por mês). Hoje o código não define o calendário, então vale o padrão do Stripe. Recomendo fixar semanal
(`settings.payouts.schedule` ao criar a conta conectada) e confirmar no painel.

## 2. O que o mercado cobra (fontes de terceiros, conferir nos sites oficiais)

| Concorrente | Preço | Observação |
|---|---|---|
| Trinks | ~R$ 110/mês (R$ 76 no anual), 1–2 profissionais | WhatsApp cobrado à parte |
| Booksy (Brasil) | R$ 99,90/mês; R$ 119,90 com 2 agendas | |
| AppBarber | R$ 79,90–89/mês | |
| BarbeiroApp, Relinq Beauty | grátis + Pro R$ 39,90/mês | |
| Agenda Tua / Minha Agenda | R$ 19,90–22,90/mês | |
| Booksy (EUA) | US$ 29,99/mês | |
| Calendly | a partir de US$ 10/mês | sem pagamento por atendimento |
| Square Appointments | grátis (1 pessoa); US$ 29–69/mês por local | taxa de cartão à parte |

O ShowUp é **mais barato que a média** e tem algo que quase nenhum deles tem: a reserva no cartão contra falta. Há espaço para subir a mensalidade.

## 3. Quanto sobrava com os planos antigos (até 29/10/2026)

Sobra mensal do ShowUp por profissional, depois do Stripe e antes de imposto:

| Perfil | Cartão | Free 10% | Profissional R$ 19,90 + 5% | Ultra R$ 59,90 + 2% |
|---|---|---|---|---|
| 30 atendimentos x R$ 100 | nacional | R$ 153,17 | R$ 21,39 | **−R$ 30,72** |
| 30 atendimentos x R$ 100 | internacional + moeda | R$ 33,17 | **−R$ 98,61** | **−R$ 150,72** |
| 60 atendimentos x R$ 120 | nacional | R$ 384,92 | R$ 42,61 | **−R$ 135,81** |

**Conclusão:** qualquer taxa abaixo de ~4,5% dá prejuízo em cada atendimento (o Stripe sozinho leva 3,99% + R$ 0,39).
O Ultra perde dinheiro a partir de uns 20 atendimentos por mês, e quanto mais o profissional usa, maior o prejuízo.

## 4. Planos em vigor desde 29/10/2026

| Plano | Mensalidade | Taxa por atendimento | Adicional em cobrança internacional |
|---|---|---|---|
| Free | R$ 0 | 10% | + 4% |
| Profissional | **R$ 29,90** | **7%** | + 4% |
| Ultra | **R$ 69,90** | **5,5%** | + 4% |

- **Nenhum perfil dá prejuízo** (a calculadora testa 4 perfis, cartão nacional e internacional; `test_calcular_precos.py` cobra isso).
- **Quando cada plano compensa para o profissional:** o Profissional passa a valer a pena acima de **~R$ 1.000/mês** em atendimentos,
  e o Ultra acima de **~R$ 2.670/mês**. São faixas realistas para autônomos.
- Mensalidades continuam abaixo de Trinks, Booksy e AppBarber.
- **Adicional de 4 pontos** (`ADICIONAL_CONVERSAO_BPS = 400`): vale quando o serviço é cobrado numa moeda que o Stripe converte para real
  (fora de `MOEDAS_RECEBIMENTO`). É gravado na reserva nos 3 fluxos (app, link com cartão, Pix). O app mostra o valor no aviso de moeda
  (Configurações e Novo serviço), lido de `GET /api/moedas`. Os Termos citam o adicional.
- **Cartão estrangeiro pagando em real não tem adicional** (seria preciso ler o país do cartão na reserva). É raro; o ShowUp absorve os 2% nesse caso.

## 5. Planos em outras moedas (sugestão, só se abrir fora do Brasil)

Hoje o servidor só tem preço de plano em reais. Os valores abaixo seguem o mercado de cada país, não a cotação, e servem de ponto de partida:

| Moeda | Profissional | Ultra |
|---|---|---|
| USD | 9,99 | 24,99 |
| EUR | 8,99 | 22,99 |
| GBP | 7,99 | 19,99 |
| CAD | 12,99 | 32,99 |
| AUD | 14,99 | 37,99 |
| MXN | 149 | 379 |
| COP | 29.900 | 74.900 |
| ARS | cobrar em USD (inflação alta) | |

## 6. Onde está cada coisa e o que falta

- [x] `PLANOS` no `backend/server.py`: Profissional R$ 29,90 + 7%, Ultra R$ 69,90 + 5,5%. Adicional de 4 pontos fora do real.
- [x] Stripe **de teste**, nos mesmos produtos (os Prices antigos de R$ 19,90 e R$ 59,90 continuam existindo, para não quebrar assinaturas de teste):
  - Profissional: `price_1UW4JvFl9Xrvr2Jycec9DkNQ` (R$ 29,90/mês)
  - Ultra: `price_1UW4JwFl9Xrvr2Jyhwi4ozls` (R$ 69,90/mês)
  - O `backend/.env` local já aponta para eles.
- [ ] **Render:** trocar `STRIPE_PRICE_ID_PROFISSIONAL` e `STRIPE_PRICE_ID_ULTRA` pelos IDs acima, **antes** de publicar o servidor novo.
  Se o servidor novo subir com os IDs antigos, ele **recusa** a assinatura ("O preço deste plano está sendo atualizado") em vez de cobrar R$ 19,90 mostrando R$ 29,90.
- [ ] **Modo real:** quando ativar o Stripe real, criar os mesmos dois Prices (mensal, BRL, R$ 29,90 e R$ 69,90) e usar esses IDs no Render.
- [ ] Assinantes que já existam no preço antigo: o Stripe continua cobrando o Price antigo. Avise com 30 dias (os Termos prometem) antes de migrar.

**Trava nova:** antes de criar a assinatura, o servidor lê o Price no Stripe e confere valor, moeda (BRL), intervalo (mensal) e se está ativo
(`_price_confere`). Mudou o preço em `PLANOS`? Crie o Price novo e troque o ID no Render no mesmo dia.
A calculadora (`ATUAIS`) e o servidor são conferidos um contra o outro em `test_calcular_precos.py`.
