// Absorve o deep link showup://auth-callback?token=... que o backend usa
// pra devolver o usuário ao app no fim do login com o Google.
//
// Quem realmente consome esse link é o WebBrowser.openAuthSessionAsync,
// dentro de signIn() (src/lib/auth.tsx) — ele lê o token, salva a sessão e
// fecha o navegador. Mas o Expo Router também enxerga o mesmo link e tenta
// abrir uma tela com esse caminho; sem essa rota, aparecia "Unmatched
// Route". Aqui a gente só devolve pro gate de autenticação (app/index.tsx),
// que é o único lugar que decide pra onde o usuário vai.

import { Redirect } from "expo-router";

export default function AuthCallback() {
  return <Redirect href="/" />;
}
