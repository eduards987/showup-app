#!/usr/bin/env python3
"""Testa a conexão com o MongoDB Atlas e explica, em português, por que falhou (sem nunca mostrar a senha).

Serve para o erro "bad auth : authentication failed" do Render, e para qualquer outro erro de banco.
Precisa do pymongo no seu computador (uma vez só):  pip install "pymongo[srv]"

Uso (da raiz do projeto):

  python lancamento/verificar-mongo.py                          # lê MONGO_URL e DB_NAME de backend/.env
  python lancamento/verificar-mongo.py --arquivo .env.render    # lê de outro arquivo
  python lancamento/verificar-mongo.py --testar-escrita         # também grava e apaga 1 documento de teste

O servidor precisa de PERMISSÃO DE ESCRITA (ele cria índices ao subir): use --testar-escrita para conferir isso.
Sai com código 1 se algo falhar.
"""
import argparse
import importlib.util
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent


def _carregar_config():
    """Reaproveita a leitura de .env e a análise da URL do verificar-config.py."""
    spec = importlib.util.spec_from_file_location("verificar_config", Path(__file__).with_name("verificar-config.py"))
    modulo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modulo)
    return modulo


def diagnosticar(exc: Exception) -> str:
    """Traduz o erro do pymongo no que você deve fazer. Nunca inclui a senha."""
    nome = type(exc).__name__
    texto = str(exc)
    codigo = getattr(exc, "code", None)
    if nome == "OperationFailure" and (codigo == 8000 or "auth" in texto.lower()) and codigo != 13:
        return ("O Atlas RECEBEU a conexão mas RECUSOU o usuário/senha (\"bad auth\"). A rede está certa; o problema é a credencial:\n"
                "   1. No Atlas: Database & Network Access > Database Users. Confira o NOME do usuário (não é o e-mail do seu login do Atlas).\n"
                "   2. Clique em Edit > Edit Password e defina uma senha NOVA só com letras e números (sem @ : / ? # %).\n"
                "   3. Garanta o papel \"Read and write to any database\" para esse usuário.\n"
                "   4. Atualize a MONGO_URL com o usuário e a senha NOVOS (sem os sinais < >), aqui e no Render, e rode este teste de novo.")
    if nome == "OperationFailure" and (codigo == 13 or "not authorized" in texto.lower() or "unauthorized" in texto.lower()):
        return ("A senha está certa, mas o usuário NÃO TEM PERMISSÃO para esta operação. No Atlas > Database Users > Edit, "
                "dê o papel \"Read and write to any database\" (o servidor precisa escrever para criar índices).")
    if nome == "ServerSelectionTimeoutError":
        return ("Não consegui falar com o Atlas (tempo esgotado). Causas comuns:\n"
                "   1. Network Access: o Atlas só aceita IPs liberados. Adicione 0.0.0.0/0 (qualquer origem; o Render gratuito não tem IP fixo) "
                "ou o seu IP atual para este teste.\n   2. Sem internet, ou o cluster está pausado (no plano gratuito ele pausa sozinho: retome no Atlas).")
    if nome == "ConfigurationError":
        return ("O endereço do cluster não foi encontrado (DNS) ou a URL está incompleta. Copie de novo a connection string em "
                "Atlas > Database > Connect > Drivers. Se estiver usando mongodb+srv://, instale: pip install \"pymongo[srv]\".")
    if nome == "InvalidURI":
        return "A URL está mal formada. O motivo mais comum é um caractere especial na senha (@ : / ? # %). Use uma senha só com letras e números."
    return f"Erro inesperado ({nome}). Mensagem do driver: {texto[:200]}"


def conectar(url: str, banco: str, testar_escrita: bool) -> list[str]:
    """Faz o teste de verdade. Devolve as mensagens de sucesso; levanta a exceção do pymongo se falhar."""
    from pymongo import MongoClient  # importado aqui: o resto do script funciona sem o pymongo

    ok: list[str] = []
    cliente = MongoClient(url, serverSelectionTimeoutMS=10000)
    try:
        cliente.admin.command("ping")
        ok.append("Conectou e o usuário/senha foram aceitos.")
        colecoes = cliente[banco].list_collection_names()
        ok.append(f"Banco '{banco}' acessível ({len(colecoes)} coleções).")
        if testar_escrita:
            c = cliente[banco]["_showup_verificacao"]
            c.insert_one({"teste": True})
            c.delete_many({"teste": True})
            ok.append("Permissão de escrita confirmada (gravou e apagou 1 documento de teste).")
    finally:
        cliente.close()
    return ok


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--arquivo", type=Path, default=RAIZ / "backend" / ".env", help="arquivo com MONGO_URL e DB_NAME")
    ap.add_argument("--testar-escrita", action="store_true")
    args = ap.parse_args(argv)

    cfg = _carregar_config()
    if not args.arquivo.exists():
        print(f"Arquivo não encontrado: {args.arquivo}")
        return 1
    valores = cfg.ler_env(args.arquivo)
    url, banco = valores.get("MONGO_URL", ""), valores.get("DB_NAME", "holdbooked")
    if not url:
        print(f"MONGO_URL não está em {args.arquivo}.")
        return 1

    print(f"Testando {cfg.mascarar(url)} · banco '{banco}' ...")
    problemas = cfg.problemas_mongo_url(url)
    if problemas:
        for p in problemas:
            print(f"[ERRO] A URL {p}")
        print("\nCorrija a URL e rode de novo (o teste de conexão só vale com a URL certa).")
        return 1
    try:
        for msg in conectar(url, banco, args.testar_escrita):
            print(f"[OK] {msg}")
    except ModuleNotFoundError:
        print('[ERRO] Falta o pymongo no seu computador. Instale com:  pip install "pymongo[srv]"  e rode de novo.')
        return 1
    except Exception as e:  # noqa: BLE001 — qualquer falha vira um diagnóstico
        print(f"[ERRO] {diagnosticar(e)}")
        return 1
    print("\nBANCO OK: pode usar esta MONGO_URL no Render.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
