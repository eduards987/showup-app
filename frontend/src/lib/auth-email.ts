// Regras e textos do login por e-mail + senha e dos erros do login com Microsoft/Google.
// Lógica PURA (sem React Native) de propósito: dá pra testar com node. A validação aqui só
// poupa uma viagem ao servidor; quem decide de verdade é o backend (que também barra senhas
// óbvias como "12345678" — a mensagem dele aparece na tela).

export type Metodos = { google: boolean; microsoft: boolean; email: boolean };
export type Modo = "entrar" | "criar" | "codigo" | "esqueci" | "redefinir";

export const SENHA_MIN = 8;
export const SENHA_MAX = 128;
const EMAIL_RE = /^[^@\s]{1,64}@[^@\s]+\.[^@\s]{2,}$/;

export function validarEmail(valor: string): string | null {
  const email = valor.trim();
  return email.length <= 254 && EMAIL_RE.test(email) ? null : "Informe um e-mail válido.";
}

export function validarNome(valor: string): string | null {
  const n = valor.trim();
  return n.length >= 2 && n.length <= 80 ? null : "Informe seu nome.";
}

export function validarSenha(senha: string, email: string): string | null {
  if (senha.length < SENHA_MIN) return `A senha precisa ter pelo menos ${SENHA_MIN} caracteres.`;
  if (senha.length > SENHA_MAX) return `A senha pode ter no máximo ${SENHA_MAX} caracteres.`;
  const e = email.trim().toLowerCase();
  if (e && senha.toLowerCase() === e) return "A senha não pode ser igual ao seu e-mail.";
  return null;
}

/** Só dígitos, no máximo 6 (o campo aceita colar "123 456" ou "123-456"). */
export function limparCodigo(valor: string): string {
  return valor.replace(/\D/g, "").slice(0, 6);
}

export function codigoCompleto(valor: string): boolean {
  return /^\d{6}$/.test(valor);
}

/** Código que o backend devolve no redirecionamento (showup://auth-callback?error=...) → texto pro usuário. */
export function mensagemErroLoginSocial(codigo: string | null, provedor: "Google" | "Microsoft"): string {
  switch (codigo) {
    case "access_denied":
    case "user_cancelled":
      return `O login com ${provedor} foi cancelado.`;
    case "microsoft_indisponivel":
      return "O login com Microsoft ainda não está disponível. Use outra opção.";
    case "estado_invalido":
      return "O pedido de login expirou. Toque no botão e tente de novo.";
    case "token_exchange_failed":
    case "token_invalido":
    case "sem_id_token":
    case "sem_code":
    case null:
      return `Não foi possível entrar com ${provedor}. Tente de novo.`;
    default:
      // o backend manda mensagens já em português (ex.: "A conta Microsoft não informou um e-mail")
      return /\s/.test(codigo) ? codigo : `Não foi possível entrar com ${provedor}. Tente de novo.`;
  }
}

export function textosDoModo(modo: Modo): { titulo: string; subtitulo: string; botao: string } {
  switch (modo) {
    case "criar":
      return { titulo: "Criar conta", subtitulo: "Funciona com qualquer e-mail: Outlook, Yahoo, iCloud, o do trabalho...", botao: "Criar conta" };
    case "codigo":
      return { titulo: "Confirme seu e-mail", subtitulo: "Digite o código de 6 dígitos que enviamos para você.", botao: "Confirmar e entrar" };
    case "esqueci":
      return { titulo: "Esqueci minha senha", subtitulo: "Enviamos um código para o seu e-mail para você criar uma nova senha.", botao: "Enviar código" };
    case "redefinir":
      return { titulo: "Nova senha", subtitulo: "Digite o código que enviamos e escolha a nova senha.", botao: "Salvar nova senha" };
    case "entrar":
    default:
      return { titulo: "Entrar com e-mail", subtitulo: "Use o e-mail e a senha que você cadastrou.", botao: "Entrar" };
  }
}
