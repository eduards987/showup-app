# Montar o ambiente de teste completo — passo a passo

> **No Windows**, se o comando `python` der erro ("Python was not found"), use **`py`** no lugar (ex.: `py lancamento\verificar-config.py`).

**Objetivo:** ao final, você consegue testar **tudo** de ponta a ponta, com dinheiro de mentira: login (Google, Microsoft,
e-mail), cadastro do profissional no Stripe, reserva pelo link e pelo app, comparecimento e falta, planos e teste grátis,
exclusão de conta. Tempo: cerca de 2 horas na primeira vez (as contas externas são o que mais demora).

> Os nomes de menus de Render, Stripe, Google e Microsoft mudam de tempos em tempos. Se um nome não bater, procure pelo
> sentido (o que a tela faz); os valores a copiar são sempre os mesmos.

**Tudo aqui é MODO TESTE.** Nada cobra de verdade. O Stripe tem um interruptor "modo de teste" (ou "sandbox") no
Dashboard: confira que está ligado antes de copiar qualquer chave. Chaves de teste começam com `sk_test_` / `pk_test_`.

---

## 1. Segredos novos (10 min)

Os segredos antigos apareceram em conversas, então gere e troque:

1. `python lancamento\verificar-config.py --gerar-segredos` — copie `INTERNAL_SERVICE_TOKEN` e `AUTH_CODE_PEPPER` para o Render (passo 3).
2. **MongoDB Atlas > Database Access > seu usuário > Edit Password:** nova senha, **só com letras e números** (caracteres como
   `@ : / ? #` quebram a URL). **Trocar a senha no Atlas não basta:** a senha também está dentro da `MONGO_URL`, e ela precisa ser
   atualizada **nos dois lugares onde existe**: (a) no **Render > Environment > `MONGO_URL`** e (b) no seu `.env.render`
   e/ou `backend\.env` locais. Se esquecer o Render, o servidor falha ao subir com `bad auth : authentication failed`.
   Veja a tabela "Quando você troca um segredo" logo abaixo.
3. **Google Cloud > seu cliente OAuth > criar novo segredo** e desativar o antigo. Atualize `GOOGLE_CLIENT_SECRET`.

### Quando você troca um segredo, onde mais precisa trocar

Um segredo costuma viver em **mais de um lugar**. Depois de trocar, atualize todos e **republique o Render** (*Save and deploy*).

| Você trocou... | Atualize também... |
|---|---|
| Senha do usuário do **MongoDB Atlas** | `MONGO_URL` no **Render** e nos seus `.env` locais (a senha vai dentro da URL) |
| Segredo do cliente **Google** | `GOOGLE_CLIENT_SECRET` no **Render** e no `backend\.env` local |
| Chave secreta do **Stripe** (`sk_test_`) | `STRIPE_API_KEY` no **Render** e no `backend\.env` local |
| Chave publicável do Stripe (`pk_test_`) | `EXPO_PUBLIC_STRIPE_PUBLISHABLE_KEY` no `frontend\.env` (e **recompilar o app**) |
| Segredo de **webhook** do Stripe (`whsec_`) | `STRIPE_WEBHOOK_SECRET` / `STRIPE_CONNECT_WEBHOOK_SECRET` no **Render** (cada endpoint tem o seu) |
| `INTERNAL_SERVICE_TOKEN` | **Render** e `backend\.env` local |
| Segredo do app **Microsoft** | `MICROSOFT_CLIENT_SECRET` no **Render** |
| Senha SMTP (e-mail) | `SMTP_PASSWORD` no **Render** |

Para conferir antes de publicar: `python lancamento\verificar-config.py` e, no caso do banco, `python lancamento\verificar-mongo.py`.

## 2. Contas e chaves — onde pegar cada valor

### 2.1 MongoDB Atlas
- **`MONGO_URL`:** Atlas > Database > Connect > Drivers > copie a *connection string* e troque `<password>` pela senha real.
- **`DB_NAME`:** `holdbooked` (o nome que já usa).
- **Network Access:** o Render gratuito não tem IP fixo; é comum liberar `0.0.0.0/0` (qualquer origem) e proteger pela senha forte.

### 2.2 Stripe (modo teste) — passo a passo detalhado

**Antes de tudo:** entre em `dashboard.stripe.com` e confirme que está no **modo de teste** (aparece um aviso "Test mode"
no topo; algumas contas chamam isso de *sandbox*). Sem o aviso, você está no modo real: **não copie nada**. O modo de teste
e o modo real são mundos separados (chaves, webhooks e preços diferentes).

Você já usou o Stripe nos testes anteriores, então **muita coisa já existe**: olhe o que há antes de criar algo novo.

**A. Chaves de API (2 valores)**
1. Abra `https://dashboard.stripe.com/apikeys` (ou Developers > API keys).
2. **Publishable key** (`pk_test_...`) já aparece inteira: copie. **Secret key** (`sk_test_...`): clique em *Reveal*
   (se só mostrar na criação, use *Create secret key* e copie na hora).
3. Cole: `sk_test_...` no Render, em `STRIPE_API_KEY`; `pk_test_...` em `frontend\.env`, em `EXPO_PUBLIC_STRIPE_PUBLISHABLE_KEY`.
4. A chave `sk_` é secreta: nunca vai no `frontend\.env`.

**B. Webhook da plataforma** (é por onde o Stripe avisa o servidor: pagamento falhou, assinatura mudou etc.)
1. Abra `https://dashboard.stripe.com/webhooks` (no painel novo é a aba **Webhooks** do *Workbench*; o botão é *Create new
   destination* ou *Add endpoint*).
2. Veja se já existe um endpoint com a URL do ShowUp. Se existir, abra-o e só ajuste os eventos (item 4). Se não, crie.
3. Preencha: **Events on = Your account** (eventos da sua conta; **não** "connected accounts") · tipo **Webhook** · URL
   `https://showup-backend-s9y1.onrender.com/api/webhooks/stripe` · versão da API: a sugerida.
4. Marque estes **7 eventos** (use a busca): `payment_intent.payment_failed`, `payment_intent.canceled`,
   `payment_intent.succeeded`, `charge.dispute.created`, `customer.subscription.updated`,
   `customer.subscription.deleted`, `customer.subscription.trial_will_end`. Crie o destino.
5. Na página do endpoint, em **Signing secret**, clique em *Reveal* e copie o `whsec_...`. Cole no Render em `STRIPE_WEBHOOK_SECRET`.

**C. Webhook de Connect** (opcional: avisa quando a conta de um profissional é liberada; sem ele, a liberação leva até 10 min)
1. Repita B1 a B3, mas em **Events on** escolha **Connected accounts**. Mesma URL.
2. Evento: só `account.updated`.
3. *Reveal* e copie o `whsec_...` **deste segundo endpoint** (é **diferente** do primeiro). Cole em `STRIPE_CONNECT_WEBHOOK_SECRET`.

**D. Preços dos planos** (só se for testar assinatura e teste grátis)
1. Abra o *Product catalog* e o produto **Profissional**. Na seção de preços, copie o ID que começa com **`price_`**
   (não o `prod_`). Repita com o **Ultra**.
2. Se não existirem: *Add product* > nome > preço **recorrente, mensal, em BRL** > salvar > copie o `price_`.
3. Cole em `STRIPE_PRICE_ID_PROFISSIONAL` e `STRIPE_PRICE_ID_ULTRA`.

**E. Connect (o profissional receber)** — já está ativo na sua conta (você conectou uma conta de teste antes). No app:
*Configurações > Conectar Stripe*. No modo teste o formulário do Stripe costuma oferecer dados de teste ou pular etapas. É
normal a conta ficar "pendente" ou "em análise"; o app mostra o estado e o botão do painel. Para reservar sem esperar a
liberação, deixe `EXIGIR_RECEBIMENTO_ATIVO=0`.

**F. Conferir:** depois de publicar o backend, abra o endpoint em Webhooks e veja *Event deliveries*: as entregas devem
mostrar **200**. Erro **400** = o `whsec_` colado é de outro endpoint; **500** = `STRIPE_WEBHOOK_SECRET` vazio no Render.
No modo de teste o Stripe tenta reenviar só 3 vezes; depois, reenvie à mão pela mesma tela.

| O que você copiou | Onde cola |
|---|---|
| `sk_test_...` | Render: `STRIPE_API_KEY` |
| `pk_test_...` | `frontend\.env`: `EXPO_PUBLIC_STRIPE_PUBLISHABLE_KEY` |
| `whsec_...` do endpoint **Your account** | Render: `STRIPE_WEBHOOK_SECRET` |
| `whsec_...` do endpoint **Connected accounts** | Render: `STRIPE_CONNECT_WEBHOOK_SECRET` |
| `price_...` do Profissional / do Ultra | Render: `STRIPE_PRICE_ID_PROFISSIONAL` / `STRIPE_PRICE_ID_ULTRA` |

### 2.3 Google (login)
- **Google Cloud Console > APIs e serviços > Credenciais > ID do cliente OAuth (Web):**
  - `GOOGLE_WEB_CLIENT_ID` e `EXPO_PUBLIC_GOOGLE_WEB_CLIENT_ID` = o mesmo ID.
  - **URI de redirecionamento autorizada:** `https://showup-backend-s9y1.onrender.com/api/auth/google/callback`
    (idêntica ao `GOOGLE_OAUTH_REDIRECT_URI`, caractere por caractere).
- **Tela de consentimento (Google Auth Platform > Público/Audience):** enquanto o app está em **"Teste"**, só entram os
  e-mails da lista de **usuários de teste**. Adicione os Gmails de quem vai testar (até 100). Se aparecer "acesso bloqueado",
  é isto.

### 2.4 Microsoft (opcional) e e-mail (opcional)
- Siga o `LOGIN.md`: seção **B** (Microsoft Entra) e seção **A** (SMTP).
- Para **testar rápido sem SMTP**, rode o backend no seu computador com `$env:EMAIL_CODIGOS_NO_LOG="1"` (o código aparece no
  terminal). **Nunca** coloque isso no Render.

## 3. Render — passo a passo (20 min)

### 3.1 Conferir o serviço (só olhar; se já funciona, não mude)
Em `dashboard.render.com`, abra o serviço `showup-backend-s9y1` e, na aba **Settings**, compare:

| Campo | Valor esperado |
|---|---|
| Repositório / Branch | o repositório do ShowUp, branch `main` |
| Root Directory | `backend` |
| Build Command | `pip install -r requirements.txt` |
| Start Command | `uvicorn server:app --host 0.0.0.0 --port $PORT` |
| Auto-Deploy | *On Commit* (cada `git push` publica sozinho) |
| Health Check Path | `/api/` (opcional, mas recomendado) |

### 3.2 Montar o arquivo de variáveis no seu computador
Crie `.env.render` na raiz do projeto (o `.gitignore` já ignora `.env.*`), **sem aspas**, uma variável por linha:

```
MONGO_URL=mongodb+srv://USUARIO:SENHA@cluster0.xxxxx.mongodb.net/?retryWrites=true&w=majority
DB_NAME=holdbooked
STRIPE_API_KEY=sk_test_...
STRIPE_WEBHOOK_SECRET=whsec_...
STRIPE_CONNECT_WEBHOOK_SECRET=whsec_...
STRIPE_PRICE_ID_PROFISSIONAL=price_...
STRIPE_PRICE_ID_ULTRA=price_...
GOOGLE_WEB_CLIENT_ID=....apps.googleusercontent.com
GOOGLE_CLIENT_SECRET=GOCSPX-...
GOOGLE_OAUTH_REDIRECT_URI=https://showup-backend-s9y1.onrender.com/api/auth/google/callback
INTERNAL_SERVICE_TOKEN=(o gerado no passo 1)
AUTH_CODE_PEPPER=(o gerado no passo 1)
ALLOWED_ORIGINS=http://localhost:8081,https://showup-509120.web.app
PUBLIC_WEB_BASE_URL=https://showup-509120.web.app
EXIGIR_RECEBIMENTO_ATIVO=0
PLANOS_COMPRA_HABILITADA=1
```

**Confira o arquivo ANTES de mandar para o Render:**

```
python lancamento\verificar-config.py --backend .env.render --frontend frontend\.env
```

Corrija tudo que sair `[FALTA]` ou `[ERRO]`. **Não** inclua `TESTING` nem `EMAIL_CODIGOS_NO_LOG`.

**Teste o banco de verdade** (usuário e senha do Atlas) antes de ir para o Render. Instale o driver uma vez
(`pip install "pymongo[srv]"`) e rode:

```
python lancamento\verificar-mongo.py --arquivo .env.render --testar-escrita
```

Ele conecta no Atlas, diz em português por que falhou (senha recusada, sem permissão, rede bloqueada, endereço errado) e
nunca mostra a senha. O servidor precisa de **permissão de escrita** (ele cria índices ao subir), por isso o `--testar-escrita`.

### 3.3 Mandar as variáveis para o Render
1. No serviço, abra a aba **Environment**.
2. Se já existirem variáveis antigas: apague as que não estão na lista (principalmente `TESTING`) e **atualize** as que mudaram.
3. Clique em **Add from .env**, cole o conteúdo do `.env.render` (ou envie o arquivo) e confirme. Ou, uma a uma, em **+ Add Environment Variable**.
4. Confira na lista: nomes idênticos (maiúsculas importam), sem espaços sobrando.
5. **Salvar:** o Render oferece 3 opções: *Save, rebuild, and deploy* (refaz o build e publica), *Save and deploy* (republica o build atual com as variáveis novas) e *Save only* (só guarda; vale no próximo deploy).
   - Se **ainda não** fez o `git push` do código novo: use **Save only** e depois faça o push (assim publica uma vez só).
   - Se o código novo **já** está publicado: use **Save and deploy**.
6. **Apague o `.env.render` do seu computador** quando terminar.

### 3.4 Publicar o código
- `git push` na `main`: com *Auto-Deploy* ligado o deploy começa sozinho. Sem ele: **Manual Deploy > Deploy latest commit**.
- Acompanhe na aba **Logs** (ou **Events**). Deu certo quando o status vira **Live** e o log mostra o Uvicorn rodando.
- **Se o deploy falhar**, o Render mantém a versão anterior no ar. Leia o final do log (tabela do passo 7).

### 3.5 Confirmar
- Abra no navegador `https://showup-backend-s9y1.onrender.com/api/` → deve mostrar `{"service":"ShowUp API","status":"ok","gateway":"stripe"}`.
  Se `gateway` vier `mock`, a `STRIPE_API_KEY` está vazia.
- Abra `.../api/auth/metodos` → mostra quais logins estão ligados.
- Rode `python lancamento\verificar-producao.py --backend https://showup-backend-s9y1.onrender.com --site https://showup-509120.web.app`.

### 3.6 Voltar atrás
Aba **Events/Deploys** > escolha o deploy anterior que funcionava > **Rollback** (ou *Redeploy* dele).

### 3.6b Mensagens normais no log (não são erro)
- `"HEAD / HTTP/1.1" 404` e `"GET / HTTP/1.1" 404`: o próprio Render (e robôs) testam o endereço `/`, que não existe no ShowUp (as
  rotas começam em `/api`). É inofensivo. Para silenciar, configure **Health Check Path = `/api/`** em *Settings*.
- `Startup complete (gateway=stripe)` e `Scheduler started`: o servidor subiu com o Stripe real e os jobs agendados.

### 3.7 Plano gratuito
O serviço "dorme" depois de uns 15 minutos sem uso e a primeira chamada demora cerca de 1 minuto. O GitHub Actions de
*keep-alive* (a cada 5 min) ameniza. Antes de ter usuários reais, considere um plano pago.

## 4. Publicar o código

Siga o `DEPLOY.md`, passos 1 a 3 (repositório, Render, webhooks). Depois:

```
python lancamento\verificar-producao.py --backend https://showup-backend-s9y1.onrender.com --site https://showup-509120.web.app
```

Tudo `[OK]` (os `[ATENÇÃO]` sobre Microsoft/e-mail desligados são normais se você não configurou). O site: extraia o
`showup-agendar-agora.zip` em `firebase-hosting` e rode `firebase deploy --only hosting --project showup-509120`.

## 5. O app no celular ou emulador

Em `frontend\.env`:

```
EXPO_PUBLIC_BACKEND_URL=https://showup-backend-s9y1.onrender.com
EXPO_PUBLIC_STRIPE_PUBLISHABLE_KEY=pk_test_...
EXPO_PUBLIC_GOOGLE_WEB_CLIENT_ID=<o mesmo do servidor>
```

**Use a URL do Render, não `10.0.2.2`:** o retorno do login (Google e Microsoft) vai para o servidor do Render, então só
fecha o ciclo se o app falar com ele. Depois: `python lancamento\verificar-config.py` (sem argumentos, confere os dois
`.env` entre si) e `cd frontend` → `npx expo start -c` → `npx expo run:android`.

A primeira chamada ao Render pode levar ~1 minuto se ele estiver dormindo.

## 6. Roteiro de teste (marque conforme for passando)

**Cartões de teste do Stripe** (qualquer validade futura, qualquer CVC):

| Cartão | O que faz |
|---|---|
| `4242 4242 4242 4242` | aprovado |
| `4000 0000 0000 0002` | recusado |
| `4000 0000 0000 9995` | saldo insuficiente |
| `4000 0025 0000 3155` | pede autenticação 3D Secure |
| `4000 0000 0000 0341` | salva, mas a cobrança falha (serve para testar "cobrança do plano falhou") |

**A. Entrar**
- [ ] Google: entra, escolhe perfil, sai e entra de novo.
- [ ] Microsoft (se configurou): entra com uma conta Outlook/Hotmail.
- [ ] E-mail: *Continuar com e-mail → Criar conta* → código → entra. Sair e entrar com e-mail e senha. *Esqueci minha senha* → código → senha nova.
- [ ] Senha errada 5 vezes: bloqueia por 15 minutos e a mensagem é clara.

**B. Profissional**
- [ ] Cadastra serviço (valor e taxa de falta) e horários de atendimento.
- [ ] *Perfil → link de agendamento*: copia o link.
- [ ] *Configurações → Repasse automático*: **Conectar Stripe**. No modo teste o formulário do Stripe oferece dados de teste ou um
  botão para pular etapas. Volte ao app: o estado muda (pendente / em análise / conectada). O botão abre o painel do Stripe.

**C. Cliente**
- [ ] Abre o link no navegador: escolhe serviço → **data e horário em dropdown** → reserva com `4242…`.
- [ ] Reserva também pelo app, logado como cliente.
- [ ] Cartão recusado (`…0002`) mostra mensagem clara e não cria a reserva.

**D. Comparecimento e falta** (precisa esperar o horário passar: reserve um horário daqui a ~20 minutos)
- [ ] **Compareceu:** no Stripe (modo teste) aparece a cobrança do valor inteiro.
- [ ] **Faltou:** aparece só a taxa de falta. *Com o profissional conectado e liberado*, a taxa do ShowUp incide sobre esse valor (e não sobre o valor total do serviço).
- [ ] **Cancelar** antes do horário: a reserva no cartão é liberada.

**E. Planos** (com `PLANOS_COMPRA_HABILITADA=1`)
- [ ] *Perfil → Plano*: vê a conta dos últimos 30 dias e o botão **Testar 14 dias grátis**. Assina com `4242…`.
- [ ] Teste grátis só pode ser usado uma vez; **cancelar** volta ao Free.
- [ ] Para ver **fim do teste** e **cobrança que falha**, use *Billing → Test clocks* do Stripe (avança o tempo) e o cartão `…0341`; o app mostra o aviso e o profissional recebe a notificação.

**F. Conta e site**
- [ ] *Perfil → Excluir minha conta*, como cliente e como profissional (com plano ativo: a assinatura é cancelada).
- [ ] Termos e Privacidade abrem pelos links do app e pelo rodapé do link de agendamento.
- [ ] Stripe > Developers > Webhooks > seu endpoint: as entregas aparecem com status **200**.

## 7. Se algo não funcionar

| Sintoma | Causa mais provável |
|---|---|
| Google: `redirect_uri_mismatch` | A URI do Google Cloud difere do `GOOGLE_OAUTH_REDIRECT_URI` (compare caractere por caractere). |
| Google: "acesso bloqueado" / app não verificado | O Gmail não está na lista de usuários de teste (passo 2.3). |
| Tela de "application loading" no meio do login | O Render estava dormindo; tente de novo (o GitHub Actions de keep-alive ajuda). |
| Reserva recusada: "profissional ainda não habilitou os recebimentos" | `EXIGIR_RECEBIMENTO_ATIVO=1`. Para testar sem Stripe liberado, deixe `0`. |
| Cartão falha logo ao cadastrar | Chave publicável do app e chave secreta do servidor de modos diferentes (rode `verificar-config.py`). |
| Webhook com erro 400 no Stripe | `STRIPE_WEBHOOK_SECRET` de outro endpoint (cada endpoint tem o seu). |
| Webhook com erro 500 | `STRIPE_WEBHOOK_SECRET` vazio no Render. |
| O código por e-mail não chega | Veja o spam; confira o `SMTP_*`; olhe os logs do Render ("falha ao enviar e-mail"). |
| Log do Render: `GOOGLE_CLIENT_SECRET não configurado` (ou `GOOGLE_OAUTH_REDIRECT_URI`) | Variável ausente ou com nome errado: o servidor recusa subir. |
| Log do Render: `bad auth : authentication failed` (MongoDB) | O Atlas recusou o usuário/senha da `MONGO_URL` (a rede está certa). Crie ou edite o usuário em *Database Users* com uma senha só de letras e números e o papel *Read and write to any database*, atualize a `MONGO_URL` (sem os sinais `< >` e sem o texto `USUARIO:SENHA` de exemplo) e rode `verificar-mongo.py`. |
| Log do Render: erro de conexão com o MongoDB (`ServerSelectionTimeout`) | No Atlas, *Network Access* não libera o Render (use `0.0.0.0/0`) ou a senha/URL da `MONGO_URL` está errada. |
| Erro de CORS no navegador (link de agendamento) | `ALLOWED_ORIGINS` não inclui o endereço do site. |
| Servidor não sobe depois de mudar variáveis | `STRIPE_API_KEY` preenchida e inválida: o servidor recusa subir de propósito (veja os Logs). |
| Os botões de Microsoft/e-mail não aparecem | As variáveis `MICROSOFT_*` / `SMTP_*` estão incompletas; o verificador diz o que falta. |
| Link de agendamento ainda mostra a lista antiga | Site não publicado; rode o deploy e olhe o rodapé: deve mostrar `v2026.10.15`. |
