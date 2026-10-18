# Idiomas: português, inglês e espanhol

## Como o app escolhe o idioma
1. Se a pessoa já escolheu um idioma, vale a escolha (guardada no aparelho).
2. Senão, usa o **idioma configurado no celular** (sem pedir GPS nem permissão de localização).
3. Idioma sem tradução (francês, japonês...) cai em **inglês**; se a região for o Brasil, em português.

A pessoa troca quando quiser: no canto da **tela de entrada** (antes de logar) e em **Perfil > IDIOMA**. A **moeda** também é um dropdown
(*Configurações do profissional > MOEDA*), com o nome de cada moeda no idioma escolhido.

## Onde o idioma vale
| Parte | Como |
|---|---|
| **App** | Todo texto fixo passa por `t("texto em português")`; os dicionários ficam em `frontend/src/i18n/en.ts` e `es.ts`. Datas e valores seguem o idioma. |
| **Página de agendamento** (`agendar.html`) | Dicionário no próprio arquivo; detecta o idioma do navegador; seletor na 1ª etapa (trocar recarrega a página); valores com `Intl`. |
| **Mensagens de erro do servidor** | O app e a página mandam `Accept-Language`; `backend/i18n_servidor.py` traduz as mensagens fixas. |
| **Fica só em português** | Notificações push (novo agendamento, lembrete, confirmação), Termos, Privacidade, exclusão de conta e a página inicial do site (público: profissionais no Brasil). |

## Como acrescentar ou mudar um texto (os testes avisam se esquecer)
- **No app:** escreva `t("Texto em português")` na tela e acrescente **uma linha** em `en.ts` e outra em `es.ts` com a mesma chave. Frases com variável usam
  `{{nome}}` (`t("Faltam {{n}} dias", { n: 3 })`) e a tradução precisa ter as mesmas variáveis. `backend/tests/test_i18n_app.py` confere tudo.
- **Na página:** `T("texto")` no JavaScript, ou o texto direto no HTML, e a tradução no `DICIONARIO` do `agendar.html` (`test_site_publicacao.py` confere).
- **No servidor:** a mensagem do `HTTPException` em português + uma entrada em `TRADUCOES` (`test_i18n_servidor.py` confere).
- **Novo idioma:** acrescente o código em `IDIOMAS` (`src/i18n/core.ts`), crie o dicionário, e repita nos três lugares acima.

## O que não foi testado em aparelho de verdade
O dropdown e a troca de idioma com o app aberto foram verificados só por testes automáticos e no Node. Teste no celular: troque o idioma em *Perfil > IDIOMA*
e confira as abas, a tela de reservas e os valores em dólar.
