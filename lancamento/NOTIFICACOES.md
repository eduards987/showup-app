# Notificações para o profissional

## O que o profissional recebe

| Aviso | Quando | Texto de exemplo |
|---|---|---|
| **Novo agendamento** | Logo depois da reserva (cartão, pelo app ou pelo link). No Pix, quando o pagamento é confirmado. | "Maria Souza agendou Personal Trainer para amanhã às 09:00." |
| **Próximo atendimento** | Antes do horário (60 minutos por padrão). | "Em 55 min, às 10:00: Maria Souza — Personal Trainer." |
| **Confirme o atendimento** | Quando o horário termina e falta marcar se o cliente compareceu. | "Maria Souza tinha horário de Personal Trainer. Compareceu?" |
| **Última chance** | Perto de a reserva expirar sem resposta. | "O horário de Maria Souza vai liberar sem cobrança em breve." |

Regras: cada aviso sai **uma única vez** por agendamento; o horário aparece no **fuso do profissional** ("hoje às", "amanhã às");
o lembrete só vale para reservas confirmadas (cartão autorizado ou Pix pago), nunca para canceladas; uma reserva feita **dentro**
da janela do lembrete não recebe o lembrete repetido (o "Novo agendamento" acabou de dizer o horário). Ao tocar na notificação, o app
abre o agendamento.

Para mudar a antecedência do lembrete, crie no Render a variável `LEMBRETE_PROFISSIONAL_MIN` (minutos; `0` desliga). Padrão: 60.

## Fazer na ordem certa (checklist)

Faça **nesta ordem** e só passe para o próximo quando o anterior estiver pronto:

1. **Servidor com o código novo.** `git push` e espere o Render ficar **Live**. Confirme abrindo no navegador
   `https://showup-backend-s9y1.onrender.com/api/me/notificacoes/teste`: deve aparecer **"Method Not Allowed"** (a rota existe).
   Se aparecer **"Not Found"**, o servidor ainda está com a versão antiga e **nenhuma** notificação nova vai sair.
2. **Chave do Firebase no Expo** (seção abaixo), enviada ao **mesmo projeto Expo** que está no `app.json` (`owner` e `extra.eas.projectId`).
3. **App com o código novo** no celular: `cd frontend` > `npx expo start -c` e abrir o app. Se você trocou de projeto Expo, só reiniciar o app
   já faz ele registrar o aparelho de novo.
4. Num **celular de verdade**, entrar como **profissional** e aceitar o pedido de permissão de notificações.
5. **Perfil > NOTIFICAÇÕES > Enviar notificação de teste.** O botão percorre as etapas e mostra ✓ ou ✗ em cada uma.
6. Só depois: reservar pelo link e ver o "Novo agendamento".

## O que cada ✗ do botão de teste significa

| Etapa que falhou | Causa | O que fazer |
|---|---|---|
| **Celular de verdade** | Está num emulador (ou no Expo Go). | Use o celular físico com o app de desenvolvimento. |
| **Permissão de notificações** | O Android bloqueou. Depois de negar duas vezes, ele não pergunta mais. | Configurações do celular > Aplicativos > ShowUp > Notificações > permitir. |
| **Código do aparelho gerado** | Mensagem "Default FirebaseApp is not initialized" / "googleServicesFile": o app instalado foi compilado **sem** o `google-services.json` (a pasta `frontend\android` é de antes da configuração). Também pode faltar o `projectId` ou a internet do celular. | Na pasta `frontend`: `npx expo prebuild --platform android --clean` e depois `npx expo run:android`. **Só rodar o `run:android` não basta:** ele reaproveita a pasta `android` antiga. |
| **Aparelho registrado no servidor** | Sessão expirada ou servidor fora do ar. | Saia e entre de novo; confira `/api/` no navegador. |
| **Servidor enviou o aviso à Expo** | Se disser que o servidor "não tem os avisos": é o passo 1 do checklist. Outras mensagens: a Expo recusou o pedido. | Publique o código novo (`git push`) e espere o Render ficar Live. |
| **Entrega confirmada pelo Firebase** | O Firebase não aceitou: chave do Expo faltando/errada (`InvalidCredentials`) ou de outro projeto (`MismatchSenderId`). | Reenvie a chave (seção abaixo), do projeto `showup-509120`, ao projeto Expo do `app.json`. |
| Tudo ✓ mas **nada aparece** no celular | O Samsung está segurando o aviso, ou o canal de notificações está silenciado. | Configurações do celular > Aplicativos > ShowUp > Bateria > "Sem restrições"; Notificações > confira que "default" não está silenciado. |

## Caso: etapas 1 a 4 ✓ e "Servidor enviou o aviso à Expo" ✗ ("falta a chave do Firebase")
O app gerou o código e o servidor o registrou; a Expo diz que **não tem a chave do Firebase para o projeto desse código**. Ou seja, a chave está em
**outro projeto Expo** (ou não está em nenhum). Passo a passo:

1. Veja qual projeto o app usa: na etapa "Código do aparelho gerado" aparece `projeto xxxxxxxx… (dono: …)` (versão nova do app). No computador:
   ```
   cd C:\Users\Edu\Downloads\ShowUp\frontend
   Select-String -Path app.json -Pattern '"owner"|"projectId"'
   ```
2. Veja onde está a chave: `npx eas-cli credentials -p android` > **production** > **Google Service Account** > **Manage your Google Service Account Key
   for Push Notifications (FCM V1)**. **Antes de escolher qualquer opção**, olhe o resumo que ele mostra:
   - "Push Notifications (FCM V1)" com `Project ID showup-509120` e `Client Email firebase-adminsdk-fbsvc@showup-509120…`: a chave está atribuída ao projeto do
     `app.json`. Então compare o ID do passo 1 com o projeto no `expo.dev` (conta do `owner` > projeto `holdbooked-app` > Project ID).
   - **"None assigned yet"**: a chave NÃO está nesse projeto. Escolha **Set up a Google Service Account Key for Push Notifications (FCM V1)** >
     **Upload a new service account key** e informe o `.json` de novo.
3. Se mudou algo: feche o app por completo, rode `npx expo start -c` e abra de novo. Em alguns casos a Expo leva alguns minutos para enxergar uma chave nova.
4. Toque em **Enviar notificação de teste** outra vez.

## Caso: o app voltou a usar o projeto Expo antigo (`owner: educerqueira`, `projectId: e403a3c9…`)
Se você trocou o projeto Expo e depois **extraiu um zip antigo por cima**, o `app.json` pode ter voltado ao valor antigo (os zips novos já não o trazem).
Sintoma: o `Select-String -Path app.json -Pattern '"owner"|"projectId"'` mostra o dono/ID antigos e a Expo recusa o envio ("falta a chave do Firebase"),
porque a chave está no projeto **novo**. Para corrigir:
**Jeito mais simples (o próprio Expo preenche o `owner` e o `projectId`):**
1. Descubra qual conta tem o projeto: abra no navegador `https://expo.dev/accounts/octalabs/projects/holdbooked-app` e
   `https://expo.dev/accounts/octa-labs/projects/holdbooked-app`. A que abrir é a dona (a outra dá "não encontrado"). O **owner** é o nome dessa conta na URL.
2. Na pasta `frontend`, aponte o `app.json` para essa conta e tire só o ID (troque `OWNER`):
   ```
   node -e "const f='app.json';const j=JSON.parse(require('fs').readFileSync(f,'utf8'));j.expo.owner='OWNER';delete j.expo.extra.eas.projectId;require('fs').writeFileSync(f,JSON.stringify(j,null,2)+'\n')"
   npx eas-cli init
   ```
3. Se ele disser **"Existing EAS project found for @OWNER/holdbooked-app … Configure this project?"**, responda **sim**: ele grava o `owner` e o `projectId`
   certos no `app.json`. Se ele perguntar **"Would you like to create a project…?"**, essa conta NÃO tem o projeto: responda **não**, e repita com a outra conta.

**Jeito manual** (copiando o ID):

1. Em `expo.dev`, entre na conta que tem o projeto novo, abra `holdbooked-app` e copie o **Project ID** (a URL mostra a conta: `expo.dev/accounts/<owner>/projects/holdbooked-app`).
2. Na pasta `frontend`, troque `SEU_OWNER` e `PROJECT_ID`:
   ```
   node -e "const f='app.json';const j=JSON.parse(require('fs').readFileSync(f,'utf8'));j.expo.owner='SEU_OWNER';j.expo.extra.eas.projectId='PROJECT_ID';require('fs').writeFileSync(f,JSON.stringify(j,null,2)+'\n')"
   ```
3. Confira de novo o `Select-String` do passo 1, feche o app, `npx expo start -c`, abra o app e toque em **Enviar notificação de teste** (isso gera um código novo para o projeto novo).

## Testar direto pela Expo (separa o app/Firebase do nosso servidor)
Depois do botão de teste, aparece **"Copiar o código do aparelho"**. Toque nele, abra `https://expo.dev/notifications` no computador, cole em
**Expo push token**, escreva um título e uma mensagem e clique em **Send a Notification**.
- **Chegou:** o app, o Firebase e a chave estão certos. O problema, se houver, está no nosso servidor (veja os logs abaixo).
- **Não chegou:** o problema está no app, na chave do Firebase ou nas permissões do celular (veja a tabela acima).

## O que procurar nos logs do Render
Cada tentativa de aviso deixa uma linha. Em **Logs**, busque por `push`:
- `push 'Novo agendamento' enviado a user_… (ticket …)`: o servidor mandou à Expo.
- `push '…' NÃO enviado: user_… não tem aparelho registrado`: o profissional **nunca registrou o aparelho** (abrir o app, permitir notificações).
- `push '…' recusado pela Expo … InvalidCredentials`: falta a chave do Firebase no Expo.
- `novo agendamento agd_…: aviso ao profissional -> enviado`: o aviso de reserva foi disparado.
Se uma reserva é feita e **nenhuma** dessas linhas aparece, o servidor ainda não tem o código novo.

### Caso real: `recusado pela Expo … InvalidCredentials` ("Unable to retrieve the FCM server key for the recipient's app")
Quer dizer que **o servidor está certo**: a reserva foi gravada, o aviso foi disparado, existe um aparelho registrado e a Expo recebeu o pedido.
Mas a Expo **não tem a chave do Firebase para o projeto ao qual aquele código de aparelho pertence**. Há duas causas, e dá para separá-las:

1. **O código de aparelho guardado no servidor é antigo** (foi gerado por uma versão anterior do app ou por outro projeto Expo, que não tem a chave).
   Sinal: no log do Render **não** aparece `PUT /api/me/push-token … 200` quando você abre o app como profissional.
   Correção: entre no app como **profissional** e toque em *Enviar notificação de teste*. Isso gera um código novo e o registra
   (aparece `PUT /api/me/push-token … 200` no log).
2. **A chave foi enviada a outro projeto Expo** que não é o do `app.json`. O `npx eas-cli credentials -p android` (rodado na pasta `frontend`) sempre
   usa o projeto do `app.json`: no resumo, em "Push Notifications (FCM V1)", a chave tem que aparecer **atribuída**. Se aparecer "None assigned yet",
   envie a chave de novo (passo 2 da configuração).

Os avisos de reservas anteriores a essa correção **não são reenviados**: só vale para os agendamentos novos.


## Configuração obrigatória no Android (uma vez só): a chave do Firebase no Expo

Sem isso o Expo **aceita** o envio mas **não consegue entregar** no Android, e nenhuma notificação chega. O `google-services.json` do app
sozinho não basta: o Expo precisa de uma **chave de serviço do Firebase (FCM V1)** guardada no projeto dele.

**1. Gerar a chave no Firebase**
1. `console.firebase.google.com` > projeto do ShowUp (o mesmo do `google-services.json`: `showup-509120`).
2. Engrenagem ao lado de "Visão geral do projeto" > **Configurações do projeto** > aba **Contas de serviço**.
3. **Gerar nova chave privada** > confirme. Baixa um arquivo `.json`.
4. Guarde o arquivo **fora da pasta do projeto** (ex.: `Documentos`). Ele é um segredo: não coloque no Git nem mande em conversa.
5. Na aba **Cloud Messaging**, confira que a "Firebase Cloud Messaging API (V1)" está **ativada**.

**2. Enviar a chave ao Expo**

*Pelo terminal (recomendado: não pede keystore):*
```
cd C:\Users\Edu\Downloads\ShowUp\frontend
npx eas-cli login
npx eas-cli credentials -p android
```
No menu, escolha na ordem: **production** > **Google Service Account** > **Manage your Google Service Account Key for Push
Notifications (FCM V1)** > **Set up a Google Service Account Key for Push Notifications (FCM V1)** > **Upload a new service account key**.
Quando ele pedir o arquivo, digite o caminho completo do `.json` que você baixou (ex.: `C:\Users\Edu\Documents\showup-firebase.json`).

*Pelo site (`expo.dev`): NÃO use.* O assistente "Add application identifier" **exige** um keystore ("You must upload a keystore file
(.jks/.p12)") e não deixa avançar sem ele. Esse arquivo serve para o EAS compilar o app na nuvem (Play Store), não para notificações. **Não crie
um keystore à mão** (nem use o de depuração do Android Studio) só para passar desse passo: use o terminal acima.

*Se o terminal também pedir keystore:* deixe o próprio EAS gerar um. Rode `npx eas-cli credentials -p android` > **production** > **Keystore**
(gerenciar o que o build precisa) > configurar um keystore novo > **gerar novo keystore** (os nomes podem variar um pouco). Ele fica guardado
no EAS e será o mesmo usado na compilação de produção. Depois repita o caminho do **Google Service Account** acima.

**Se o terminal responder `Entity Not Authorized` / "You don't have the required permissions":** a conta Expo em que você fez login
não tem acesso ao projeto do `app.json` (`extra.eas.projectId`). Descubra qual conta tem o projeto:
1. `npx eas-cli whoami` mostra o usuário (e as organizações) do login atual.
2. No navegador, em `expo.dev`, abra a lista de projetos de **cada conta/organização** que você tem (menu da conta, no canto superior).
   Procure `holdbooked-app` e compare o **Project ID** dele com o do `app.json`.
3. Projeto está em **outra conta sua**: `npx eas-cli logout`, depois `npx eas-cli login` entrando nessa conta (use uma janela anônima do
   navegador para não reaproveitar a conta errada).
   **Atenção:** o `npx eas-cli login` abre o navegador e entra na conta que estiver aberta lá. Para escolher a conta, copie o link que o terminal
   mostra ("If your browser doesn't automatically open, visit this link…") e abra numa **janela anônima** (Ctrl+Shift+N), entrando na conta certa.
   Confira com `npx eas-cli whoami`: o usuário precisa ser o mesmo do campo `owner` do `app.json`.
   Se você não tem mais acesso à conta do `owner`, mude o `owner` do `app.json` para a conta que você tem e rode `npx eas-cli init` (item 5).
4. Projeto está numa **organização** e você é só membro: peça ao dono para te dar o papel de *Developer* ou *Admin*.
5. Projeto **não existe** em nenhuma conta sua, ou você não tem mais acesso à conta do `owner`: crie um novo na conta em que você está logado.
   O `npx eas-cli init` **só cria** se o `app.json` não tiver `extra.eas.projectId` (senão responde "Project already linked"). Na pasta `frontend`:
   ```
   node -e "const f='app.json';const j=JSON.parse(require('fs').readFileSync(f,'utf8'));j.expo.owner='SEU_USUARIO_EXPO';delete j.expo.extra.eas.projectId;require('fs').writeFileSync(f,JSON.stringify(j,null,2)+'\n')"
   npx eas-cli init
   ```
   Troque `SEU_USUARIO_EXPO` pelo usuário que o `npx eas-cli whoami` mostra. O `init` pergunta se quer criar o projeto: responda sim (se ele
   oferecer mais de uma conta, escolha a mesma do `owner`). Ele grava o ID novo no `app.json`. Depois: `npx expo start -c` e abra o app (os tokens
   de notificação antigos deixam de valer, e o app registra o aparelho de novo sozinho).

A chave e o `google-services.json` do app precisam ser do **mesmo projeto do Firebase**, senão o Expo devolve `MismatchSenderId`.
Não precisa recompilar o app: a chave fica no servidor do Expo.

**3. Testar (1 minuto)**
No celular: **Perfil > NOTIFICAÇÕES > Enviar notificação de teste**. O app pede permissão, registra o aparelho, manda uma
notificação de verdade e diz o resultado:

| Mensagem no app | O que fazer |
|---|---|
| "Emuladores não recebem notificações" | Use um celular de verdade (no Android, push também não funciona no Expo Go: use o app de desenvolvimento que você já usa). |
| "As notificações estão bloqueadas…" | Configurações do celular > Aplicativos > ShowUp > Notificações > permitir. |
| "…sem a configuração do Firebase (google-services.json)…" | O app foi compilado sem o arquivo: confira `frontend/google-services.json` e rode `npx expo run:android` de novo. |
| "A Expo recusou o envio: falta a chave do Firebase (FCM V1)…" | Faça o passo 2 acima. |
| "A chave do Firebase… é de OUTRO projeto…" | Gere a chave (passo 1) no mesmo projeto do `google-services.json`. |
| "…aparelho não está mais registrado…" | Feche e abra o app (ele se registra de novo) e teste outra vez. |
| "Enviamos o teste, mas a Expo ainda não confirmou…" | Espere 1 ou 2 minutos. Se não chegar, veja a tabela acima de novo. |
| "Notificação enviada." e **chegou** | Está tudo certo. |

## Teste de ponta a ponta
1. **Novo agendamento:** faça uma reserva pelo link (cartão `4242 4242 4242 4242`). Em segundos o profissional recebe "Novo agendamento".
2. **Próximo atendimento:** reserve um horário daqui a ~90 minutos (reservas feitas dentro de 60 minutos do horário não ganham lembrete extra).
   Quando faltar 1 hora o aviso sai no próximo ciclo (o servidor verifica a cada 5 minutos).
3. **Confirmação:** depois do horário terminar, "Confirme o atendimento".

## Cuidados
- **Render gratuito dorme.** Os avisos de lembrete e de confirmação dependem do servidor acordado. O GitHub Actions de *keep-alive*
  (a cada 5 minutos) cuida disso; antes de ter usuários reais, considere um plano pago.
- **Samsung e outras marcas** podem atrasar avisos para apps "dormindo". Em *Configurações > Aplicativos > ShowUp > Bateria*, escolha
  "Sem restrições".
- **Um aparelho por profissional:** o último aparelho em que ele entrou é o que recebe. Clientes não recebem notificações.
- A falha em mandar um aviso **nunca** derruba a reserva: o aviso é enviado depois que a resposta já foi dada.

## Recompilar o app com o Firebase (quando aparece "Default FirebaseApp is not initialized")
O `app.json` já aponta para o `google-services.json`, mas a pasta `frontend\android` (gerada, e ignorada pelo Git) pode ter sido criada **antes** disso.
O `npx expo run:android` não a gera de novo. Passo a passo:

1. Pare o Metro (**Ctrl+C**).
2. Conecte o celular **por cabo USB** e aceite "Permitir depuração USB" (a depuração por Wi-Fi costuma cair).
   Confira: `& "$env:LOCALAPPDATA\Android\Sdk\platform-tools\adb.exe" devices -l` deve listar o aparelho como `device`.
3. `cd C:\Users\Edu\Downloads\ShowUp\frontend`
4. `npx expo prebuild --platform android --clean` (apaga e recria a pasta `android` a partir do `app.json`).
5. Confira: `Test-Path android\app\google-services.json` deve dar **True**, e
   `Select-String -Path android\build.gradle,android\app\build.gradle -Pattern "google-services"` deve mostrar linhas.
6. `npx expo run:android` (compila e instala; na primeira vez leva alguns minutos).
7. Abra o app, entre como profissional e use o botão de teste de novo.
