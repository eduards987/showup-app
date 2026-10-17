// Textos de erro do cadastro do aparelho para notificações. Lógica PURA (sem React Native): testável no Node.
// Antes, qualquer falha aqui virava só um console.warn no computador e o profissional nunca soube que não receberia avisos.

export const MSG_EMULADOR = "Emuladores não recebem notificações. Use um celular de verdade.";
export const MSG_PERMISSAO =
  "As notificações estão bloqueadas para o ShowUp. Abra as Configurações do celular > Aplicativos > ShowUp > Notificações e permita.";
export const MSG_SEM_PROJECT_ID =
  "O app foi compilado sem o identificador do projeto Expo (extra.eas.projectId no app.json). Veja lancamento/NOTIFICACOES.md.";

/** Traduz a mensagem de erro do expo-notifications ao tentar obter o token do aparelho. */
export function explicarFalhaDoToken(mensagem: string): string {
  const m = mensagem.toLowerCase();
  if (m.includes("firebaseapp") || m.includes("google-services") || m.includes("fcm")) {
    return (
      "O app foi compilado sem a configuração do Firebase (google-services.json). Confira o arquivo em frontend/ e recompile com " +
      "`npx expo run:android`."
    );
  }
  if (m.includes("service_not_available") || m.includes("timeout") || m.includes("network") || m.includes("unable to resolve")) {
    return "Não consegui falar com o Google/Expo para registrar o aparelho. Confira a internet e tente de novo.";
  }
  if (m.includes("projectid") || m.includes("project id")) {
    return MSG_SEM_PROJECT_ID;
  }
  if (/\b401\b|\b403\b|bearer|session/.test(m)) {
    return "Sua sessão expirou. Saia da conta, entre de novo e tente outra vez.";
  }
  return `Não foi possível registrar este aparelho para notificações (${mensagem.slice(0, 140)}).`;
}

// ---------------------------------------------------------------------------------------------------------------------
// Diagnóstico passo a passo (o botão "Enviar notificação de teste" mostra esta lista com ✓ e ✗)
// ---------------------------------------------------------------------------------------------------------------------
export type EstadoPasso = "aguardando" | "executando" | "ok" | "falhou" | "pendente" | "pulado";
export type IdPasso = "aparelho" | "permissao" | "token" | "registro" | "envio" | "entrega";
export type PassoDiagnostico = { id: IdPasso; titulo: string; estado: EstadoPasso; detalhe?: string };

export const ORDEM_PASSOS: IdPasso[] = ["aparelho", "permissao", "token", "registro", "envio", "entrega"];

const TITULOS: Record<IdPasso, string> = {
  aparelho: "Celular de verdade (não emulador)",
  permissao: "Permissão de notificações",
  token: "Código do aparelho gerado (Expo)",
  registro: "Aparelho registrado no servidor",
  envio: "Servidor enviou o aviso à Expo",
  entrega: "Entrega confirmada pelo Firebase",
};

export function novoDiagnostico(): PassoDiagnostico[] {
  return ORDEM_PASSOS.map((id) => ({ id, titulo: TITULOS[id], estado: "aguardando" as EstadoPasso }));
}

export const MSG_SEM_RECURSO_NO_SERVIDOR =
  "O servidor ainda não tem os avisos por notificação. Publique o código novo (git push) e espere o Render ficar Live.";

/** O que a pessoa deve fazer agora: a mensagem do PRIMEIRO passo que falhou (ou a conclusão, se tudo deu certo). */
export function acaoFinal(passos: PassoDiagnostico[]): { ok: boolean; texto: string } {
  const falhou = passos.find((p) => p.estado === "falhou");
  if (falhou) return { ok: false, texto: falhou.detalhe ?? `Falhou: ${falhou.titulo}.` };
  const pendente = passos.find((p) => p.estado === "pendente");
  if (pendente) return { ok: true, texto: pendente.detalhe ?? "A entrega ainda não foi confirmada. Espere 1 ou 2 minutos." };
  if (passos.every((p) => p.estado === "ok")) {
    return { ok: true, texto: "Tudo certo: a notificação de teste foi enviada. Ela deve aparecer no celular em instantes." };
  }
  return { ok: false, texto: "O teste não terminou. Tente de novo." };
}
