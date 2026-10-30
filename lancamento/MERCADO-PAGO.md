# Mercado Pago: segunda forma de o profissional receber (só Brasil)

Desde 30/10/2026 o profissional escolhe, em **Configurações > Onde você recebe**, entre **Stripe** e **Mercado Pago**.
Sem as variáveis abaixo no Render, a opção nem aparece e tudo continua só com o Stripe.

## Como funciona

| | Stripe | Mercado Pago |
|---|---|---|
| Quem paga a tarifa do cartão | o ShowUp | **o profissional** (sai do valor dele) |
| Taxa do ShowUp | Free 10%, Profissional 7%, Ultra 5,5% | **3 pontos a menos**: 7%, 4%, 2,5% (`DESCONTO_MERCADOPAGO_BPS`) |
| Reserva no cartão vale | 7 dias | **5 dias** (agenda abre menos dias à frente) |
| Bandeiras | todas | **Visa, Mastercard, Amex, Cabal** (só elas aceitam cobrar só a taxa de falta) |
| Pix | só por convite (`PIX_STRIPE_HABILITADO`) | **sempre ligado**, 30 minutos para pagar |
| Moedas | 9 | **só reais** |
| Onde o cliente agenda | app ou link | **só pelo link** (o cartão salvo no app é do Stripe) |

- O dinheiro cai direto na conta do profissional e o Mercado Pago repassa ao ShowUp a `application_fee` (modelo marketplace).
- Cada agendamento grava o gateway em que foi feito (`gateway: "mercadopago"`). Trocar de Stripe para Mercado Pago (ou o contrário)
  vale só para os agendamentos novos; os antigos terminam onde começaram.
- Os tokens do profissional ficam **cifrados** no banco (`cofre.py`, chave `MERCADOPAGO_TOKEN_KEY`). O token vale 180 dias e é renovado
  sozinho (antes de cada cobrança, se faltar menos de 7 dias, e por um job a cada 12 h para quem vence em 30 dias).
- Pagamento confirmado: o servidor nunca confia no corpo do aviso. Ele confere a assinatura (`x-signature`) e **consulta** o pagamento no
  Mercado Pago. A página do cliente também consulta enquanto espera o Pix, então funciona mesmo se o aviso atrasar.

## O que você precisa fazer (uma vez)

1. **Conta de desenvolvedor:** [mercadopago.com.br/developers](https://www.mercadopago.com.br/developers) > *Suas integrações* > *Criar aplicação*.
   Tipo: pagamentos on-line, **Checkout Transparente / Checkout API**, modelo **marketplace**. Peça a liberação de marketplace se for solicitado.
2. **URL de redirecionamento** da aplicação (OAuth): `https://SEU-SERVIDOR/api/mercadopago/callback`
   (hoje `https://showup-backend-s9y1.onrender.com/api/mercadopago/callback`). Tem que ser idêntica à do Render.
3. **Webhooks** (*Suas integrações > Webhooks*): URL `https://SEU-SERVIDOR/api/webhooks/mercadopago`, evento **Pagamentos**.
   Copie a **chave secreta** que o painel mostra.
4. **Chave do cofre:** gere uma vez e guarde (perder a chave obriga cada profissional a conectar de novo):
   `py -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"`
5. **Render > Environment** (nunca no código nem em conversa):

| Variável | Valor |
|---|---|
| `MERCADOPAGO_CLIENT_ID` | *Client ID* da aplicação |
| `MERCADOPAGO_CLIENT_SECRET` | *Client Secret* da aplicação |
| `MERCADOPAGO_REDIRECT_URI` | a URL do passo 2 |
| `MERCADOPAGO_WEBHOOK_SECRET` | a chave secreta do passo 3 |
| `MERCADOPAGO_TOKEN_KEY` | a chave do passo 4 |
| `MERCADOPAGO_SANDBOX` | `1` enquanto testa com credenciais de teste; apague em produção |

6. Publique na ordem de sempre: **site** (`firebase deploy`) → **servidor** → **app**. A página nova lê `recebimento`, `mp_public_key` e
   `pix_disponivel` do servidor; com o site antigo, quem recebe pelo Mercado Pago veria o formulário do Stripe.

## Teste obrigatório antes de ligar em produção (sandbox)

A documentação do Mercado Pago deixa três pontos em aberto. O código se protege, mas **confirme com cobranças de teste**:

- [ ] **Reserva sem cobrar (`capture: false`):** a documentação lista o erro 2077 "Deferred capture not supported". Faça uma reserva de teste
  e confira no painel que o pagamento fica **autorizado** (não aprovado). Se vier aprovado direto, o servidor devolve o dinheiro e recusa a
  reserva (o cliente vê erro e pode pagar com Pix).
- [ ] **Taxa na cobrança da falta:** na captura parcial o servidor manda a taxa proporcional (`application_fee` do valor da falta) e depois
  confere o que o Mercado Pago gravou. Se ele mantiver a taxa cheia, o agendamento fica com `taxa_a_devolver_centavos` e aparece no log
  ("Mercado Pago gravou taxa..."). Faça uma falta de teste e confira no painel quanto ficou para o ShowUp.
- [ ] **Avisos de pagamento:** pague um Pix de teste e confira no log do Render que chegou o aviso com assinatura válida. (Pagamentos com
  credenciais de teste às vezes não mandam aviso; a página confirma consultando, então o agendamento confirma do mesmo jeito.)
- [ ] Repita uma reserva, um "compareceu", uma falta, um cancelamento e um Pix com **R$ 5** em produção antes de divulgar.

## Onde está cada coisa

- `backend/mercadopago_gateway.py`: chamadas ao Mercado Pago, conversão centavos ↔ reais, assinatura dos avisos.
- `backend/cofre.py`: cifra dos tokens.
- `backend/server.py`: `MERCADOPAGO_*`, `DESCONTO_MERCADOPAGO_BPS`, `_recebe_pelo_mp`, `/api/me/recebimento`, `/api/me/mercadopago/conectar`,
  `/api/mercadopago/callback`, `/api/public/agendamentos/mercadopago/cartao`, Pix em `/api/public/agendamentos/pix`, `/api/webhooks/mercadopago`.
- `backend/agenda.py`: `HOLD_DIAS_MERCADOPAGO = 5`.
- App: `src/lib/recebimento.ts`, `src/components/recebimento-card.tsx`, `configuracoes.tsx`, `book/[servicoId].tsx` (manda para o link).
- Página: `firebase-hosting/public/agendar.html` (formulário do Mercado Pago e Pix).
- Testes: `backend/tests/test_mercadopago.py`.

## Problemas comuns

- **A opção não aparece no app:** falta uma das 5 variáveis ou a `MERCADOPAGO_TOKEN_KEY` é inválida. O log do Render mostra
  `mercadopago=False` no "Startup complete".
- **"Essa conta do Mercado Pago já está ligada a outro profissional":** cada conta do Mercado Pago recebe por um profissional só.
- **"Não foi possível conectar":** a URL de redirecionamento do painel não é idêntica à `MERCADOPAGO_REDIRECT_URI`.
- **Pix pago depois do prazo** (aviso muito atrasado): o agendamento fica com `pago_apos_expirar: true` e um erro no log. Devolva ao cliente
  pelo painel do Mercado Pago.
