"""verificar-mongo.py: diagnóstico do erro de banco, sem nunca mostrar a senha."""
import importlib.util
import sys
from pathlib import Path

import pytest
from pymongo.errors import ConfigurationError, InvalidURI, OperationFailure, ServerSelectionTimeoutError

RAIZ = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("verificar_mongo", RAIZ / "lancamento" / "verificar-mongo.py")
vm = importlib.util.module_from_spec(spec)
spec.loader.exec_module(vm)

SENHA = "SenhaSecreta9988"
URL_BOA = f"mongodb+srv://eduardo:{SENHA}@cluster0.abc.mongodb.net/?retryWrites=true"


def arquivo(tmp_path, url=URL_BOA, banco="holdbooked"):
    p = tmp_path / ".env.render"
    p.write_text(f"MONGO_URL={url}\nDB_NAME={banco}\n", encoding="utf-8")
    return str(p)


# ------------------------------------------------------------------ diagnóstico (o erro do Render)
def test_bad_auth_do_atlas_e_explicado_como_problema_de_usuario_e_senha():
    erro = OperationFailure("bad auth : authentication failed, full error: {'ok': 0, 'errmsg': 'bad auth : authentication failed', 'code': 8000}", 8000)
    texto = vm.diagnosticar(erro)
    assert "RECUSOU o usuário/senha" in texto and "A rede está certa" in texto
    assert "Database Users" in texto and "Edit Password" in texto and "Read and write" in texto


def test_sem_permissao_nao_e_confundido_com_senha_errada():
    texto = vm.diagnosticar(OperationFailure("not authorized on holdbooked to execute command { createIndexes }", 13))
    assert "NÃO TEM PERMISSÃO" in texto and "RECUSOU" not in texto


@pytest.mark.parametrize("erro,trecho", [
    (ServerSelectionTimeoutError("timed out"), "0.0.0.0/0"),
    (ConfigurationError("The DNS query name does not exist"), "endereço do cluster"),
    (InvalidURI("Username and password must be escaped"), "caractere especial na senha"),
    (RuntimeError("algo inesperado"), "Erro inesperado (RuntimeError)"),
])
def test_demais_erros_tem_orientacao(erro, trecho):
    assert trecho in vm.diagnosticar(erro)


# ------------------------------------------------------------------ o script inteiro
def test_url_com_erro_de_digitacao_nem_tenta_conectar(tmp_path, capsys, monkeypatch):
    monkeypatch.setattr(vm, "conectar", lambda *a: pytest.fail("não devia conectar com a URL errada"))
    assert vm.main(["--arquivo", arquivo(tmp_path, "mongodb+srv://USUARIO:SENHA@cluster0.abc.mongodb.net/")]) == 1
    assert "texto de exemplo" in capsys.readouterr().out


def test_tudo_certo_sai_com_zero_e_nao_mostra_a_senha(tmp_path, capsys, monkeypatch):
    chamadas = []
    monkeypatch.setattr(vm, "conectar", lambda url, banco, escrita: chamadas.append((banco, escrita)) or ["Conectou e o usuário/senha foram aceitos."])
    assert vm.main(["--arquivo", arquivo(tmp_path), "--testar-escrita"]) == 0
    saida = capsys.readouterr().out
    assert chamadas == [("holdbooked", True)] and "BANCO OK" in saida and SENHA not in saida


def test_bad_auth_real_do_render_sai_com_erro_e_orientacao(tmp_path, capsys, monkeypatch):
    def falha(*a):
        raise OperationFailure(f"bad auth : authentication failed (usuario eduardo senha {SENHA})", 8000)

    monkeypatch.setattr(vm, "conectar", falha)
    assert vm.main(["--arquivo", arquivo(tmp_path)]) == 1
    saida = capsys.readouterr().out
    assert "RECUSOU o usuário/senha" in saida and "Edit Password" in saida
    assert SENHA not in saida                                  # nem a URL nem a mensagem do driver vazam a senha


def test_sem_pymongo_instalado_orienta_a_instalar(tmp_path, capsys, monkeypatch):
    def sem_modulo(*a):
        raise ModuleNotFoundError("No module named 'pymongo'")

    monkeypatch.setattr(vm, "conectar", sem_modulo)
    assert vm.main(["--arquivo", arquivo(tmp_path)]) == 1
    assert 'pip install "pymongo[srv]"' in capsys.readouterr().out


def test_arquivo_inexistente_ou_sem_url(tmp_path, capsys):
    assert vm.main(["--arquivo", str(tmp_path / "nao-existe")]) == 1
    vazio = tmp_path / "vazio.env"
    vazio.write_text("DB_NAME=x\n", encoding="utf-8")
    assert vm.main(["--arquivo", str(vazio)]) == 1
    assert "MONGO_URL não está" in capsys.readouterr().out


# ------------------------------------------------------------------ conectar() com um cliente falso
class ClienteFalso:
    eventos: list = []

    def __init__(self, url, **kw):
        ClienteFalso.eventos.append(("abrir", kw.get("serverSelectionTimeoutMS")))
        self.admin = self
        self._colecao = self

    def command(self, nome):
        ClienteFalso.eventos.append(("comando", nome))

    def __getitem__(self, nome):
        ClienteFalso.eventos.append(("banco/colecao", nome))
        return self

    def list_collection_names(self):
        return ["users", "agendamentos"]

    def insert_one(self, doc):
        ClienteFalso.eventos.append(("gravou", doc))

    def delete_many(self, filtro):
        ClienteFalso.eventos.append(("apagou", filtro))

    def close(self):
        ClienteFalso.eventos.append(("fechou",))


def test_conectar_faz_ping_lista_e_so_grava_se_pedido(monkeypatch):
    import pymongo
    monkeypatch.setattr(pymongo, "MongoClient", ClienteFalso)
    ClienteFalso.eventos = []
    ok = vm.conectar(URL_BOA, "holdbooked", False)
    assert len(ok) == 2 and ("comando", "ping") in ClienteFalso.eventos and ("fechou",) in ClienteFalso.eventos
    assert not any(e[0] in ("gravou", "apagou") for e in ClienteFalso.eventos)       # por padrão NÃO escreve no banco
    ClienteFalso.eventos = []
    ok = vm.conectar(URL_BOA, "holdbooked", True)
    assert len(ok) == 3 and ("gravou", {"teste": True}) in ClienteFalso.eventos and ("apagou", {"teste": True}) in ClienteFalso.eventos
