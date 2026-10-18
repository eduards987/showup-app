#!/usr/bin/env python3
"""Troca o endereço do site em TODOS os arquivos do projeto, de uma vez (sem esquecer nenhum).

O endereço atual (showup-509120.web.app) está gravado em páginas do site (link canônico, imagem de pré-visualização, sitemap,
robots), no app (frontend/src/lib/legal.ts) e no servidor (valor padrão de PUBLIC_WEB_BASE_URL). Quando você tiver um domínio
próprio, rode:

  py lancamento\\trocar-dominio.py --para meusite.com.br

  py lancamento\\trocar-dominio.py --para meusite.com.br --simular   # só mostra o que mudaria, sem alterar nada

O script NÃO mexe no seu frontend/.env nem nas variáveis do Render (são seus): no fim ele lista o que você precisa ajustar lá.
Veja lancamento/DOMINIO.md para o passo a passo completo (comprar o domínio, ligar no Firebase, DNS).
"""
import argparse
import re
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
DOMINIO_PADRAO = "showup-509120.web.app"
HOST_RE = re.compile(r"^(?!-)[a-z0-9-]{1,63}(?<!-)(\.(?!-)[a-z0-9-]{1,63}(?<!-))+$")

# onde o endereço fica gravado (relativo à raiz do projeto)
PADROES = (
    "firebase-hosting/public/*.html",
    "firebase-hosting/public/*.xml",
    "firebase-hosting/public/*.txt",
    "frontend/src/lib/legal.ts",
    "frontend/.env.example",
    "backend/server.py",
)


def validar_host(host: str) -> str:
    h = host.strip().lower()
    if not HOST_RE.match(h):
        raise ValueError(f"'{host}' não é um domínio válido. Informe só o nome, sem http:// e sem barras (ex.: meusite.com.br).")
    return h


def arquivos(raiz: Path) -> list[Path]:
    achados: list[Path] = []
    for padrao in PADROES:
        achados += sorted(raiz.glob(padrao))
    return achados


def trocar(raiz: Path, de: str, para: str, aplicar: bool = True) -> dict[str, int]:
    """Devolve {arquivo: quantas vezes o endereço aparecia}. Só grava se `aplicar`."""
    trocas: dict[str, int] = {}
    for arq in arquivos(raiz):
        texto = arq.read_text(encoding="utf-8")
        n = texto.count(de)
        if n:
            trocas[str(arq.relative_to(raiz)).replace("\\", "/")] = n
            if aplicar:
                arq.write_text(texto.replace(de, para), encoding="utf-8")
    return trocas


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--para", required=True, help="o domínio novo, ex.: meusite.com.br")
    ap.add_argument("--de", default=DOMINIO_PADRAO, help=f"o domínio atual (padrão: {DOMINIO_PADRAO})")
    ap.add_argument("--simular", action="store_true", help="só mostra o que mudaria")
    ap.add_argument("--raiz", type=Path, default=RAIZ, help="pasta do projeto (uso interno)")
    args = ap.parse_args(argv)
    try:
        novo, antigo = validar_host(args.para), validar_host(args.de)
    except ValueError as e:
        print(f"ERRO: {e}")
        return 1
    if novo == antigo:
        print("O domínio novo é igual ao atual: nada a trocar.")
        return 0
    trocas = trocar(args.raiz, antigo, novo, aplicar=not args.simular)
    if not trocas:
        print(f"Nada a trocar: '{antigo}' não aparece nos arquivos (já foi trocado?).")
        return 0
    print(("Mudaria" if args.simular else "Trocado") + f" '{antigo}' por '{novo}':")
    for nome, n in trocas.items():
        print(f"  {nome}: {n} ocorrência(s)")
    print(f"""
Agora, FORA do código (são seus):
  1. Render > Environment: PUBLIC_WEB_BASE_URL=https://{novo}
  2. Render > Environment: ALLOWED_ORIGINS = a lista atual + https://{novo}   (se esquecer, a página de agendamento deixa de funcionar)
  3. frontend\\.env: EXPO_PUBLIC_WEB_URL=https://{novo}   (depois: npx expo start -c)
  4. Publique o site: cd firebase-hosting ; firebase deploy --only hosting --project showup-509120
  5. Faça commit e push (o Render atualiza o servidor).
  6. Confira: py lancamento\\verificar-producao.py --backend https://showup-backend-s9y1.onrender.com --site https://{novo} --completo""")
    return 0


if __name__ == "__main__":
    sys.exit(main())
