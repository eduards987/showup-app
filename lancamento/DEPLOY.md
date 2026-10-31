# Publicar tudo em produção — passo a passo

**Ordem obrigatória: repositório → backend (Render) → Stripe → site (Firebase) → conferir → app.**
O app novo precisa do backend novo; por isso o backend vai antes.

> **Este deploy continua em modo TESTE do Stripe**, a menos que você troque as chaves. Recomendo subir assim primeiro,
> conferir tudo, e só depois fazer a troca para as chaves reais (`CHAVES-PRODUCAO.md`).

> **Primeira vez montando tudo?** Comece pelo `TESTAR-TUDO.md`: ele lista onde pegar cada chave e traz o roteiro de teste.
> Antes de publicar, rode `python lancamento\verificar-config.py` para conferir seus arquivos de variáveis.

## Antes de começar (2 minutos)
- [ ] Os segredos foram trocados? (Google, MongoDB, token interno, webhook — ver `LANCAMENTO.md`, seção 1.)
- [ ] Você tem à mão: acesso ao GitHub, ao Render, ao Stripe Dashboard e o `firebase` instalado e logado.

## Passo 1 — Atualizar o repositório

> **O zip não traz mais** o `frontend/app.json`, o `package.json` nem os arquivos de versões (`package-lock.json`, `yarn.lock`): são os seus, e
> extrair o zip por cima os sobrescrevia (foi assim que o `owner` e o `projectId` do Expo voltaram para os antigos). As **páginas legais do site**
> (Termos, Privacidade, Exclusão) ainda vêm com os campos em branco: depois de extrair um zip, rode **`py lancamento\preencher-site.py --reaplicar`**
> (na primeira vez, preencha com `--responsavel`, `--email` e `--documento`/`--sem-documento`; os dados ficam guardados só no seu computador).
1. Extraia o `holdbooked-app-corrigido.zip` **por cima** da pasta do projeto (substituindo). Extrair não apaga arquivos
   antigos: se existirem, apague `frontend\cd` e `frontend\rmdir`.
2. No terminal, na pasta do projeto: `git status`. **Não pode aparecer nenhum arquivo `.env`** na lista. Se aparecer, pare.
3. `git add -A` → `git commit -m "Preparação para o lançamento"` → `git push`.
4. No GitHub, aba **Actions**: o workflow "Testes" deve ficar verde. Se ficar vermelho, não siga.

## Passo 2 — Backend no Render
1. Se o deploy automático estiver ligado, o `push` já começou. Se não: Render > seu serviço > **Manual Deploy > Deploy latest commit**.
2. Em **Environment**, confira (as marcadas "nova" são opcionais; sem elas o comportamento antigo continua):

   | Variável | Valor agora (teste) | Valor no lançamento |
   |---|---|---|
   | `STRIPE_API_KEY` | `sk_test_...` (a que já está) | `sk_live_...` |
   | `STRIPE_WEBHOOK_SECRET` | o que já está | o do endpoint de produção |
   | `STRIPE_CONNECT_WEBHOOK_SECRET` (nova) | vazio, ou o do endpoint de Connect | o do endpoint de Connect |
   | `EXIGIR_RECEBIMENTO_ATIVO` (nova) | `0` | `1` |
   | `PLANOS_COMPRA_HABILITADA` (nova) | `1` | `0` na 1ª versão do Google Play |
   | `MICROSOFT_CLIENT_ID`, `MICROSOFT_CLIENT_SECRET`, `MICROSOFT_OAUTH_REDIRECT_URI` (novas) | vazias (sem o botão Microsoft) | ver `LOGIN.md`, seção B |
   | `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASSWORD`, `SMTP_FROM` (novas) | vazias (sem cadastro por e-mail) | ver `LOGIN.md`, seção A — **só depois** de publicar a Política de Privacidade nova |
   | `PROXIES_NA_FRENTE` (nova, 30/10/2026) | não crie (vale `1`) | `1`; veja o aviso abaixo |
   | `LEMBRETE_CLIENTE_HORAS` (nova, 30/10/2026) | não crie (vale `24,2`) | horas antes do atendimento em que o cliente é lembrado; `0` desliga |

3. Espere o painel mostrar **Live**. Se o deploy falhar, abra os **Logs**: uma `STRIPE_API_KEY` preenchida e inválida
   derruba a subida de propósito (e o Render **mantém a versão anterior no ar**).
4. **Não há migração de banco.** Os campos novos são opcionais; as reservas antigas continuam funcionando.
   **Índice único das reservas (30/10/2026):** ao subir, o servidor cria o índice `uniq_vaga_ativa` (agora cobre também o
   Pix) e só então apaga o antigo `uniq_slot_ativo`. Nada a fazer. Se nos Logs aparecer "índice uniq_vaga_ativa não
   criado: há reservas ativas duplicadas", o antigo continua valendo: me chame para resolver as duplicadas.
5. **Limite de tentativas por IP (30/10/2026):** confira nos Logs, depois do primeiro acesso, a linha
   `limite por IP: conexão de ..., X-Forwarded-For com N IP(s); PROXIES_NA_FRENTE=1`. Com `N` igual a 1, está certo.
   Se `N` for 2 ou mais **em todo pedido** (há outro proxy, como Cloudflare, na frente do Render), crie
   `PROXIES_NA_FRENTE` com esse número. Errar para mais deixa o limite valendo para o IP do proxy (todos juntos);
   errar para menos deixa um atacante trocar o IP. Nunca use `0` no Render.

## Passo 3 — Stripe Dashboard (5 minutos)
1. **Reenviar os webhooks que falharam**: Developers > Webhooks > seu endpoint > filtre por falhas > **Resend**.
   (Havia um erro que fazia os eventos de assinatura e de conta conectada falharem; foi corrigido nesta versão.)
2. No endpoint da plataforma, adicione o evento **`customer.subscription.trial_will_end`**.
3. Crie o endpoint de **Connect** (mesma URL, "Escutar eventos em contas conectadas", evento `account.updated`) e copie o
   `whsec_` dele para `STRIPE_CONNECT_WEBHOOK_SECRET` no Render. Detalhes em `CHAVES-PRODUCAO.md`, seção 4.

## Passo 4 — Site no Firebase

> **Ordem importante com o link novo (`/p/nome`):** publique o **site primeiro** (este passo) e só depois o servidor/app. Se o app passar a mostrar
> o link `/p/nome` antes de o site ter o redirecionamento no ar, o cliente que abrir o link vê "página não encontrada".
> Antes de publicar, rode `py lancamento\preencher-site.py --reaplicar` (a página inicial e as páginas legais voltam com os campos em branco a cada zip novo).
> Depois confira com `verificar-producao.py ... --completo`: ele testa a página inicial, o `/p/...` e a página 404.

> ⚠️ O `firebase deploy` (sempre de dentro de `firebase-hosting`; a raiz não tem mais site) publica **a pasta `public` inteira**, inclusive os Termos, a Privacidade e a Exclusão de conta. Desde esta
> versão há uma **trava**: antes de publicar, o Firebase roda `verificar-antes-de-publicar.js` e **cancela o deploy** se alguma
> página ainda tiver campo em branco (`{{...}}`). Se ela cancelar, é só preencher (comando abaixo) e publicar de novo.
- **Quer só o dropdown de data e horário agora?** Extraia o `showup-agendar-agora.zip` dentro da pasta `firebase-hosting`
  e rode `cd firebase-hosting` e `firebase deploy --only hosting --project showup-509120`.
- **Quer o site completo (Termos, Privacidade, Exclusão de conta)?** Depois de ter o nome, o CPF/CNPJ e o e-mail:
  1. `python lancamento/preencher-site.py --responsavel "Seu Nome" --documento "CPF 000.000.000-00" --email "contato@..."`
  2. `python lancamento/preencher-site.py --verificar` (tem que dizer OK)
  3. `cd firebase-hosting` e `firebase deploy --only hosting --project showup-509120`

## Passo 5 — Conferir que subiu de verdade (2 minutos)
Na raiz do projeto (use `--completo` se publicou o site completo):

```
python lancamento/verificar-producao.py --backend https://showup-backend-s9y1.onrender.com --site https://showup-509120.web.app
```

A primeira chamada pode levar ~1 minuto (o Render gratuito "dorme"). Tudo deve sair `[OK]`. O que cada `[FALHOU]` significa:

| Mensagem | O que fazer |
|---|---|
| "Backend ainda está na versão ANTIGA" | O deploy do Render não terminou ou não pegou o último commit. |
| "gateway = mock" | `STRIPE_API_KEY` vazia no Render: o modo simulado não cobra ninguém. |
| "Webhook respondeu 500" | Falta `STRIPE_WEBHOOK_SECRET` no Render. |
| "versão ANTIGA (sem os dropdowns)" / "Versão ... não aparece" | O Firebase ainda serve a página antiga: refaça o deploy e abra em aba anônima. |
| "publicado COM campo em branco" | Rode `preencher-site.py` e publique de novo. |

## Passo 6 — Teste manual (5 minutos, com cartão de teste `4242 4242 4242 4242`)
1. Entre no app como profissional, cadastre um serviço e um horário de atendimento.
2. Abra o link de agendamento no celular: escolha o serviço, a data e o horário nos dropdowns, e reserve com o cartão de teste.
3. No app do profissional: marque **Compareceu** numa reserva e **Não compareceu** em outra.
4. Confira no Stripe (modo teste) a cobrança cheia e a cobrança só da taxa de falta.

## Passo 7 — O app
- **Testar no seu celular agora:** `npx expo run:android` (para usar o backend do Render, ponha a URL `https://` dele em `EXPO_PUBLIC_BACKEND_URL` no seu `.env`).
- **Google Play:** crie as variáveis no EAS (ambiente production), rode `eas build --profile production --platform android` e
  suba o `.aab` no teste fechado. Ver `LANCAMENTO.md`, seção 3, e `CHAVES-PRODUCAO.md`, seção 3.

## Se algo der errado
- **Render:** Deploys > escolha o deploy anterior > **Rollback**.
- **Firebase:** Console > Hosting > histórico de versões > **Reverter**.
- **App:** não há volta depois de publicado. Por isso o Passo 6 vem antes do Play.

## O que este deploy NÃO é (ainda)
Produção real. Faltam: chaves reais do Stripe, a conta da plataforma ativada, os dados do site, o teste fechado do Google Play
e a revisão jurídica. Está tudo no `LANCAMENTO.md`.
