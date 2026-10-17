#!/usr/bin/env python3
"""Confere os seus arquivos de variáveis (.env) ANTES de publicar/testar e diz o que falta ou está errado.

Roda no seu computador, só com o Python. NUNCA imprime os valores (só o começo, ex.: "sk_test_…").

Como usar (da raiz do projeto):

  python lancamento/verificar-config.py                                  # confere backend/.env e frontend/.env
  python lancamento/verificar-config.py --backend .env.render            # confere o que você colou do Render
  python lancamento/verificar-config.py --modo producao                  # exige chaves reais (sk_live_/pk_live_)
  python lancamento/verificar-config.py --gerar-segredos                 # gera INTERNAL_SERVICE_TOKEN e AUTH_CODE_PEPPER novos

Para conferir o Render: no painel do serviço, Environment > "Edit" > copie tudo e cole num arquivo `.env.render`
na raiz do projeto (o .gitignore já ignora `.env.*`). Apague o arquivo depois.

Resultado: [OK] certo · [ATENÇÃO] vale olhar · [FALTA] variável que o servidor precisa · [ERRO] valor que vai quebrar algo.
Sai com código 1 se houver FALTA ou ERRO.
"""
import argparse
import re
import secrets
import sys
from pathlib import Path
from urllib.parse import urlparse

RAIZ = Path(__file__).resolve().parent.parent
RE_STRIPE_SECRETA = re.compile(r"^(sk|rk)_(test|live)_\S+$")


def ler_env(caminho: Path) -> dict[str, str]:
    """Lê um arquivo .env simples: CHAVE=valor, com ou sem aspas, ignorando comentários."""
    valores: dict[str, str] = {}
    for linha in caminho.read_text(encoding="utf-8-sig").splitlines():
        linha = linha.strip()
        if not linha or linha.startswith("#") or "=" not in linha:
            continue
        if linha.startswith("export "):
            linha = linha[len("export "):]
        chave, _, valor = linha.partition("=")
        valor = valor.strip()
        if len(valor) >= 2 and valor[0] == valor[-1] and valor[0] in "\"'":
            valor = valor[1:-1]
        elif " #" in valor:
            valor = valor.split(" #")[0].strip()
        valores[chave.strip()] = valor
    return valores


PLACEHOLDERS_MONGO = ("usuario:senha", "seu_usuario", "sua_senha", "<password>", "db_password", "user:pass", "usuario:password")


def problemas_mongo_url(url: str) -> list[str]:
    """Erros de digitação típicos da MONGO_URL, achados SEM conectar (e sem nunca repetir a senha)."""
    m = re.match(r"^(mongodb(?:\+srv)?)://(.*)$", url)
    if not m:
        return ["não começa com mongodb:// nem mongodb+srv://."]
    resto = m.group(2)
    if "@" not in resto:
        if re.split(r"[:/?]", resto, maxsplit=1)[0] in ("localhost", "127.0.0.1"):
            return []   # banco local de desenvolvimento, sem senha, é legítimo
        return ["não tem usuário e senha (o formato é mongodb+srv://USUARIO:SENHA@endereco-do-cluster/...)."]
    userinfo, _, _host = resto.rpartition("@")
    problemas: list[str] = []
    if re.search(r"[<>]", userinfo):
        problemas.append("o usuário ou a senha ainda estão entre < > (o texto de exemplo do Atlas). Troque pelo valor real e TIRE os sinais < >.")
    elif any(p in userinfo.lower() for p in PLACEHOLDERS_MONGO):
        problemas.append("ainda tem o texto de exemplo (USUARIO:SENHA) no lugar do usuário e da senha reais.")
    usuario, dois_pontos, senha = userinfo.partition(":")
    if not dois_pontos or not senha:
        problemas.append("falta a senha (o formato é USUARIO:SENHA).")
        return problemas
    if "@" in senha:
        problemas.append("a senha contém o caractere @ sem codificar, e isso corta a URL no meio. Use uma senha só com letras e números (o mais simples) ou troque @ por %40.")
    elif re.search(r"[/?#\[\]:]", senha):
        problemas.append("a senha contém um caractere especial (/ ? # [ ] :) sem codificar. Use uma senha só com letras e números (o mais simples) ou codifique o caractere.")
    if re.search(r"%(?![0-9A-Fa-f]{2})", senha):
        problemas.append("a senha tem um % que não é uma codificação válida (como %40). Use uma senha só com letras e números.")
    if not usuario:
        problemas.append("falta o nome do usuário antes dos dois pontos.")
    return problemas


def mascarar(valor: str) -> str:
    """Nunca devolve o valor: só o prefixo e o tamanho."""
    if not valor:
        return "(vazio)"
    prefixo = re.match(r"^[a-z]{2,3}_(?:test_|live_)?|^whsec_|^price_|^GOCSPX-|^mongodb(?:\+srv)?://", valor)
    return f"{prefixo.group(0) if prefixo else ''}…({len(valor)} caracteres)"


class Relatorio:
    def __init__(self):
        self.linhas: list[tuple[str, str]] = []

    def ok(self, m): self.linhas.append(("OK", m))
    def atencao(self, m): self.linhas.append(("ATENÇÃO", m))
    def falta(self, m): self.linhas.append(("FALTA", m))
    def erro(self, m): self.linhas.append(("ERRO", m))
    def titulo(self, t): self.linhas.append(("#", t))

    @property
    def codigo_saida(self) -> int:
        return 1 if any(n in ("FALTA", "ERRO") for n, _ in self.linhas) else 0

    def imprimir(self):
        for nivel, msg in self.linhas:
            print(f"\n== {msg} ==" if nivel == "#" else f"[{nivel}] {msg}")
        cont = {n: sum(1 for x, _ in self.linhas if x == n) for n in ("OK", "ATENÇÃO", "FALTA", "ERRO")}
        problemas = cont["FALTA"] + cont["ERRO"]
        print(f"\n{'CONFIGURAÇÃO OK' if not problemas else 'CORRIJA ' + str(problemas) + ' item(ns)'} — "
              f"{cont['OK']} ok, {cont['ATENÇÃO']} aviso(s), {cont['FALTA']} faltando, {cont['ERRO']} com erro.")


def _host(url: str) -> str:
    return urlparse(url).hostname or ""


def _preenchido(v: dict, *chaves) -> list[str]:
    return [c for c in chaves if v.get(c)]


def verificar_backend(v: dict, modo: str, rel: Relatorio) -> None:
    rel.titulo("BACKEND (Render / backend/.env)")

    # --- obrigatórias para o servidor subir
    for chave, dica in (
        ("MONGO_URL", "Atlas > Connect > Drivers"), ("DB_NAME", "ex.: holdbooked"),
        ("INTERNAL_SERVICE_TOKEN", "gere com --gerar-segredos"), ("GOOGLE_WEB_CLIENT_ID", "Google Cloud > Credenciais"),
        ("GOOGLE_CLIENT_SECRET", "Google Cloud > Credenciais"), ("GOOGLE_OAUTH_REDIRECT_URI", "URL do backend + /api/auth/google/callback"),
    ):
        if not v.get(chave):
            rel.falta(f"{chave} — o servidor NÃO sobe sem ela ({dica}).")

    # --- MongoDB
    mongo = v.get("MONGO_URL", "")
    if mongo:
        achados = problemas_mongo_url(mongo)
        for achado in achados:
            rel.erro(f"MONGO_URL {achado}")
        if not achados:
            rel.ok(f"MONGO_URL no formato certo ({mascarar(mongo)}). Para testar usuário e senha de verdade: python lancamento/verificar-mongo.py")

    # --- segredos internos
    token = v.get("INTERNAL_SERVICE_TOKEN", "")
    if token:
        (rel.ok if len(token) >= 32 else rel.atencao)(
            "INTERNAL_SERVICE_TOKEN com tamanho bom." if len(token) >= 32
            else "INTERNAL_SERVICE_TOKEN é curto (menos de 32 caracteres). Gere outro com --gerar-segredos.")

    # --- Stripe
    chave_stripe = v.get("STRIPE_API_KEY", "")
    modo_stripe = None
    if not chave_stripe:
        rel.atencao("STRIPE_API_KEY vazia: o servidor usa o modo SIMULADO (aprova reservas sem cobrar ninguém). "
                    "Para testar pagamentos de verdade, preencha com a chave secreta sk_test_.")
    elif not RE_STRIPE_SECRETA.match(chave_stripe) or len(chave_stripe) <= 20:
        rel.erro(f"STRIPE_API_KEY não parece uma chave secreta do Stripe ({mascarar(chave_stripe)}): "
                 "o servidor RECUSA subir. Use sk_test_... (teste) ou sk_live_... (produção), completa.")
    else:
        modo_stripe = "teste" if "_test_" in chave_stripe else "producao"
        if modo_stripe == modo:
            rel.ok(f"STRIPE_API_KEY de {modo_stripe} ({mascarar(chave_stripe)}).")
        else:
            rel.erro(f"STRIPE_API_KEY é de {modo_stripe}, mas você está conferindo o modo {modo}.")

    webhook = v.get("STRIPE_WEBHOOK_SECRET", "")
    if chave_stripe and not webhook:
        rel.falta("STRIPE_WEBHOOK_SECRET — sem ela o webhook responde 500 e o Stripe não consegue avisar de nada "
                  "(Stripe > Developers > Webhooks > seu endpoint > Signing secret).")
    elif webhook and not webhook.startswith("whsec_"):
        rel.erro(f"STRIPE_WEBHOOK_SECRET deveria começar com whsec_ ({mascarar(webhook)}).")
    elif webhook:
        rel.ok("STRIPE_WEBHOOK_SECRET no formato certo.")
    conn = v.get("STRIPE_CONNECT_WEBHOOK_SECRET", "")
    if conn and not conn.startswith("whsec_"):
        rel.erro(f"STRIPE_CONNECT_WEBHOOK_SECRET deveria começar com whsec_ ({mascarar(conn)}).")
    elif not conn and chave_stripe:
        rel.atencao("STRIPE_CONNECT_WEBHOOK_SECRET vazia: tudo funciona, mas a liberação das contas dos profissionais "
                    "depende do job de 10 minutos em vez de ser imediata.")

    planos_ligados = v.get("PLANOS_COMPRA_HABILITADA", "1") != "0"
    for chave in ("STRIPE_PRICE_ID_PROFISSIONAL", "STRIPE_PRICE_ID_ULTRA"):
        valor = v.get(chave, "")
        if valor and not valor.startswith("price_"):
            rel.erro(f"{chave} deveria começar com price_ ({mascarar(valor)}).")
        elif not valor and planos_ligados and chave_stripe:
            rel.atencao(f"{chave} vazia: esse plano aparece como \"em breve\" no app.")

    # --- Google
    redir = v.get("GOOGLE_OAUTH_REDIRECT_URI", "")
    if redir:
        if not redir.endswith("/api/auth/google/callback"):
            rel.erro("GOOGLE_OAUTH_REDIRECT_URI deve terminar em /api/auth/google/callback.")
        elif not redir.startswith("https://") and _host(redir) not in ("localhost", "127.0.0.1"):
            rel.erro("GOOGLE_OAUTH_REDIRECT_URI precisa ser https:// (o Google não aceita http fora do localhost).")
        else:
            rel.ok(f"GOOGLE_OAUTH_REDIRECT_URI ok ({_host(redir)}). Ela precisa ser IDÊNTICA à cadastrada no Google Cloud.")
    cid = v.get("GOOGLE_WEB_CLIENT_ID", "")
    if cid and not cid.endswith(".apps.googleusercontent.com"):
        rel.erro("GOOGLE_WEB_CLIENT_ID deveria terminar em .apps.googleusercontent.com.")
    seg = v.get("GOOGLE_CLIENT_SECRET", "")
    if seg and not seg.startswith("GOCSPX-"):
        rel.atencao("GOOGLE_CLIENT_SECRET normalmente começa com GOCSPX-. Confira se copiou o segredo certo.")

    # --- Microsoft (tudo ou nada)
    ms = _preenchido(v, "MICROSOFT_CLIENT_ID", "MICROSOFT_CLIENT_SECRET", "MICROSOFT_OAUTH_REDIRECT_URI")
    if not ms:
        rel.atencao("Login com Microsoft DESLIGADO (nenhuma MICROSOFT_* preenchida). O botão não aparece no app.")
    elif len(ms) < 3:
        faltam = [c for c in ("MICROSOFT_CLIENT_ID", "MICROSOFT_CLIENT_SECRET", "MICROSOFT_OAUTH_REDIRECT_URI") if c not in ms]
        rel.erro(f"Login com Microsoft INCOMPLETO: falta {', '.join(faltam)}. Enquanto faltar, o botão não aparece.")
    else:
        ms_redir = v["MICROSOFT_OAUTH_REDIRECT_URI"]
        if not ms_redir.endswith("/api/auth/microsoft/callback"):
            rel.erro("MICROSOFT_OAUTH_REDIRECT_URI deve terminar em /api/auth/microsoft/callback.")
        elif not ms_redir.startswith("https://"):
            rel.erro("MICROSOFT_OAUTH_REDIRECT_URI precisa ser https://.")
        else:
            rel.ok("Login com Microsoft configurado. A URI precisa ser IDÊNTICA à cadastrada no Microsoft Entra.")
            if redir and _host(redir) != _host(ms_redir):
                rel.atencao("A URI da Microsoft e a do Google apontam para servidores diferentes. Confira se é isso mesmo.")
        if not re.fullmatch(r"[0-9a-fA-F-]{36}", v["MICROSOFT_CLIENT_ID"]):
            rel.atencao("MICROSOFT_CLIENT_ID normalmente é um GUID (xxxxxxxx-xxxx-...). Confira se copiou o 'ID do aplicativo (cliente)'.")

    # --- E-mail (SMTP)
    smtp = _preenchido(v, "SMTP_HOST", "SMTP_FROM")
    log_codigos = v.get("EMAIL_CODIGOS_NO_LOG") == "1"
    if not smtp and not log_codigos:
        rel.atencao("Cadastro por e-mail DESLIGADO (SMTP_HOST e SMTP_FROM vazios). A opção não aparece no app.")
    elif smtp and len(smtp) < 2:
        rel.erro("Cadastro por e-mail INCOMPLETO: precisa de SMTP_HOST **e** SMTP_FROM. Enquanto faltar um, a opção não aparece.")
    elif smtp:
        problemas = False
        if "@" not in v["SMTP_FROM"]:
            rel.erro("SMTP_FROM precisa conter um e-mail (ex.: ShowUp <nao-responda@seudominio.com.br>)."); problemas = True
        if v.get("SMTP_PORT") and not v["SMTP_PORT"].isdigit():
            rel.erro("SMTP_PORT precisa ser um número (587 ou 465)."); problemas = True
        if v.get("SMTP_USER") and not v.get("SMTP_PASSWORD"):
            rel.erro("SMTP_USER está preenchido mas falta SMTP_PASSWORD."); problemas = True
        if not v.get("SMTP_USER"):
            rel.atencao("SMTP_USER vazio: a maioria dos serviços de e-mail exige usuário e senha SMTP.")
        dominio = v["SMTP_FROM"].rsplit("@", 1)[-1].strip(" >").lower()
        if dominio in ("gmail.com", "hotmail.com", "outlook.com", "yahoo.com", "yahoo.com.br", "live.com"):
            rel.atencao(f"SMTP_FROM usa um endereço @{dominio}: serve para TESTAR, mas e-mails assim costumam cair no spam "
                        "ou ser recusados. Para produção use um domínio seu.")
        if not problemas:
            rel.ok("Cadastro por e-mail configurado (SMTP).")
    if log_codigos:
        if modo == "producao":
            rel.erro("EMAIL_CODIGOS_NO_LOG=1 em PRODUÇÃO: os códigos de verificação iriam para o log e qualquer pessoa que lê o log "
                     "entra em qualquer conta. Remova.")
        else:
            rel.atencao("EMAIL_CODIGOS_NO_LOG=1: os códigos aparecem no LOG em vez de ir por e-mail. Só para teste local; NUNCA no Render.")

    # --- site, CORS e flags
    site = v.get("PUBLIC_WEB_BASE_URL", "")
    if not site:
        rel.falta("PUBLIC_WEB_BASE_URL — o link de agendamento que o profissional compartilha usa isto (ex.: https://showup-509120.web.app).")
    elif not site.startswith("https://"):
        rel.atencao("PUBLIC_WEB_BASE_URL não é https://.")
    origens = [o.strip() for o in v.get("ALLOWED_ORIGINS", "").split(",") if o.strip()]
    if not origens:
        rel.falta("ALLOWED_ORIGINS — sem isso a página de agendamento do navegador é bloqueada pelo CORS.")
    else:
        if site and site.rstrip("/") not in [o.rstrip("/") for o in origens]:
            rel.erro(f"ALLOWED_ORIGINS não inclui o site ({site}): o navegador bloqueia o link de agendamento.")
        elif site:
            rel.ok("ALLOWED_ORIGINS inclui o site.")   # sem PUBLIC_WEB_BASE_URL não há o que comparar (já saiu FALTA acima)
        if modo == "producao" and any("localhost" in o or "127.0.0.1" in o for o in origens):
            rel.atencao("ALLOWED_ORIGINS ainda tem localhost: em produção, tire.")

    if v.get("TESTING", "").lower() in ("1", "true", "yes"):
        (rel.erro if modo == "producao" else rel.atencao)("TESTING=1 desliga o limite de requisições (proteção contra força bruta). Só para rodar testes; remova do Render.")

    recebimento = v.get("EXIGIR_RECEBIMENTO_ATIVO", "0") == "1"
    if modo == "producao" and not recebimento:
        rel.atencao("EXIGIR_RECEBIMENTO_ATIVO não está em 1: sem isso dá para agendar com profissional que ainda não recebe por Stripe "
                    "(o dinheiro fica na conta da plataforma). Recomendado 1 em produção.")
    else:
        rel.ok(f"EXIGIR_RECEBIMENTO_ATIVO = {'1 (só agenda com conta Stripe liberada)' if recebimento else '0 (agenda mesmo sem Stripe liberado — bom para testar)'}.")
    if modo == "producao" and planos_ligados:
        rel.atencao("PLANOS_COMPRA_HABILITADA está ligada: o Google Play costuma exigir a cobrança dele para vender planos dentro do app. "
                    "Na 1ª versão, o seguro é 0 (ver LANCAMENTO.md, decisão 1).")
    elif modo == "teste":
        rel.ok(f"Planos pagos {'LIGADOS (dá para testar assinatura e teste grátis)' if planos_ligados else 'DESLIGADOS (aparecem como \"em breve\")'}.")


def verificar_frontend(f: dict, b: dict | None, modo: str, rel: Relatorio) -> None:
    rel.titulo("APP (frontend/.env / variáveis do EAS)")
    url = f.get("EXPO_PUBLIC_BACKEND_URL", "")
    if not url:
        rel.falta("EXPO_PUBLIC_BACKEND_URL — o app não sabe onde está o servidor.")
    elif _host(url) in ("10.0.2.2", "localhost", "127.0.0.1") or re.match(r"^\d+\.\d+\.\d+\.\d+$", _host(url)):
        rel.atencao(f"EXPO_PUBLIC_BACKEND_URL aponta para a sua máquina ({_host(url)}): serve para o emulador, mas o login com Google/Microsoft "
                    "NÃO funciona assim (o retorno vai para o servidor do Render). Para testar tudo, use a URL https do Render.")
    elif not url.startswith("https://"):
        rel.atencao("EXPO_PUBLIC_BACKEND_URL não é https://.")
    else:
        rel.ok(f"EXPO_PUBLIC_BACKEND_URL aponta para {_host(url)}.")
        if b and b.get("GOOGLE_OAUTH_REDIRECT_URI") and _host(b["GOOGLE_OAUTH_REDIRECT_URI"]) != _host(url):
            rel.erro(f"O app aponta para {_host(url)}, mas o retorno do Google do servidor é {_host(b['GOOGLE_OAUTH_REDIRECT_URI'])}: o login não vai fechar.")

    pk = f.get("EXPO_PUBLIC_STRIPE_PUBLISHABLE_KEY", "")
    if not pk:
        rel.falta("EXPO_PUBLIC_STRIPE_PUBLISHABLE_KEY — o app não consegue cadastrar cartão sem ela (começa com pk_).")
    elif not re.match(r"^pk_(test|live)_\S{10,}$", pk):
        rel.erro(f"EXPO_PUBLIC_STRIPE_PUBLISHABLE_KEY deveria começar com pk_test_ ou pk_live_ ({mascarar(pk)}). Nunca a sk_ (secreta).")
    else:
        modo_pk = "teste" if pk.startswith("pk_test_") else "producao"
        (rel.ok if modo_pk == modo else rel.erro)(
            f"Chave publicável do Stripe é de {modo_pk}." if modo_pk == modo
            else f"Chave publicável do Stripe é de {modo_pk}, mas você está conferindo o modo {modo}.")
        sk = (b or {}).get("STRIPE_API_KEY", "")
        if RE_STRIPE_SECRETA.match(sk):
            modo_sk = "teste" if "_test_" in sk else "producao"
            if modo_sk != modo_pk:
                rel.erro(f"MODOS MISTURADOS: o app usa chave de {modo_pk} e o servidor usa chave de {modo_sk}. O cartão não vai funcionar.")

    cid = f.get("EXPO_PUBLIC_GOOGLE_WEB_CLIENT_ID", "")
    if not cid:
        rel.falta("EXPO_PUBLIC_GOOGLE_WEB_CLIENT_ID — o botão do Google não abre sem ele.")
    elif b and b.get("GOOGLE_WEB_CLIENT_ID") and cid != b["GOOGLE_WEB_CLIENT_ID"]:
        rel.erro("EXPO_PUBLIC_GOOGLE_WEB_CLIENT_ID é diferente do GOOGLE_WEB_CLIENT_ID do servidor: o login do Google vai falhar.")
    else:
        rel.ok("Client ID do Google presente" + (" e igual ao do servidor." if b else "."))

    # nada secreto pode ir dentro do app: qualquer pessoa extrai as variáveis EXPO_PUBLIC_* do APK
    for chave, valor in f.items():
        if re.search(r"SECRET|PASSWORD|PRIVATE|TOKEN", chave, re.I) or re.match(r"^(sk_|rk_|whsec_|GOCSPX-)", valor):
            rel.erro(f"{chave} parece um SEGREDO e está nas variáveis do app. Variáveis do app ficam DENTRO do APK e qualquer um as lê. Tire daqui.")


def gerar_segredos() -> None:
    print("Cole estes valores no Render (Environment). Eles só aparecem agora; não ficam salvos em lugar nenhum.\n")
    print(f"INTERNAL_SERVICE_TOKEN={secrets.token_hex(32)}")
    print(f"AUTH_CODE_PEPPER={secrets.token_hex(32)}")
    print("\nObs.: trocar o AUTH_CODE_PEPPER invalida só os códigos de verificação pendentes (duram 10 minutos). "
          "Trocar o INTERNAL_SERVICE_TOKEN exige atualizar também quem chama as rotas internas.")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--backend", type=Path, default=RAIZ / "backend" / ".env", help="arquivo de variáveis do servidor")
    ap.add_argument("--frontend", type=Path, default=RAIZ / "frontend" / ".env", help="arquivo de variáveis do app")
    ap.add_argument("--modo", choices=("teste", "producao"), default="teste")
    ap.add_argument("--gerar-segredos", action="store_true")
    args = ap.parse_args(argv)

    if args.gerar_segredos:
        gerar_segredos()
        return 0

    rel = Relatorio()
    backend = ler_env(args.backend) if args.backend.exists() else None
    frontend = ler_env(args.frontend) if args.frontend.exists() else None
    if backend is None and frontend is None:
        print(f"Nenhum arquivo encontrado ({args.backend} / {args.frontend}). Copie o .env.example para .env e preencha.")
        return 1
    print(f"Modo conferido: {args.modo.upper()}  ·  backend: {args.backend if backend is not None else '(não encontrado)'}  ·  "
          f"app: {args.frontend if frontend is not None else '(não encontrado)'}")
    if backend is not None:
        verificar_backend(backend, args.modo, rel)
    else:
        rel.atencao(f"{args.backend} não encontrado: o servidor não foi conferido.")
    if frontend is not None:
        verificar_frontend(frontend, backend, args.modo, rel)
    else:
        rel.atencao(f"{args.frontend} não encontrado: o app não foi conferido.")
    rel.imprimir()
    return rel.codigo_saida


if __name__ == "__main__":
    sys.exit(main())
