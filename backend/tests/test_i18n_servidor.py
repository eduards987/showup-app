"""Mensagens de erro do servidor em inglês e espanhol (cabeçalho Accept-Language)."""
import ast
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import offline_env  # noqa: E402,F401

import pytest
from fastapi.testclient import TestClient

import agenda
import i18n_servidor as i18n
import server

RAIZ = Path(__file__).resolve().parents[1]


def mensagens_fixas_do_servidor() -> set[str]:
    """Todo texto literal passado como 2º argumento de HTTPException(...) em server.py e webhooks.py (leitura do código, sem executar)."""
    achadas: set[str] = set()
    for arq in ("server.py", "webhooks.py"):
        arvore = ast.parse((RAIZ / arq).read_text(encoding="utf-8"))
        for no in ast.walk(arvore):
            if isinstance(no, ast.Call) and getattr(no.func, "id", getattr(no.func, "attr", "")) == "HTTPException" and len(no.args) >= 2:
                if isinstance(no.args[1], ast.Constant) and isinstance(no.args[1].value, str):
                    achadas.add(no.args[1].value)
    return achadas


def test_toda_mensagem_fixa_do_servidor_tem_traducao_para_en_e_es():
    faltam = sorted(m for m in mensagens_fixas_do_servidor() | set(agenda.MENSAGENS.values()) if m not in i18n.TRADUCOES)
    assert faltam == [], f"mensagens sem tradução: {faltam}"


def test_nao_sobra_traducao_de_mensagem_que_nao_existe_mais():
    existentes = mensagens_fixas_do_servidor() | set(agenda.MENSAGENS.values())
    assert sorted(set(i18n.TRADUCOES) - existentes) == []


def test_traducoes_completas_e_sem_variaveis_perdidas():
    for pt, (en, es) in i18n.TRADUCOES.items():
        assert en.strip() and es.strip(), pt
        for tr in (en, es):
            assert tr.count('"') == pt.count('"'), f"aspas diferentes em {pt!r}"                     # a frase com "Esqueci minha senha" mantém as aspas
            assert "https://dashboard.stripe.com/connect" in tr if "dashboard.stripe.com" in pt else True


@pytest.mark.parametrize("cabecalho,esperado", [
    ("en-US,en;q=0.9", "en"), ("EN", "en"), ("es-MX", "es"), ("es_AR", "es"), ("pt-BR", "pt"), ("pt", "pt"), ("fr-FR", "pt"),
    ("", "pt"), (None, "pt"), ("*", "pt"), (";;;", "pt"), ("xx-yy,en", "pt"),
])
def test_idioma_da_requisicao(cabecalho, esperado):
    assert i18n.idioma_da_requisicao(cabecalho) == esperado


def test_traduzir_so_troca_o_que_conhece():
    assert i18n.traduzir("Cartão não cadastrado", "en") == "No card on file"
    assert i18n.traduzir("Cartão não cadastrado", "es") == "Tarjeta no registrada"
    assert i18n.traduzir("Cartão não cadastrado", "pt") == "Cartão não cadastrado"
    assert i18n.traduzir("Mensagem nova sem tradução", "en") == "Mensagem nova sem tradução"
    assert i18n.traduzir({"erros": ["lista do pydantic"]}, "en") == {"erros": ["lista do pydantic"]}
    assert i18n.traduzir(None, "es") is None


def test_erro_da_api_sai_no_idioma_pedido_e_o_formato_continua_o_mesmo():
    client = TestClient(server.app)
    pt = client.get("/api/me/connect")                                                   # sem login: 401 do servidor
    assert pt.status_code == 401 and set(pt.json()) == {"detail"}
    en = client.get("/api/me/connect", headers={"Accept-Language": "en"})
    es = client.get("/api/me/connect", headers={"Accept-Language": "es-MX"})
    assert en.status_code == es.status_code == 401
    assert en.json()["detail"] == i18n.TRADUCOES["Missing bearer token"][0] and es.json()["detail"] == "Falta el token de acceso"


def test_erro_de_negocio_em_portugues_ingles_e_espanhol(monkeypatch):
    from test_notificacoes import DB                                                     # banco falso: o teste não fala com Mongo de verdade
    monkeypatch.setattr(server, "db", DB())
    client = TestClient(server.app)
    r = {i: client.get("/api/profissionais/ninguem", headers={"Accept-Language": i}) for i in ("pt-BR", "en", "es")}
    assert all(x.status_code == 404 for x in r.values())
    assert [r["pt-BR"].json()["detail"], r["en"].json()["detail"], r["es"].json()["detail"]] == ["Não encontrado", "Not found", "No encontrado"]
