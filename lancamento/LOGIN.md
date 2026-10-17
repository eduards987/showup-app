# Login: Google, Microsoft e e-mail + senha

O app oferece três jeitos de entrar. **Os botões aparecem sozinhos, conforme o servidor estiver configurado**
(o app consulta `GET /api/auth/metodos`): sem configuração, só o Google aparece, como antes. Nada quebra se você
não configurar nada.

| Jeito | Para quem | O que precisa configurar |
|---|---|---|
| Google | quem tem Gmail | já está pronto |
| **Microsoft** | quem tem Outlook, Hotmail ou Live | um app no Microsoft Entra (seção B) |
| **E-mail e senha** | qualquer e-mail (Yahoo, iCloud, trabalho...) | um serviço de envio de e-mail (seção A) |

> ⚠️ **Ordem importante:** publique **antes** o site com a Política de Privacidade e os Termos atualizados
> (`DEPLOY.md`, passo 4). A política antiga dizia que o ShowUp "nunca armazena senhas", e isso deixa de ser verdade
> assim que o cadastro por e-mail estiver ligado. Só depois configure as variáveis abaixo no Render.

## A. Cadastro por e-mail e senha

**Como funciona para o usuário:** toca em "Continuar com e-mail" → "Criar conta" (nome, e-mail, senha) → recebe um
código de 6 dígitos no e-mail → digita → entra. A conta **só é criada depois do código**. Quem esquece a senha pede um
código novo no próprio app.

**1. Escolha um serviço de envio de e-mail (SMTP).** Qualquer um que ofereça SMTP serve: Brevo, Amazon SES, SendGrid,
Mailgun, Resend... Vários têm plano gratuito com limite diário; confira o plano atual. Você vai precisar de: servidor,
porta, usuário e senha SMTP.

**2. Remetente.** Use um endereço de um **domínio seu** (ex.: `nao-responda@seudominio.com.br`) e peça ao serviço para
configurar a autenticação do domínio (SPF/DKIM — eles mostram os registros para você colocar no DNS). Enviar "como
Gmail" por outro serviço costuma cair no spam ou ser recusado. Se você ainda não tem domínio, vale registrar um: ele
também serve para o e-mail de contato dos Termos.

**3. No Render > Environment**, crie:

| Variável | Exemplo |
|---|---|
| `SMTP_HOST` | `smtp-relay.brevo.com` |
| `SMTP_PORT` | `587` (padrão; com `SMTP_SSL=1` use `465`) |
| `SMTP_USER` | o usuário SMTP do serviço |
| `SMTP_PASSWORD` | a senha/chave SMTP do serviço |
| `SMTP_FROM` | `ShowUp <nao-responda@seudominio.com.br>` |

**4. Teste.** Depois do deploy: `python lancamento/verificar-producao.py ...` deve mostrar "e-mail e senha" entre os
logins ativos. No app: *Continuar com e-mail → Criar conta* com um e-mail seu. Se o código não chegar, olhe o spam e
os logs do Render ("falha ao enviar e-mail").

**Só para desenvolvimento:** `EMAIL_CODIGOS_NO_LOG=1` imprime os códigos no log em vez de enviar. **Nunca em produção**
(quem lê o log consegue entrar em qualquer conta).

**O que já está protegido no servidor:** senha guardada só como hash (scrypt); código de uso único que vale 10 minutos e
só aceita 5 tentativas (e só o hash dele é guardado); espera de 60 s entre pedidos; bloqueio de 15 minutos depois de 5
senhas erradas; a resposta não revela se um e-mail tem conta; trocar a senha desconecta todos os aparelhos.

## B. Login com Microsoft (Outlook, Hotmail, Live)

Aceita **só contas pessoais** Microsoft, de propósito (nas contas de trabalho/escola o e-mail pode ser definido pelo
administrador do diretório, o que permitiria tomar contas de outras pessoas).

Os nomes dos menus mudam de tempos em tempos; o caminho geral é este:

1. Entre em `https://entra.microsoft.com` (ou `portal.azure.com`) com a sua conta Microsoft. Registrar um app exige um
   diretório do Microsoft Entra; se você ainda não tem, o cadastro gratuito do Azure cria um (pode pedir um cartão só para
   verificar a identidade).
2. **Identidade > Aplicativos > Registros de aplicativo > Novo registro.**
3. Nome: `ShowUp`. Tipos de conta com suporte: **"Contas Microsoft pessoais"** (ou a opção que inclui contas pessoais e
   organizacionais — o servidor recusa as organizacionais mesmo assim).
4. **URI de redirecionamento:** plataforma **Web**, valor exato:
   `https://showup-backend-s9y1.onrender.com/api/auth/microsoft/callback`
5. Registrar. Na tela do app, copie o **ID do aplicativo (cliente)**.
6. **Certificados e segredos > Novo segredo do cliente.** Copie o **Valor** na hora (ele só aparece uma vez; não é o "ID
   do segredo"). Ele **expira** (no máximo 24 meses): marque no calendário para renovar, senão o login Microsoft para.
7. Em **Identidade visual**, preencha os links dos Termos (`/termos`) e da Política (`/privacidade`) do site.
8. **No Render > Environment**, crie:

| Variável | Valor |
|---|---|
| `MICROSOFT_CLIENT_ID` | o ID do aplicativo (cliente) |
| `MICROSOFT_CLIENT_SECRET` | o **Valor** do segredo |
| `MICROSOFT_OAUTH_REDIRECT_URI` | **exatamente** a mesma URL do passo 4 |

9. **Teste:** o botão "Continuar com Microsoft" aparece no app; entre com uma conta Outlook.

**Se der erro:** `redirect_uri` não confere → compare a URL do Azure e a do Render caractere por caractere;
`invalid_client` → você copiou o "ID do segredo" em vez do "Valor"; "O pedido de login expirou" → demorou mais de 10
minutos entre abrir e concluir; "A conta Microsoft não informou um e-mail" → a conta não tem e-mail associado.

## C. Para o revisor do Google Play

Crie a conta de revisão **pelo próprio app, com e-mail e senha** (sem verificação em duas etapas, sem depender de
Google). Informe o e-mail e a senha em *Acesso ao app* no Play Console. Detalhes em `PLAY-STORE.md`.

## D. iOS (no futuro)

Quando for publicar na App Store, confira a regra 4.8 da Apple sobre oferecer login de terceiros: ela pode exigir uma
opção equivalente (como "Entrar com a Apple").
