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
