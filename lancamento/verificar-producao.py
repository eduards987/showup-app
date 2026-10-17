#!/usr/bin/env python3
"""Confere se o que você publicou está mesmo no ar (backend no Render + site no Firebase).

Roda no seu computador, só com o Python (sem instalar nada). Da raiz do projeto:

  python lancamento/verificar-producao.py --backend https://showup-backend-s9y1.onrender.com --site https://showup-509120.web.app

Com --completo, exige também os Termos, a Privacidade e a Exclusão de conta publicados
(use depois de preencher os dados com preencher-site.py).

Resultado: [OK] passou · [ATENÇÃO] vale olhar, não impede · [FALHOU] algo não subiu / está errado.
Sai com código 1 se qualquer item FALHOU. A primeira chamada ao backend pode levar ~1 minuto
(o Render gratuito "dorme"); o script espera.
"""
import argparse
import json
import sys
import urllib.error
import urllib.request

VERSAO_PAGINA = "v2026.10.15"
EMAIL_ANTIGO = "privacidade@showup.app"


def requisitar(url: str, metodo: str = "GET", corpo: bytes | None = None, timeout: int = 90):
    """Devolve (status, cabecalhos, texto). Erros HTTP viram resposta normal; falha de rede vira (0, {}, motivo)."""
    req = urllib.request.Request(url, data=corpo, method=metodo, headers={"User-Agent": "showup-verificador/1.0"})
    if corpo is not None:
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, dict(r.headers), r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, dict(e.headers), e.read().decode("utf-8", "replace")
    except Exception as e:  # sem rede, DNS, timeout
        return 0, {}, f"{type(e).__name__}: {e}"


class Relatorio:
    def __init__(self):
        self.itens: list[tuple[str, str]] = []

    def ok(self, msg): self.itens.append(("OK", msg))
    def atencao(self, msg): self.itens.append(("ATENÇÃO", msg))
    def falhou(self, msg): self.itens.append(("FALHOU", msg))

    @property
    def codigo_saida(self) -> int:
        return 1 if any(n == "FALHOU" for n, _ in self.itens) else 0

    def imprimir(self):
        for nivel, msg in self.itens:
            print(f"[{nivel}] {msg}")
        falhas = sum(1 for n, _ in self.itens if n == "FALHOU")
        avisos = sum(1 for n, _ in self.itens if n == "ATENÇÃO")
        print(f"\n{'TUDO CERTO' if not falhas else 'ATENÇÃO: ' + str(falhas) + ' item(ns) FALHOU'}"
              f" — {len(self.itens) - falhas - avisos} ok, {avisos} aviso(s), {falhas} falha(s).")


def verificar_backend(base: str, rel: Relatorio) -> None:
    base = base.rstrip("/")
    status, _, texto = requisitar(f"{base}/api/")
    if status == 0:
        rel.falhou(f"Backend não respondeu ({texto}). Confira a URL e se o deploy no Render terminou ('Live').")
        return
    try:
        info = json.loads(texto)
    except ValueError:
        info = {}
    if status != 200 or info.get("status") != "ok":
        rel.falhou(f"GET /api/ devolveu {status} — o backend não está saudável. Veja os logs no Render.")
        return
    rel.ok("Backend no ar (GET /api/ → ok).")
    if info.get("gateway") == "stripe":
        rel.ok("Pagamentos com o Stripe real ativados (gateway = stripe).")
    else:
        rel.falhou(f"gateway = {info.get('gateway')!r}: o backend está em modo SIMULADO. "
                   "STRIPE_API_KEY está vazia nas variáveis do Render (o modo simulado NÃO cobra ninguém).")

    # a rota do painel do Stripe só existe na versão nova do backend
    status, _, _ = requisitar(f"{base}/api/me/connect/painel", "POST", b"{}")
    if status in (401, 403):
        rel.ok("Backend na versão NOVA (rota do painel do Stripe existe e exige login).")
    elif status in (404, 405):
        rel.falhou("Backend ainda está na versão ANTIGA (rota /me/connect/painel não existe). "
                   "O deploy no Render não terminou ou não pegou o último commit.")
    else:
        rel.atencao(f"Rota do painel do Stripe respondeu {status} (esperado 401).")

    # quais jeitos de entrar o servidor oferece (Microsoft e e-mail dependem de configuração)
    status, _, texto = requisitar(f"{base}/api/auth/metodos")
    if status == 200:
        try:
            metodos = json.loads(texto)
        except ValueError:
            metodos = {}
        ativos = [nome for chave, nome in (("google", "Google"), ("microsoft", "Microsoft"), ("email", "e-mail e senha"))
                  if metodos.get(chave)]
        rel.ok("Login disponível: " + (", ".join(ativos) or "nenhum") + ".")
        if not metodos.get("microsoft"):
            rel.atencao("Login com Microsoft desligado (faltam MICROSOFT_* no Render). Tudo bem se você não quer essa opção ainda.")
        if not metodos.get("email"):
            rel.atencao("Cadastro por e-mail desligado (faltam SMTP_* no Render). Tudo bem se você não quer essa opção ainda.")
    elif status in (404, 405):
        rel.atencao("O backend ainda não tem a lista de logins (/api/auth/metodos): versão antiga.")

    # o webhook precisa existir e RECUSAR chamadas sem assinatura do Stripe
    status, _, _ = requisitar(f"{base}/api/webhooks/stripe", "POST", b"{}")
    if status == 400:
        rel.ok("Webhook do Stripe existe e recusa chamadas sem assinatura.")
    elif status == 500:
        rel.falhou("Webhook respondeu 500: falta STRIPE_WEBHOOK_SECRET nas variáveis do Render.")
    elif status in (404, 405):
        rel.falhou("Rota do webhook (/api/webhooks/stripe) não existe nesse backend.")
    else:
        rel.atencao(f"Webhook respondeu {status} a uma chamada sem assinatura (esperado 400).")


def buscar_pagina(site: str, caminho: str):
    """Tenta a URL limpa do Firebase (/termos); se só abrir com .html, devolve também esse aviso."""
    status, cab, texto = requisitar(f"{site}/{caminho}", timeout=30)
    if status == 200:
        return status, cab, texto, False
    status2, cab2, texto2 = requisitar(f"{site}/{caminho}.html", timeout=30)
    if status2 == 200:
        return status2, cab2, texto2, True
    return status, cab, texto, False


def verificar_site(site: str, completo: bool, rel: Relatorio) -> None:
    site = site.rstrip("/")
    status, cab, texto, so_html = buscar_pagina(site, "agendar")
    if status != 200:
        rel.falhou(f"Página de agendamento não abre (/agendar → {status}). O deploy do Firebase não terminou?")
    else:
        if 'id="selectData"' in texto and "selectHora" in texto:
            rel.ok("Link de agendamento com os dropdowns de data e horário.")
        else:
            rel.falhou("Link de agendamento está na versão ANTIGA (sem os dropdowns). Publique de novo e atualize com Ctrl+F5.")
        if VERSAO_PAGINA in texto:
            rel.ok(f"Versão da página confere ({VERSAO_PAGINA}).")
        else:
            rel.falhou(f"Versão {VERSAO_PAGINA} não aparece na página: o que está no ar não é o último pacote.")
        if "no-cache" in {v.strip() for v in cab.get("Cache-Control", cab.get("cache-control", "")).split(",")}:
            rel.ok("Página sempre revalidada (Cache-Control: no-cache).")
        else:
            rel.atencao("Cache-Control sem no-cache: o navegador pode mostrar uma cópia antiga por até 1h. "
                        "Publique também o firebase.json novo.")
        if so_html:
            rel.atencao("A página só abre com .html (URL limpa /agendar não funciona): confira o firebase.json.")

    for caminho, rotulo in (("termos", "Termos de Uso"), ("privacidade", "Política de Privacidade"),
                            ("excluir-conta", "Exclusão de conta")):
        status, _, texto, _ = buscar_pagina(site, caminho)
        if status != 200:
            msg = f"{rotulo} não está publicado (/{caminho} → {status})."
            (rel.falhou if completo else rel.atencao)(msg + ("" if completo else " Tudo bem se ainda não preencheu os dados."))
            continue
        if "{{" in texto:
            rel.falhou(f"{rotulo} publicado COM campo em branco ({{{{...}}}}). Rode preencher-site.py e publique de novo.")
        elif EMAIL_ANTIGO in texto:
            rel.atencao(f"{rotulo} ainda usa o e-mail antigo {EMAIL_ANTIGO}. Troque por um e-mail que você leia.")
        else:
            rel.ok(f"{rotulo} publicado e completo.")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--backend", required=True, help="URL do backend (Render)")
    ap.add_argument("--site", required=True, help="URL do site (Firebase)")
    ap.add_argument("--completo", action="store_true", help="exige Termos, Privacidade e Exclusão publicados")
    args = ap.parse_args(argv)
    rel = Relatorio()
    print("Verificando o backend (a primeira chamada pode demorar ~1 minuto)...")
    verificar_backend(args.backend, rel)
    print("Verificando o site...")
    verificar_site(args.site, args.completo, rel)
    print()
    rel.imprimir()
    return rel.codigo_saida


if __name__ == "__main__":
    sys.exit(main())
