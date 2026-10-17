# HoldBooked — PRD

## Vision
SaaS de agendamentos para prestadores de serviço com **retenção de pagamento anti-no-show**: pré-autorização (hold) no cartão do cliente no ato da reserva; captura total, captura da taxa de no-show, ou liberação natural conforme o profissional confirmar.

## Stack
- **Frontend**: Expo Router (React Native) — iOS, Android, web preview.
- **Backend**: FastAPI + Motor + MongoDB.
- **Auth**: Google Sign-In gerenciada pela Emergent (`https://auth.emergentagent.com`).
- **Payment gateway**: MOCADO em `/app/backend/gateway.py` (mesma máquina de estados do Stripe `capture_method='manual'`, persistida em MongoDB). Substituição por Stripe real é drop-in — apenas trocar `MockGateway` por `StripeGateway`.

## Papéis
- Cliente: busca profissionais, reserva serviços, salva cartão de teste, vê status do hold.
- Profissional: cadastra serviços com valor + taxa de no-show + duração, vê agenda, confirma **compareceu** (captura total) ou **não compareceu** (captura só a taxa).

## Modelo de dados (MongoDB)
- `users` — user_id, email, name, picture, role.
- `user_sessions` — session_token, expires_at (TTL 7d).
- `customer_cards` — user_id, customer_id, payment_method_id, brand, last4.
- `servicos` — servico_id, profissional_id, valor_centavos, taxa_no_show_centavos, duracao_min, ativo.
- `agendamentos` — agendamento_id, profissional_id, cliente_id, servico_id, horario_inicio/fim, snapshots de valor+taxa, hold_status, status_confirmacao, payment_intent_id, hold_expira_em, janela_confirmacao_expira_em, valor_capturado_centavos.
- `transacoes` — ledger imutável (authorization, capture, partial_capture) com gateway_object_id.
- `gateway_payment_intents` — MockGateway store simulando o PI do Stripe.

## Endpoints
Auth:
- `POST /api/auth/session`, `GET /api/auth/me`, `POST /api/auth/role`, `POST /api/auth/logout`

Cliente:
- `POST /api/me/card`, `GET /api/me/card`
- `GET /api/profissionais?q=`, `GET /api/profissionais/{id}`
- `POST /api/agendamentos`, `POST /api/agendamentos/{id}/cancelar`
- `GET /api/agendamentos`, `GET /api/agendamentos/{id}`

Profissional:
- `POST /api/servicos`, `GET /api/servicos`, `DELETE /api/servicos/{id}` (soft delete)
- `POST /api/agendamentos/{id}/confirmar` `{ resultado: compareceu | nao_compareceu }`

Jobs:
- `POST /api/internal/jobs/expirar-janela` — cron que marca `sem_resposta` + `hold_status=expirado`.

## Máquina de estados do hold
```
                            ┌─── compareceu ────────► capturado_total (100% valor)
autorizado ──confirmar──────┤
                            └─── nao_compareceu ────► capturado_taxa (só taxa no-show)

autorizado ──cancelar──────► cancelado (void)

autorizado ──janela expira─► expirado (job cron)
```

## Frontend (screens)
- `app/welcome.tsx` — Google Sign-In.
- `app/role-select.tsx` — Cliente / Profissional.
- Tabs em `(app)/`:
  - **Início** (`home.tsx`) — cliente vê próximas reservas + banner cartão; profissional vê "precisam de confirmação" + agenda.
  - **Buscar** (`search.tsx`, só cliente) — lista com filtro por nome.
  - **Serviços** (`servicos.tsx` + `novo-servico.tsx`, só profissional).
  - **Reservas** (`agendamentos.tsx`) — lista com badges de hold/confirmação.
  - **Perfil** (`perfil.tsx`) — cadastro de cartão (cliente), logout.
- Detalhe: `profissional/[id].tsx`, `book/[servicoId].tsx` (chip de dia/horário, sticky pay bar), `agendamento/[id].tsx` (ações compareceu / no-show com modal de confirmação).

## Testes
- Backend: 28/28 casos pytest passando (`/app/backend/tests/test_full_backend.py`) cobrindo criação de serviço, hold, captura total/parcial, cancelamento, expiração, RBAC e índices.

## Próximos passos
- Substituir `MockGateway` por `StripeGateway` quando uma chave real for provida.
- Proteger `/api/internal/jobs/*` por token de serviço.
- Migrar `@app.on_event` para `lifespan`.
- Adicionar disponibilidade real do profissional (hoje slots são gerados no frontend).
- Notificações (build nativa) para lembrete de janela de confirmação.

## Changelog — Módulos de confiabilidade (auditoria)

### Módulo 1 — Confiabilidade de pagamento
- `security.py` (novo): guarda de token de serviço para rotas `/internal/*`.
- `webhooks.py` (novo): `POST /api/webhooks/stripe` com verificação de assinatura,
  idempotência por event_id, tratamento de payment_intent.payment_failed,
  charge.dispute.created, account.updated, payment_intent.canceled.
- Scheduler (APScheduler) chama `_expirar_janela()` automaticamente a cada 5min —
  antes dependia de chamada manual ao endpoint.
- `confirmar()` e `_expirar_janela()` usam transição atômica pendente->processando
  (find_one_and_update) para eliminar corrida entre confirmação e expiração.
- CORS: allowlist via env var `ALLOWED_ORIGINS` (antes: `*` com credentials, inválido).
- Migrado `@app.on_event` -> `lifespan`.

### Módulo 2 — Idempotência e erros do gateway
- `payment_errors.py` (novo): CardDeclinedError, GatewayUnavailableError,
  InvalidPaymentRequestError — server.py não depende mais do SDK do Stripe
  para tratar erro.
- Todas as chamadas ao gateway (authorize/capture/void/expire) agora exigem
  `idempotency_key` determinística (baseada em agendamento_id) — retry de rede
  não duplica hold nem captura.
- `requirements.txt`: adicionado `stripe` (estava faltando — quebraria
  `pip install` em ambiente limpo) e `apscheduler`.

## Pendente (não coberto ainda)
- Rate limiting em endpoints de auth/booking.
- Coleta de cartão real (Payment Sheet) — hoje usa cartão de teste fixo do Stripe.
- Push notification nativa para pedir confirmação de presença ao profissional.
- `memory/test_credentials.md` foi REMOVIDO deste pacote por conter segredos de
  teste — remova-o também do histórico do git antes de tornar o repo público.
- INTERNAL_SERVICE_TOKEN no .env é um placeholder — gere um valor real com
  `openssl rand -hex 32` antes de subir o servidor (ele falha o boot sem isso).

### Módulo 3 — Rate limiting
- Adicionado `slowapi` (Limiter por IP, limite default global de 200/min).
- Limites específicos nos endpoints de maior risco de abuso:
  - `POST /api/auth/session` — 10/min (alvo clássico de força-bruta de sessão)
  - `POST /api/me/card` — 10/min (superfície de "card testing")
  - `POST /api/agendamentos` — 20/min (cada chamada gera hold real no cartão)
  - `POST /api/agendamentos/{id}/confirmar` — 30/min
  - `POST /api/agendamentos/{id}/cancelar` — 30/min
- BUG REAL encontrado e corrigido durante validação: `from __future__ import
  annotations` em server.py quebrava a geração do schema OpenAPI nos
  endpoints decorados com `@limiter.limit(...)` (interação conhecida entre
  PEP 563 e o wrapper do slowapi). Removido — Python 3.12 não precisa dele
  para a sintaxe usada no arquivo (list[str], X | None, etc.).
- Validado de verdade: import do módulo + geração do schema OpenAPI rodando
  com as versões EXATAS do requirements.txt (fastapi==0.110.1). 27 rotas
  /api registradas corretamente, nenhum payload vazando para querystring.

### Módulo 4 — Push notification "compareceu?"
Backend:
- `expo_push.py` (novo): cliente HTTP puro para a Expo Push API, sem SDK.
  Detecta token `DeviceNotRegistered` para auto-limpeza.
- `PUT/DELETE /api/me/push-token`: registra/remove o Expo push token do
  usuário logado (um token por usuário, mesmo padrão de /me/card).
- Novo job agendado `_enviar_pushes_confirmacao()` (mesma cadência de 5min do
  job de expiração):
  1. "Pergunta": assim que `horario_fim` passa e status ainda é pendente,
     manda push perguntando se o cliente compareceu.
  2. "Urgência": quando faltam <2h para o hold expirar sem resposta, manda
     um segundo push de última chance.
  Cada uma dispara só uma vez por agendamento (campos
  `push_pergunta_enviada_em` / `push_urgencia_enviada_em`).
- Rota manual `/internal/jobs/enviar-pushes` (mesma proteção de token de
  serviço) para depuração/operação.

Frontend:
- `src/lib/push-notifications.ts` (novo): pede permissão, obtém o Expo push
  token (`expo-notifications` + `expo-device`) e registra no backend.
- `src/lib/use-push-registration.ts` (novo): hook que registra o token para
  profissionais autenticados e navega para `/agendamento/[id]` ao tocar na
  notificação (cobre app em background E cold start).
- Conectado em `app/(app)/_layout.tsx`; `signOut()` em `auth.tsx` agora
  desregistra o token antes de encerrar a sessão.
- `app.json`: plugin `expo-notifications` adicionado; `extra.eas.projectId`
  criado como placeholder — PRECISA ser preenchido com o project ID real
  (rode `eas init`) antes de gerar um build de produção, senão o token nunca
  é obtido.

## IMPORTANTE — limitação de plataforma
Push remoto real (não local) exige um **development build via EAS**, não
funciona no app Expo Go a partir do SDK 53+ no Android. Teste com
`eas build --profile development` ou `npx expo run:android` /
`npx expo run:ios`, nunca só com `expo start` + app Expo Go da loja.

## Validação real feita (não só sintaxe)
- Backend: import do módulo + geração do schema OpenAPI com as versões
  pinadas do requirements.txt — 26 rotas, incluindo as duas novas de push.
- Frontend: `expo-notifications@57.0.19` e `expo-device@57.0.2` instalados
  de verdade (versões confirmadas compatíveis com o SDK 57 via registry do
  npm) e `tsc --noEmit` rodado no projeto inteiro — zero erros nos arquivos
  novos/editados (os erros pré-existentes em configuracoes.tsx, search.tsx,
  welcome.tsx e theme.ts não são deste módulo e continuam pendentes).

## Módulo 5 — Auditoria completa do projeto (erros e brechas)

### Bugs de lógica/segurança corrigidos no backend
1. **Double-booking (crítico)**: `criar_agendamento` nunca checava conflito de
   horário antes de criar o hold. Corrigido com checagem de sobreposição de
   intervalo + índice único parcial no Mongo (profissional_id+horario_inicio,
   só entre holds ativos) como defesa em profundidade contra a corrida exata.
   Em caso de perder a corrida, o hold já autorizado no cartão do perdedor é
   desfeito automaticamente (void), em vez de ficar órfão.
2. **Corrida cancelar() x confirmar()/expirar_janela (crítico)**: cancelar()
   não tinha guarda atômica — um cancelamento podia entrar bem no meio de uma
   confirmação em andamento e chamar void() num payment_intent que confirmar()
   estava capturando ao mesmo tempo. Corrigido com a mesma técnica de
   transição atômica (find_one_and_update) usada em confirmar()/expirar_janela.
3. **Rótulo errado no cancelamento**: cancelar() sempre gravava
   status_agendamento="cancelado_cliente", mesmo quando era o profissional
   quem cancelava. Corrigido para refletir quem realmente cancelou.
4. **auth/session quebrava em replay**: o redirect de OAuth pode disparar
   duas vezes no mobile (deep link quente + cold start); a segunda chamada
   com o mesmo session_token quebrava com 500 por violar o índice único.
   Trocado insert_one por upsert (replace_one).
5. **500 cru em disponibilidade malformada**: HH:MM inválido ("25:99") ou
   hora_fim <= hora_inicio não eram validados, gerando erro não tratado em
   vez de 422 claro. Adicionados field_validators no Pydantic.
6. `.dict()` (deprecated no Pydantic v2) trocado por `.model_dump()`.

### Bugs corrigidos no frontend
- `api.ts`: corpo de erro não-JSON (ex: página HTML de um proxy/gateway)
  derrubava com SyntaxError crua em vez de ApiError tratável.
- 4 erros reais de TypeScript pré-existentes (type-check completo do projeto
  agora passa com ZERO erros):
  - `ProfissionalPublic` no frontend não tinha o campo `categorias`, que o
    backend sempre retorna (search.tsx já tentava usá-lo).
  - `StyleSheet.absoluteFillObject` não existe nos types desta versão de RN
    — trocado por `StyleSheet.absoluteFill`.
  - `useColorScheme()` pode devolver "unspecified" (comum no Android), não
    tratado no `useTheme()`.
  - `configuracoes.tsx` passava `categorias` possivelmente undefined pro
    useState tipado como string[].

### Item identificado, NÃO corrigido ainda (decisão de produto necessária)
- **Fuso horário**: disponibilidade (HH:MM) e cálculo de slots assumem UTC
  implicitamente. Para profissionais no Brasil (UTC-3), os horários que eles
  cadastram provavelmente saem 3h defasados do que pretendiam. Precisa de um
  campo de timezone por profissional + conversão consistente — escopo maior,
  fica pendente de decisão.

### Validação real (não só sintaxe)
- Backend: reimportado + schema OpenAPI gerado após cada mudança (26 rotas).
- Backend: os 3 cenários do novo validador de disponibilidade testados de
  verdade (válido / formato inválido / fim antes do início) — todos corretos.
- Frontend: `tsc --noEmit` no projeto inteiro — 0 erros (eram 6 antes desta
  auditoria).

## Módulo 6 — Timezone por profissional

Backend:
- Campo `timezone` no User (default `America/Sao_Paulo`), validado contra
  uma lista fechada de fusos brasileiros (`TIMEZONES_BR`): São Paulo, Manaus,
  Rio Branco, Fernando de Noronha. Lista fechada em vez de aceitar qualquer
  IANA tz — evita erro de digitação e mantém a UI simples (4 opções).
- `GET /api/timezones` (lista as opções) e `PUT /api/me/timezone`.
- `slots_disponiveis` reescrito para usar `zoneinfo.ZoneInfo` de verdade: o
  HH:MM cadastrado em disponibilidade agora é interpretado como hora de
  parede NO FUSO do profissional, convertido corretamente pro instante UTC
  via `datetime.combine(data, hora, tzinfo=tz)`. O "hoje" usado pra gerar os
  próximos 14 dias também passou a ser calculado no calendário local do
  profissional, não em UTC (importante pra quem está perto da virada do dia).
- `timezone` exposto em `ProfissionalDetail` para o app do cliente rotular
  os horários mostrados.

Frontend:
- `configuracoes.tsx`: nova seção "FUSO HORÁRIO" (mesmo padrão visual de
  categorias) pro profissional escolher e salvar.
- `book/[servicoId].tsx`: mostra "Horários no fuso de Brasília (UTC-3)" (ou
  o fuso correspondente) acima da lista de dias/horários, pro cliente nunca
  ficar em dúvida sobre a que horário local aquilo corresponde.
- `TIMEZONE_LABELS` centralizado em `src/lib/format.ts` (usado nas duas telas).

### Validação real
- Testei a conversão de fuso de verdade (não só leitura de código): 09:00
  em America/Sao_Paulo -> 12:00 UTC ✓; 09:00 em America/Manaus -> 13:00 UTC
  ✓; timezone inválida/ausente cai pro default sem quebrar ✓.
- Backend: reimportado + schema OpenAPI (28 rotas agora).
- Frontend: `tsc --noEmit` no projeto inteiro — 0 erros.

## Módulo 7 — Suporte a múltiplas moedas ("código pra todos os países")

Contexto: moeda estava hardcoded em "BRL"/"brl" em 5 lugares do backend +
formatação fixa em pt-BR no frontend. Generalizado pra qualquer país que o
Stripe atenda, sem quebrar nada que já funcionava em BRL.

Backend:
- Moeda é uma propriedade do PROFISSIONAL (`User.moeda`, default BRL), não
  do serviço individual — decisão deliberada: a conta Connect dele só
  liquida numa moeda, então faz mais sentido configurar uma vez no perfil.
  Serviço criado herda a moeda do profissional NO MOMENTO da criação
  (mudar depois não altera serviços já existentes, só os próximos).
- `MOEDAS_SUPORTADAS`: lista fechada (BRL, USD, EUR, GBP, MXN, ARS, COP,
  CLP, CAD, AUD) — mesma filosofia de TIMEZONES_BR (evita erro de digitação,
  fácil de estender depois sem tocar em mais nada).
- `GET /api/moedas` + `PUT /api/me/moeda`.
- Os 5 pontos com "BRL"/"brl" hardcoded (criar_servico, criar_agendamento,
  doc do agendamento, transação de captura, stripe_gateway.py, gateway.py)
  agora leem a moeda real do profissional/serviço/agendamento.
- `StripeGateway.authorize()` e `MockGateway.authorize()` ganharam parâmetro
  `moeda` (default "BRL" só por compatibilidade, sempre passado explicitamente
  pelas chamadas reais).

Frontend:
- `formatBRL()` → `formatMoney(centavos, moeda)`, usando `Intl` com locale
  indefinido (deixa o dispositivo formatar, só a moeda vem do dado) —
  atualizado nos 6 arquivos que exibem valores monetários (17 chamadas).
  `formatBRL` mantido como alias deprecated (chama formatMoney com "BRL")
  como rede de segurança.
- Nova seção "MOEDA" em Configurações, mesmo padrão visual de fuso horário.
- `User.moeda` adicionado ao tipo de auth.

### O que "todos os países" NÃO cobre ainda (decisão de escopo, não bug)
- **Idioma/tradução**: todo o app está em português. Suportar outro idioma
  é um projeto de i18n separado (extrair strings, sistema de tradução),
  não coberto por este módulo.
- **Onboarding de Connect por país**: já funciona automaticamente — o
  Stripe Connect Express onboarding (pra onde o app já redireciona) se
  adapta sozinho às exigências legais/fiscais de cada país suportado pelo
  Stripe. Nenhuma mudança de código necessária aqui.
- **Preço das assinaturas (Free/Profissional/Top) em outras moedas**: usar
  o recurso de multi-currency Price do próprio Stripe (a tela que já vimos)
  é o caminho certo, mas os valores por moeda devem ser escolhidos a dedo
  por mercado (ex: US$4,99), não gerados por conversão automática de câmbio.

### Validação real
- Testei de verdade (não só leitura de código): `MockGateway.authorize()`
  chamado com moeda="USD", "EUR" e sem moeda (default) — o PaymentIntent
  simulado grava a currency correta em cada caso (usd/eur/brl).
- Backend: reimportado + schema OpenAPI (30 rotas).
- Frontend: `tsc --noEmit` no projeto inteiro — 0 erros.

## Módulo 8 — Planos de assinatura (Free/Profissional/Top)

Backend:
- `PLANOS`: Free (10%, R$0), Profissional (5%, R$19,90), Top (2%, R$59,90).
- Campo `plano` no profissional (default "free"); `_fee_bps_for()` calcula a
  taxa vigente por chamada (nunca afeta agendamentos já criados, só os
  próximos — cada authorize() já grava o fee_bps no momento da criação via
  application_fee_amount do PaymentIntent).
- Corrigido de brinde: `create_connect_account` tinha `country="BR"` fixo —
  agora usa `MOEDA_PAIS_CONNECT` pra abrir a conta Connect no país certo a
  partir da moeda do profissional (heurística razoável, não uma seleção de
  país explícita — ver comentário no código).
- Endpoints: `GET /api/planos`, `POST /api/me/plano/checkout` (cria Checkout
  Session do Stripe em modo subscription), `POST /api/me/plano/cancelar`
  (cancela a assinatura e volta pro Free imediatamente).
- Webhook: `checkout.session.completed` ativa o plano de verdade (fonte da
  verdade — não confia no retorno síncrono do checkout, que pode não
  acontecer se o usuário fechar o navegador antes);
  `customer.subscription.deleted/updated` reverte pro Free se a assinatura
  cair (cartão expirado, cancelamento direto no dashboard do Stripe, etc).
- `.env`: `STRIPE_PRICE_ID_PROFISSIONAL` / `STRIPE_PRICE_ID_TOP` são
  PLACEHOLDERS vazios — sem eles, `/api/planos` marca `disponivel: false` e
  o checkout recusa com erro claro (não quebra).
- `APP_SAAS_FEE_BPS` marcado como obsoleto no `.env` (substituído por PLANOS).

Frontend:
- `src/lib/open-external-checkout.ts` (novo): helper que abre fluxos
  hospedados (Stripe Checkout, Connect onboarding) corretamente em web E
  nativo. BUG REAL corrigido de brinde: o fluxo de Connect onboarding só
  funcionava na web (dependia de `window`, inexistente em React Native) —
  no app nativo ele não fazia nada, silenciosamente. Reescrito com
  `expo-web-browser` + `expo-linking` pro caso nativo.
- `app/(app)/planos.tsx` (novo): mostra os 3 planos, taxa de cada um, plano
  atual destacado, botão de assinar (abre Checkout) ou cancelar (volta pro
  Free). Planos sem Price ID configurado mostram "Em breve" em vez de
  quebrar.
- Card "Plano e taxa por agendamento" adicionado em `perfil.tsx`, mesmo
  padrão visual do card de Configurações.

### Limitação conhecida (não é bug, é natureza do fluxo assíncrono)
Depois do checkout, a confirmação de verdade vem do webhook do Stripe, que
pode levar alguns segundos pra chegar depois do navegador fechar. A tela
atualiza otimisticamente (auth.refresh() logo após o retorno), mas o plano
pode não refletir instantaneamente — normal, resolve sozinho em poucos
segundos.

### Validação real
- Testei de verdade `_fee_bps_for()` nos 5 cenários (free/profissional/top/
  sem doc/plano desconhecido) — todos corretos.
- Backend: reimportado + schema OpenAPI (33 rotas).
- Frontend: `npx expo export --platform web` rodou com sucesso (Metro
  empacotou o app inteiro, 1376 módulos, sem erro de bundling) — confirma
  que `planos.tsx` e as mudanças em `perfil.tsx`/`configuracoes.tsx` estão
  sintaticamente corretas e todos os imports resolvem de verdade.
- `tsc --noEmit`: 1 erro remanescente, que é falso-positivo de cache do
  expo-router (`.expo/types/router.d.ts` desatualizado — arquivo gerado,
  não versionado, não vai no zip, se regenera sozinho no primeiro
  `expo start` do usuário).

## Módulo 9 — Coleta de cartão real (Stripe Payment Sheet) + app mobile-only

### Decisão de escopo: app é MOBILE-ONLY, sem build web
Toda lógica condicional de plataforma web foi removida do projeto:
- `app.json`: removido o bloco `"web"` (bundler/output/favicon).
- `package.json`: removidas `react-dom` e `react-native-web` (não usadas
  diretamente em lugar nenhum, só existiam pra suportar build web).
- `src/utils/storage/index.web.ts` REMOVIDO — só resta `index.ts` (Keychain/
  EncryptedSharedPreferences reais via expo-secure-store).
- `auth.tsx`: removida toda a ramificação `Platform.OS === "web"` no fluxo
  de login/sessão (extração de session_id da URL do navegador, etc.) — só
  resta o fluxo nativo (deep link + WebBrowser.openAuthSessionAsync).
- `open-external-checkout.ts` e `push-notifications.ts`: mesma limpeza.

Por que isso importa tecnicamente, não só como preferência: o pacote
`@stripe/stripe-react-native` importa código nativo no NÍVEL DO MÓDULO —
isso quebrava o build web inteiro mesmo com um `if (Platform.OS...)` dentro
do componente (o bundler tenta resolver o import antes de qualquer código
rodar). Descobri isso rodando `expo export --platform web` de verdade, não
só com `tsc`. Como a decisão agora é não ter build web, esse problema
simplesmente deixa de existir — não precisou de nenhuma divisão de arquivo
`.native.tsx`/`.web.tsx` (cheguei a criar essa divisão numa iteração
anterior desta mesma conversa e depois consolidei de volta em arquivos
únicos quando o escopo mudou para mobile-only).

### Coleta de cartão real
Backend (`stripe_gateway.py` + `gateway.py` mock + `server.py`):
- Removido `attach_test_card` (usava o cartão de teste fixo `pm_card_visa`).
- Novo fluxo com `SetupIntent` (não `PaymentIntent`) — apropriado pra só
  salvar um cartão pra uso futuro (`usage="off_session"`, o que já é
  exatamente o que `authorize()` faz depois nos agendamentos).
- `POST /api/me/card/setup-intent`: cria/reusa o Customer do cliente, gera
  uma Ephemeral Key (exigida pelo Payment Sheet pra gerenciar métodos de
  pagamento do customer com segurança) e um SetupIntent. Retorna os 3
  segredos que o app precisa pra inicializar o Payment Sheet.
- `POST /api/me/card/confirm`: chamado depois que o Payment Sheet já
  confirmou no app. NÃO confia cegamente no relato do cliente — busca o
  SetupIntent de volta no Stripe e confere `status == "succeeded"` e
  `customer == <o customer certo>` antes de salvar qualquer coisa como
  cartão válido. Testei de verdade os dois casos (confirma certo, rejeita
  customer errado).
- Sem webhook adicional aqui (diferente do checkout de assinatura) —
  decisão deliberada: como o /confirm já busca a verdade direto no Stripe
  de forma síncrona, um webhook seria redundante pra este fluxo específico.

Frontend:
- `@stripe/stripe-react-native@0.77.0` instalado, plugin configurado em
  `app.json` (sem Apple Pay/Google Pay — fora de escopo, exige setup de
  merchant ID separado).
- `EXPO_PUBLIC_STRIPE_PUBLISHABLE_KEY` — PLACEHOLDER vazio no `.env`,
  precisa da chave publicável real (Dashboard > Developers > API keys).
- `src/components/card-setup-button.tsx` (novo): fluxo completo
  setup-intent -> initPaymentSheet -> presentPaymentSheet -> confirm.
- `src/components/stripe-app-provider.tsx` (novo): envolve a árvore com
  `StripeProvider` (só pula se a chave publicável não estiver configurada
  ainda — não é mais sobre plataforma).
- `perfil.tsx`: nota antiga "Cartão de teste, não é feita cobrança real"
  removida — não é mais verdade, cartões agora podem ser reais dependendo
  de qual chave Stripe (test ou live) está configurada no backend.
- IMPORTANTE: `@stripe/stripe-react-native` EXIGE development build via
  EAS — não funciona no app Expo Go da loja (mesma exigência já documentada
  pra push notification no Módulo 4).

### Validação real
- Backend: testei o fluxo completo no mock (ensure_customer ->
  ephemeral_key -> setup_intent -> confirm), incluindo o caso de segurança
  de rejeitar confirmação com customer_id errado.
- Frontend: `npx expo export --platform ios` E `--platform android`
  rodaram com sucesso (1773 módulos cada), confirmando que o app bundla de
  verdade nas duas plataformas mobile com o SDK do Stripe integrado.
- `tsc --noEmit`: único erro remanescente é o falso-positivo de cache de
  rotas já documentado (`.expo/types/router.d.ts`), não relacionado a este
  módulo.

## Item resolvido — INTERNAL_SERVICE_TOKEN real
Gerado via `openssl rand -hex 32` (64 caracteres hex) e já substituído no
`.env` do backend, no lugar do placeholder. Validado: o servidor importa e
sobe normalmente com o valor real (security.py aceita o token na inicialização).

## Itens resolvidos — Price IDs reais + renomeação Top -> Ultra

- Plano "Top" renomeado para "Ultra" em todo o código (chave do dicionário
  PLANOS, nome exibido, env var STRIPE_PRICE_ID_TOP -> STRIPE_PRICE_ID_ULTRA,
  descrição no frontend). Nenhuma referência antiga restante (confirmado via
  busca no projeto inteiro).
- `.env`: STRIPE_PRICE_ID_PROFISSIONAL e STRIPE_PRICE_ID_ULTRA preenchidos
  com os Price IDs reais criados no Stripe Dashboard. Confirmado: os 3
  planos (free/profissional/ultra) aparecem com `disponivel: true` na rota
  /api/planos — o checkout dos planos pagos já pode funcionar de verdade.
- `app/+html.tsx` removido (era o template HTML específico de build web do
  Expo Router — órfão desde a decisão de app mobile-only no módulo anterior).

### Validação real
- Backend: reimportado, PLANOS impresso e conferido (3 planos, taxas
  corretas, disponibilidade correta com os Price IDs reais).
- Frontend: `expo export --platform ios` rodou com sucesso depois de
  remover +html.tsx — confirma que a remoção não quebrou nada.

## MongoDB Atlas real configurado (substituindo localhost)

- `.env`: `MONGO_URL` agora aponta pro cluster real do Atlas (`ProjectFirst`,
  usuário `eduards987_db_user`). `DB_NAME` renomeado de "test_database"
  (placeholder do template original) para "holdbooked".
- `requirements.txt`: adicionado `dnspython` (obrigatório pra connection
  strings `mongodb+srv://`, que é o formato do Atlas — sem isso o
  `pip install` fica incompleto e a conexão falha só na hora de rodar).
- Removida a linha `emergentintegrations==0.2.0`: não existe no PyPI
  público e não é importada em lugar nenhum do código — quebraria
  `pip install -r requirements.txt` de qualquer pessoa, inclusive você.

### Limitação confirmada deste ambiente sandbox
Testei de verdade (DNS + conexão TCP) e confirmei: este ambiente de
desenvolvimento NÃO tem acesso de rede a `*.mongodb.net` — só alguns
domínios específicos (PyPI, npm, GitHub) são liberados aqui. Por isso não
consigo rodar a suíte pytest contra o Atlas real a partir daqui; os scripts
de simulação com mongomock que eu tinha montado foram removidos (ficaram
obsoletos assim que você trouxe o Atlas real).

### Como rodar a suíte de verdade (você, na sua máquina)
```
cd backend
pip install -r requirements.txt
export EXPO_PUBLIC_BACKEND_URL=http://127.0.0.1:8001
uvicorn server:app --host 0.0.0.0 --port 8001 &
pytest
```
O `.env` já tem o MONGO_URL do Atlas — o servidor vai ler de lá sozinho.
Se o STRIPE_API_KEY no .env for uma chave de teste válida, os testes vão
exercitar a integração real com o Stripe (modo teste), não um mock.

**Atenção:** o Atlas por padrão só libera conexão do IP que você cadastrou
no onboarding (Network Access). Se rodar de uma rede diferente, precisa
adicionar o novo IP lá antes.

## Bug real corrigido — testes usando MongoDB errado (localhost em vez de Atlas)

Causa raiz confirmada (rodado pelo próprio usuário): o servidor (uvicorn)
carrega o `.env` sozinho via `load_dotenv()` dentro de `server.py`, mas os
arquivos de teste (`tests/test_*.py`) leem `MONGO_URL`/`DB_NAME` direto de
`os.environ` SEM carregar o `.env` — como pytest roda num processo
diferente do servidor, essas variáveis nunca chegavam lá. Resultado: os
testes caíam no default `mongodb://localhost:27017/test_database` (um
Mongo que não existe nesse ambiente) enquanto o servidor rodava contra o
Atlas de verdade — causando "Invalid session" em cascata (24 passed, 34
failed, 15 errors).

Corrigido com `tests/conftest.py` (convenção padrão do pytest, carregado
automaticamente antes de qualquer teste) que chama `load_dotenv()` no
`.env` do backend. Validei de verdade que MONGO_URL/DB_NAME carregam
corretamente depois disso (sem imprimir a senha).

Também seta EXPO_PUBLIC_BACKEND_URL com um default sensato
(http://127.0.0.1:8001) caso não seja passada na linha de comando —
test_auth_endpoints.py exige essa var sem fallback e quebraria com KeyError
confuso sem isso.

### Ainda não confirmado
Não sei se isso resolve TODAS as 34 falhas + 15 erros — é muito provável
que a maioria fosse efeito cascata da mesma causa raiz (sessão/usuário não
encontrado no banco errado), mas só teremos certeza rodando de novo.

## Bug real encontrado e corrigido — customer_id inconsistente no fluxo de cartão

Ao validar localmente antes de pedir pro usuário rodar de novo, achei um bug
genuíno de arquitetura no Módulo 9 (não era problema do MongoDB/Atlas):
`ensure_customer()` só considerava um customer_id "existente" se já houvesse
um documento em `customer_cards` — mas esse documento só é criado no FINAL
do fluxo (depois do cartão confirmado). Resultado: `/me/card/setup-intent`
criava um Customer A, e `/me/card/confirm` (chamado logo em seguida, ainda
sem customer_cards) criava um Customer B DIFERENTE — o SetupIntent (vinculado
a A) nunca batia com o customer usado pra confirmar (B), falhando sempre.
Isso afetaria o Stripe real do mesmo jeito, não só o mock.

Corrigido: `ensure_customer()` agora persiste o customer_id em
`db.users.stripe_customer_id` assim que criado — idempotente desde a
primeira chamada, não só depois do cartão confirmado. Mesma correção
aplicada em `gateway.py` (mock) e `stripe_gateway.py` (real).
`card_confirm()` simplificado pra sempre usar `ensure_customer()` (que
agora é confiável) em vez da lógica ad-hoc anterior.

### Testes atualizados pra API nova
- `tests/conftest.py`: novo helper `attach_test_card()` que simula o que o
  Payment Sheet faria — pega o SetupIntent, confirma com o cartão de teste
  oficial do Stripe (`pm_card_visa`, ou nada se for MockGateway, que já
  marca como succeeded na criação), confirma no backend. Substituído em
  12 call sites (nos dois arquivos de teste) que ainda chamavam o antigo
  `POST /api/me/card` (removido no Módulo 9).
- `test_auth_endpoints.py`: `test_cors_allows_cross_origin` testava o
  comportamento ANTIGO e inseguro (CORS aberto pra qualquer origem) — é
  exatamente o que o Módulo 3 corrigiu. Substituído por dois testes:
  origem cadastrada é aceita, origem não cadastrada é bloqueada.

### Validação real (local, com Mongo simulado — não o Atlas)
- `attach_test_card()` testado de verdade contra um servidor rodando: 200,
  brand=visa, last4=4242. Confirma que a correção do customer_id resolveu.
- CORS: origem cadastrada → aceita; origem não cadastrada → bloqueada.
- Disponibilidade + slots: criar serviço, setar disponibilidade (7 dias),
  buscar slots → 195 horários gerados corretamente, todos com
  iso/day_label/time_label. Sugere que a falha de "slots" relatada era
  efeito cascata do bug do cartão, não um problema à parte — mas isso só
  será confirmado de verdade rodando a suíte completa de novo.

## Rate limiting bloqueando a própria suíte de testes

Das 5 falhas restantes, pelo menos 3 eram causadas pelo rate limiting do
Módulo 3: a suíte chama `/me/card/setup-intent` (limite 10/min) e outros
endpoints protegidos dezenas de vezes em poucos segundos, todas do mesmo IP
(localhost) — os próprios testes tomavam 429 em vez do status que estavam
verificando (ex: esperava 403 "profissional não pode salvar cartão", veio
429 "rate limit excedido" antes de sequer chegar na checagem de role).

Corrigido com uma env var dedicada `TESTING=1` que desliga o rate limiter
inteiro (`Limiter(..., enabled=not _TESTING)` — parâmetro nativo do
slowapi). Testado nos dois sentidos: com TESTING=1 o limiter fica
desabilitado; sem a variável (produção), continua protegido por padrão.

### Comando de teste atualizado
```
TESTING=1 uvicorn server:app --host 0.0.0.0 --port 8001 &
EXPO_PUBLIC_BACKEND_URL=http://127.0.0.1:8001 pytest
```

### As 2 falhas de "slots sem serviço disponível" — hipótese, não confirmada
`test_no_disponibilidade_returns_empty` (TestSlots) espera que um serviço já
exista pra profissional2, criado antes em `test_filter_by_categoria`
(TestDiscoveryCategoria, classe diferente no mesmo arquivo). O pytest.ini
usa `-n 2 --dist loadscope`, que por padrão mantém testes do mesmo MÓDULO
(arquivo) no mesmo worker — então a hipótese de corrida entre workers
paralelos é fraca, mas não descartada. Não tive como confirmar sem rodar de
verdade; pedido ao usuário a saída completa (traceback, não só resumo) caso
persista depois do fix do rate limit.

## Última falha corrigida — 73/74 → 74/74 (esperado)

`TestExpirarJanela::test_job_marks_expired` chamava
`POST /api/internal/jobs/expirar-janela` sem o header `X-Internal-Token` —
exatamente a proteção que adicionamos no Módulo 1 pra esse endpoint nunca
ficar acessível sem autenticação. Corrigido: o teste agora manda
`X-Internal-Token: <INTERNAL_SERVICE_TOKEN do .env>`, lido via
`os.environ["INTERNAL_SERVICE_TOKEN"]` (já carregado pelo conftest.py).

De brinde: `httpx` estava faltando no `requirements.txt` — usado de
verdade em `server.py` (chamada ao serviço de auth do Emergent), mas nunca
declarado. Adicionado.

### Suíte de testes: status final
73 passando / 1 falhando (antes desta correção) → esperado 74/74 depois
dela. Progresso total desde o início: 24 passed/34 failed/15 errors →
74/74 esperado, todas as causas raiz identificadas e corrigidas:
1. conftest.py não carregava .env (Mongo errado)
2. Endpoint de cartão mudou de API (Módulo 9) — testes desatualizados
3. Bug real: customer_id inconsistente no fluxo de SetupIntent
4. Teste de CORS testava o comportamento antigo inseguro de propósito
5. Rate limiting (Módulo 3) bloqueando a própria suíte
6. Teste do job interno sem o token de serviço exigido (Módulo 1)

## As 2 últimas falhas — causa raiz confirmada

Eram exatamente a hipótese que eu tinha levantado: `pytest-xdist` com
`--dist loadscope` agrupa testes por CLASSE (não por arquivo inteiro) —
então `TestDiscoveryCategoria` e `TestSlots`, apesar de estarem no mesmo
arquivo, podem rodar em workers paralelos diferentes, sem garantia de
ordem entre si. Dois testes em `TestSlots` dependiam de um serviço criado
por `TestDiscoveryCategoria.test_filter_by_categoria` — uma corrida, não
uma garantia, e por isso passava ou falhava dependendo de qual worker
terminava primeiro.

Corrigido tornando os dois testes autossuficientes — cada um cria seu
próprio serviço via API em vez de depender de outra classe já ter rodado:
- `TestSlots.test_no_disponibilidade_returns_empty`
- `TestSlots.test_slots_generated_for_14_days`

Isso é uma correção de design de teste, não uma mudança em `pytest.ini`
(que segue como estava, -n 2 --dist loadscope intocado).

### Status esperado: 74/74

## ✅ SUÍTE DE TESTES: 74/74 PASSANDO (confirmado pelo usuário, contra Atlas real)

Validação ponta a ponta completa: MongoDB Atlas real + servidor real +
suíte pytest real, todas as causas raiz corrigidas. Backend considerado
validado para este ciclo de desenvolvimento.

## .gitignore criado + .env.example (backend e frontend)

Criado `.gitignore` na raiz cobrindo: segredos (.env, memory/test_credentials.md),
Python (__pycache__, .pytest_cache, venv), Expo/Node (node_modules, .expo,
.metro-cache, builds nativos ios/android), ferramentas geradas (.emergent,
test_reports) e SO/editor (.DS_Store, .vscode).

Criados `backend/.env.example` e `frontend/.env.example` com todas as
variáveis necessárias, sem valores reais — documentação de setup pra quem
clonar o projeto do zero.

### Validação real
Rodei `git init` temporário + `git add -A` + `git status` pra confirmar de
verdade (não só ler o .gitignore): apenas os `.env.example` ficaram
rastreados, os `.env` reais e `memory/test_credentials.md` foram
corretamente ignorados, e node_modules/__pycache__ não apareceram. O `.git`
de teste foi removido antes de empacotar — o usuário roda `git init` de
verdade na própria máquina.

**Ação pendente do usuário:** se já tinha um `.git` local antes desta
mudança com test_credentials.md commitado em algum commit antigo, precisa
apagar `.git` e rodar `git init` de novo (nunca foi pra um repositório
remoto, então é seguro) — passos já dados na conversa.

## ✅ EAS project ID configurado

Projeto criado na conta Expo do usuário (educerqueira): slug
"holdbooked-app", ID e403a3c9-d25f-4337-860a-2bd5df12e201. Atualizado no
app.json: `extra.eas.projectId` (era placeholder), `slug` (era "frontend",
agora bate com o nome real do projeto na Expo) e `owner` adicionado
explicitamente. Validado via leitura do JSON.

Com isso, todos os itens do checklist de lançamento estão fechados:
cartão real, planos com Price IDs reais, INTERNAL_SERVICE_TOKEN,
MongoDB Atlas real, suíte pytest 74/74, .gitignore, e agora EAS project ID.
Push notification e Payment Sheet já têm tudo que precisam pra funcionar
num development build.

## eas.json criado (perfis de build)

Não existia ainda — criado com 3 perfis:
- **development**: `developmentClient: true` (obrigatório — sem isso, o
  build não inclui os módulos nativos do Stripe/push, e viraria só mais um
  "Expo Go" que não serve pro que precisamos testar), distribuição interna
  (instala direto por link, sem loja), Android gera `.apk` (mais fácil de
  instalar manualmente que `.aab`). iOS aponta pra dispositivo físico por
  padrão (`simulator: false`) — Payment Sheet real e push notification real
  precisam de aparelho físico pra validação de verdade.
- **preview**: build interno sem dev client, pra testar antes de produção.
- **production**: incremento automático de versão, pronto pra either loja.

Testei `eas whoami` neste ambiente: "Not logged in" — confirma que a build
em si (`eas build`) precisa rodar na máquina do usuário, onde a sessão de
login (feita via navegador) realmente existe. Este ambiente sandbox não tem
acesso à sessão da conta Expo do usuário.

## Plano de build: Android agora, iOS em duas etapas

Usuário confirmou: sem conta Apple Developer ainda. Adicionado perfil
`development-simulator` no eas.json (ios.simulator: true) — não exige conta
Apple nem gera custo, mas só roda no Simulador Xcode (precisa de Mac) e não
recebe push notification real (limitação da própria Apple pra simuladores,
não do nosso código).

Plano:
1. Android: `eas build --profile development --platform android` — sem
   bloqueio, testa push E cartão real.
2. iOS sem conta Apple: `eas build --profile development-simulator --platform ios`
   — só testa cartão (Payment Sheet), não push.
3. iOS completo (quando tiver conta Apple, US$99/ano):
   `eas build --profile development --platform ios` (perfil original,
   dispositivo físico) — testa tudo, inclusive push.

## Rebranding: HoldBooked → ShowUp

Nome final escolhido pelo usuário: **ShowUp**. Atualizado:
- `app.json`: `name` ("frontend" → "ShowUp" — esse era o problema mais
  sério, "frontend" apareceria embaixo do ícone no celular);
  `android.package` (de "com.emergent.noshowguard.e2b287", resquício da
  plataforma original, para "com.educerqueira.showup" — usando o username
  Expo do usuário como namespace, já que ele não tem domínio próprio e não
  precisa ter pra isso).
- `slug` mantido como "holdbooked-app" DE PROPÓSITO — o projeto já foi
  criado na Expo com esse slug vinculado ao projectId real
  (e403a3c9-d25f-4337-860a-2bd5df12e201); trocar o slug agora sem recriar o
  projeto geraria inconsistência. Slug é só técnico, nunca aparece pro
  usuário final, então não há problema prático em ficar diferente do nome
  visível do app.
- Frontend: texto da tela de seleção de papel, `merchantDisplayName` do
  Payment Sheet (visível na tela de pagamento de verdade).
- Backend: título da API FastAPI, resposta do endpoint raiz, docstrings.
- Testes: `test_auth_endpoints.py` verificava o texto exato
  `"HoldBooked API"` na resposta — corrigido pra não quebrar a suíte
  74/74 que tínhamos acabado de fechar.

### ⚠️ IMPORTANTE — package Android é praticamente permanente
Depois de publicar na Play Store com um `android.package`, trocar esse
valor depois equivale a lançar um app NOVO do zero (perde reviews,
histórico, downloads). Se o usuário quiser mudar de novo, precisa ser
ANTES do primeiro upload real pra Play Store.

### Validação real
- Backend: `py_compile` em todos os arquivos alterados (incl. testes).
- Frontend: `tsc --noEmit` (só o falso-positivo de cache de rotas já
  documentado) + `expo export --platform android` rodou com sucesso
  (bundle de 4.4MB gerado sem erro).

## Ícone do app criado (ShowUp)

O ícone anterior (`assets/images/icon.png`) era o logo genérico da
plataforma "Emergent" que gerou o projeto originalmente — nunca tinha sido
trocado. Desenhei um ícone novo do zero: um calendário estilizado com um
check mark grande, comunicando "confirmado/compareceu" (o conceito central
do produto). Cor de marca reaproveitada do `theme.ts` (#5C7C64), com um
gradiente sutil pro fundo do ícone principal.

Arquivos gerados (via SVG desenhado à mão + cairosvg pra conversão):
- `icon.png` (1024×1024): ícone principal, com fundo em gradiente.
- `adaptive-icon.png` (1024×1024): só o foreground (calendário+check),
  fundo transparente, desenhado dentro da "safe zone" de ~66% central —
  o Android aplica sua própria máscara de forma (círculo/squircle) por
  cima, então o conteúdo real não pode encostar nas bordas.
- `splash-image.png` (1024×1024): mesmo design, escala maior (85%), usado
  centralizado sobre o `backgroundColor` na tela de abertura do app.

`app.json`: `adaptiveIcon.backgroundColor` e o `backgroundColor` do plugin
`expo-splash-screen` trocados de `#000000` (preto, não combinava) para
`#4A6650` (o tom mais escuro do gradiente do ícone) — consistência visual
entre o ícone e a tela de abertura.

### Validação real
Testado em duas resoluções (512px e 80px simulando o tamanho real na tela
do celular) — o design permanece legível e reconhecível mesmo pequeno.
Simulei também a máscara circular do Android sobre o adaptive-icon pra
confirmar que nada importante fica cortado. `expo export --platform
android` rodou com sucesso depois de trocar os assets.

## Ícone trocado de novo — monograma "S/U" (versão refinada)

Usuário trouxe 5 variações de monograma "SU" (fita/ribbon style) geradas
externamente, pediu avaliação. Testei as 5 redimensionadas pra 100px (uso
real de ícone) — confirmou visualmente que as 2 com efeito "negative
space" (segundo tom verde-claro sobre fundo verde-escuro) perdem
legibilidade nesse tamanho: o segundo tom quase desaparece por baixo
contraste, virando uma mancha confusa em vez de uma letra reconhecível.
As 3 de tom único (fita creme sólida) se mantiveram nítidas.

Usuário pediu uma versão MELHOR ainda, usando as 5 como referência. Redesenhei
do zero um monograma S→U: um único traço contínuo, sem se cruzar (as
primeiras tentativas cruzavam o traço no meio e ficavam confusas, tipo nó/
letra "8" quebrada — descartadas). A versão final é um gesto de "S" na
metade de cima que se estende pra baixo e abre numa alça de "U", em fita
creme sólida (#F5F1E8) sobre fundo em gradiente verde-floresta (#345940 →
#213B29) — paleta extraída por amostragem de pixel das referências do
usuário, não inventada.

Arquivos gerados (mesmo processo de sempre: SVG à mão + cairosvg):
- `icon.png`: monograma completo, com fundo gradiente + sombra suave.
- `adaptive-icon.png`: só o traço, sem fundo, dentro da safe zone Android.
- `splash-image.png`: mesmo traço, escala maior, centralizado.
- `app.json`: `adaptiveIcon.backgroundColor` e `expo-splash-screen.
  backgroundColor` trocados de #4A6650 (do ícone anterior, calendário) pra
  #213B29 (tom mais escuro do gradiente novo).

### ⚠️ Ponto em aberto — consistência de marca
A cor de marca usada DENTRO do app (`theme.ts`, `brandPrimary: "#5C7C64"`,
um verde-oliva claro) agora está DIFERENTE da paleta do ícone (verde-
floresta escuro + creme). Ficou assim de propósito — o pedido foi só pelo
ícone — mas fica uma inconsistência visual entre o ícone na tela inicial
do celular e as cores dentro do app. Não alterado ainda; decisão do
usuário se quer unificar.

### Validação real
- Testei as 5 referências do usuário reduzidas a 100px ANTES de opinar —
  não dei recomendação só olhando em tamanho grande.
- 3 iterações do meu próprio design, testando em 512px, 100px e 48px a
  cada rodada, até eliminar cruzamentos confusos no traço.
- `expo export --platform android` rodou com sucesso depois da troca final.

## Ícone e paleta refeitos por completo — baseados numa referência do usuário

Usuário achou minha versão anterior (monograma verde-floresta sólido) "cara
de feito por criança" e trouxe uma referência gerada externamente
(Gemini): um logo S→U com um check integrado, em gradiente azul→verde,
com brilho/profundidade "glossy". Pediu pra recriar isso como ícone de
app de verdade E levar essa paleta pro app inteiro.

### Processo de design (várias iterações até acertar)
1. Extraí as cores REAIS da referência por amostra de pixel automatizada
   (filtrando por saturação HSV pra ignorar o fundo cinza) — não inventei:
   azul #3071A7→#4E98C2, verde #5FAE6E.
2. Tentei reconstruir com arcos SVG geométricos "perfeitos" (svg arc
   command) — resultado ficou parecendo um número "6"/"b", não S→U.
   Descartado.
3. Tentei S e U como 2 formas separadas sobrepostas — o S ficou incompleto,
   lendo como "C". Descartado.
4. Voltei pra estrutura de curvas bezier já validada numa iteração anterior
   da conversa (que lia bem como S→U), aplicando o gradiente novo — forma
   boa, mas o check ficou escondido atrás da curva do S.
5. Afastei o check pra fora da forma principal — aí sim ficou reconhecível
   como ✓ separado, sem se perder na curva.
6. Adicionei brilho sutil (gradiente branco translúcido) na borda superior
   das curvas + sombra suave — o efeito "glossy" que dava a sensação
   premium na referência.

### Arquivos gerados
- `icon.png`, `adaptive-icon.png` (foreground, safe zone Android),
  `splash-image.png` — mesmo processo de sempre (SVG à mão + cairosvg).
- `app.json`: `backgroundColor` do adaptive icon e splash trocado de
  #213B29 (verde escuro, ícone anterior) pra #F4F4F2 (cinza bem claro,
  igual ao fundo da nova referência).

### Paleta levada pro app inteiro (não só o ícone)
`theme.ts` é a fonte única de cores de marca do app inteiro (usado via
`makeStyles` em praticamente toda tela) — trocar lá propaga sozinho pra
quase todos os botões/destaques, sem precisar caçar tela por tela:
- `brandPrimary`/`brand`: #5C7C64 (verde-oliva antigo) → #3F86B5 (azul do
  logo)
- `brandSecondary`: #9CAEA2 → #5FAE6E (verde do logo)
- `brandTertiary`/`onBrandTertiary`: tons claros de verde → tons claros
  de azul (#E3EEF5 / #1E4A63)
Achei também 2 lugares com a cor antiga hardcoded FORA do theme.ts
(`agendamentos.tsx` e `agendamento/[id].tsx`, no mapa de cor do badge de
status "info") — corrigidos pra bater com a paleta nova.

### Validação real
- Testei cada iteração do desenho em 512px/100px/48px antes de seguir pra
  próxima etapa — só avancei quando a legibilidade se confirmava.
- `tsc --noEmit`: só o falso-positivo de cache de rotas já documentado.
- `expo export --platform android` rodou com sucesso depois de toda a
  mudança de tema.

## Revertido — usuário não gostou do ícone azul-verde com check

O ícone/paleta azul-verde (S→U→check, gradiente, tema do app inteiro
mudado) foi revertido a pedido do usuário ("ficou muito ruim, mantenha
como estava"). Voltou tudo ao estado anterior:
- `icon.png`/`adaptive-icon.png`/`splash-image.png`: monograma S→U verde-
  floresta sólido (sem check, sem gradiente azul).
- `app.json`: backgroundColor de volta pra #213B29.
- `theme.ts`: brand/brandPrimary/brandSecondary/brandTertiary de volta
  pro verde-oliva original (#5C7C64 e derivados).
- `agendamentos.tsx` / `agendamento/[id].tsx`: badge "info" de volta pra
  #E4EBE6/#3B5241.

Lição: antes de propagar uma mudança de paleta pro app inteiro, vale
confirmar com o usuário só o ícone primeiro, já validado em isolamento,
antes de levar a mudança pra mais lugares.

## Ícone final — usando a imagem real do usuário (não recriação manual)

Depois de várias tentativas frustradas de recriar o logo S/U/check à mão
via SVG (nenhuma ficou boa o suficiente), o usuário mandou a imagem já
ajustada/limpa e pediu pra usar ELA diretamente. Mudei de abordagem:
processar a imagem real em vez de redesenhar do zero.

### Processo
1. Detecção da bounding box do logo por saturação HSV (mais robusto que
   comparar cor de fundo direto — a imagem tinha uma leve vinheta/gradiente
   no fundo que confundia uma detecção ingênua).
2. Recorte com margem de 6%, centralizado num canvas quadrado 1024×1024
   (a imagem original era 1439×1149, não quadrada).
3. Remoção de fundo por threshold de saturação, gerando canal alpha suave
   (transição curta, não corte binário duro) — sem serrilhado visível.
4. `adaptive-icon.png`: logo transparente redimensionado pra 62% do canvas
   (safe zone Android) — simulei a máscara circular do sistema por cima
   pra confirmar que nada corta errado.
5. `splash-image.png`: mesma logo, 78% do canvas.
6. Cores extraídas por amostragem automática (filtro de saturação HSV,
   igual да vez anterior): azul #4C97C1, verde #7FB667, fundo #EDEBEC.

### Paleta levada pro app inteiro de novo
`theme.ts`: brandPrimary/brand → #4C97C1 (azul), brandSecondary → #7FB667
(verde), brandTertiary/onBrandTertiary → tons claros de azul. Mais os 2
hardcodes de badge "info" em `agendamentos.tsx`/`agendamento/[id].tsx`
atualizados pra combinar.

### Validação real
- Testei a versão recortada em 100px e 48px antes de aplicar — muito mais
  legível que qualquer uma das minhas tentativas de recriação manual.
- Simulei a máscara circular do Android sobre o adaptive-icon.
- `tsc --noEmit` + `expo export --platform android` rodaram limpos.

### Lição registrada
Quando o usuário já tem uma imagem de referência PRONTA (não um esboço
pra interpretar), processar a imagem real (recorte, remoção de fundo,
extração de cor) é muito mais confiável do que tentar recriar o desenho à
mão via SVG — evita a divergência de qualidade que causou 2 rodadas de
insatisfação antes desta.

## 🎉 App rodou de verdade no emulador Android pela primeira vez

Depois de 3 erros de ambiente resolvidos em sequência pelo usuário (JAVA_HOME
inválido, NDK corrompido, JDK do Android Studio incompatível com o CMake do
React Native — resolvido instalando JDK 17 dedicado), o build funcionou:
"Android Bundled 17193ms, node_modules/expo-router/entry.js (2026 modules)".
Tela de boas-vindas renderizada no emulador Pixel 10a.

## Último resquício de branding "HOLDBOOKED" encontrado e corrigido
`app/welcome.tsx` tinha `<Text style={styles.brand}>HOLDBOOKED</Text>` —
escapou da varredura de rebranding anterior (a busca original não pegou
esse arquivo por algum motivo). Corrigido pra "SHOWUP". Sweep final
case-insensitive confirmou mais 2 ocorrências triviais (domínio de e-mail
fictício `@holdbooked.example.com` usado só internamente pelos testes,
sem nenhum efeito visível) — corrigidas por consistência total.
Frontend e backend confirmados 100% livres do nome antigo agora.

## Limpeza de resquícios da plataforma Emergent (parte 1 — cosmética)

Removidos artefatos internos da plataforma original que não têm nenhum
valor pro projeto:
- `.emergent/` (config interna da plataforma: emergent.yml, cron, markers)
- `test_result.md` (protocolo de comunicação entre agentes da própria
  Emergent — "main_agent"/"testing_agent" — não é nosso)
- `test_reports/` (relatórios de execuções antigas, gerados pela Emergent)
- `design_guidelines.json` (paleta de cores "HoldBooked" já desatualizada
  desde o rebranding pra ShowUp — nada no código lê esse arquivo)
- `README.md` reescrito do zero (antes só tinha o placeholder "Here are
  your Instructions" da plataforma)

Corrigido de brinde: `app.json` tinha `ios.bundleIdentifier:
"com.emergent.noshowguard.e2b287"` — só troquei o `android.package`
antes e esqueci esse. Agora "com.educerqueira.showup".

Achado real (não só cosmético): os arquivos de teste tinham um
**fallback pra um servidor de demonstração hospedado pela própria
Emergent** (`https://no-show-guard.preview.emergentagent.com`) — se
alguém rodasse a suíte sem configurar EXPO_PUBLIC_BACKEND_URL
explicitamente, tentaria bater nesse servidor de terceiros em vez de
falhar claramente. Trocado pra `http://127.0.0.1:8001`.

## ⚠️ PENDENTE — dependência crítica de arquitetura (parte 2, não feita ainda)

O sistema de login inteiro do app depende de dois endpoints que pertencem
à Emergent, não a nós:
- Backend: `EMERGENT_AUTH_URL = "https://demobackend.emergentagent.com/auth/v1/env/oauth/session-data"`
- Frontend: `AUTH_URL = "https://auth.emergentagent.com/"`

O fluxo hoje: o app abre a página de login da Emergent (não do Google
direto), o usuário loga com Google LÁ, a Emergent devolve um session_id,
nosso backend troca esse ID por dados do usuário chamando o servidor
deles. A Emergent atua como proxy completo do OAuth — nunca falamos com o
Google diretamente.

Isso é um risco real de continuidade: é um serviço rotulado "demo" que
pode sair do ar sem aviso, e o usuário não tem controle nenhum sobre ele.

Correção necessária: integrar direto com o Google OAuth (Google Cloud
Console, criando Client IDs OAuth próprios do usuário — isso precisa ser
feito pelo usuário, não é algo que dá pra fazer sem a conta Google dele),
usando `expo-auth-session` ou `@react-native-google-signin/google-signin`
no frontend, e validação direta do ID token do Google no backend (sem
mais depender de nenhum servidor de terceiros).

Ainda não implementado — depende de decisão/setup do usuário no Google
Cloud Console antes de eu poder escrever o código.

## ✅ Item crítico resolvido — login direto com o Google, sem Emergent

Substituído o fluxo inteiro de autenticação que dependia de servidores de
terceiros (`demobackend.emergentagent.com` e `auth.emergentagent.com`) por
integração direta com o Google.

### Backend (`server.py`)
- `SessionRequest.session_id` → `SessionRequest.id_token`.
- `/auth/session` agora usa `google.oauth2.id_token.verify_oauth2_token()`
  (biblioteca oficial `google-auth`) pra validar o ID token que o app manda
  — confere assinatura, expiração, e que o `audience` bate com
  `GOOGLE_WEB_CLIENT_ID`. Zero chamada de rede pra qualquer servidor
  nosso ou de terceiros além do próprio Google.
- `GOOGLE_WEB_CLIENT_ID` obrigatório no `.env` — servidor recusa subir sem
  isso, mesmo padrão de proteção já usado pro `INTERNAL_SERVICE_TOKEN`.
- Tratamento de erro específico: `ValueError` (token malformado/assinatura
  inválida/expirado) → 401; `GoogleAuthError` (falha de rede buscando as
  chaves públicas do Google) → 503, distinto de token realmente inválido.
- `session_token` (a sessão interna do nosso app) agora é gerado por nós
  mesmos (`uuid4+uuid4`), nunca mais repassado de um servidor externo.
- `httpx` removido dos imports do server.py (não é mais usado ali — segue
  sendo dependência real via `expo_push.py`, não removido do
  requirements.txt).
- `google-auth>=2.35.0` adicionado ao requirements.txt.

### Frontend (`auth.tsx` reescrito)
- `@react-native-google-signin/google-signin` instalado (SDK nativo oficial
  do Google) + plugin no `app.json`.
- Todo o mecanismo de deep link (`Linking`, `WebBrowser`,
  `extractSessionId`, captura de URL fria/quente) foi removido — o SDK
  nativo devolve o resultado direto no app, sem precisar de navegador nem
  redirect.
- `signIn()`: `GoogleSignin.hasPlayServices()` → `GoogleSignin.signIn()` →
  extrai `idToken` → manda pro backend em `POST /auth/session
  {id_token}`.
- `GoogleSignin.configure({webClientId: ...})` lido de
  `EXPO_PUBLIC_GOOGLE_WEB_CLIENT_ID` — precisa ser o MESMO Client ID tipo
  Web usado no backend (`GOOGLE_WEB_CLIENT_ID`), já que é o "audience" que
  o backend confere.
- `signOut()` agora também chama `GoogleSignin.signOut()`.

### Placeholders que o usuário precisa preencher (Google Cloud Console)
- `backend/.env`: `GOOGLE_WEB_CLIENT_ID=""`
- `frontend/.env`: `EXPO_PUBLIC_GOOGLE_WEB_CLIENT_ID="SUBSTITUA_PELO_CLIENT_ID_TIPO_WEB"`
- Os dois precisam ter o MESMO valor (o Client ID tipo "Web application",
  não o Android nem o iOS).
- Também precisa criar Client ID tipo Android (package
  com.educerqueira.showup + SHA-1 do keystore de debug) e tipo iOS
  (bundle com.educerqueira.showup) no mesmo projeto do Google Cloud —
  esses dois não entram em nenhum arquivo de código, só precisam existir
  cadastrados no Console pra o SDK nativo funcionar.

### Validação real
- Testei local (sandbox sem rede pra googleapis.com): confirmado que um
  token válido tentaria buscar as chaves reais do Google (comportamento
  correto); um token malformado ainda tenta a chamada de rede antes de
  falhar — meu tratamento de GoogleAuthError cobre esse caso como 503.
  Numa máquina com internet normal, um token realmente malformado deve
  cair em ValueError (401) depois de baixar as chaves — não consegui
  confirmar esse caminho específico aqui por falta de rede no sandbox,
  mas a lógica e o teste estão corretos para o ambiente real.
- Backend: reimportado com um Client ID de teste configurado + schema
  OpenAPI gerado (35 rotas, sem mudança de contagem — só o payload mudou).
- Frontend: `tsc --noEmit` (só o falso-positivo de cache já documentado) +
  `expo export --platform android` rodou com sucesso incluindo o novo
  módulo nativo de login.
- Teste `test_auth_session_invalid_session_id_returns_401` renomeado e
  atualizado pra `test_auth_session_invalid_id_token_returns_401`,
  refletindo o novo payload e mensagem de erro.

## ✅ Client IDs do Google configurados com valores reais

Usuário criou os 3 Client IDs no Google Cloud Console (projeto "showup"):
- **Web** (com Client Secret, não usada no fluxo mobile —
  offlineAccess:false não precisa dela): usado nos dois `.env`.
- **Android**: package `com.educerqueira.showup` + SHA-1 do keystore de
  debug — cadastrado no Console, não entra em nenhum arquivo de código.
- **iOS**: bundle `com.educerqueira.showup` — idem, só cadastrado.

`backend/.env` (`GOOGLE_WEB_CLIENT_ID`) e `frontend/.env`
(`EXPO_PUBLIC_GOOGLE_WEB_CLIENT_ID`) atualizados com o Client ID tipo Web
real — confirmei programaticamente que os dois valores são idênticos
(condição necessária pro backend aceitar o token que o app manda).

### Validação real
Backend reimportado com o Client ID real carregado do `.env` — subiu sem
erro, schema OpenAPI gerado normalmente (35 rotas).

### Próximo passo do usuário
Rodar `npx expo run:android` de novo (recompila com o módulo nativo do
Google Sign-In) e testar o botão de login de verdade.

## Limpeza de resquícios da Emergent — parte 3 (sistema de "guarda de comandos")

Achado ao investigar o erro `npm install` no Windows: um sistema inteiro de
"guarda de comandos" (`cmd-guard.js`, `cmd-guard/` com modes.js/rules.js/
matcher.js, `install-guard.sh`, `sync-shims.sh`) que a Emergent usa
internamente pra interceptar/validar binários executados durante o
desenvolvimento (referências a `/opt/install-guard/bin`, que só existe no
ambiente sandbox deles). Isso escapou das varreduras anteriores porque não
continha a palavra "emergent" no texto.

Esse sistema tornava o `npm install` do usuário disparar um hook
`preinstall` que rodava `./scripts/cmd-guard.js` — sintaxe de shell Unix
(`./`) que o `cmd.exe` do Windows não reconhece, quebrando a instalação
com "'.' não é reconhecido como um comando interno".

Removido por completo: os 4 arquivos/pastas do sistema de guarda + a linha
`"preinstall"` do `package.json`. Mantido `scripts/reset-project.js` —
esse é um utilitário PADRÃO e legítimo do próprio template Expo Router
(o comentário no arquivo até avisa que é seguro remover depois de usado),
nada a ver com a Emergent.

Backend conferido também — não tinha nada equivalente lá, o sistema de
guarda existia só no frontend.

### Validação real
- `npm install --dry-run` rodou sem erro, confirmando que o hook quebrado
  não dispara mais.
- `tsc --noEmit`: só o falso-positivo de cache de rotas já documentado.

## 🔴 Achado grave — limpeza de Emergent parte 4: arquivos .env nunca foram varridos

O erro 404 reportado pelo usuário ao tentar logar (depois do Google Sign-In
já estar funcionando) tinha uma causa raiz simples mas séria:
`frontend/.env` tinha 3 variáveis apontando pra infraestrutura da própria
Emergent, usada internamente durante o desenvolvimento no ambiente
sandbox deles:
- `EXPO_PUBLIC_BACKEND_URL=https://no-show-guard.preview.emergentagent.com`
  — o app estava tentando logar num SERVIDOR DE DEMONSTRAÇÃO DA EMERGENT,
  não no nosso próprio backend. Daí o 404 (rota inexistente lá).
- `EXPO_PACKAGER_HOSTNAME` e `EXPO_PACKAGER_PROXY_URL` — mesma URL de
  demo, usadas só em cenários de túnel/proxy do ambiente deles.
- `METRO_CACHE_ROOT=/app/frontend/.metro-cache` — caminho ABSOLUTO estilo
  Linux, específico de onde o projeto ficava DENTRO do sandbox da
  Emergent (`/app/frontend`), sem sentido nenhum no Windows do usuário.
- `EXPO_TUNNEL_SUBDOMAIN=no-show-guard` — nome antigo do projeto, órfão.

**Por que isso escapou de 3 rodadas anteriores de limpeza:** minhas
varreduras anteriores só cobriam `--include="*.py" --include="*.tsx"
--include="*.ts" --include="*.json" --include="*.md"` — nunca incluí
`.env` explicitamente. Arquivo de config não é "código-fonte" no sentido
estrito, mas claramente devia ter sido varrido desde o início.

### Corrigido
`.env` reescrito do zero: `EXPO_PUBLIC_BACKEND_URL="http://10.0.2.2:8001"`
(10.0.2.2 é o endereço especial que o emulador Android usa pra apontar de
volta pro localhost da máquina host — "localhost" sozinho, de dentro do
emulador, aponta pro PRÓPRIO emulador, não pro Windows do usuário — essa é
a causa de confusão mais comum em quem testa Android pela primeira vez).
Removidas as 4 variáveis órfãs. `.env.example` também atualizado com essa
explicação documentada, pra não se perder de novo.

### Validação real
Sweep final confirmado programaticamente: `grep -rli "emergent"
--include=".env" --include="*.env*"` em todo backend/ e frontend/ agora
retorna vazio.

**Lição registrada:** ao fazer varredura de "resquícios de uma
plataforma/marca", incluir SEMPRE arquivos de configuração/ambiente
(`.env`, `.env.*`), não só código-fonte — são frequentemente esquecidos
por não parecerem "código", mas podem conter os resquícios mais
impactantes (like this one, that quebrava o login inteiro).

## Varredura ampla e final — parte 5 (a pedido explícito do usuário)

Usuário pediu uma varredura completa antes de testar de novo. Fui além de
busca de texto por "emergent" — procurei também estruturas/caminhos que
são infraestrutura da plataforma mesmo sem a palavra aparecer:

1. **`frontend/constants/testIds/`** (auth.js + index.js) — infraestrutura
   de testes automatizados do bot de QA da própria Emergent ("qabot"),
   com uma regra de lint literalmente chamada `emergent(kebab-case-...)`.
   Continha campos pra um fluxo de login por e-mail/senha que nosso app
   nem tem (login é só Google) — confirmado como código 100% órfão
   (nenhum import em lugar nenhum) antes de remover.
2. **`tests/__init__.py`** na RAIZ do projeto (diferente de
   `backend/tests/`) — pasta vazia/órfã, sem nenhum teste real dentro.
   Removida.
3. **`frontend/src/theme.ts`** — comentário órfão referenciando
   `/app/design_guidelines.json` (caminho absoluto do sandbox da Emergent,
   apontando pro arquivo que já tinha sido removido numa limpeza
   anterior). Corrigido; também removida uma duplicata acidental da linha
   de comentário "Design tokens for ShowUp" que ficou repetida.
4. **`backend/pytest.ini`** — comentário endereçado a um "AGENT:"
   genérico. A explicação técnica por trás (por que `-n 2 --dist
   loadscope` não pode ser mudado sem cuidado) continua válida e real —
   reformulado em português, sem o endereçamento a "agente", mantendo a
   justificativa técnica.
5. **`frontend/package.json`**: `"name": "frontend"` → `"showup"`.

### Observação separada (não é "info da Emergent", mas notada durante a varredura)
`backend/requirements.txt` tem várias dependências que nenhuma parte do
código usa (boto3, pandas, numpy, black, mypy, flake8, isort, jq, typer,
passlib, bcrypt, python-jose, requests-oauthlib) — parecem ser um conjunto
padrão que a plataforma inclui em todo projeto FastAPI gerado por ela.
Não removido nesta rodada (fora do escopo do pedido específico), só
sinalizado como possível limpeza futura.

### Validação real
- Confirmado que `constants/testIds/` não tinha nenhum import em nenhum
  arquivo real do app antes de remover.
- Sweep final com grep por "emergentagent", "preview\.", "qabot", "/app/"
  em TODOS os tipos de arquivo de texto do projeto (não só as extensões
  de código que eu vinha filtrando antes) — retornou vazio.
- Backend: `py_compile` no server.py, OK.
- Frontend: `tsc --noEmit` (só o falso-positivo de cache já documentado)
  + `expo export --platform android` rodou com sucesso.

## Limpeza geral de dependências não usadas (backend + frontend)

A pedido do usuário ("tire tudo que não tenha nada a ver com o projeto").
Verifiquei uso real de CADA dependência antes de remover qualquer uma —
nunca por suposição.

### Backend (`requirements.txt`): 33 → 17 linhas
Removidas (zero uso, direto ou indireto, confirmado por grep): boto3,
requests-oauthlib, cryptography (redundante — já vem via `google-auth`,
confirmado com `pip show google-auth` listando cryptography como
dependência dela), pyjwt, bcrypt, passlib, python-jose, pandas, numpy,
python-multipart (nenhum endpoint usa File/Form/UploadFile), jq, typer,
black, isort, flake8, mypy.

Mantidos apesar de zero import direto, por uso indireto confirmado:
- `pymongo`: `from pymongo.errors import DuplicateKeyError` em server.py +
  `MongoClient` usado nos 3 arquivos de teste.
- `email-validator`: exigido pelo Pydantic quando usa `EmailStr` (linha
  179 do server.py) — Pydantic v2 delega validação de e-mail pra essa lib
  por baixo dos panos, sem import explícito nosso.
- `dnspython`: necessário pro pymongo resolver `mongodb+srv://` (a URL do
  Atlas usa esse esquema).
- `tzdata`: necessário pro `zoneinfo.ZoneInfo` (usado em `_tz_for()`)
  funcionar corretamente em alguns SOs sem banco de dados IANA nativo.
- `requests`: usado nos 3 arquivos de teste (chamadas HTTP síncronas pro
  servidor rodando durante os testes) — não é usado no código de
  PRODUÇÃO (que usa httpx), mas é uma dependência de teste real.

### Frontend (`package.json`): 35 → 30 dependências
Removidas (zero uso confirmado por grep, inclusive busca ampla por
`Haptics.` sem import nomeado específico): `date-fns`, `dayjs` (dois
formatadores de data concorrentes, nenhum dos dois usado — a formatação
deve ser feita manualmente/Intl nativo), `expo-symbols`, `expo-blur`,
`expo-haptics`.

Mantidos apesar de zero import direto, por serem dependências reais
confirmadas via package.json de outras libs:
- `react-native-worklets`: peerDependency real do `react-native-
  reanimated` (confirmado lendo o package.json dele).
- `@expo/metro-runtime`: dependência real do `expo-router` (idem).

Rodei `npm install` pra sincronizar node_modules com o package.json
editado — removeu 4 pacotes fisicamente.

### Validação real
- Backend: reimportei `server.py` depois da limpeza — OK.
- Frontend: `tsc --noEmit` (só o falso-positivo de cache já documentado)
  + `expo export --platform android` — bundle gerado com o MESMO hash de
  antes da limpeza (85f74c5c...), confirmando que essas dependências
  nunca influenciaram o bundle final (eram peso morto real, sem
  tree-shaking necessário porque nem chegavam a ser referenciadas).

## ⚠️ Correção importante: o erro de TS que eu vinha chamando de "falso-positivo" NÃO era

Ao longo de TODA a sessão, toda validação com `tsc --noEmit` mostrava o
mesmo erro: `app/(app)/perfil.tsx(209,42): error TS2345: Argument of type
'"/(app)/planos"' is not assignable to...`. Eu vinha classificando isso
como "falso-positivo de cache de rotas" sem nunca confirmar de verdade —
erro meu de julgamento, repetido em dezenas de validações.

Usuário reportou o sintoma real: clicar no card "Plano e taxa por
agendamento" em perfil.tsx não fazia nada. Investiguei a fundo dessa vez:

1. `app/(app)/planos.tsx` existe, com `export default function Planos()`
   válido — arquivo correto, sem bug de código.
2. Inspecionei o arquivo de tipos que o Expo Router gera de verdade
   (`.expo/types/router.d.ts`) — TODAS as outras rotas apareciam
   (`/perfil`, `/agendamentos`, `/configuracoes`, etc.) MENOS "planos".
3. Confirmei que `npx expo export` e `npx tsc --noEmit` sozinhos NÃO
   regeneram esse arquivo do zero — só um Metro dev server rodando de
   verdade (`npx expo start`) reconstrói a lista de rotas completa.
4. Depois de apagar `.expo/` e rodar o Metro de verdade, "planos" passou
   a aparecer na lista, e o erro do `tsc` sumiu por completo (exit code 0,
   zero erros) — confirma que a causa raiz era cache desatualizado do
   próprio Expo Router, não um bug no código do app.

### Instrução passada ao usuário
Apagar a pasta `frontend/.expo/` na máquina dele e rodar `npx expo
run:android` de novo, forçando a reconstrução completa do cache de rotas.

### Lição registrada (importante pra mim mesmo)
Nunca mais classificar um erro de TypeScript recorrente como
"falso-positivo" sem investigar a fundo — mesmo que pareça inofensivo por
não travar o bundle, pode ser sintoma de um bug real esperando o cenário
certo pra se manifestar (nesse caso, o clique que não fazia nada). O teste
real não é "o bundle compila apesar do erro", é "o erro realmente não
teria efeito nenhum on runtime" — e eu nunca verifiquei isso de verdade
antes de agora.

## Bug real: checkout externo (Stripe) "não faz nada" — corrigido tratamento de erro silencioso

Usuário reportou: clicar em "Assinar" (planos) e no botão de conectar
Stripe (configurações) — os dois usam a mesma função `openExternalCheckout`
— mostra um "rodinha" de carregamento breve e depois não abre nenhum
navegador, sem nenhuma mensagem de erro visível em lugar nenhum.

Diagnóstico feito por eliminação:
- Confirmado que o problema afeta os DOIS fluxos igualmente (não é bug do
  backend específico de planos).
- Confirmado que o Chrome funciona normalmente dentro do emulador quando
  aberto manualmente (não é "Chrome quebrado").
- Causa raiz do sintoma "nada acontece, sem erro": `openExternalCheckout`
  chamava `WebBrowser.openAuthSessionAsync(url, returnUrl)` e IGNORAVA
  completamente o valor de retorno — se o navegador falhasse ao abrir
  (`type: 'cancel'`, `'dismiss'` inesperado, ou qualquer coisa que não
  fosse sucesso), a função nunca lançava erro nem logava nada. Do ponto de
  vista do usuário, silêncio total.

### Corrigido
`open-external-checkout.ts`: agora captura o `result` de
`openAuthSessionAsync`, loga com `console.warn` se não for
`'success'`/`'dismiss'`, e lança um `Error` com mensagem clara nesse caso
— que agora aparece de verdade na tela via o estado `erro` que já existia
em `planos.tsx` (só nunca era populado porque a exceção nunca era lançada).

De brinde: achei que `app.json`'s `"scheme"` ainda era `"frontend"` (nome
genérico de antes do rebranding) — trocado pra `"showup"`.

### ⚠️ Ação necessária do usuário
Mudança de `scheme` no app.json só é aplicada numa pasta `android/`
NOVA — precisa apagar `frontend/android/` de novo e rodar `npx expo
run:android` do zero pra essa mudança entrar em vigor. Depois disso, se
o problema persistir, agora vai aparecer uma mensagem de erro real na
tela (embaixo da lista de planos), revelando a causa exata pela primeira
vez — meu próximo passo depende de ver essa mensagem.

### Validação real
`tsc --noEmit`: zero erros (confirmei os valores reais do enum
`WebBrowserResultType`/`WebBrowserRedirectResult` direto no `.d.ts` da
lib antes de escrever a condição, não assumi). `expo export
--platform android` rodou com sucesso.

## Checkout de planos migrado pro fluxo 100% nativo (sem navegador)

A pedido do usuário: Stripe Checkout (página hospedada, exigia
WebBrowser) substituído por criação direta da assinatura via API +
Payment Sheet nativo — mesmo padrão já usado pro cartão do cliente no
fluxo de no-show. Resolve de vez o "nada acontece" nessa tela
especificamente (o Connect, que segue precisando do navegador por
exigência de conformidade do próprio Stripe — KYC, sem alternativa de
API —, já tinha sido corrigido antes com tratamento de erro real).

### Backend
- `stripe_gateway.py`: `create_plano_checkout_session` (Checkout Session)
  REMOVIDO — substituído por `create_plano_subscription` (cria a
  Subscription direto via API com `payment_behavior='default_incomplete'`,
  `payment_settings.save_default_payment_method='on_subscription'`,
  expandindo `latest_invoice.payment_intent` pra pegar o client_secret) e
  `get_subscription_status` (confere o status real depois do pagamento).
- `server.py`: `POST /me/plano/checkout` REMOVIDO. Dois novos endpoints:
  - `POST /me/plano/subscription-intent`: cria a assinatura pendente,
    devolve `{customer_id, ephemeral_key_secret,
    payment_intent_client_secret, subscription_id}` pro Payment Sheet.
  - `POST /me/plano/confirm`: recebe `{subscription_id, plano}`, CONFERE
    direto com o Stripe (`get_subscription_status`) que o status é
    `active`/`trialing` antes de liberar a taxa reduzida — nunca confia só
    no "sucesso" que o SDK do app reporta.
- `webhooks.py`: handler `_handle_checkout_completed` (tratava
  `checkout.session.completed`) REMOVIDO — órfão, já que não criamos mais
  Checkout Sessions em lugar nenhum do projeto (confirmado por grep antes
  de remover).

### Frontend (`planos.tsx`)
Reescrita a mutation de checkout: chama `/subscription-intent` →
`initPaymentSheet` → `presentPaymentSheet` → se sucesso, chama `/confirm`
→ `auth.refresh()` + invalida a query da lista de planos. Removida a
dependência de `openExternalCheckout`/`WebBrowser` nesta tela
especificamente (`open-external-checkout.ts` continua existindo e sendo
usado só por `configuracoes.tsx`, o fluxo de Connect).

### Validação real
- Confirmei por grep que nenhum teste cobria o fluxo antigo de checkout
  de plano, e que o próprio endpoint já bloqueava o caminho MockGateway
  por design (`if GATEWAY_KIND != "stripe": raise HTTPException`) — não
  precisei implementar os novos métodos no mock.
- Confirmei por grep que `create_plano_checkout_session` era o ÚNICO lugar
  no projeto inteiro que criava um `stripe.checkout.Session` antes de
  remover — e que `_handle_checkout_completed` era o único consumidor do
  evento `checkout.session.completed` antes de remover esse handler.
- Backend: reimportado com sucesso, schema OpenAPI confirma as novas
  rotas (`/me/plano/subscription-intent`, `/me/plano/confirm`) e a
  ausência da antiga (`/me/plano/checkout`).
- Frontend: `tsc --noEmit` zero erros, `expo export --platform android`
  gerou bundle com sucesso.
- Confirmado por grep que `openExternalCheckout` continua em uso ativo
  só em `configuracoes.tsx` (Connect) — a correção de tratamento de erro
  feita nela antes continua válida e necessária pra esse fluxo.

## Bug real de produção: campo removido pela própria Stripe (API "Basil")

Ao testar o checkout nativo de planos de verdade, erro 500:
`AttributeError: The 'payment_intent' attribute is no longer available
on Invoice objects`.

Causa: a Stripe removeu de propósito o campo `payment_intent` do objeto
Invoice na mudança de API "Basil" (31/03/2025) — parte do suporte a
pagamentos parciais múltiplos por fatura. Nosso código expandia
`latest_invoice.payment_intent`, que simplesmente não existe mais na
versão da API que o SDK Python instalado usa por padrão (não fixamos
nenhuma versão específica no código, então pega sempre a mais recente).

### Corrigido
`stripe_gateway.py::create_plano_subscription`: expande
`latest_invoice.confirmation_secret` em vez de `.payment_intent`, lê
`.client_secret` de lá. Confirmei na documentação OFICIAL da Stripe
especificamente pro SDK React Native (não só pro componente web "Payment
Element") que esse client_secret funciona exatamente igual com
`initPaymentSheet` — não precisou mudar nada no frontend, só o campo que
o backend lê internamente antes de devolver a mesma chave de resposta de
sempre (`payment_intent_client_secret`, mantida por compatibilidade,
comentário explicando a decisão).

### Validação real
Pesquisei a documentação oficial da Stripe duas vezes: uma pra confirmar
a mudança de API em si (changelog Basil), outra especificamente pra
confirmar compatibilidade com `stripe-react-native` (não bastava saber
que existia um substituto — precisava confirmar que funcionava no SDK
mobile, não só no componente web). Backend reimportado com sucesso depois
da correção.

## ✅ Migração pra modo TEST do Stripe — chaves atualizadas

Causa raiz do "Payment Sheet abre e fecha sozinho" confirmada: a chave
publicável do frontend (`EXPO_PUBLIC_STRIPE_PUBLISHABLE_KEY`) ainda era o
placeholder original (`pk_test_SUBSTITUA_PELA_SUA_CHAVE`), nunca
substituída — o SDK nativo do Stripe não conseguia inicializar de verdade.

Descoberta séria durante a investigação: a conta Stripe estava em modo
LIVE (produção real) durante os testes anteriores — risco real de gerar
cobrança/assinatura de verdade. Confirmado com o usuário que NENHUMA
assinatura ativa foi criada (a mesma falha do Payment Sheet, ironicamente,
evitou qualquer cobrança real — a assinatura nunca saiu do estado
"incomplete" porque o pagamento nunca foi confirmado).

Migração completa feita:
- `backend/.env`: `STRIPE_API_KEY` trocado pela chave secreta de TESTE
  real (`sk_test_...`), substituindo uma chave de teste genérica antiga
  que estava lá (não era a chave real da conta do usuário).
- `frontend/.env`: `EXPO_PUBLIC_STRIPE_PUBLISHABLE_KEY` trocado pela
  chave publicável de TESTE real (`pk_test_...`), substituindo o
  placeholder que nunca tinha sido preenchido.

### Validação real
Ao validar, meu primeiro teste apontou "LIVE" por engano — investiguei e
descobri que era um bug no MEU script de teste (importei `stripe_gateway`
diretamente, pulando o `load_dotenv()` que só roda no topo do `server.py`,
então peguei uma chave vazia/residual, não a real). Corrigido importando
`server` primeiro (ordem certa) — confirmado TEST mode com a chave certa.

### ⚠️ Pendente — usuário ainda precisa
- Recriar os 2 produtos/preços (Profissional R$19,90, Ultra R$59,90) em
  modo TESTE no Stripe (os Price IDs de teste são diferentes dos de
  produção) e atualizar `STRIPE_PRICE_ID_PROFISSIONAL`/
  `STRIPE_PRICE_ID_ULTRA` no `.env` com os novos valores de teste.
- Reiniciar backend e frontend (`npx expo run:android`) depois de tudo
  configurado.
- Testar "Assinar Profissional" com cartão de teste `4242 4242 4242 4242`.

## Robustez: erro de Price ID inválido não derruba mais o servidor com 500

Usuário testou o checkout de planos antes de eu ter passado os Price IDs
de teste novos pra ele — resultado esperado (Price ID de produção não
existe pra uma chave de teste), mas o servidor respondeu com um 500 cru e
traceback completo do Python, em vez de uma mensagem de erro limpa.

### Corrigido
- `stripe_gateway.py::create_plano_subscription`: chamada ao Stripe
  envolvida em try/except, traduzindo `stripe.error.StripeError` via
  `_translate_stripe_error` (função já existente, reaproveitada — mesmo
  padrão usado em outros métodos deste arquivo).
- `server.py::plano_subscription_intent`: captura `InvalidPaymentRequestError`
  → HTTP 400 com a mensagem real do Stripe; `PaymentError` genérico → 502.
  Mesmo padrão já usado no endpoint de confirmação de cartão
  (`confirm_setup_intent_card`), só replicado aqui.

### Validação real
Simulei o erro EXATO do log do usuário
(`InvalidRequestError("No such price: 'price_...'")`) diretamente contra
`_translate_stripe_error()` — confirmado que vira `InvalidPaymentRequestError`
com a mensagem original preservada. Backend reimportado com sucesso.

## Price IDs de teste configurados

`STRIPE_PRICE_ID_PROFISSIONAL` e `STRIPE_PRICE_ID_ULTRA` atualizados no
`backend/.env` com os Price IDs reais de modo TESTE (recriados pelo
usuário no Product catalog em sandbox), substituindo os antigos de
produção. Confirmado que o Price ID do Profissional é idêntico ao que
apareceu no erro "No such price" da tentativa anterior — indício de que o
produto ainda não tinha propagado no Stripe na hora daquele teste, e
agora já existe de verdade.

## Correção: erro de transcrição meu na chave secreta do Stripe

Ao ler a chave secreta de um print anterior, transcrevi errado um
caractere ambíguo: `pgm1SN` (dígito 1) em vez do correto `pgmlSN` (letra
L minúscula) — erro clássico de OCR/leitura visual em strings longas com
caracteres parecidos. Isso gerou `AuthenticationError: Invalid API Key`
quando o usuário testou.

Corrigido: usuário colou o valor certo diretamente em texto (não print) —
`backend/.env` atualizado com o valor exato. Confirmei a correção
comparando caractere por caractere (não visualmente) contra o texto que
o usuário digitou.

**Lição registrada:** nunca mais transcrever chaves/segredos longos a
partir de screenshots sem alertar sobre o risco de erro de leitura
(1 vs l, 0 vs O, etc.) — pedir pro usuário colar o texto direto sempre
que possível, evitando essa classe inteira de erro.

### Limitação de validação
Tentei confirmar a chave nova com uma chamada real (`stripe.Balance.
retrieve()`) — meu próprio sandbox não tem acesso de rede irrestrito a
`api.stripe.com` (erro de certificado/proxy, limitação do ambiente, não
da chave). Validação real só acontece na máquina do usuário.

## Robustez: auto-recuperação quando o customer_id salvo é de outra conta/modo

Usuário testou com a chave corrigida — chave OK agora, mas novo erro:
"No such customer: 'cus_VIC0mclbmLh24i'". Causa: o `stripe_billing_
customer_id` já estava salvo no banco de uma tentativa anterior (quando
a chave ainda era live, ou a de teste antiga) — clientes do Stripe não
são compartilhados entre contas/modos diferentes, então esse ID ficou
órfão assim que trocamos a chave.

### Corrigido
- `stripe_gateway.py::create_ephemeral_key`: agora também traduz erros
  do Stripe via `_translate_stripe_error` (antes chamava a API crua sem
  nenhum tratamento — o erro real do log veio daqui, não de
  `create_plano_subscription`).
- `server.py::plano_subscription_intent`: extraída a lógica de preparar o
  Payment Sheet (`_prepare_payment_sheet`) numa função auxiliar. Se a
  primeira tentativa falhar com "No such customer" especificamente,
  recria o customer automaticamente, salva o novo ID no banco, e tenta
  de novo UMA vez antes de desistir — evita que o usuário fique travado
  pra sempre por causa de um ID órfão de uma sessão de configuração
  anterior (troca de chave live→teste, recriação de conta Stripe, etc.).
  Qualquer outro erro de "invalid request" (não relacionado a customer
  órfão) continua indo direto pro 400 sem tentar de novo.

### Validação real
Simulei o erro EXATO do log (`InvalidRequestError("No such customer:
'cus_...'")`) contra `_translate_stripe_error()` — confirmado que vira
`InvalidPaymentRequestError` com "No such customer" na mensagem,
disparando corretamente a lógica de recriação. Backend compilado sem
erro.

## 🎉 MARCO: checkout de planos funcionando de ponta a ponta, confirmado

Usuário testou o fluxo completo: Assinar Profissional → Payment Sheet
nativo → cartão de teste 4242 → confirmação. Validado por DUAS fontes
independentes:
- App: card "Profissional" mostra "PLANO ATUAL", "Free" virou "Cancelar
  assinatura e voltar ao Free" — a troca de plano persistiu de verdade.
- Stripe Dashboard (sandbox): "Gross volume R$19.90" registrado, saldo
  R$18.72 depois da taxa do Stripe — transação de teste processada com
  sucesso, sem nenhum risco (modo sandbox confirmado pela faixa azul).

Isso fecha a cadeia completa de correções desta sessão: login direto
Google (sem Emergent) → MongoDB Atlas → Payment Sheet nativo → Stripe
modo teste com chaves e Price IDs corretos → auto-recuperação de
customer_id órfão. Todas as camadas do app validadas juntas, rodando de
verdade num emulador Android.

## Correção proativa: mesma auto-recuperação aplicada ao Connect

Antes do usuário testar o Connect, apliquei preventivamente a mesma
correção que resolveu o customer_id órfão dos planos — já era previsível
que o `stripe_account_id` salvo (criado em modo LIVE) também não
existiria no modo TESTE atual, causando o mesmo tipo de erro.

### Corrigido
- `stripe_gateway.py::create_onboarding_link`: agora traduz erros do
  Stripe (não tinha nenhum tratamento antes).
- `stripe_gateway.py::create_connect_account`: erros que não são "Connect
  not enabled" agora também são traduzidos (antes subiam crus).
- `server.py::connect_onboarding`: mesma lógica de auto-recuperação dos
  planos — se a conta salva não existir mais na conta/modo atual, recria
  e tenta de novo uma vez.

### Generalização importante: "No such X" em vez de frase exata
Não encontrei confirmação oficial do texto exato do Stripe pra "conta
Connect não existe" (só tinha confirmado "No such customer" e "No such
price" por teste real). Em vez de apostar numa terceira frase não
confirmada, generalizei a checagem nos dois endpoints pra `"No such" in
str(e)` — cobre os 3 casos confirmados (customer/price/account) e
qualquer variação futura desse mesmo padrão consistente do Stripe, sem
depender de eu adivinhar o texto exato de cada tipo de recurso.

### Validação real
Simulei os 3 cenários (`No such customer`, `No such account`, `No such
price`) contra `_translate_stripe_error()` — os 3 disparam a detecção
genérica corretamente. Backend reimportado com sucesso, rotas de Connect
e planos confirmadas no schema.

## Decisão: adiar migração pra Accounts v2 (Stripe) até sair de preview

Investigado a fundo (não implementado): migrar `create_connect_account`
pra Accounts v2 do Stripe. Achados que motivaram adiar:
- v2 usa modelo de dados totalmente diferente (`configuration` com
  personas merchant/customer/recipient), não é troca de nome de método.
- O SDK Python (`stripe` package) NÃO tem suporte completo pra v2 ainda —
  documentação oficial recomenda HTTP cru (`requests`/`httpx`) pra
  algumas partes, já que nem tudo foi portado pro SDK.
- É API em "preview" (exige `Stripe-Version` com selo de pré-lançamento)
  — ainda está mudando, não é versão estável.
- Boa notícia parcial: `AccountLink.create()` (onboarding) continua
  funcionando sem mudança nenhuma com um account_id criado via v2 — só a
  CRIAÇÃO da conta muda, não o onboarding em si.

Decisão do usuário: manter v1 (ativando "Accounts v1 support" no
Dashboard) até a v2 sair de preview e o SDK Python ganhar suporte
completo. Nenhuma mudança de código feita nesta rodada — só decisão
registrada pra não reabrir essa discussão sem necessidade.

## Nova feature: agendamento via link público (base do fluxo WhatsApp) — backend completo

Primeira etapa de uma feature maior: profissional compartilha um link
(futuramente via WhatsApp, número único da plataforma) que o cliente
abre numa página web (não no app) pra agendar sem precisar ter conta.
Decisão de negócio importante confirmada por pesquisa: Pix não suporta
captura manual no Stripe (confirmado na doc oficial: "Manual capture
support: No") — é sempre instantâneo e irreversível. Por isso o fluxo Pix
cobra o valor TOTAL do serviço de uma vez, sem a proteção de no-show que
existe no fluxo de cartão (que continua intacto, sem mudança nenhuma).

Decisão de arquitetura pro WhatsApp (pesquisada, não implementada ainda):
número ÚNICO da plataforma, não um por profissional — confirmado por
pesquisa de mercado que é o padrão de TODOS os concorrentes diretos
(AgendZap, RobotiZap, Barbeiro.app) nesse segmento no Brasil, com custo
fixo por faixa de equipe (~R$50-150/mês total) em vez de custo por
profissional (~R$80-270/mês CADA, inviável em escala).

### Backend implementado nesta rodada
- `server.py`: novos modelos `AgendamentoPublicoCreate`,
  `AgendamentoPublicoCartaoRequest`, `AgendamentoPublicoPixResponse`.
- `_find_or_create_cliente_por_telefone()`: cliente sem conta no app,
  identificado por telefone (não email/Google) — cria um usuário com
  email sintético (`tel_<numero>@showup.cliente`), nunca usado pra login
  de verdade (login continua só Google). Índice único esparso em
  `telefone` (só usuários desse fluxo têm telefone) pra não duplicar
  cliente que volta a agendar pelo mesmo número.
- `_valida_servico_e_conflito()`: extraída do endpoint original de
  agendamento pra ser reaproveitada pelos 2 fluxos públicos novos.
- `POST /public/agendamentos/cartao`: mesmo hold de sempre, mas sem
  sessão — cartão coletado via Stripe.js Elements na página web (ainda
  não construída), `payment_method_id` já confirmado é passado direto.
- `POST /public/agendamentos/pix`: cria o agendamento com
  `hold_status="aguardando_pix"`, reservado por `PIX_RESERVA_MINUTOS=20`
  minutos. Cobra o valor TOTAL (sem taxa de no-show separada — já pago).
- `GET /public/agendamentos/{id}/status`: público, pra página web fazer
  polling e saber quando o Pix confirmou (pagamento acontece no app do
  banco do cliente, fora do nosso controle).
- `stripe_gateway.py::create_pix_payment_intent`: PaymentIntent com
  `payment_method_types=["pix"]`, sem capture_method manual (não
  suportado), com o mesmo padrão de split via `transfer_data` que o
  cartão já usa.
- `webhooks.py::_handle_pix_succeeded`: novo handler pra
  `payment_intent.succeeded` — só mexe em agendamentos ainda
  `aguardando_pix` (idempotente contra webhook duplicado).
- `server.py::_expirar_pix_pendentes`: novo job no scheduler (a cada 2
  min, mais frequente que o de cartão) — libera o horário se o Pix não
  for pago dentro da janela de reserva. Diferente do cartão, não precisa
  desfazer hold nenhum no gateway (Pix nunca trava nada antes de pagar).

### Validação real
- Backend reimportado com sucesso, as 3 rotas públicas confirmadas no
  schema OpenAPI.
- Testei a validação de telefone isoladamente (Pydantic field_validator)
  com 4 casos: 11 dígitos, formatado com parênteses/traço, 10 dígitos
  (fixo), e um valor inválido — os 4 se comportaram como esperado.
- Confirmei que `hold_status: str` no modelo de resposta `Agendamento`
  aceita os 2 valores novos (`aguardando_pix`, `pago_integral`) sem
  quebrar a serialização.

### Falta (próximas etapas)
1. A página web em si (formulário nome/telefone/pagamento, QR code do
   Pix, campo de cartão via Stripe.js) — ainda não construída.
2. Integração WhatsApp de verdade — depende do usuário escolher e
   contratar um BSP (decisão externa, como Stripe/Google/MongoDB antes).

## Página web de agendamento público publicada (Pix funcionando, cartão pendente)

Publiquei `agendar.html` como artifact:
https://claude.ai/artifact/WXwzJb6DdsYxamvaepH1gA

### Descoberta técnica importante durante a construção
Stripe.js (necessário pro fluxo de cartão via navegador) só pode ser
carregado de `js.stripe.com` — domínio que NÃO está na lista de origens
permitidas pra páginas publicadas aqui (só cdnjs/jsdelivr/tailwind/
jquery). Isso bloqueia cartão nessa página POR ENQUANTO.

Resolvido pro Pix contornando essa limitação por completo: em vez de usar
Stripe.js no navegador, o BACKEND confirma o PaymentIntent imediatamente
(`confirm=True, payment_method_data={"type": "pix"}`), e o código Pix
"copia e cola" (`next_action.pix_display_qr_code.data`) vem pronto na
própria resposta da nossa API — o QR code é renderizado 100% no
navegador usando `qrcodejs` (biblioteca pequena, hospedada no cdnjs, já
permitido), sem precisar de nenhum SDK do Stripe no cliente.

### Design
Reaproveitei a paleta real da marca (verde-floresta + creme do
monograma), não uma paleta nova — Fraunces (serifada) pro nome do
profissional/valores, Inter pro resto. Fluxo em 4 etapas numeradas de
verdade (serviço → horário → dados → pagamento), resumo sempre visível
antes de pagar.

### ⚠️ Duas coisas que o usuário PRECISA fazer antes de testar de verdade
1. Trocar a constante `BACKEND_URL` no topo do `<script>` pela URL
   PÚBLICA real do backend — `localhost`/`10.0.2.2` só funcionam dentro
   da própria máquina/emulador do usuário, uma página publicada aberta
   por QUALQUER pessoa não consegue alcançar isso. O backend precisa
   estar hospedado em algum lugar acessível pela internet.
2. Testar com `?prof=<user_id de um profissional real>` na URL da
   página publicada.

### Validação real
- Extraí e validei a sintaxe do JavaScript inline com `node --check` —
  válido.
- Verifiquei balanceamento de tags HTML com um parser Python — pilha
  final vazia (tudo fechado corretamente); os avisos que apareceram
  eram falsos positivos do meu verificador simplificado com tags
  auto-fechadas (`<meta/>`, `<input/>`), não problemas reais.
- Corrigi um bug real antes de publicar: uso do `event` global implícito
  (frágil) no clique de seleção de serviço — passei o elemento
  explicitamente pro handler em vez de depender disso.

### Ainda falta
- Cartão via essa página (bloqueado pela limitação de CSP do Stripe.js
  — precisaria de hospedagem própria fora do sistema de Artifacts pra
  contornar, algo a considerar mais pra frente).
- A integração de verdade com WhatsApp (depende do BSP escolhido).

## Bug real: Connect onboarding recusado pelo Stripe ("Not a valid URL")

Testando o botão de conectar Stripe (Connect) de verdade, erro 400:
"Not a valid URL" no param `return_url`. Causa confirmada por pesquisa
(achei um caso idêntico documentado, mesma mensagem de erro, mesmo
cenário): o `AccountLink.create` do Stripe (usado só pro onboarding do
Connect) **só aceita URLs http(s) de verdade** pro return_url/refresh_url
— recusa esquemas customizados como `showup://`, mesmo sendo um deep
link válido do app. Isso é diferente do `checkout.Session` (usado nos
planos antes de migrarmos pro Payment Sheet nativo), que aceita esquema
customizado — a limitação é específica do AccountLink.

### Corrigido: página-ponte publicada
Criei e publiquei `stripe-bounce.html`:
https://claude.ai/artifact/45ugcMrgMZTBWMy7s5nWN6

Uma página https mínima que só repassa o redirecionamento de volta pro
esquema `showup://` do app (lê `?next=<deep link>` da query string,
redireciona na hora que carrega, com um botão de fallback "toque aqui"
caso o redirect automático falhe em algum navegador/WebView específico).
Tem uma allowlist restrita ao esquema `showup://` — nunca redireciona pra
qualquer URL vinda de fora, evitando virar um "open redirect" explorável
(padrão de segurança que copiei do mesmo caso real que encontrei
documentado, que tinha exatamente essa mesma preocupação).

`open-external-checkout.ts`: agora manda pro Stripe a URL da PONTE
(com o deep link codificado no `?next=`) em vez do deep link puro. O
`WebBrowser.openAuthSessionAsync` continua de olho no deep link DIRETO
(não na ponte) — é ele que o SO intercepta de verdade quando a ponte
redireciona no final; a ponte é só o intermediário que o Stripe aceita.

### Validação real
- `tsc --noEmit`: zero erros. `expo export --platform android`: bundle
  gerado com sucesso.
- Extraí e validei a sintaxe JS da página-ponte com `node --check`.
- Testei a lógica de allowlist com 3 casos: deep link válido (aceito),
  URL maliciosa arbitrária (rejeitada), tentativa de `javascript:`
  (rejeitada) — os 3 se comportaram como esperado.

## Páginas migradas do artifact do Claude pro Firebase Hosting (produção real)

Usuário levantou preocupação válida: depender do sistema de artefatos do
Claude pra tráfego de produção não é confiável o suficiente pro negócio.
Migrado pro Firebase Hosting, dentro do MESMO projeto Google Cloud já
existente (showup-509120, reaproveitado do setup OAuth) — sem precisar
criar conta/projeto novo.

URL real: https://showup-509120.web.app
- `/agendar` — página de agendamento público (Pix)
- `/stripe-bounce` — página-ponte do Connect onboarding

(URLs "limpas", sem `.html`, por causa do `cleanUrls: true` configurado
no `firebase.json`.)

### Código atualizado
- `open-external-checkout.ts`: `STRIPE_BOUNCE_URL` trocado do artifact
  do Claude pra `https://showup-509120.web.app/stripe-bounce`.
- `backend/.env`: `ALLOWED_ORIGINS` trocado do placeholder antigo
  (nunca corrigido de verdade — só tinha sido mencionado numa tabela pro
  Render antes, mas nunca aplicado no arquivo local) pra incluir o
  domínio real do Firebase Hosting.

### ⚠️ Ação pendente do usuário
`ALLOWED_ORIGINS` também precisa ser atualizado na variável de ambiente
do RENDER (separada do arquivo .env local) — sem isso, o CORS vai
bloquear as chamadas da página `/agendar` pro backend.

### Validação real
`tsc --noEmit`: zero erros. `expo export --platform android`: bundle
gerado com sucesso. Backend reimportado confirmando o novo
ALLOWED_ORIGINS carregado corretamente.

## Novo: card "Seu link de agendamento" no perfil do profissional

Usuário levantou um gap real de UX: pra pegar o link de agendamento
público, era preciso olhar o banco de dados direto — inviável pra um
profissional de verdade, sem acesso técnico. Corrigido com uma solução
imediata (não depende de nenhuma integração de WhatsApp automatizada,
que continua pendente do BSP): o profissional agora vê o PRÓPRIO link
direto na tela de Perfil, com botão de copiar e botão de compartilhar
(abre o menu nativo do celular, WhatsApp aparece como uma das opções —
sem precisar de nenhuma API do WhatsApp pra isso).

### Implementado
- `expo-clipboard@7.1.5` instalado (via npm direto — `npx expo install`
  falhou no sandbox por falta de acesso à API do Expo pra resolver
  versões, resolvido escolhendo manualmente a série 7.x compatível com
  SDK 57).
- `perfil.tsx`: novo card "SEU LINK DE AGENDAMENTO" na seção do
  profissional, mostrando o link completo (`https://showup-509120.web.app/
  agendar?prof=<user_id>`, montado no cliente usando o user_id já
  disponível pelo auth), com botão "Copiar" (Clipboard, com feedback
  visual "Copiado!" por 2s) e "Compartilhar" (`Share.share()` nativo do
  React Native — abre o menu do SO, WhatsApp é uma opção ali junto com
  qualquer outro app instalado).

### Bug real corrigido durante a implementação
Coloquei o `useState` novo DEPOIS de um `return null` condicional — viola
as Rules of Hooks do React (hooks nunca podem vir depois de um return
condicional, sempre no topo, incondicionalmente). Corrigido movendo pro
topo do componente, junto dos outros hooks já existentes.

### Validação real
`tsc --noEmit`: zero erros (pegaria esse tipo de erro de qualquer forma,
mas corrigi antes mesmo de rodar, revisando o código). `expo export
--platform android`: bundle gerado com sucesso incluindo o novo módulo
nativo.

### ⚠️ Ação necessária do usuário
Como `expo-clipboard` é um módulo NATIVO novo, precisa apagar
`frontend/android/` de novo e rodar `npx expo run:android` do zero (mesma
rotina de sempre quando adicionamos dependência nativa) — não basta só
recarregar o JS.

## EXPO_PUBLIC_BACKEND_URL trocado pra apontar pro Render (produção)

Usuário quer testar num celular Android físico (não emulador) — o
`10.0.2.2` que estava configurado só funciona de DENTRO do emulador,
nunca de um celular real. Trocado pra apontar direto pro backend já
publicado no Render (`https://showup-backend-s9y1.onrender.com`), em vez
de tentar configurar IP de rede local (mais frágil — exigiria mesma
WiFi, firewall liberado, etc.). Também é mais representativo de produção
de verdade a partir de agora.

### Validação real
Confirmado por leitura direta do arquivo que o valor novo foi aplicado
corretamente.

## expo-dev-client instalado (necessário pro EAS Build de development)

O comando `eas build --profile development` avisou que faltava esse
pacote — é exigido especificamente pra builds com `developmentClient:
true` (nosso perfil "development" no eas.json). Instalado
`expo-dev-client@6.0.21` (série compatível com Expo SDK 57).

### Validação real
`tsc --noEmit`: zero erros. `expo export --platform android`: bundle
gerado com sucesso.

## Política de Privacidade + exclusão de conta (bloqueios da Play Store resolvidos)

Dois itens identificados como obrigatórios pra publicação, nunca
construídos até agora. Implementados nesta rodada.

### Política de Privacidade
`privacidade.html` — conteúdo real e específico do ShowUp (não texto
genérico), cobrindo: quais dados coletamos (login Google, telefone via
link público, dados de pagamento processados pelo Stripe — nunca
armazenados por nós), com quem compartilhamos (Google, Stripe, MongoDB
Atlas), direitos do usuário sob a LGPD, retenção de dados (anonimização
ao excluir conta, exceção pra registros financeiros por obrigação
legal), segurança, menores de idade, contato. Adicionado ao pacote do
Firebase Hosting (`/mnt/user-data/outputs/showup-firebase-hosting.zip`,
atualizado) — precisa rodar `firebase deploy --only hosting` de novo
pra publicar em `/privacidade`.

**Nota que passei ao usuário: não sou advogado — recomendei revisão
jurídica antes do lançamento real, especialmente por envolver LGPD.**

### Exclusão de conta
- `server.py`: novo endpoint `DELETE /me`. Não apaga o documento do
  usuário de verdade — anonimiza campos pessoais (nome → "Usuário
  excluído", email → sintético único baseado no user_id, foto e
  telefone removidos), marca `deleted_at`, remove referências Stripe
  (`stripe_customer_id`, `stripe_billing_customer_id`,
  `stripe_account_id`), invalida todas as sessões. Preserva
  agendamentos/transações já ocorridos (obrigação fiscal), agora
  desvinculados de dado pessoal identificável.
- Bloqueia a exclusão (409) se o usuário tiver agendamento com hold
  ativo (`autorizado`/`cancelando`/`aguardando_pix`) ou compromisso
  futuro agendado — evita perder dinheiro travado ou deixar cliente/
  profissional no vácuo.
- `configuracoes.tsx`: novo card "ZONA DE PERIGO" com botão "Excluir
  minha conta", confirmação via `Alert.alert` (estilo destrutivo,
  padrão nativo do SO) antes de disparar a exclusão de verdade.

### Bug real corrigido durante a implementação
Escrevi a query de checagem de compromisso pendente com a chave `"$or"`
duas vezes no MESMO dicionário Python — a segunda ocorrência
sobrescrevia a primeira silenciosamente (chaves de dict são únicas em
Python, isso não dá erro de sintaxe, só comportamento errado). Isso
faria a checagem ignorar completamente o filtro por cliente_id/
profissional_id, bloqueando a exclusão de QUALQUER usuário se existisse
QUALQUER agendamento pendente de QUALQUER pessoa no sistema inteiro.
Corrigido usando `$and` pra combinar as duas condições `$or`
corretamente — validei a estrutura resultante com um teste isolado
antes de seguir, confirmando que as duas condições sobrevivem.

### Validação real
- Testei a estrutura da query MongoDB isoladamente (sem precisar de
  banco real) — confirmei que as duas condições `$or` coexistem
  corretamente depois da correção.
- Backend: compilado, reimportado com sucesso, rota `DELETE /api/me`
  confirmada no schema OpenAPI.
- Frontend: `tsc --noEmit` zero erros, `expo export --platform android`
  gerou bundle com sucesso.
- Confirmei por grep que `auth.signOut` existe de verdade no hook antes
  de usar (não assumi).

### Ainda falta pro checklist da Play Store
Conta de desenvolvedor no Play Console, Termos de Uso, ícone/screenshots/
descrição da loja, formulário de segurança de dados, build de produção
(.aab), envio pra revisão.

## Achado sério: .gitignore incompleto expôs segredos e quebrou o build do EAS

Investigando por que o build do EAS Build falhava repetidamente ("Gradle
build failed with unknown error", mesmo depois de reinstalar node_modules
do zero), achei a causa real: `frontend/.gitignore` só tinha UMA linha
(`expo-env.d.ts`, gerada automaticamente) — sem excluir `node_modules/`,
`android/`, nem `.env`. O `.gitignore` da RAIZ do projeto sempre esteve
completo e correto, mas o repositório Git real parece ter sido criado
dentro da pasta `frontend/` especificamente (via "Share Project on
GitHub" do Android Studio), então só o `.gitignore` incompleto de lá
valia de verdade.

Isso explica o arquivo de 380MB no upload do EAS Build visto nos logs
(node_modules inteiro sendo enviado) e, mais grave: a pasta `android/`
sendo enviada com arquivos que guardam caminhos absolutos do Windows
(`C:\Users\Edu\...`) — que não significam nada nos servidores Linux do
EAS Build, e é a explicação mais provável pra falha persistente do
Gradle na nuvem (nunca falhava localmente, só lá).

### Corrigido
- `frontend/.gitignore`: reescrito completo (node_modules, .env,
  /android, /ios, .expo, cache do Metro, arquivos de assinatura, etc.)
  — mesmo padrão já usado no `.gitignore` da raiz.
- Passado ao usuário: `git rm -r --cached node_modules android .env` +
  commit + push, pra remover esses itens do rastreamento (sem apagar
  localmente).

### Segredos rotacionados por precaução
Mesmo sendo repositório privado, os segredos ficam visíveis no HISTÓRICO
de commits antigos mesmo depois da limpeza acima (gitignore só previne
daqui pra frente). Rotacionado:
- `INTERNAL_SERVICE_TOKEN`: novo valor gerado (`openssl rand -hex 32`),
  aplicado no `backend/.env` local. **Usuário ainda precisa aplicar o
  mesmo valor no Render.**
- `MONGO_URL`: usuário está trocando a senha do usuário do banco no
  Atlas Database Access — aguardando a senha nova pra atualizar.
- `STRIPE_API_KEY`: decidido NÃO trocar — é chave de modo TESTE, risco
  baixo mesmo exposta.

### Validação real
Backend reimportado com sucesso depois da troca do token.

## MONGO_URL rotacionada com a senha nova

Usuário trocou a senha do usuário `eduards987_db_user` no MongoDB Atlas
Database Access. `MONGO_URL` atualizada no `backend/.env` local com a
senha nova (só alfanumérica, não precisou de URL-encoding). Backend
reimportado com sucesso.

**Usuário ainda precisa aplicar essa mesma MONGO_URL nova no Render.**

## Causa real da falha persistente do EAS Build: faltava .easignore

Depois de 3 tentativas de build falhando com o mesmo erro genérico
("Gradle build failed with unknown error"), e depois de confirmar que
`git rm --cached node_modules` nem encontrava o pathspec (node_modules
nunca esteve rastreado no git) — reconsiderei a causa raiz. O passo
"Compressing project files" do `eas build` lê direto do DISCO LOCAL,
não do estado do Git — corrigir o `.gitignore` nunca teria efeito nisso.

### Corrigido
Criado `frontend/.easignore` (arquivo específico do EAS Build, com
prioridade sobre `.gitignore`, documentado oficialmente pra esse
propósito exato) excluindo `node_modules/`, `android/`, `ios/`,
`.expo/`, `.metro-cache/`, `.git/`. Excluir `android/` é seguro porque
nunca fizemos nenhuma edição manual nela — é 100% gerada
automaticamente a partir do `app.json`, então o EAS Build vai
regenerá-la do zero, direto no Linux dele, sem nenhum caminho absoluto
do Windows sobrando (a suspeita original, nunca confirmada por falta de
acesso ao log detalhado, mas consistente com "só falha na nuvem, nunca
local").

### Ainda sem confirmação
Não consegui acessar o log detalhado do "Run gradlew" em nenhuma
tentativa (nem pela página, nem por `eas build:view`) — essa correção é
baseada em raciocínio sobre o mecanismo do EAS Build (documentado), não
em confirmação direta da causa exata. Pode não resolver sozinha; se
persistir, o próximo passo é insistir em conseguir o log real.

## Causa confirmada do .easignore não funcionar: bug conhecido no EAS CLI

Pesquisei mais fundo depois do .easignore não reduzir o tamanho do
pacote (380MB idêntico, 4ª tentativa) — achei o issue exato:
github.com/expo/eas-cli/issues/4259 (aberto há ~30 dias, ainda sem
correção): quando o projeto está dentro de um repositório Git, o EAS
CLI detecta a "raiz do git" internamente e ignora qualquer `.easignore`
colocado do lado do `eas.json`, usando em vez disso (silenciosamente,
sem warning) a raiz do git — que pode não ser a mesma pasta.

Também confirmei na doc oficial (expo/fyi eas-build-archive.md): EAS CLI
"sempre respeita .gitignore" e "node_modules é ignorado por padrão" —
então node_modules provavelmente NUNCA foi a causa do tamanho grande;
é mais provável que seja a pasta `android/` (que tem caches do Gradle
que costumam ser enormes).

### Correção (contorno oficial documentado pro bug)
`EAS_NO_VCS=1` desativa a detecção via Git por completo, fazendo o EAS
ler o `.easignore` direto da pasta do `eas.json` (onde já coloquei
corretamente antes) — contornando o bug. Passado ao usuário:
```
$env:EAS_NO_VCS=1; eas build --profile development --platform android
```
(sintaxe PowerShell pra variável de ambiente numa linha só).

### Ainda sem confirmação definitiva
Essa é a 2ª tentativa de correção sem conseguir ver o log real do
Gradle — baseada em pesquisa e raciocínio sobre o mecanismo do EAS CLI,
não confirmação direta da causa exata do "Gradle build failed with
unknown error". Se persistir depois disso, o log real vira prioridade
máxima antes de tentar mais uma correção às cegas.

## Achado real (finalmente!): versão errada do expo-dev-client

Depois de 8+ tentativas de build no EAS falhando com erro genérico
"unknown error" sem nenhum log acessível, consegui reproduzir o MESMO
processo localmente (`npx expo run:android` sem pasta android/, forçando
regeneração do zero) — e esse SIM mostrou o erro real, específico:

```
> Task :expo-dev-menu-interface:compileDebugKotlin
e: .../ReactHostWrapper.kt:12:21 Unresolved reference 'rncompatibility'.
e: .../ReactHostWrapper.kt:24:9 Unresolved reference 'ReactNativeFeatureFlags'.
```

Pesquisei e achei um relato praticamente idêntico ao nosso caso (mesma
categoria de erro: TypeScript/JS passam limpo, dev server roda normal,
só o build NATIVO do Gradle quebra) — confirma que a causa é pacotes do
Expo instalados em versão incompatível com o SDK do projeto. Isso é
provavelmente minha responsabilidade: quando instalei `expo-dev-client`
antes, `npx expo install` (a ferramenta oficial que resolve a versão
certa) falhou no MEU sandbox por restrição de rede, e escolhi a versão
manualmente (`6.0.21`) só inferindo um padrão a partir de outro pacote —
sem confirmar contra a tabela de compatibilidade real do Expo. O artigo
que encontrei é explícito: "o número da versão do pacote nem sempre
bate com o número do SDK — só olhar a versão principal não é
suficiente."

### Correção passada ao usuário
`npx expo install --check` (lista o que está desalinhado) seguido de
`npx expo install --fix` (corrige automaticamente pra versão certa,
usando a tabela oficial do Expo) — só funciona na máquina do usuário,
que tem acesso de rede completo (diferente do meu sandbox).

### Ainda sem confirmação final
Passei a correção mas ainda não tenho confirmação de que resolveu — essa
é a hipótese mais forte até agora, baseada em evidência REAL pela
primeira vez (não mais raciocínio às cegas), mas falta validar o
resultado.

## ✅ CONFIRMADO: build local funcionou depois da correção de versões

`npx expo run:android` completou com sucesso: "BUILD SUCCESSFUL in 3m 32s",
588 tasks (326 executadas, 244 do cache, 18 já atualizadas), zero erros —
o `expo-dev-menu-interface:compileDebugKotlin` que falhava antes agora
compila limpo. Metro Bundler iniciou normalmente depois.

Isso fecha de vez a investigação de 10+ tentativas: a causa raiz real era
versões de pacote desalinhadas com o Expo SDK 57 (introduzidas por mim,
ao escolher versões manualmente quando `npx expo install` falhava no meu
sandbox por restrição de rede). Resolvido com `npx expo install --check`
+ `--fix` (ferramenta oficial do Expo, rodada na máquina do usuário, que
tem acesso de rede completo).

### Próximo passo natural
Testar `eas build` na nuvem de novo agora — como a causa raiz era nas
DEPENDÊNCIAS (não no `.easignore`/pasta android/, que também foram
ajustados ao longo do caminho), o build na nuvem deve funcionar agora
também.

## Login do Google trocado: SDK nativo → fluxo via navegador (backend callback)

Depois de esgotar toda causa de configuração possível pro travamento
silencioso do login do Google (SHA-1 confirmado 100% correto via keytool,
emulador novo do zero, usuário de teste certo, sem revisão pendente,
cliente Android duplicado removido — nada resolveu), a pesquisa achou um
issue aberto HOJE no GitHub, ambiente idêntico ao nosso (mesma versão da
lib @react-native-google-signin 16.1.5, mesmo Expo SDK 57), sem solução —
e a doc oficial confirma que a versão GRATUITA dessa lib usa o SDK
"legado" do Google no Android, enquanto existe uma versão PAGA feita
especificamente pra New Architecture (obrigatória no SDK 57).

### Decisão
Trocar pro fluxo via navegador, que não depende de nenhum certificado de
assinatura (SHA-1) — elimina de vez essa classe inteira de bugs que nos
perseguiu a conversa toda (DEVELOPER_ERROR, travamento silencioso, EAS vs
keystore local, etc).

### Descoberta importante no caminho
Client ID tipo "Web" do Google **não aceita** esquema customizado
(`showup://`) como redirect_uri — é bloqueado pelo próprio Google
("Custom scheme URIs are not allowed for 'WEB' client type"). A solução
correta: o redirect_uri cadastrado no Google é uma URL HTTPS do próprio
backend, que troca o `code` por tokens (usando Client Secret, nunca
exposto no app), monta a sessão, e só DEPOIS redireciona pro app via
`showup://auth-callback?token=...`.

### Implementado
- **Backend** (`server.py`): endpoint novo `GET /auth/google/callback`
  (recebe `code`, troca no `oauth2.googleapis.com/token`, valida
  `id_token`, monta sessão, redireciona pro app). Lógica de
  criação/atualização de usuário extraída pra
  `_login_or_create_session_from_google_claims()`, reaproveitada pelo
  endpoint antigo (`/auth/session`, mantido só por compatibilidade) e
  pelo novo. Variáveis novas: `GOOGLE_CLIENT_SECRET`,
  `GOOGLE_OAUTH_REDIRECT_URI`.
- **Frontend** (`src/lib/auth.tsx`): removido
  `@react-native-google-signin/google-signin` (do package.json e do
  plugin no app.json). `signIn()` agora monta a URL de autorização do
  Google manualmente e usa `WebBrowser.openAuthSessionAsync` (já com
  `expo-web-browser`, sem precisar de `expo-auth-session` nem
  `expo-crypto` — cheguei a adicionar essas duas e removi de novo ao
  perceber que não eram necessárias pra essa abordagem).

### Pendente do lado do usuário (não fiz por não ter acesso)
1. Pegar o Client Secret do Client ID Web já existente no Google Cloud
   Console (mesma tela do Client ID).
2. Cadastrar `https://showup-backend-s9y1.onrender.com/api/auth/google/callback`
   como "URI de redirecionamento autorizado" nesse mesmo Client ID Web.
3. Colocar `GOOGLE_CLIENT_SECRET` e `GOOGLE_OAUTH_REDIRECT_URI` no
   `backend/.env` local E nas variáveis de ambiente do Render.
4. `npm install` no frontend (remove a lib antiga do node_modules).
5. Testar o login end-to-end.

### Ainda sem confirmação
Implementação nova, nunca testada de ponta a ponta ainda.

## Login do Google via navegador: FUNCIONOU (28/09/2026)

Testado no celular físico: tela de escolha de conta do Google no
navegador, backend trocou o `code` pelo id_token, criou a sessão, e o app
abriu logado (tela "Bem-vindo Eduardo"). Confirmado depois de:
- URI de redirecionamento cadastrada e salva no Client ID Web do Google
  (o erro `redirect_uri_mismatch` sumiu);
- `MONGO_URL` do Render atualizada com a senha nova (antes dava
  `bad auth` no startup);
- commit + push do `backend/server.py` (o Render publica pelo GitHub —
  o zip só muda a pasta local, nunca o Render).

### Efeito colateral corrigido
O Expo Router também capturava o deep link `showup://auth-callback?token=…`
e mostrava "Unmatched Route" por cima. Criado `app/auth-callback.tsx`,
que só faz `<Redirect href="/" />` pro gate de auth (`app/index.tsx`).

### Pendente
- Commit separado das remoções da pasta `frontend/android/` (staged, não
  commitadas) e arquivos soltos `frontend/cd` e `frontend/rmdir` (criados
  por comandos digitados errado) — apagar.
- Trocar o Client Secret do Google (foi colado no chat) e atualizar
  `backend/.env` + Render.
- Testar o EAS Build com esse fluxo novo (não depende mais de SHA-1).
- Testar o logout e novo login; testar com conta que nunca logou.

## Link público (web): escolha entre cartão e Pix

Firebase Hosting refeito (o deploy antigo tinha rodado de dentro de
`public/` e nunca publicou os HTMLs — `/privacidade` dava 404). Pacote novo
traz `.firebaserc` (projeto `showup-509120`); deploy = na pasta que tem o
`firebase.json`: `firebase deploy --only hosting --project showup-509120`
(deve dizer "found 3 files").

`agendar.html` passo 4 agora deixa o cliente escolher:
- **Cartão** (padrão): Stripe.js Card Element → `POST /public/cartao/setup-intent`
  (novo) → `stripe.confirmCardSetup` → `POST /public/agendamentos/cartao`
  (hold, mesma proteção anti no-show do app). Mostra a taxa de no-show no
  resumo. Chave `pk_test_...` hardcoded na página (publicável) — trocar
  pela `pk_live_` junto com as chaves do backend.
- **Pix**: fluxo que já existia (cobra total, QR code + polling).

Backend: endpoint novo `POST /public/cartao/setup-intent` (nome+telefone →
acha/cria cliente, ensure_customer, SetupIntent off_session), rate limit
10/min. `stripe_gateway.create_setup_intent` agora converte erro do Stripe
em PaymentError (antes vazava como 500). Testado com TestClient (4 casos)
e a página com Playwright (cartão ok, Pix, cartão recusado, horário
ocupado).

### Pendente
- Pix falha em produção-teste com "Falha ao gerar cobrança Pix junto ao
  gateway" (502): a causa real está no log do Render, linha
  `create_pix_payment_intent falhou ...`. Hipóteses: Pix não ativado nos
  métodos de pagamento da conta Stripe (modo teste) ou a conta Connect do
  profissional sem a capability de Pix.
- Cartão nunca testado contra o Stripe de verdade (só com Stripe.js
  simulado): testar com 4242 4242 4242 4242.

## Pix: causa do erro e decisão (28/09/2026)

Log do Stripe (`POST /v1/payment_intents`, 400): "The payment method type
"pix" is invalid. Please ensure the provided type is activated in your
dashboard…". Não é bug nosso: no Stripe **Brasil o Pix é por convite**
(conta em boa situação + 60+ dias processando; conta criada em 19/09/2026,
ainda não elegível). Contas de outros países (US, EU…) aceitam Pix com
liquidação em moeda local, mas a nossa é BR.

Decisão: Pix **desligado** no link público até o Stripe liberar.
- `agendar.html`: `const PIX_DISPONIVEL = false;` — some seletor e botão,
  fica só o formulário de cartão. Fluxo de Pix (QR, copia e cola,
  polling) continua no código; pra religar: trocar pra `true`, republicar.
- Backend: `POST /public/agendamentos/pix` devolve 503 "Pix indisponível
  no momento. Pague com cartão." quando o Stripe recusa o tipo pix (antes
  era 502 genérico); outros erros seguem 502.

### Pra religar o Pix depois
Dashboard Stripe > Settings > Payment methods: se Pix aparecer, ativar;
se não, pedir acesso ao suporte do Stripe. Depois de ativado, testar em
modo teste (email de teste do Stripe simula pago/expirado) e só então
`PIX_DISPONIVEL = true`. Se usar conta Connect com cobrança direta ou
`on_behalf_of`, a conta conectada também precisa da capability
`pix_payments`.

## Onboarding do Stripe Connect simplificado (28/09/2026)

Reclamação: o cadastro do profissional pedia coisa demais (tipo de conta,
"Business information"/site, etc).

Feito (backend, `stripe_gateway.create_connect_account` +
`server._connect_prefill`): a conta Express agora nasce pré-preenchida —
`business_type=individual` (some a pergunta pessoa física/empresa), nome
e e-mail do Google em `individual`, e o perfil público: `business_profile.url`
= página de agendamento do próprio profissional
(`{PUBLIC_WEB_BASE_URL}/agendar?prof=<id>`, é o que a doc do Stripe manda
usar pra autônomo sem site) + `product_description` (com as categorias).
O hospedado do Stripe não pergunta o pré-preenchido, só pede confirmação.
Contas já existentes: `prefill_connect_profile` completa url/descrição SÓ
se estiverem vazios (nunca sobrescreve o que o profissional digitou),
best-effort — falha vira log, não bloqueia. Env nova opcional:
`PUBLIC_WEB_BASE_URL` (default `https://showup-509120.web.app`).

NÃO removível (exigência do Stripe/KYC de pessoa física no Brasil): data de
nascimento, CPF, endereço, telefone e conta bancária pra repasse. Ocultar
campo não remove a exigência; e não coletamos esses dados no app (LGPD).
Não mexi nas `capabilities` (transfers + card_payments): não consegui
confirmar que dá pra reduzir sem quebrar os repasses.

Pra testar do zero: apagar a conta conectada de teste no Dashboard
(Connect > Accounts) — o backend recria sozinho no próximo "configurar
recebimentos" (recuperação de conta órfã "No such account").

## Onboarding do Connect: erro silencioso ao tentar conectar (29/09/2026)

Depois de aplicar o pré-preenchimento e apagar a conta Connect de teste
antiga, o botão "Conectar Stripe" parou de abrir o navegador — sem erro
visível, botão só volta ao normal. Achada a causa: `connectM` (a mutation
do botão, em `configuracoes.tsx`) não tinha `onError` nenhum — qualquer
falha (da chamada à API ou do `openExternalCheckout`) era engolida em
silêncio pelo react-query.

Corrigido: `onError` agora mostra `Alert.alert` com a mensagem real (o
`detail` que o backend manda via `ApiError`, confirmado que `api.ts`
propaga certinho). Isso não conserta a causa raiz (ainda não sabemos qual
é — pode ser algo no meu `create_connect_account` novo, ou outra coisa),
só torna o erro visível pra diagnosticar na próxima tentativa.

Separado disso: no vídeo anterior, a tela de "Date of birth" do
onboarding hospedado do Stripe travava com "Sorry, something went wrong"
mesmo preenchendo mês → dia → ano em ordem — mas isso era com a conta
ANTIGA (antes do pré-preenchimento). Ainda não sabemos se esse travamento
específico também acontece com a conta nova, porque a criação da conta
está falhando antes de chegar lá.

### Pendente
Usuário vai tentar de novo com o Alert novo e mandar a mensagem exata.

## Causa real do "Internal Server Error" no Connect (29/09/2026)

Confirmado: `await gateway.create_connect_account(...)` (as duas
ocorrências) e `await gateway.prefill_connect_profile(...)` estavam FORA
de qualquer try/except no endpoint `connect_onboarding` — só a chamada
seguinte (`create_onboarding_link`) tinha proteção. Antes do
pré-preenchimento isso nunca importava (a chamada quase nunca falhava);
com os campos novos (`individual`, `business_profile.url`,
`product_description`), uma recusa do Stripe nesses campos virava
exceção crua até o FastAPI → 500 "Internal Server Error" sem mensagem
nenhuma — e como o onError do app também não existia (corrigido
antes), ficava tudo mudo dos dois lados.

### Corrigido
Todo o corpo do endpoint (criação/reaproveitamento da conta +
prefill + link) agora está dentro de um único try, com:
- `except InvalidPaymentRequestError` → 400 com a mensagem REAL do Stripe
  (é informação nossa, sobre o que mandamos errado — segura de mostrar,
  diferente de expor detalhe de erro genérico de servidor);
- `except PaymentError` → 502 genérico (falha transitória/rede).
`prefill_connect_profile` do gateway real já era best-effort de verdade
(nunca propaga), confirmado lendo o código-fonte no teste.

Testado (TestClient): campo recusado → 400 com mensagem real; erro
transitório → 502; fluxo normal sem account_id → 200. Nenhum caminho
mais vira 500 cru.

### Ainda não sabemos
Qual campo exatamente o Stripe está recusando na conta do usuário — o
teste é com erro simulado. Próxima tentativa real do usuário, com essa
correção aplicada, deve finalmente mostrar a mensagem verdadeira no
Alert do app.

## Causa real, confirmada pelo log (29/09/2026): AttributeError no prefill

Log do Render deu a resposta exata:
```
AttributeError: 'get' is a dict method, but a Account is not a dict.
Use .to_dict() to convert it.
  File ".../stripe_gateway.py", line 339, in prefill_connect_profile
    bp = acct.get("business_profile") or {}
```

Causa: a versão do `stripe-python` instalada (mais nova) não deixa mais
tratar `stripe.Account` como dict — `.get()` quebra com AttributeError.
Meu `prefill_connect_profile` usava `acct.get(...)` e `bp.get(...)`,
copiando um padrão antigo da lib. `account_status` (método já existente
antes) já usava atributos corretamente (`acct.details_submitted` etc.),
por isso nunca deu esse erro antes — só o método NOVO tinha o padrão
errado.

### Corrigido
`prefill_connect_profile` agora acessa `acct.business_profile` por
atributo (pode vir `None` numa conta recém-criada — tratado), e
`getattr(bp, "url", None)` / `getattr(bp, "product_description", None)`
em vez de `.get(...)`. Except amplia pra `(StripeError, AttributeError)`
por segurança, mas a causa raiz (não o sintoma) é o que foi corrigido.
Conferido que não há mais nenhum outro `.get()` em objeto Stripe no
arquivo (só em dict nosso do Mongo e em `os.environ`).

Testado com objeto que reproduz o comportamento exato do `Account` real
(rejeita `.get()`, aceita atributos): perfil `None` (caso da conta
recém-criada, que foi o que quebrou), perfil existente vazio, e perfil já
preenchido (não sobrescreve). Os três passam.

## Onboarding do Connect trava no Android (Custom Tab) mas funciona no desktop (29/09/2026)

Vídeos confirmaram: no navegador embutido do Android (Custom Tab, via
`WebBrowser.openAuthSessionAsync`), a etapa de "Date of birth" do
onboarding hospedado do Stripe trava com "Sorry, something went wrong" —
às vezes depois de preencher a data (mesmo em ordem), às vezes a página
nem termina de carregar. MESMA conta, MESMO link, aberto no Chrome do
computador: completa sem erro nenhum, chega até "Verify your identity".
Isolado: não é nosso código, não é a conta, não é o Stripe em geral — é
específico do Custom Tab no Android nesse ambiente.

### Corrigido
Só o onboarding do Connect (não o checkout de planos, que nunca teve
esse problema) passa a abrir no **navegador do sistema**
(`WebBrowser.openBrowserAsync`, sai do app de verdade) em vez do Custom
Tab embutido — mesmo motor que funcionou no desktop.
`openExternalCheckout` ganhou um 4º parâmetro `useSystemBrowser`
(default `false`, só o Connect passa `true`).

Detalhe que quase passou batido: a doc oficial do Expo confirma que no
Android `openBrowserAsync` sozinho resolve a Promise assim que o
navegador ABRE, não quando o usuário volta (diferente de
`openAuthSessionAsync`). Isso significa que `onReturn` nesse caminho
dispara cedo demais pra servir de sinal de "terminou". Resolvido com um
listener de `AppState` em `configuracoes.tsx`: toda vez que o app volta
ao primeiro plano, revalida a query `connect-status` — cobre o caso real
(usuário completa no navegador externo, volta pro app depois).

### Ainda não confirmado end-to-end
Não testei essa troca de navegador de verdade ainda (só a lógica e a
doc). Próximo passo do usuário: tentar "Conectar Stripe" de novo no
celular e ver se completa sem travar.

## Correção da correção: openBrowserAsync também usa Custom Tab no Android

A tentativa anterior (trocar pra `WebBrowser.openBrowserAsync`) estava
errada — não resolveu nada porque, no Android, essa função SEMPRE abre
via "custom Chrome tabs" por baixo (confirmado na doc oficial do Expo:
"Opens the url with... Chrome in a new custom tab on Android" e "This
will be done using a 'custom Chrome tabs' browser"). É literalmente o
mesmo mecanismo de `openAuthSessionAsync`, só com outro nome de função —
por isso "não usou o Chrome" (visualmente continuou sendo o navegador
embutido, com o mesmo bug esperado).

### Corrigido de verdade
Trocado pra `Linking.openURL(url)` — essa sim sai do app de verdade,
abrindo o navegador PADRÃO do sistema (como se o usuário tivesse tocado
num link fora do app), sem passar pelo mecanismo de Custom Tabs. É o
único caminho documentado do Expo pra isso ("The expo-linking API allows
you to open a URL using the operating system's default web browser
app").

Mesma estrutura de antes (parâmetro `useSystemBrowser`, listener de
`AppState` em `configuracoes.tsx` pra revalidar o status ao voltar) —
só a chamada interna mudou.

### Ainda não confirmado end-to-end
Como da vez passada: a lógica está certa, mas não testei contra o app de
verdade ainda. Próximo passo do usuário: tentar "Conectar Stripe" de novo
e confirmar que agora sim abre o Chrome/navegador padrão separado do app.

## Busca por risco de expor a URL do Render em produção (30/09/2026)

Usuário levantou preocupação: a tela genérica "APPLICATION LOADING" do
Render (que aparece quando o backend dorme e alguém navega o navegador
pra URL dele) não pode aparecer pra cliente/profissional de verdade.

### Busca no código inteiro
Toda referência à URL do backend (`onrender.com`,
`EXPO_PUBLIC_BACKEND_URL`, `BACKEND_URL` no agendar.html) usa
exclusivamente `fetch()` — chamada de dados, nunca abre a URL numa aba do
navegador. Isso cobre: app mobile (api.ts), página pública de agendamento
(agendar.html). Confirmado também que `Linking.openURL` em
`open-external-checkout.ts` abre a URL que a API DEVOLVE (sempre
connect.stripe.com, nunca nosso backend) — seguro.

### Achado real: fluxo de login com Google
`redirect_uri` do OAuth aponta pro nosso `/api/auth/google/callback` — é
o próprio GOOGLE quem redireciona o navegador do usuário pra lá no fim do
login (não é uma chamada nossa). Diferente de toda chamada via fetch(),
essa É uma navegação de verdade — se o backend estiver dormindo bem
nesse momento, o usuário veria a tela do Render no meio do login.

### Mitigado (não eliminado 100%)
`AuthProvider` agora dispara um fetch "silencioso" pro backend
(`fire-and-forget`) assim que o app abre, bem antes do usuário chegar a
tocar em "Entrar com Google". `signIn()` dá até 3s de folga (Promise.race
com essa chamada) antes de abrir o navegador do Google. Reduz bastante a
chance na prática (a maioria dos usuários leva mais que alguns segundos
entre abrir o app e tocar em login), mas não elimina 100% — quem for
rápido demais, ou abrir o app depois de muito tempo com o backend já
dormindo de novo, ainda pode ver a tela por alguns segundos.

### Solução definitiva, não implementada (decisão do usuário)
Um "keep-alive" de verdade (pingar o backend a cada ~10min pra nunca
deixar dormir) elimina o problema por completo — cabe dentro das 750h
grátis do Render (ligado o mês inteiro = ~744h). Não implementado ainda;
precisa de um cron/scheduler externo (o Render free tier não tem cron
job embutido gratuito) ou upgrade de plano.

## Keep-alive do backend via GitHub Actions (30/09/2026)

Criado `.github/workflows/keepalive.yml`: pinga `GET /api/` a cada 5
minutos (bem abaixo dos ~15min que o Render leva pra dormir, com folga
pra atrasos do agendador do GitHub, que não garante pontualidade exata).
`workflow_dispatch` habilitado pra rodar manualmente também. Conta de
uso: a cada 5min = ~288 execuções/dia, poucos segundos cada, soma uns
~1440 min/mês — dentro do limite gratuito de 2000 min/mês do GitHub
Actions pra repositório privado.

Isso resolve de vez o risco de o navegador do usuário ver a tela de
"acordando" do Render no meio do login com Google (mitigado antes com o
"wake up" no app, mas não eliminado 100%) — com o backend sempre
acordado, esse cenário deixa de acontecer.

### Nota de manutenção
GitHub desativa workflows agendados automaticamente se o repositório
ficar 60 dias sem nenhum push. Se isso acontecer, precisa reativar
manualmente na aba Actions do GitHub (Enable workflow).

## Dois bugs reais confirmados por teste (01/10/2026)

### Bug 1: horário errado no app (3h de diferença)
Prints comparados: página web mostrava "05:30" (consistente, confirmação e
pagamento), app mostrava "08:30" — diferença de exatamente 3h (offset de
Brasília). Confirmado NÃO ser o fuso do celular (estava automático e
correto). Testei a serialização do backend (Pydantic + `_aware()`) e
confirmei que o JSON já vem certo, com "Z" explícito de UTC.

Causa real: `formatDateTime`/`formatDateOnly`/`formatTimeOnly`
(`src/lib/format.ts`) usavam `toLocaleString`/`toLocaleDateString` do
`Intl`, sem fuso explícito — dependendo do motor JS do React Native
(Hermes) converter certo pro fuso do dispositivo. Hermes tem histórico
de bugs reais com `Intl`/timezone (ex: facebook/hermes#431, entre
outros) — comportamento inconsistente dependendo da versão/build.

Corrigido: as três funções agora calculam data/hora manualmente a partir
de um offset FIXO em minutos por fuso (`OFFSET_MINUTOS`, um por entrada
de `TIMEZONE_LABELS` — todos sem horário de verão atualmente no Brasil),
sem depender do Intl pra conversão de fuso. Aceitam um `timezone?: string`
opcional (IANA, ex: "America/Sao_Paulo"); sem fuso informado cai no
default (São Paulo). As 4 chamadas no app (home.tsx ×2, agendamentos.tsx,
agendamento/[id].tsx ×2) agora passam `auth.user?.timezone` — o fuso do
PRÓPRIO profissional logado (backend sempre preenche esse campo, com
fallback pro default, nunca undefined). Testado isoladamente com Node:
caso exato do bug, os 4 fusos suportados, e virada de dia — todos corretos.

⚠️ Se o Brasil voltar a adotar horário de verão no futuro, os offsets
fixos em `OFFSET_MINUTOS` ficam desatualizados parte do ano — precisa
revisar nessa hipótese (improvável hoje, mas registrando a premissa).

### Bug 2: horários "picados" (slot de 30 em 30 mesmo com serviço de 60min)
Confirmado pela evidência: um slot de "05:30" apareceu com disponibilidade
começando às 05:00 e serviço de 60min — só é possível com step fixo de
30min (não a duração do serviço). O CÓDIGO que tenho aqui (`server.py`,
`slots_disponiveis`) já usa `step = duracao` (corrigido antes, ver
PRD mais acima) — o comentário no código já explica o problema certinho.
A causa provável é essa correção nunca ter sido publicada (commit+push)
pro Render depois de feita. Reforçado ao usuário: confirmar que o
`server.py` atual (com essa correção) está realmente no ar.

## Pagamento com cartão quebrado: API do Stripe mudou (04/10/2026)

Log do Render deu a causa exata: `stripe._error.InvalidRequestError: The
`payment_method_types` parameter is no longer supported. Payment methods
are now managed from your Dashboard settings`. Confirmado na doc oficial
do Stripe (changelog da API `2026-08-26.preview`): esse parâmetro virou
somente-leitura em PaymentIntent/SetupIntent — passar ele na criação
agora dá 400. Não é um bug nosso, é uma mudança da própria API do Stripe
que passou a valer pra essa conta.

Afetava TRÊS chamadas em `stripe_gateway.py`:
- `create_setup_intent` (passo 1 do cartão no link público) — trocado
  por `automatic_payment_methods={"enabled": True, "allow_redirects":
  "never"}` (o substituto oficial; `never` restringe a métodos sem
  redirect, equivalente ao que `["card"]` garantia).
- `authorize` (hold do cartão, usado em TODO agendamento com cartão —
  app e link público) — só removido, sem substituto: já passamos
  `payment_method` específico + `confirm=True`, o Stripe usa esse método
  direto sem precisar de parâmetro adicional.
- `create_pix_payment_intent` — só removido também, mesmo motivo
  (`payment_method_data={"type": "pix"}` já especifica o método). Não
  resolve o Pix (que já sabemos que falha por outro motivo — não
  habilitado na conta), só evita um erro A MAIS em cima disso.

### Pendente
Usuário vai publicar (commit+push) e testar o cartão de ponta a ponta de
novo — essa correção nunca foi testada contra o Stripe real ainda, só
validei a sintaxe Python.

## Confirmado: _hydrate() já está correto no código local (04/10/2026)

O `TypeError: Agendamento() got multiple values for keyword argument
'horario_inicio'` que apareceu no log do Render é de uma versão ANTIGA
do `server.py` — o código local já tem a correção (campos convertidos
excluídos do spread via `_campos_convertidos`, comentário já documentando
esse exato erro). Provavelmente nunca foi publicada antes porque esse
caminho de código (listar agendamentos de cartão reais) nunca tinha sido
exercitado em produção até esse primeiro agendamento de teste bem-sucedido.

Testado isoladamente (simulando doc do Mongo com datetime naive, como
realmente vem) — sem erro, `horario_inicio` sai serializado com "+00:00"
explícito.

### Resumo do que está pendente de publicação nesse momento
Backend (`server.py` + `stripe_gateway.py`): step de slots por duração,
`payment_method_types` removido (3 chamadas), `_hydrate` sem duplicação.
Tudo no mesmo arquivo/commit — um push só resolve os três de uma vez.

## Link público: data e horário em dropdowns encadeados (05/10/2026)

Passo 2 do `agendar.html` deixou de ser uma grade de botões com todos os
dias/horários e virou dois `<select>` nativos: **Data** (dia/mês/ano, ex:
"seg, 05/10/2026") e **Horário**, que fica desabilitado ("Escolha a data
primeiro") até a data ser escolhida. Botão "Continuar" só habilita com
data + horário. Trocar a data zera o horário e trava o Continuar; voltar
pro placeholder de data trava o horário de novo. "Trocar horário" no passo
3 mantém as escolhas.

- Só aparecem datas que têm horário livre (dia lotado não entra na lista).
- A data é lida dos 10 primeiros caracteres do `iso` do slot (o backend
  manda no fuso do PROFISSIONAL, ex "2026-10-05T09:00:00-03:00"), e o dia
  da semana sai de aritmética UTC pura — nada depende do fuso do navegador
  de quem agenda. Testado com navegador em UTC+14 (slot 23:30 -03:00
  continua em 05/10).
- Resumo e tela de sucesso agora mostram "seg, 05/10/2026 às 06:00" em
  português (antes vinha o `day_label` do backend, em inglês: "Mon, 05 Oct").
- Removido o CSS da grade antiga (`.slot-btn`, `.slot-grid`, `.day-*`).
- Testes (Playwright, backend e Stripe simulados): estado inicial,
  encadeamento, reset ao trocar data, fluxo completo com cartão (confere o
  `horario_inicio` enviado), voltar mantendo escolhas, fuso diferente, sem
  horários.
- Interpretação: "dia, mês e ano" = UM dropdown de datas disponíveis
  mostrando dd/mm/aaaa, não três dropdowns separados (três permitiriam
  combinar datas sem horário livre).

## Planos: conta com os números do profissional + teste grátis (12/10/2026)

Motivo: os 3 planos só diferiam na % de taxa (Free 10% / Profissional 5% por
R$ 19,90 / Ultra 2% por R$ 59,90) — pouco atrativo. Primeira rodada do plano
de valor (ordem: 1) conta personalizada + teste grátis; 2) relatórios e link
personalizado; 3) lista de espera / recorrência / lembrete ao cliente).

### Backend (`server.py`, `stripe_gateway.py`)
- `GET /me/plano/resumo`: últimos 30 dias (`RESUMO_JANELA_DIAS`), agendamentos
  JÁ COBRADOS (`capturado_total` = compareceu, `capturado_taxa` = falta), só da
  moeda do profissional. Devolve atendimentos/valor, faltas cobradas/valor,
  custo (taxa + mensalidade) em cada plano, economia vs plano atual, plano
  recomendado (só se ECONOMIZA e está disponível — nunca recomenda upgrade que
  sai mais caro) e pontos de equilíbrio (Profissional R$ 398,00/mês; Ultra
  R$ 748,75 vs Free e R$ 1.333,34 vs Profissional). Taxa estimada = % do
  `valor_total_centavos` de CADA agendamento, arredondando por agendamento
  (igual à cobrança). Comparação só em BRL (preços dos planos são BRL).
- Teste grátis de 14 dias (`TRIAL_DIAS`), 1 por profissional: só quem está no
  Free, nunca testou (`plano_trial_usado`) nem pagou (`plano_ja_pago`).
  `subscription-intent` aceita `usar_trial`; com trial o Stripe devolve
  `pending_setup_intent` (Payment Sheet só salva o cartão) e
  `trial_settings.end_behavior.missing_payment_method=cancel`. Cancelar no
  teste volta pro Free sem cobrar e NÃO devolve novo teste.
- Hardening do `/me/plano/confirm` (necessário pro teste grátis): a assinatura
  com trial já nasce `trialing` ANTES do cartão ser salvo (stripe-react-native
  #1509), então status sozinho não prova nada. Agora o servidor grava
  `plano_pendente` no subscription-intent e o confirm: exige a mesma
  subscription_id, usa o plano GRAVADO (não o do app — antes dava pra
  confirmar um plano mais caro pagando o mais barato), exige `trialing` +
  SetupIntent `succeeded` no trial, `active` no pago, dono da assinatura =
  usuário, e é idempotente. Assinatura pendente anterior (sheet fechado sem
  salvar) é cancelada ao tentar de novo.

### Frontend (`app/(app)/planos.tsx`, só JS)
Card "Seus últimos 30 dias" (atendimentos, faltas recuperadas, tabela do que
pagaria em cada plano, veredito), selo "MELHOR PRA VOCÊ", descrição de cada
plano com o ponto de equilíbrio real (some a promessa fixa "~4-5 agendamentos"),
botão "Testar 14 dias grátis" (Payment Sheet em modo SetupIntent) e aviso
"Teste grátis até <data>" no plano atual.

### Testes
`tests/test_planos_resumo.py` + `tests/test_plano_gateway.py`: 34 testes OFFLINE
(banco e gateway falsos; objetos reais da lib do Stripe no gateway). Rodar:
`cd backend && python -m pytest tests/test_planos_resumo.py tests/test_plano_gateway.py`.
Mutação conferida: remover cada proteção do confirm derruba o teste certo.
Tela: type-check estrito do TS com stubs dos módulos nativos (0 erros).
NÃO testado ainda: fluxo real do trial contra o Stripe e a tela no aparelho.

### Resolvido (12/10/2026): taxa na FALTA proporcional ao valor cobrado
O `application_fee_amount` é fixado no authorize sobre o valor TOTAL do
serviço e o Stripe não o recalcula numa captura parcial (só muda se for
informado na captura). Numa falta de R$ 30 em serviço de R$ 120 a plataforma
ficaria com R$ 12 (Free) em vez de R$ 3.
- `StripeGateway.capture(..., fee_bps=None)`: em captura PARCIAL lê o
  PaymentIntent e manda `application_fee_amount = valor_capturado * fee_bps //
  10_000`. Captura total não muda (mantém a taxa do authorize). Cobrança SEM
  repasse (sem `application_fee_amount` no PI) não manda nada (daria erro).
- O percentual vem de `fee_bps`, gravado em TODA reserva no momento da criação
  (plano da época — mudar de plano nunca afeta reservas feitas). Reserva antiga,
  sem esse campo, usa a proporção da taxa já fixada no PI.
- `plano_resumo`: base da taxa = valor EFETIVAMENTE cobrado (serviço inteiro no
  atendimento, só a taxa de falta na falta).
- Testes: `tests/test_taxa_falta.py` (+ ajustes em test_planos_resumo.py) — 45
  testes offline no total; mutação conferida (desligar cada parte derruba o
  teste certo).
- ⚠️ Só dá pra VER isso no Dashboard do Stripe quando a conta conectada do
  profissional estiver liberada (`connect_ready`): enquanto ela estiver
  restrita as reservas nascem sem repasse e, portanto, sem taxa nenhuma.

## Preparação para o lançamento (13–15/10/2026)

Guias em `lancamento/`: `LANCAMENTO.md` (checklist em ordem, com quem faz), `PLAY-STORE.md` (ficha, respostas
de segurança de dados, acesso do revisor), `CHAVES-PRODUCAO.md` (troca teste→produção, webhooks),
`TESTADORES.md` (teste fechado de 12 pessoas × 14 dias) e `preencher-site.py`.

### Código novo
- **Connect**: `GET /me/connect` devolve `estado` (nao_conectada | pendente_informacoes | em_analise | restrita |
  recusada | ativa | indisponivel) + `pendencias` + `motivo_bloqueio`; `POST /me/connect/painel` abre o painel
  Express (onde ficam as "Tasks" do Stripe). App: `src/lib/connect-estado.ts` (lógica pura, testada em node) +
  `src/components/connect-card.tsx`. Job de 10 min reconsulta contas pendentes.
- **`EXIGIR_RECEBIMENTO_ATIVO`** (default 0; ligar em produção): sem conta do Stripe liberada não dá pra agendar
  (3 rotas de reserva) e `GET /profissionais/{id}` devolve `aceita_agendamentos=false` (página pública e app avisam).
- **`PLANOS_COMPRA_HABILITADA`** (default 1; **0 pro 1º lançamento no Play**): planos pagos viram "em breve",
  assinatura/teste grátis recusados (403), quem já assina continua e pode cancelar. Motivo: o Play costuma exigir
  a cobrança dele pra vender acesso a funções do app; não consegui confirmar a regra vigente no Brasil.
- **Cobrança do plano**: webhook `past_due` marca `plano_cobranca_pendente` + push (uma vez); `trial_will_end`
  avisa por push; banner na tela de planos.
- **Exclusão de conta**: cancela assinatura ANTES (503 se falhar, não exclui), apaga device_tokens, customer_cards e
  os Customers do Stripe. Botão movido para o **Perfil** (todos os papéis) — antes só o profissional tinha.
- **Bug de produção corrigido no webhook**: o evento do Stripe não é dict (stripe-python novo) e os tratadores
  usam `.get()` → AttributeError. `_como_dict()` converte na entrada. Webhook agora aceita 2 segredos
  (`STRIPE_WEBHOOK_SECRET` + `STRIPE_CONNECT_WEBHOOK_SECRET`).
- **Site**: `termos.html`, `excluir-conta.html`, `privacidade.html` atualizada, rodapé legal e aviso de
  "não aceita agendamentos" no `agendar.html`. Campos `{{RESPONSAVEL}}`, `{{DOCUMENTO}}`, `{{EMAIL_CONTATO}}`
  ficam em branco até `preencher-site.py`, que também bloqueia publicar com campo vazio ou link quebrado.
- **Testes**: `backend/tests/offline_env.py` dá variáveis FALSAS (sem isso o server não importa sem `.env`).
  CI em `.github/workflows/tests.yml` (97 testes offline; simulado com `env -i` numa cópia sem `.env`).

### Lições
- Pacotes antigos levavam `backend/.env` e `frontend/.env` — `empacotar` agora exclui `.env`, `*.pem`, `*.key`.
- Testes que chamam tratadores com dict comum escondem bugs de objeto do Stripe: passar pelo caminho real
  (assinatura → `construct_event`).

### Link de agendamento: dropdown "não aparecia" (15/10/2026)
O código já tinha os dois `<select>`; o que o usuário via era a versão ANTIGA publicada (o pacote completo do
site estava travado por causa dos campos em branco dos Termos). Correções: `firebase.json` com
`Cache-Control: no-cache` (o padrão do Firebase deixa HTML em cache ~1h), marcador de versão `v2026.10.15` no
rodapé do `agendar.html` (confirma o que está no ar) e pacote `showup-agendar-agora.zip` (só a página, sem
depender dos Termos). Testado no navegador com os horários REAIS gerados pelo backend, em 3 fusos.

### Bug crítico achado antes do go-live: gateway "mock" com chave de produção (15/10/2026)
`server.py` só ligava o Stripe real se `STRIPE_API_KEY` começasse com `sk_test_`. Com `sk_live_` o backend caía em
SILÊNCIO no `MockGateway` (aprova reservas sem cobrar nada). Corrigido com `_gateway_para_chave`: vazia → mock;
`sk_/rk_` + `test/live` → stripe; preenchida e inválida → RuntimeError (o servidor não sobe; o Render mantém a versão
anterior). Achado ao rodar `lancamento/verificar-producao.py` contra o backend real, que acusa `gateway = mock`.
Roteiro de publicação em `lancamento/DEPLOY.md`.

## Login por e-mail + senha e Microsoft (15/10/2026)
Pedido: o cliente criar a conta sem depender do Gmail (ex.: Outlook). Guia completo em `lancamento/LOGIN.md`.
- **Config-driven**: `GET /auth/metodos` diz o que está ligado (`google` sempre; `microsoft` com `MICROSOFT_*`;
  `email` com `SMTP_HOST`+`SMTP_FROM`). O app só mostra os botões que o servidor atende; sem config, nada muda.
- **E-mail + senha** (`/auth/email/{cadastro,verificar,login,esqueci,redefinir}`): a conta só é criada DEPOIS do
  código de 6 dígitos (10 min, 5 tentativas, uso único, guardado só como HMAC); senha em scrypt (`senhas.py`, sem
  dependência nova); 60 s entre pedidos; bloqueio de 15 min após 5 falhas; respostas idênticas para e-mail com e sem
  conta (e aviso por e-mail ao dono); redefinir derruba todas as sessões; senha nova só vale depois de provar o e-mail
  (conta Google existente ganha senha pelo mesmo caminho). Envio por SMTP padrão (`emailer.py`).
- **Microsoft** (`/auth/microsoft/{start,callback}`): só contas PESSOAIS (tenant `9188040d-...`); `state` de uso único
  e `nonce` guardados no servidor; confere aud/iss/tid/nonce/exp (assinatura dispensada por vir direto do endpoint de
  token via TLS). Contas corporativas recusadas de propósito (falha "nOAuth": e-mail do claim não é confiável).
- **Exclusão de conta** também apaga `password_hash`, `microsoft_id`, códigos e bloqueios.
- **Política de Privacidade corrigida**: dizia "nunca armazenamos senhas" — falso com este recurso. Também passou a
  listar Microsoft, provedor de e-mail, Render, Expo e Firebase. Publicar o site ANTES de ligar o SMTP.
- App: `src/lib/auth-email.ts` (validação pura, testada em node), `app/entrar-email.tsx` (entrar / criar / código /
  esqueci / redefinir), `signInMicrosoft` e `signInWithToken` em `auth.tsx`, botões em `welcome.tsx`.
- Testes: `test_senhas_e_email.py` (SMTP falso em socket real), `test_auth_email.py` (fluxos + ataques; mutação
  conferida em 7 proteções). Não testado em aparelho nem contra Microsoft/SMTP reais.

## Avisos ao profissional: novo agendamento e próximo atendimento (17/10/2026)
Guia: `lancamento/NOTIFICACOES.md`. Módulo novo `backend/notificacoes.py` (textos, fuso do profissional, "avisar uma vez").
- **Novo agendamento**: `BackgroundTasks` depois de gravar a reserva nos dois fluxos por cartão (app e link); no Pix, quando o
  webhook `payment_intent.succeeded` confirma (estado `pago_integral`). Marcação atômica `push_novo_enviado_em`.
- **Próximo atendimento**: job de 5 min (`_enviar_lembretes_proximo`), `LEMBRETE_PROFISSIONAL_MIN` (padrão 60; 0 desliga),
  marcação `push_lembrete_enviado_em`; só reservas confirmadas (`autorizado`/`pago_integral`, `agendado`); reserva feita
  dentro da janela é marcada sem repetir o aviso.
- **BUG achado e corrigido**: `_enviar_pushes_confirmacao` lia `ag['cliente_nome']`/`ag['servico_nome']`, campos que o registro
  do banco NÃO tem (só existem na resposta montada por `_hydrate`) → KeyError depois de marcar o aviso como enviado: os avisos
  "Compareceu?" e "Última chance" nunca saíam. Agora os nomes vêm de `dados_do_agendamento`.
- **Teste de notificação**: `POST /me/notificacoes/teste` + botão em Configurações. Ticket "ok" só prova que a Expo recebeu o
  pedido; erro de credencial do Firebase aparece no RECIBO, por isso o endpoint espera e consulta (`buscar_recibo`).
- **Pré-requisito no Android**: chave de serviço FCM V1 enviada ao EAS (sem ela nenhuma notificação é entregue).
- O registro do aparelho no app deixou de falhar calado (`registrarComDiagnostico`).
- Testes: `tests/test_notificacoes.py` (49), mutação conferida em 7 proteções.
