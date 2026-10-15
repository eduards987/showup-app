# Ficha do Google Play — textos e respostas prontos

Tudo aqui é um **ponto de partida**: o Play Console muda os formulários de tempos em tempos, então confira
cada pergunta na tela antes de enviar. Troque o que estiver entre `[colchetes]`.

## Informações do app

| Campo | Valor |
|---|---|
| Nome (máx. 30) | `ShowUp` |
| Categoria | Negócios *(alternativa: Produtividade)* |
| E-mail de contato | `[o mesmo e-mail que você pôs nos Termos]` |
| Site | `https://showup-509120.web.app` |
| Política de privacidade | `https://showup-509120.web.app/privacidade` |
| Exclusão de conta (URL) | `https://showup-509120.web.app/excluir-conta` |
| Anúncios | Não |
| Público-alvo | 18 anos ou mais |
| Pacote | `com.educerqueira.showup` |

## Descrição curta (máx. 80 caracteres)

```
Agenda com proteção contra faltas: o cartão do cliente garante o seu horário.
```

## Descrição completa (máx. 4000 caracteres)

```
O ShowUp é a agenda de quem trabalha por hora marcada — personal trainers, nutricionistas, esteticistas, terapeutas e outros profissionais autônomos — com uma diferença: o cliente que reserva deixa o cartão como garantia, e a falta deixa de sair do seu bolso.

COMO FUNCIONA
• Você cadastra seus serviços, valores e horários de atendimento.
• Envia o seu link de agendamento pelo WhatsApp. O cliente escolhe a data e o horário, sem precisar instalar nada.
• Ao reservar, o valor do serviço fica reservado no cartão do cliente. Não é uma cobrança imediata.
• Depois do atendimento, você responde com um toque: o cliente compareceu ou faltou.
• Compareceu: o valor do serviço é cobrado. Faltou: é cobrada apenas a taxa de falta que você definiu. Se você não responder no prazo, a reserva é liberada e ninguém é cobrado de forma errada.

PARA O PROFISSIONAL
• Link de agendamento próprio, com horários que respeitam a duração de cada serviço.
• Notificações pedindo a confirmação de presença, com aviso de última chance.
• Recebimento direto na sua conta pelo Stripe, com a taxa do ShowUp descontada automaticamente.
• Você acompanha agenda, reservas e o que o app já recuperou em faltas.

PARA O CLIENTE
• Agende em poucos toques, direto pelo link do seu profissional.
• Você só paga o serviço depois do atendimento, e é liberado se o profissional não confirmar a sua falta.
• Seu cartão é processado pelo Stripe; o ShowUp não guarda o número completo.

SEUS DADOS
Você pode excluir a sua conta e os seus dados pessoais a qualquer momento, dentro do app (Perfil > Excluir minha conta).

O ShowUp não presta os serviços agendados: eles são combinados diretamente entre profissional e cliente.
```

## Acesso ao app (instruções para o revisor do Google)

O login é só com Google, e o revisor precisa conseguir entrar:

1. Crie **uma conta Google dedicada** à revisão (ex.: `showup.revisao@gmail.com`), **sem verificação em duas etapas** — o revisor não consegue receber o código.
2. Em *Acesso ao app*, escolha "todas ou algumas funcionalidades têm restrições" e informe:
   > Login apenas com conta Google. Use: e-mail `[...]` / senha `[...]`. Ao entrar, escolha o perfil "Profissional" para cadastrar serviços e ver a agenda, ou "Cliente" para reservar. O pagamento usa o modo de teste do Stripe: cartão 4242 4242 4242 4242, qualquer validade futura e CVC.
3. Essa conta deve ter um serviço e horários já cadastrados, para o revisor conseguir fazer uma reserva de ponta a ponta.

*(Se o build enviado ao Google já estiver em modo de produção do Stripe, troque a frase do cartão: o revisor não deve fazer cobranças reais.)*

## Segurança dos dados (rascunho das respostas)

Baseado no que o app coleta hoje (conferir com a política de privacidade). Dados processados pelo Stripe **em seu nome**
costumam não contar como "compartilhamento" no Play, mas **declare-os como coletados**.

| Categoria do Play | Coleta? | Detalhe | Finalidade |
|---|---|---|---|
| Informações pessoais: nome | Sim | Vem do login com Google | Funcionalidade do app; gerenciamento de conta |
| Informações pessoais: e-mail | Sim | Vem do login com Google | Funcionalidade do app; gerenciamento de conta |
| Informações pessoais: ID de usuário | Sim | ID interno da conta | Funcionalidade do app; gerenciamento de conta |
| Fotos | Sim | Foto de perfil do Google (guardamos o link) | Funcionalidade do app |
| Informações financeiras: informações de pagamento | Sim | Cartão coletado pelo SDK do Stripe; não guardamos o número completo | Funcionalidade do app; pagamentos |
| Informações financeiras: histórico de compras | Sim | Registros de agendamentos, valores e taxas | Funcionalidade do app; obrigações legais |
| Identificadores de dispositivo ou outros | Sim | Token de notificações push (Expo) | Funcionalidade do app (notificações) |
| Localização, contatos, mensagens, áudio, arquivos, calendário | Não | — | — |
| Desempenho/diagnóstico (relatórios de falha) | Não | Nenhuma ferramenta de falhas instalada hoje; se adicionar uma (ex.: Sentry), volte aqui | — |

Telefone: o app **não** coleta; o número é digitado só na **página web** de agendamento (que não faz parte da ficha do app).

| Pergunta | Resposta |
|---|---|
| Dados criptografados em trânsito? | Sim (HTTPS) |
| Usuários podem pedir exclusão dos dados? | Sim — dentro do app e pela URL de exclusão |
| O app segue a política "Famílias"? | Não (público 18+) |

## Classificação de conteúdo (questionário IARC)

App de agendamento sem violência, conteúdo sexual, linguagem imprópria, jogos de azar ou interação livre entre usuários.
Responda "não" a esses itens; o resultado esperado é a classificação mais baixa (Livre). Marque que o app permite
**pagamentos por serviços reais** (não são bens digitais).

## Recursos financeiros e pagamentos

O Console tem um formulário de *recursos financeiros*. O ShowUp: processa pagamentos de serviços (cartão, via Stripe) e
faz repasses a profissionais; **não** oferece empréstimos, investimentos, criptomoedas ou serviços bancários.
Os planos pagos do ShowUp são **assinaturas de funções do app** — é exatamente o ponto que a política de pagamentos do
Google costuma cobrar; por isso a recomendação é lançar com `PLANOS_COMPRA_HABILITADA=0` (ver `LANCAMENTO.md`).

## Imagens (confira as medidas atuais no Console)

- [ ] Ícone 512×512 px (PNG, sem transparência) — usar o ícone do app.
- [ ] Imagem de destaque 1024×500 px.
- [ ] Capturas de tela de celular (mínimo 2; o ideal é 6–8), em retrato.

Sugestão de telas (use uma conta com dados fictícios, **nunca nomes ou valores reais de clientes**):

1. Agenda com os próximos atendimentos
2. Perfil com "Seu link de agendamento"
3. Página de agendamento (data e horário em dropdown) — pode ser captura do navegador
4. Confirmação "Compareceu / Não compareceu"
5. Serviços cadastrados
6. Repasse automático (Stripe conectado)
