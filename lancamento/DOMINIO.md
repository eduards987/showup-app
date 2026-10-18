# Domínio próprio para o site do ShowUp

Hoje o site é `showup-509120.web.app` (o endereço de teste do Firebase, com o número do projeto no nome). Um domínio próprio
(ex.: `showup.com.br`) passa mais confiança ao cliente e ao profissional, vai na ficha da Google Play e nos e-mails.

> **Faça ANTES de publicar o app na Google Play.** O endereço do site fica na ficha da loja, nos Termos e na Privacidade e dentro do app.
> Trocar depois dá mais trabalho e obriga a publicar uma versão nova do app.

O link de agendamento já ficou curto e legível: `https://SEU-DOMINIO/p/eduardo-cerqueira`. Os links antigos
(`/agendar?prof=user_...`) continuam funcionando.

## 1. Escolher e registrar o domínio
- Prefira um nome **curto e fácil de ditar**, terminado em **.com.br** (o público é brasileiro). Confira se está livre em `registro.br`.
- "ShowUp" é um nome muito comum: antes de investir na marca, **pesquise no INPI** (busca de marcas, `busca.inpi.gov.br`) se já existe registro
  parecido na sua área. Isso não é aconselhamento jurídico: em caso de dúvida, consulte um advogado.
- Registro de `.com.br`: pelo `registro.br`, com CPF ou CNPJ, e custa algumas dezenas de reais por ano. Outros registradores servem para `.com`.
- Use um endereço **sem hífen e sem números**, para o profissional falar por telefone sem confusão.

## 2. Ligar o domínio ao Firebase Hosting
No Firebase Console (`console.firebase.google.com`), projeto `showup-509120`:
1. Menu **Hosting** > **Add custom domain** (Adicionar domínio personalizado).
2. Digite o domínio **sem** `www` (ex.: `showup.com.br`). Marque a opção de redirecionar o `www` para ele, se aparecer.
3. O Firebase mostra um registro **TXT** para provar que o domínio é seu. No painel do seu registrador (no `registro.br`: *Editar zona DNS*
   / *Configurar DNS*), crie esse registro **exatamente como mostrado** (tipo TXT, nome `@` ou o próprio domínio, valor copiado do Firebase).
   Mantenha esse registro **sempre** lá.
4. Espere alguns minutos (pode levar até 24 h) e clique em **Verify**.
5. O Firebase passa a mostrar os registros **A** (e às vezes **AAAA**) para colocar no DNS. Crie-os. **Apague registros A/AAAA/CNAME antigos**
   que o registrador criou (página "estacionada"), senão o certificado de segurança (HTTPS) não é emitido.
6. Espere o status mudar de *Pending* para **Connected**. O certificado HTTPS é emitido sozinho (pode levar até algumas horas).
7. Repita para `www.SEU-DOMINIO`, escolhendo redirecionar para o domínio principal.

## 3. Trocar o endereço em todo o projeto (um comando)
Só depois que o domínio estiver **Connected** e abrir com HTTPS no navegador:
```
py lancamento\trocar-dominio.py --para SEU-DOMINIO
```
Ele troca o endereço nas páginas do site, no sitemap, no app e no servidor, e mostra o que sobra para você ajustar à mão.
Use `--simular` para ver o que mudaria sem alterar nada.

## 4. Ajustes fora do código (todos obrigatórios)
| Onde | O quê |
|---|---|
| **Render > Environment** | `PUBLIC_WEB_BASE_URL=https://SEU-DOMINIO` |
| **Render > Environment** | `ALLOWED_ORIGINS`: **acrescente** `https://SEU-DOMINIO` e mantenha a lista atual. **Se esquecer, a página de agendamento para de funcionar** (o servidor recusa o novo endereço). |
| **`frontend\.env`** | `EXPO_PUBLIC_WEB_URL=https://SEU-DOMINIO` e depois `npx expo start -c` |
| **Firebase** | `cd firebase-hosting` e `firebase deploy --only hosting --project showup-509120` |
| **Git** | commit e push (o Render atualiza o servidor) |
| **Google Play** | URLs da Política de Privacidade e da exclusão de conta na ficha da loja |

## 5. Conferir
```
py lancamento\verificar-producao.py --backend https://showup-backend-s9y1.onrender.com --site https://SEU-DOMINIO --completo
```
Tudo `[OK]` (os avisos de Microsoft e e-mail desligados são normais). Abra também, no celular, um link `https://SEU-DOMINIO/p/...` de um profissional.

## 6. E-mail com o domínio (recomendado)
Com o domínio, use `contato@SEU-DOMINIO` como e-mail público (Termos, Privacidade, página inicial e Google Play):
1. Crie o e-mail no seu provedor (ex.: encaminhamento gratuito do Cloudflare, Zoho Mail ou Google Workspace).
2. Atualize o site: `py lancamento\preencher-site.py --responsavel "..." --email "contato@SEU-DOMINIO" --sem-documento` (ou `--documento "..."`) e publique de novo.
3. Para o **envio** dos códigos de login por e-mail (SMTP), o provedor de envio pede registros SPF/DKIM no DNS deste domínio: veja `LOGIN.md`.

## O que NÃO precisa mudar
- O endereço do servidor (`showup-backend-s9y1.onrender.com`) continua o mesmo: o cliente nunca o vê.
- Login com o Google, webhooks do Stripe e o `EXPO_PUBLIC_BACKEND_URL` não dependem do domínio do site.
- O endereço antigo `showup-509120.web.app` continua funcionando: links já enviados por WhatsApp não quebram.
