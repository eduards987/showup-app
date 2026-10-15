# Teste fechado do Google Play — como juntar 12 testadores

**A regra** (conta pessoal criada depois de 13/11/2023): rodar um teste fechado com **no mínimo 12 testadores inscritos
por 14 dias seguidos** antes de pedir acesso à produção. Quem sair antes de completar os 14 dias não conta, mesmo que
volte. Em 2026 o Google também confere se os testadores **usaram** o app de verdade, então "inscrito" não basta.

## O que decidir antes

- **Modo do Stripe no teste:** use o **modo de teste** (chaves `pk_test`/`sk_test`). Ninguém é cobrado e o cartão é
  `4242 4242 4242 4242`. Avise isso no convite. O build de **produção** (com chaves reais) é um build **novo**,
  gerado depois.
- **Quem convidar (meta: 15 a 20 pessoas)**: 5 ou 6 profissionais que atendem por hora marcada (são o seu público de
  verdade, e o feedback deles vale ouro) e o resto, amigos e familiares que topem agir como clientes.
- Cada testador precisa de uma **conta Google** (o e-mail que usa no celular Android). iPhone não serve para o teste do Play.

## Passo a passo

1. No Play Console: **Testes > Teste fechado > Criar faixa** e suba o `.aab` de teste.
2. Crie a lista de testadores (por e-mail, ou um Grupo do Google) e **salve**.
3. Copie o **link de adesão** da faixa e mande para cada pessoa. Ela precisa abrir o link, tocar em
   "Tornar-se testador" e instalar o app pela Play Store.
4. Acompanhe no Console quantos já aderiram. Passou de 12 inscritos, o relógio dos 14 dias começa a contar para cada um.
5. Durante os 14 dias: peça uso real (lista abaixo), colete feedback e **reponha quem desistir** na hora.
6. No 15º dia aparece o botão **"Solicitar acesso à produção"** (responder o questionário com exemplos concretos do que os testadores fizeram e do que você corrigiu).

## Mensagem para mandar (WhatsApp)

> Oi, [nome]! Estou lançando o **ShowUp**, um app de agenda com proteção contra falta de cliente: o cartão do cliente
> garante o horário. Preciso de gente testando por **14 dias seguidos** antes de publicar na Play Store, e queria você
> nessa. Leva 2 minutos para entrar:
> 1) abra este link no celular Android: **[link de adesão]**
> 2) toque em "Tornar-se testador" e instale o app
> 3) use de vez em quando nos próximos 14 dias e me conte o que achou
>
> É modo de teste: ninguém é cobrado. Se for pagar algo, use o cartão 4242 4242 4242 4242 (qualquer validade futura e CVC).
> Por favor, **não saia do teste antes dos 14 dias**, senão perde a contagem. Obrigado!

## O que pedir que eles façam (uso real, para o Google ver atividade)

- **Profissional:** entrar com o Google, escolher "Profissional", cadastrar um serviço e horários, copiar o link de agendamento, reservar uma vez com esse link, e responder "compareceu" ou "faltou".
- **Cliente:** entrar, escolher "Cliente", cadastrar o cartão de teste, reservar um horário e cancelar outro.
- **Todos:** abrir o app em dias diferentes ao longo das duas semanas.

## Planilha de acompanhamento (colunas)

`Nome · E-mail Google · Perfil (profissional/cliente) · Entrou no teste em · Ainda inscrito? · Usou o app? · Feedback · Observações`

## Perguntas de feedback (formulário de 5 minutos)

1. Conseguiu entrar com o Google sem dificuldade? 2. O que ficou confuso? 3. Algo quebrou ou travou? 4. Você usaria no seu trabalho
(ou indicaria a um profissional)? Por quê? 5. O que faltou?

## Depois dos 14 dias

Aplique o que for mais urgente do feedback, siga o `LANCAMENTO.md` (Pagamentos em produção) e só então publique o build de produção.
