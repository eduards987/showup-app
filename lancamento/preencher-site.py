#!/usr/bin/env python3
"""Preenche os dados do responsável nas páginas do site e confere se está tudo
pronto pra publicar.

Os Termos, a Política de Privacidade e a página de exclusão de conta precisam
dizer QUEM é o responsável pelo ShowUp e ter um e-mail de contato que funcione
(o Google Play confere isso). Esses três dados ficam como {{RESPONSAVEL}},
{{DOCUMENTO}} e {{EMAIL_CONTATO}} até você preencher.

Uso (da raiz do projeto):

  python lancamento/preencher-site.py --responsavel "Seu Nome Completo" \\
      --documento "CPF 000.000.000-00" --email "contato@seudominio.com"

  python lancamento/preencher-site.py --responsavel "Seu Nome" --sem-documento --email "contato@..."
                                                       # não quer mostrar CPF/CNPJ no site: o campo é removido do texto

  python lancamento/preencher-site.py --reaplicar     # preenche de novo com os dados da última vez (use depois de extrair um zip novo)
  python lancamento/preencher-site.py --verificar     # só confere, sem alterar nada

Ao preencher, os dados ficam guardados em lancamento/dados-site.local.json (arquivo só seu, fora do Git). Cada zip novo devolve as
páginas com os campos em branco; `--reaplicar` refaz o preenchimento sem você digitar tudo de novo.

No Windows, se `python` não funcionar, use `py` no lugar.

Rode --verificar antes de cada `firebase deploy`: ele sai com erro (código 1)
se sobrou algum campo em branco ou algum link interno quebrado.
"""
import argparse
import json
import re
import sys
from pathlib import Path

PASTA_PADRAO = Path(__file__).resolve().parent.parent / "firebase-hosting" / "public"
DADOS_LOCAIS = Path(__file__).resolve().parent / "dados-site.local.json"   # fora do Git (ver .gitignore)
CAMPOS = {"responsavel": "{{RESPONSAVEL}}", "documento": "{{DOCUMENTO}}", "email": "{{EMAIL_CONTATO}}"}
EMAIL_RE = re.compile(r"^[^@\s<>\"']+@[^@\s<>\"']+\.[^@\s<>\"']+$")
# Textos de exemplo da própria documentação. Já foram parar no site uma vez (sem sobrar nenhum {{...}}, a trava não via):
# o preenchimento recusa e o --verificar acusa.
EXEMPLOS = ("Seu nome ou razão social", "Seu Nome Completo", "seu@email.com", "contato@seudominio.com",
            "CPF 000.000.000-00", "000.000.000-00", "00.000.000/0000-00")


def paginas(pasta: Path) -> list[Path]:
    return sorted(pasta.glob("*.html"))


def preencher(pasta: Path, valores: dict[str, str]) -> dict[str, int]:
    """Troca os campos pelos valores informados. Devolve quantas trocas por arquivo."""
    if valores.get("email") and not EMAIL_RE.match(valores["email"]):
        raise ValueError(f"e-mail inválido: {valores['email']!r}")
    for chave in CAMPOS:
        if valores.get(chave) and any(ex.lower() in valores[chave].lower() for ex in EXEMPLOS):
            raise ValueError(f"{chave} ainda é o texto de exemplo ({valores[chave]!r}): informe o dado real")
    if valores.get("documento") and valores.get("sem_documento"):
        raise ValueError("use --documento OU --sem-documento, não os dois")
    trocas: dict[str, int] = {}
    for arq in paginas(pasta):
        texto = arq.read_text(encoding="utf-8")
        novo, n = texto, 0
        for chave, token in CAMPOS.items():
            if valores.get(chave):
                n += novo.count(token)
                novo = novo.replace(token, valores[chave])
        if valores.get("sem_documento"):
            # "<strong>Nome</strong> ({{DOCUMENTO}})." vira "<strong>Nome</strong>."
            novo, k = re.subn(r"\s*\(\{\{DOCUMENTO\}\}\)", "", novo)
            n += k
        if n:
            arq.write_text(novo, encoding="utf-8")
            trocas[arq.name] = n
    return trocas


def verificar(pasta: Path) -> list[str]:
    """Problemas que impedem publicar: campo em branco ou link interno quebrado."""
    problemas: list[str] = []
    existentes = {p.stem for p in paginas(pasta)}  # cleanUrls: /termos -> termos.html
    for arq in paginas(pasta):
        texto = arq.read_text(encoding="utf-8")
        for token in sorted(set(re.findall(r"\{\{[A-Z_]+\}\}", texto))):
            problemas.append(f"{arq.name}: campo {token} ainda em branco")
        for ex in EXEMPLOS:
            if ex in texto:
                problemas.append(f"{arq.name}: ainda tem o texto de exemplo {ex!r} no lugar do dado real")
        for alvo in sorted(set(re.findall(r'href="/([a-z0-9-]*)(?:[?#][^"]*)?"', texto))):
            if alvo and alvo not in existentes:
                problemas.append(f"{arq.name}: link para /{alvo}, mas não existe {alvo}.html")
    return problemas


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--responsavel", help="nome completo ou razão social")
    ap.add_argument("--documento", help="CPF ou CNPJ (como quer que apareça, ex: 'CPF 000.000.000-00')")
    ap.add_argument("--sem-documento", action="store_true", help="não mostrar CPF/CNPJ no site (remove o campo)")
    ap.add_argument("--email", help="e-mail de contato que você realmente lê")
    ap.add_argument("--verificar", action="store_true", help="só confere, sem alterar nada")
    ap.add_argument("--reaplicar", action="store_true", help="preenche de novo com os dados guardados da última vez")
    ap.add_argument("--pasta", type=Path, default=PASTA_PADRAO)
    args = ap.parse_args(argv)

    if args.reaplicar:
        if not DADOS_LOCAIS.exists():
            print("Não há dados guardados. Preencha uma vez com --responsavel, --email e --documento (ou --sem-documento).")
            return 1
        try:
            guardados = json.loads(DADOS_LOCAIS.read_text(encoding="utf-8"))
            trocas = preencher(args.pasta, guardados)
        except (ValueError, OSError) as e:
            print(f"ERRO ao reaplicar os dados guardados: {e}")
            return 1
        for nome, n in trocas.items():
            print(f"  {nome}: {n} campo(s) preenchido(s) (dados guardados)")
    elif not args.verificar:
        valores = {"responsavel": args.responsavel, "documento": args.documento, "email": args.email,
                   "sem_documento": args.sem_documento}
        if not any(valores.values()):
            ap.error("informe --responsavel, --documento e --email (ou use --verificar ou --reaplicar)")
        try:
            trocas = preencher(args.pasta, valores)
        except ValueError as e:
            print(f"ERRO: {e}")
            return 1
        for nome, n in trocas.items():
            print(f"  {nome}: {n} campo(s) preenchido(s)")
        # guarda o que foi informado (mesclando com o que já havia) para o --reaplicar; é o mesmo dado que fica público no site
        antigos = json.loads(DADOS_LOCAIS.read_text(encoding="utf-8")) if DADOS_LOCAIS.exists() else {}
        novos = {k: v for k, v in valores.items() if v}
        if novos.get("documento"):
            antigos.pop("sem_documento", None)
        if novos.get("sem_documento"):
            antigos.pop("documento", None)
        antigos.update(novos)
        DADOS_LOCAIS.write_text(json.dumps(antigos, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    problemas = verificar(args.pasta)
    if problemas:
        print("\nAINDA NÃO ESTÁ PRONTO PRA PUBLICAR:")
        for p in problemas:
            print(f"  - {p}")
        return 1
    print("\nOK: nenhum campo em branco e todos os links internos existem. Pode publicar.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
