#!/usr/bin/env python3
"""Testa se o ID do cliente e o segredo do Google (login) estão certos — sem precisar fazer login.

Serve para o sintoma "escolho minha conta e volto para a tela inicial": quase sempre o servidor não conseguiu trocar o
código do Google por uma sessão porque o GOOGLE_CLIENT_SECRET (ou o ID) do Render não confere com o do Google Cloud.

Como funciona: manda ao Google um código FALSO junto com o seu ID, segredo e endereço de retorno. Se o ID e o segredo
estiverem certos, o Google recusa só o código ("invalid_grant") — e isso é o resultado BOM. Se estiverem errados,
ele diz "invalid_client". Nenhum login é feito e nada é alterado. O segredo nunca é mostrado.

Uso (da raiz do projeto):

  py lancamento\\verificar-google.py --arquivo .env.render
  py lancamento\\verificar-google.py --arquivo backend\\.env

Sem arquivo à mão, use:  py lancamento/verificar-google.py --perguntar
(ele pergunta os 3 valores; o segredo fica oculto e não é gravado em lugar nenhum)

Sai com código 1 se algo estiver errado.
"""
import argparse
import getpass
import importlib.util
import json
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
TOKEN_URL = "https://oauth2.googleapis.com/token"


def _config():
    spec = importlib.util.spec_from_file_location("verificar_config", Path(__file__).with_name("verificar-config.py"))
    modulo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modulo)
    return modulo


def perguntar_ao_google(url: str, client_id: str, client_secret: str, redirect_uri: str) -> tuple[int, dict]:
    corpo = urllib.parse.urlencode({
        "code": "codigo-falso-so-para-testar", "client_id": client_id, "client_secret": client_secret,
        "redirect_uri": redirect_uri, "grant_type": "authorization_code",
    }).encode()
    req = urllib.request.Request(url, data=corpo, method="POST", headers={"Content-Type": "application/x-www-form-urlencoded"})
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            return r.status, json.loads(r.read().decode() or "{}")
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read().decode() or "{}")
        except ValueError:
            return e.code, {}


def interpretar(status: int, resposta: dict) -> tuple[bool, str]:
    """(deu certo?, explicação). 'invalid_grant' = ID e segredo corretos, só o código de teste foi recusado."""
    erro = resposta.get("error", "")
    if erro == "invalid_grant":
        return True, "O Google ACEITOU o ID e o segredo (ele recusou só o código de teste, como esperado). As credenciais estão certas."
    if erro == "invalid_client":
        return False, ("O Google NÃO reconhece essa combinação de ID do cliente + segredo (invalid_client). Corrija assim:\n"
                       "   1. Google Cloud > APIs e serviços > Credenciais > abra o cliente OAuth do tipo \"Aplicativo da Web\".\n"
                       "   2. Confira que o \"ID do cliente\" é o mesmo do GOOGLE_WEB_CLIENT_ID.\n"
                       "   3. Em \"Segredos do cliente\", crie um novo (ou use um ATIVO) e copie o valor NA HORA (ele só aparece inteiro uma vez).\n"
                       "      ATENÇÃO: se o projeto tem MAIS DE UM cliente \"Aplicativo da Web\", o segredo precisa ser do MESMO cliente do ID. "
                       "Segredo de um cliente não funciona com o ID de outro.\n"
                       "   4. Cole em GOOGLE_CLIENT_SECRET no Render (Environment) e use Save and deploy. Se você trocou o segredo no Google "
                       "e não no Render, é exatamente isto.")
    if erro == "redirect_uri_mismatch":
        return False, ("O endereço de retorno não está cadastrado. No Google Cloud, no mesmo cliente, adicione em \"URIs de redirecionamento "
                       "autorizados\" EXATAMENTE o valor do GOOGLE_OAUTH_REDIRECT_URI.")
    if erro == "unauthorized_client":
        return False, "Esse cliente OAuth não pode usar este tipo de fluxo. Confirme que ele é do tipo \"Aplicativo da Web\"."
    return False, f"Resposta inesperada do Google (HTTP {status}): {erro or 'sem detalhe'} {resposta.get('error_description', '')[:120]}"


def main(argv=None, url_token: str = TOKEN_URL) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--arquivo", type=Path, default=RAIZ / "backend" / ".env")
    ap.add_argument("--perguntar", action="store_true", help="não usa arquivo: pergunta os valores aqui no terminal")
    ap.add_argument("--app-env", type=Path, default=RAIZ / "frontend" / ".env", help="frontend/.env, para conferir se o app usa o MESMO ID")
    args = ap.parse_args(argv)
    cfg = _config()
    if args.perguntar:
        padrao = "https://showup-backend-s9y1.onrender.com/api/auth/google/callback"
        v = {
            "GOOGLE_WEB_CLIENT_ID": input("GOOGLE_WEB_CLIENT_ID (termina em .apps.googleusercontent.com): ").strip(),
            "GOOGLE_CLIENT_SECRET": getpass.getpass("GOOGLE_CLIENT_SECRET (não aparece enquanto você digita): ").strip(),
            "GOOGLE_OAUTH_REDIRECT_URI": input(f"GOOGLE_OAUTH_REDIRECT_URI [Enter = {padrao}]: ").strip() or padrao,
        }
    elif not args.arquivo.exists():
        print(f"Arquivo não encontrado: {args.arquivo}. Use --perguntar para digitar os valores aqui.")
        return 1
    else:
        v = cfg.ler_env(args.arquivo)
    faltam = [c for c in ("GOOGLE_WEB_CLIENT_ID", "GOOGLE_CLIENT_SECRET", "GOOGLE_OAUTH_REDIRECT_URI") if not v.get(c)]
    if faltam:
        print(f"[ERRO] Faltam no arquivo: {', '.join(faltam)}")
        return 1
    print(f"Testando o ID {v['GOOGLE_WEB_CLIENT_ID'].split('-')[0]}-… e o segredo ({cfg.mascarar(v['GOOGLE_CLIENT_SECRET'])}) no Google ...")
    if v["GOOGLE_CLIENT_SECRET"].startswith("GOCSPX-...") or v["GOOGLE_CLIENT_SECRET"].strip() in ("GOCSPX-", "GOCSPX-..."):
        print("[ERRO] O segredo ainda é o texto de exemplo (GOCSPX-...). Cole o segredo real do Google Cloud.")
        return 1
    try:
        status, resposta = perguntar_ao_google(url_token, v["GOOGLE_WEB_CLIENT_ID"], v["GOOGLE_CLIENT_SECRET"], v["GOOGLE_OAUTH_REDIRECT_URI"])
    except OSError as e:
        print(f"[ERRO] Não consegui falar com o Google ({type(e).__name__}). Confira a internet e tente de novo.")
        return 1
    # o app e o servidor precisam usar o MESMO cliente: confere o ID do app (frontend/.env), se existir
    if args.app_env.exists():
        id_app = cfg.ler_env(args.app_env).get("EXPO_PUBLIC_GOOGLE_WEB_CLIENT_ID", "")
        if id_app and id_app != v["GOOGLE_WEB_CLIENT_ID"]:
            print(f"[ATENÇÃO] O app (frontend/.env) usa OUTRO ID de cliente ({id_app.split('-')[0]}-{id_app.split('-')[1][:6]}…) "
                  f"diferente do que você digitou ({v['GOOGLE_WEB_CLIENT_ID'].split('-')[0]}-{v['GOOGLE_WEB_CLIENT_ID'].split('-')[1][:6]}…). "
                  "O login só funciona se app, Render e segredo forem do MESMO cliente.")
    ok, explicacao = interpretar(status, resposta)
    print(f"[{'OK' if ok else 'ERRO'}] {explicacao}")
    if ok:
        print("\nAgora garanta que o MESMO ID e o MESMO segredo estejam em: Render (GOOGLE_WEB_CLIENT_ID e GOOGLE_CLIENT_SECRET) "
              "e no app (frontend/.env: EXPO_PUBLIC_GOOGLE_WEB_CLIENT_ID).")
        print("\nSe o login ainda falhar com credenciais certas, o problema é outro: veja os logs do Render (linha com \"google/callback\") "
              "e o código entre parênteses que o app agora mostra na tela.")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
