# Trocar as chaves de teste pelas de produção

**Regra de ouro:** o Stripe tem dois mundos separados, *teste* e *produção*. Clientes, cartões, contas
conectadas, produtos (Price IDs) e webhooks **não passam de um para o outro**. Nunca misture a chave
secreta de um modo com a publicável do outro.

## 1. Onde cada coisa mora

| O quê | Teste | Produção | Onde é configurado |
|---|---|---|---|
| Chave secreta | `sk_test_...` | `sk_live_...` | Render > Environment: `STRIPE_API_KEY` |
| Chave publicável | `pk_test_...` | `pk_live_...` | EAS (`EXPO_PUBLIC_STRIPE_PUBLISHABLE_KEY`) **e** `firebase-hosting/public/agendar.html` (constante `STRIPE_PUBLISHABLE_KEY`) |
| Segredos dos webhooks | `whsec_...` (teste) | `whsec_...` (produção) | Render: `STRIPE_WEBHOOK_SECRET` (plataforma) e `STRIPE_CONNECT_WEBHOOK_SECRET` (Connect) |
| Price IDs dos planos | `price_...` (teste) | `price_...` (produção) | Render: `STRIPE_PRICE_ID_PROFISSIONAL` / `_ULTRA` (só se `PLANOS_COMPRA_HABILITADA=1`). O Price precisa ter **exatamente** o valor de `PLANOS` (R$ 29,90 e R$ 69,90, mensal, BRL), senão o servidor recusa assinar |
| Backend usado pelo app | — | URL pública (https) | EAS: `EXPO_PUBLIC_BACKEND_URL`; `agendar.html`: `BACKEND_URL` |

> **Como o backend escolhe o gateway:** `STRIPE_API_KEY` vazia = modo **simulado** (aprova reservas sem cobrar nada — só
> para desenvolvimento); `sk_test_`/`sk_live_`/`rk_...` válida = Stripe real; preenchida e **inválida** = o servidor se
> recusa a subir (o Render mantém a versão anterior no ar). Depois de trocar a chave, confirme com
> `python lancamento/verificar-producao.py ...`: ele acusa `gateway = mock` se algo escapou.

## 2. Ordem

1. Ative a conta da plataforma no Stripe (Dashboard > Ativar conta) e espere ficar liberada.
2. Faça os webhooks (seção 4) **antes** de trocar a chave, para já ter o `whsec_` de produção.
3. No **Render > Environment**, troque `STRIPE_API_KEY`, `STRIPE_WEBHOOK_SECRET` e `STRIPE_CONNECT_WEBHOOK_SECRET` e defina:
   - `EXIGIR_RECEBIMENTO_ATIVO=1`
   - `PLANOS_COMPRA_HABILITADA=0` (primeira versão no Google Play — ver `LANCAMENTO.md`, decisão 1)
   - `PUBLIC_WEB_BASE_URL` e `ALLOWED_ORIGINS` com o endereço do site
4. Edite `agendar.html`: troque `pk_test_...` por `pk_live_...`, rode `python lancamento/preencher-site.py --verificar` e publique (`firebase deploy --only hosting`).
5. No **EAS** (seção 3), troque a chave publicável e gere o build de produção.
6. Faça uma reserva real de valor baixo (R$ 5) e confira: cobrança, taxa, repasse e webhooks chegando (Dashboard > Developers > Webhooks > ver entregas).

## 3. Variáveis no EAS (build de produção)

Em `expo.dev` > projeto `holdbooked-app` > **Environment variables**, crie no ambiente **production**:

- `EXPO_PUBLIC_BACKEND_URL` — URL https do backend
- `EXPO_PUBLIC_GOOGLE_WEB_CLIENT_ID` — o mesmo do backend
- `EXPO_PUBLIC_STRIPE_PUBLISHABLE_KEY` — `pk_live_...`

Variáveis `EXPO_PUBLIC_*` ficam **dentro do app** (qualquer pessoa pode lê-las). Só coloque ali o que é público:
nunca a `sk_`, o `GOOGLE_CLIENT_SECRET` nem tokens. Depois: `eas build --profile production --platform android`.

## 4. Webhooks no Stripe (Developers > Webhooks) — dois endpoints, mesma URL

URL dos dois: `https://SEU-BACKEND/api/webhooks/stripe`

**A) Endpoint da plataforma.** Eventos:
`payment_intent.payment_failed`, `payment_intent.canceled`, `payment_intent.succeeded`,
`charge.dispute.created`, `customer.subscription.updated`, `customer.subscription.deleted`,
**`customer.subscription.trial_will_end`** (avisa o profissional 3 dias antes do fim do teste grátis).
O `whsec_` desse endpoint vai em `STRIPE_WEBHOOK_SECRET`.

**B) Endpoint de Connect** — marque **"Escutar eventos em contas conectadas"**. Evento: `account.updated`
(é o que mantém a liberação dos repasses em dia). Cada endpoint tem o **seu próprio** `whsec_`: o desse vai
em **`STRIPE_CONNECT_WEBHOOK_SECRET`**. O backend aceita a assinatura de qualquer um dos dois e recusa o resto.
Sem o endpoint B o sistema continua funcionando: um job a cada 10 minutos reconsulta as contas ainda pendentes.

## 5. Voltar atrás

Se algo der errado, volte `STRIPE_API_KEY` e `STRIPE_WEBHOOK_SECRET` para os de teste no Render: o backend
volta ao modo teste em segundos. O app e o site, porém, trazem a chave publicável embutida — por isso o teste
com R$ 5 antes de divulgar.
