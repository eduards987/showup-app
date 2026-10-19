# Fusos horários e categorias: como funcionam e como mexer

## Categorias de profissional
- Lista única no servidor: `CATEGORIAS_POR_GRUPO` em `backend/server.py` (35 categorias em 7 grupos, mais "Outros"). O profissional escolhe de **1 a 3**.
- O **código** (`odontologia`, `fitness`...) é o que fica gravado no perfil; **nunca renomeie um código já usado**. O nome aparece traduzido no app (`frontend/src/lib/categorias.ts`).
- **Para acrescentar uma categoria:** código no servidor + nome em `categorias.ts` + tradução em `en.ts`/`es.ts` + a página inicial (`index.html`, seção "Para quem é").
  O `test_categorias.py` avisa se esquecer qualquer um desses.
- No app: dropdown por grupo com marcação múltipla (*Configurações > CATEGORIAS*). O cliente filtra a busca por um dropdown por grupo.

## Fusos horários (99, em 7 grupos)
- Lista no servidor: `TIMEZONES_POR_GRUPO`. O servidor calcula tudo com a base oficial de fusos (`ZoneInfo`), então **ele sempre acerta o horário de verão**.
- **O app NÃO usa `Intl`** (bugs do motor do React Native com fuso). Por isso `frontend/src/lib/fusos.ts` tem a **regra de horário de verão de cada fuso** (EUA/Canadá, Europa, Austrália, Nova Zelândia, Chile, ou nenhuma).
- **Para acrescentar um fuso:** servidor + `fusos.ts` (deslocamento, regra e grupo) + nome em `fusos.ts` + traduções. Se ele **tiver horário de verão com regra diferente das cinco que existem**, não
  acrescente sem conversar: é preciso uma regra nova. O `test_fusos.py` compara **todos os fusos com a base oficial** em cada troca de horário (2025 a 2032, minuto a minuto) e falha se algum divergir.
- **Fusos que ficaram de fora de propósito:** os que mudam de regra com frequência ou por calendário religioso (Egito, Marrocos, Israel, Cuba, Líbano, Irã com horário de verão antigo etc.).
- **Governos mudam as regras.** O teste já pegou uma: segundo a base oficial atual, Colúmbia Britânica, Alberta e Manitoba entram no horário de verão em 8/mar/2026 e **não voltam mais**; isso está codificado
  (`permanenteDesde`). Por isso o `requirements.txt` exige `tzdata>=2026.5`, e o teste usa essa base. **Quando o Render atualizar a base e o teste do GitHub falhar, é um aviso de que alguma regra mudou:** atualize `fusos.ts`.
- O rótulo mostra o deslocamento **de hoje** ("Nova York (UTC-4)" no verão, "(UTC-5)" no inverno).
- O CI instala o Node 22 e **falha** (em vez de pular) se faltar Node ou `tzdata`; localmente, sem Node, esses testes são pulados.

## O que não foi testado em aparelho de verdade
Os dropdowns (rolagem da lista longa, marcar até 3 categorias, aviso no limite, "Concluir") foram verificados por análise de tipos e testes das regras, não em celular. Teste: *Configurações > CATEGORIAS*
(marque 3 e tente o 4º), *FUSO HORÁRIO* (escolha Nova York e confira os horários nas Reservas) e o filtro de categoria na busca do cliente.
