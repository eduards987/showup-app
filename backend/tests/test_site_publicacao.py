"""O script que impede publicar o site com campo em branco ou link quebrado."""
import importlib.util
import shutil
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("preencher_site", RAIZ / "lancamento" / "preencher-site.py")
ps = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ps)

SITE = RAIZ / "firebase-hosting" / "public"


@pytest.fixture
def pasta(tmp_path):
    destino = tmp_path / "public"
    shutil.copytree(SITE, destino)
    return destino


def test_site_do_repositorio_esta_com_os_campos_em_branco_de_proposito(pasta):
    problemas = ps.verificar(pasta)
    campos = {p.split("campo ")[1].split(" ")[0] for p in problemas if "campo" in p}
    assert campos == {"{{RESPONSAVEL}}", "{{DOCUMENTO}}", "{{EMAIL_CONTATO}}"}
    assert not [p for p in problemas if "link" in p]   # e nenhum link interno quebrado


def test_preencher_resolve_tudo_e_libera(pasta):
    trocas = ps.preencher(pasta, {"responsavel": "Ana Lima", "documento": "CPF 111.222.333-44", "email": "oi@ana.com"})
    assert set(trocas) == {"termos.html", "excluir-conta.html", "privacidade.html"}
    assert ps.verificar(pasta) == []
    termos = (pasta / "termos.html").read_text(encoding="utf-8")
    assert "Ana Lima" in termos and "CPF 111.222.333-44" in termos and 'mailto:oi@ana.com' in termos


def test_preencher_parcial_ainda_acusa_o_que_falta(pasta):
    ps.preencher(pasta, {"email": "oi@ana.com"})
    assert all("EMAIL_CONTATO" not in p for p in ps.verificar(pasta))
    assert any("RESPONSAVEL" in p for p in ps.verificar(pasta))


def test_email_invalido_e_recusado_e_nada_e_alterado(pasta):
    antes = (pasta / "termos.html").read_text(encoding="utf-8")
    with pytest.raises(ValueError):
        ps.preencher(pasta, {"email": "isso-nao-e-email"})
    assert (pasta / "termos.html").read_text(encoding="utf-8") == antes


def test_link_interno_quebrado_e_detectado(pasta):
    (pasta / "termos.html").unlink()
    problemas = ps.verificar(pasta)
    assert any("link para /termos" in p for p in problemas)


def test_linha_de_comando_sai_com_erro_enquanto_houver_campo_em_branco(pasta):
    assert ps.main(["--verificar", "--pasta", str(pasta)]) == 1
    assert ps.main(["--responsavel", "Ana", "--documento", "CPF 1", "--email", "a@b.co", "--pasta", str(pasta)]) == 0


# ------------------------------------------------------------------ CPF/CNPJ opcional
def test_sem_documento_remove_o_campo_do_texto_sem_deixar_parenteses_soltos(pasta):
    ps.preencher(pasta, {"responsavel": "Ana Lima", "email": "oi@ana.com", "sem_documento": True})
    assert ps.verificar(pasta) == []
    for nome in ("termos.html", "privacidade.html"):
        texto = (pasta / nome).read_text(encoding="utf-8")
        assert "<strong>Ana Lima</strong>." in texto and "()" not in texto and "{{" not in texto


def test_documento_e_sem_documento_juntos_sao_recusados_e_nada_muda(pasta):
    antes = (pasta / "termos.html").read_text(encoding="utf-8")
    with pytest.raises(ValueError):
        ps.preencher(pasta, {"responsavel": "Ana", "documento": "CPF 1", "sem_documento": True})
    assert (pasta / "termos.html").read_text(encoding="utf-8") == antes


def test_linha_de_comando_aceita_sem_documento(pasta):
    assert ps.main(["--responsavel", "Ana", "--sem-documento", "--email", "a@b.co", "--pasta", str(pasta)]) == 0


# ------------------------------------------------------------------ trava de publicação do Firebase
HOSPEDAGEM = RAIZ / "firebase-hosting"


def test_firebase_json_valido_com_a_trava_cleanurls_e_cache():
    import json
    hosting = json.loads((HOSPEDAGEM / "firebase.json").read_text(encoding="utf-8"))["hosting"]
    assert hosting["predeploy"] == ["node verificar-antes-de-publicar.js"]
    assert hosting["cleanUrls"] is True and hosting["public"] == "public"
    cabecalhos = {h["key"]: h["value"] for bloco in hosting["headers"] for h in bloco["headers"]}
    assert cabecalhos["Cache-Control"] == "no-cache"


@pytest.mark.skipif(shutil.which("node") is None, reason="Node não instalado")
def test_a_trava_cancela_o_deploy_com_campo_em_branco_e_libera_depois_de_preencher(tmp_path):
    import subprocess
    copia = tmp_path / "firebase-hosting"
    shutil.copytree(HOSPEDAGEM, copia)
    script = copia / "verificar-antes-de-publicar.js"
    r = subprocess.run(["node", str(script)], capture_output=True, text=True, cwd=copia)
    assert r.returncode == 1 and "PUBLICAÇÃO CANCELADA" in r.stderr
    for campo in ("{{RESPONSAVEL}}", "{{EMAIL_CONTATO}}", "termos.html", "privacidade.html"):
        assert campo in r.stderr
    ps.preencher(copia / "public", {"responsavel": "Ana Lima", "email": "oi@ana.com", "sem_documento": True})
    r = subprocess.run(["node", str(script)], capture_output=True, text=True, cwd=copia)
    assert r.returncode == 0 and "pode publicar" in r.stdout
