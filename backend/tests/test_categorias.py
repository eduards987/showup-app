"""Categorias de profissional: lista por grupo no servidor, nomes no app em 3 idiomas, e a página inicial do site, tudo em sincronia."""
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import offline_env  # noqa: E402,F401

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

import server

RAIZ = Path(__file__).resolve().parents[2]
ORIGINAIS = ["fitness", "terapia", "consultoria", "estetica", "coaching", "nutricao"]       # já gravados nos perfis: o código NUNCA muda


def _casos(arquivo_ts: str, trecho: str) -> dict[str, str]:
    return {k: json.loads(v) for k, v in re.findall(r'case "(\w+)": return t\(("(?:[^"\\]|\\.)*")\);', trecho)}


def _nomes_do_app():
    ts = (RAIZ / "frontend" / "src" / "lib" / "categorias.ts").read_text(encoding="utf-8")
    antes, depois = ts.split("export function nomeDoGrupo")
    return _casos("categorias.ts", antes), _casos("categorias.ts", depois)


def _dicionario(nome):
    texto = (RAIZ / "frontend" / "src" / "i18n" / f"{nome}.ts").read_text(encoding="utf-8")
    return {json.loads(k): json.loads(v) for k, v in re.findall(r'^\s+("(?:[^"\\]|\\.)*"): ("(?:[^"\\]|\\.)*"),$', texto, flags=re.M)}


def test_os_seis_codigos_antigos_continuam_valendo():
    assert set(ORIGINAIS) <= set(server.CATEGORIAS)


def test_lista_de_categorias_e_bem_formada():
    assert len(server.CATEGORIAS) >= 30 and len(set(server.CATEGORIAS)) == len(server.CATEGORIAS)       # sem repetição entre grupos
    assert all(re.fullmatch(r"[a-z]+(_[a-z]+)*", c) for c in server.CATEGORIAS)
    assert all(cs for cs in server.CATEGORIAS_POR_GRUPO.values())                                       # nenhum grupo vazio
    assert server.CATEGORIAS == [c for cs in server.CATEGORIAS_POR_GRUPO.values() for c in cs]


def test_rota_lista_categorias_planas_grupos_e_o_maximo():
    r = TestClient(server.app).get("/api/categorias").json()
    assert r["categorias"] == server.CATEGORIAS and r["maximo"] == 3
    assert [g["grupo"] for g in r["grupos"]] == list(server.CATEGORIAS_POR_GRUPO)
    assert [c for g in r["grupos"] for c in g["categorias"]] == r["categorias"]


@pytest.mark.parametrize("escolha", [["odontologia"], ["psicologia", "terapia"], ["barbearia", "unhas", "maquiagem"], ["fitness"], ["outros"]])
def test_profissional_pode_escolher_de_1_a_3_categorias_novas_ou_antigas(escolha):
    assert server.CategoriasRequest(categorias=escolha).categorias == escolha


@pytest.mark.parametrize("escolha,motivo", [
    ([], "nenhuma"), (["fitness", "terapia", "coaching", "nutricao"], "mais de 3"), (["fitness", "fitness"], "repetida"),
    (["nao_existe"], "código desconhecido"), (["fitness", "Odontologia"], "maiúscula não é o código"),
])
def test_escolhas_invalidas_sao_recusadas(escolha, motivo):
    with pytest.raises(ValidationError):
        server.CategoriasRequest(categorias=escolha)


def test_servidor_recusa_categoria_desconhecida_com_422(monkeypatch):
    async def usuario(auth):
        return {"user_id": "u1", "role": "profissional", "name": "Eduardo", "email": "e@x.com"}

    monkeypatch.setattr(server, "_current_user", usuario)
    client = TestClient(server.app)
    for corpo in ({"categorias": ["nao_existe"]}, {"categorias": ["fitness", "fitness"]}, {"categorias": []}, {"categorias": ["a", "b", "c", "d"]}):
        assert client.put("/api/me/categorias", json=corpo).status_code == 422, corpo


def test_todo_codigo_do_servidor_tem_nome_no_app_e_todo_grupo_tambem():
    cats, grupos = _nomes_do_app()
    assert set(cats) == set(server.CATEGORIAS), (set(cats) ^ set(server.CATEGORIAS))
    assert set(grupos) == set(server.CATEGORIAS_POR_GRUPO), (set(grupos) ^ set(server.CATEGORIAS_POR_GRUPO))


def test_todo_nome_de_categoria_e_grupo_tem_traducao_em_ingles_e_espanhol():
    cats, grupos = _nomes_do_app()
    en, es = _dicionario("en"), _dicionario("es")
    for nome in list(cats.values()) + list(grupos.values()):
        assert nome in en and nome in es, nome
    assert en["Dentista"] == "Dentist" and es["Barbearia"] == "Barbería" and en["Saúde"] == "Health" and es["Mascotas" if False else "Pets"] == "Mascotas"


def test_nomes_de_categoria_nao_se_repetem_para_nao_confundir_quem_escolhe():
    cats, _ = _nomes_do_app()
    nomes = list(cats.values())
    assert len(set(nomes)) == len(nomes), [n for n in nomes if nomes.count(n) > 1]


def test_busca_usa_a_lista_do_servidor_e_nao_uma_copia_fixa():
    busca = (RAIZ / "frontend" / "app" / "(app)" / "search.tsx").read_text(encoding="utf-8")
    assert '"/api/categorias"' in busca and 'const CATEGORIAS = ["' not in busca


def test_pagina_inicial_lista_para_quem_e_o_showup_com_todas_as_categorias():
    cats, grupos = _nomes_do_app()
    inicio = (RAIZ / "firebase-hosting" / "public" / "index.html").read_text(encoding="utf-8")
    import html as h
    assert 'id="para-quem"' in inicio and 'href="#para-quem"' in inicio
    for codigo, nome in cats.items():
        if codigo != "outros":
            assert f"<li>{h.escape(nome)}</li>" in inicio, f"a página inicial não lista {nome!r}"
    for g, nome in grupos.items():
        if g != "outros":
            assert f"<h3>{h.escape(nome)}</h3>" in inicio, nome
