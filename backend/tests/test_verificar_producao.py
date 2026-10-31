"""O verificador de produção, contra servidores locais que simulam cada situação."""
import functools
import http.server
import importlib.util
import json
import threading
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("verificar_producao", RAIZ / "lancamento" / "verificar-producao.py")
vp = importlib.util.module_from_spec(spec)
spec.loader.exec_module(vp)

AGENDAR_NOVO = '<meta name="versao-da-pagina" content="v2026.10.30"><select id="selectData"></select><select id="selectHora"></select>'
AGENDAR_ANTIGO = '<div class="slot-grid"></div>'


def _servidor(rotas, cabecalhos=None):
    """rotas: {(metodo, caminho): (status, corpo)}; desconhecida → 404."""
    class H(http.server.BaseHTTPRequestHandler):
        def _resp(self):
            status, corpo = rotas.get((self.command, self.path.split("?")[0]), (404, "nao existe"))
            dados = corpo.encode()
            self.send_response(status)
            for k, v in (cabecalhos or {}).items():
                self.send_header(k, v)
            self.send_header("Content-Length", str(len(dados)))
            self.end_headers()
            self.wfile.write(dados)

        do_GET = do_POST = _resp

        def log_message(self, *a):
            pass

    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, f"http://127.0.0.1:{srv.server_address[1]}"


@pytest.fixture
def servidores():
    abertos = []

    def montar(backend=None, site=None, cab_site=None):
        b_rotas = {("GET", "/api/"): (200, json.dumps({"service": "ShowUp API", "status": "ok", "gateway": "stripe"})),
                   ("GET", "/api/auth/metodos"): (200, json.dumps({"google": True, "microsoft": True, "email": True})),
                   ("POST", "/api/me/connect/painel"): (401, "{}"),
                   ("POST", "/api/me/notificacoes/teste"): (401, "{}"),
                   ("GET", "/api/me/link-publico"): (401, "{}"),
                   ("POST", "/api/webhooks/stripe"): (400, "{}")}
        b_rotas.update(backend or {})
        s_rotas = {("GET", "/agendar"): (200, AGENDAR_NOVO), ("GET", "/termos"): (200, "Termos completos"),
                   ("GET", "/"): (200, '<main id="conteudo">ShowUp</main>'), ("GET", "/p/verificacao-showup"): (200, AGENDAR_NOVO),
                   ("GET", "/pagina-que-nao-existe-showup"): (404, "Página não encontrada — ShowUp"),
                   ("GET", "/robots.txt"): (200, "User-agent: *\nSitemap: https://x/sitemap.xml"),
                   ("GET", "/privacidade"): (200, "Privacidade completa"), ("GET", "/excluir-conta"): (200, "Exclusão")}
        s_rotas.update(site or {})
        sb, ub = _servidor(b_rotas)
        ss, us = _servidor(s_rotas, cab_site if cab_site is not None else {"Cache-Control": "no-cache"})
        abertos.extend([sb, ss])
        return ub, us

    yield montar
    for s in abertos:
        s.shutdown()


def _rodar(ub, us, completo=False):
    return vp.main(["--backend", ub, "--site", us] + (["--completo"] if completo else []))


def test_tudo_certo_sai_com_zero(servidores, capsys):
    ub, us = servidores()
    assert _rodar(ub, us, completo=True) == 0
    assert "TUDO CERTO" in capsys.readouterr().out


def test_backend_na_versao_antiga_falha(servidores, capsys):
    ub, us = servidores(backend={("POST", "/api/me/connect/painel"): (404, "{}")})
    assert _rodar(ub, us) == 1
    assert "versão ANTIGA" in capsys.readouterr().out


def test_gateway_simulado_falha(servidores, capsys):
    ub, us = servidores(backend={("GET", "/api/"): (200, json.dumps({"status": "ok", "gateway": "mock"}))})
    assert _rodar(ub, us) == 1
    assert "STRIPE_API_KEY" in capsys.readouterr().out


def test_webhook_sem_segredo_falha(servidores, capsys):
    ub, us = servidores(backend={("POST", "/api/webhooks/stripe"): (500, "{}")})
    assert _rodar(ub, us) == 1
    assert "STRIPE_WEBHOOK_SECRET" in capsys.readouterr().out


def test_pagina_de_agendamento_antiga_falha(servidores, capsys):
    ub, us = servidores(site={("GET", "/agendar"): (200, AGENDAR_ANTIGO)})
    assert _rodar(ub, us) == 1
    assert "ANTIGA (sem os dropdowns)" in capsys.readouterr().out


def test_sem_cache_no_cache_so_avisa(servidores, capsys):
    ub, us = servidores(cab_site={})
    assert _rodar(ub, us) == 0
    assert "Cache-Control sem no-cache" in capsys.readouterr().out


def test_termos_nao_publicados_so_avisam_sem_completo_e_falham_com_completo(servidores, capsys):
    ub, us = servidores(site={("GET", "/termos"): (404, "x")})
    assert _rodar(ub, us) == 0
    assert "Termos de Uso não está publicado" in capsys.readouterr().out
    assert _rodar(ub, us, completo=True) == 1


def test_pagina_legal_com_campo_em_branco_falha_sempre(servidores, capsys):
    ub, us = servidores(site={("GET", "/privacidade"): (200, "Responsável: {{RESPONSAVEL}}")})
    assert _rodar(ub, us) == 1
    assert "COM campo em branco" in capsys.readouterr().out


def test_email_antigo_so_avisa(servidores, capsys):
    ub, us = servidores(site={("GET", "/privacidade"): (200, "fale com privacidade@showup.app")})
    assert _rodar(ub, us) == 0
    assert "e-mail antigo" in capsys.readouterr().out


def test_backend_fora_do_ar_falha(servidores, capsys):
    ub, us = servidores()
    assert vp.main(["--backend", "http://127.0.0.1:9", "--site", us]) == 1
    assert "Backend não respondeu" in capsys.readouterr().out


def test_mostra_os_logins_ativos_e_so_avisa_dos_desligados(servidores, capsys):
    ub, us = servidores()
    assert _rodar(ub, us) == 0
    assert "Login disponível: Google, Microsoft, e-mail e senha." in capsys.readouterr().out
    ub, us = servidores(backend={("GET", "/api/auth/metodos"): (200, json.dumps({"google": True, "microsoft": False, "email": False}))})
    assert _rodar(ub, us) == 0                       # desligados não impedem o lançamento
    saida = capsys.readouterr().out
    assert "Login disponível: Google." in saida and "Microsoft desligado" in saida and "e-mail desligado" in saida


def test_backend_sem_lista_de_logins_avisa(servidores, capsys):
    ub, us = servidores(backend={("GET", "/api/auth/metodos"): (404, "x")})
    assert _rodar(ub, us) == 0
    assert "lista de logins" in capsys.readouterr().out


def test_backend_sem_os_avisos_por_notificacao_falha_e_manda_publicar(servidores, capsys):
    ub, us = servidores(backend={("POST", "/api/me/notificacoes/teste"): (404, "{}")})
    assert _rodar(ub, us) == 1
    saida = capsys.readouterr().out
    assert "NÃO tem os avisos por notificação" in saida and "git push" in saida


def test_backend_com_os_avisos_por_notificacao_passa(servidores, capsys):
    ub, us = servidores()
    assert _rodar(ub, us) == 0
    assert "avisos por notificação (novo agendamento e próximo atendimento)" in capsys.readouterr().out


# ------------------------------------------------------------------ site novo: início, /p/, 404, robots
def test_backend_sem_o_link_legivel_falha_e_manda_publicar(servidores, capsys):
    ub, us = servidores(backend={("GET", "/api/me/link-publico"): (404, "{}")})
    assert _rodar(ub, us) == 1
    saida = capsys.readouterr().out
    assert "NÃO tem o link de agendamento legível" in saida and "git push" in saida


def test_endereco_legivel_que_nao_abre_falha_porque_o_link_do_app_daria_erro(servidores, capsys):
    ub, us = servidores(site={("GET", "/p/verificacao-showup"): (404, "nao existe")})
    assert _rodar(ub, us) == 1
    assert "/p/nome NÃO abre a página de agendamento" in capsys.readouterr().out


def test_pagina_inicial_ausente_so_avisa_no_modo_normal_e_falha_no_completo(servidores, capsys):
    rotas = {("GET", "/"): (404, "nao existe")}
    ub, us = servidores(site=rotas)
    assert _rodar(ub, us) == 0
    assert "página inicial do site não está publicada" in capsys.readouterr().out
    ub, us = servidores(site=rotas)
    assert _rodar(ub, us, completo=True) == 1
    assert "página inicial do site não está publicada" in capsys.readouterr().out


def test_pagina_inicial_com_campo_em_branco_falha(servidores, capsys):
    ub, us = servidores(site={("GET", "/"): (200, '<main id="conteudo">{{EMAIL_CONTATO}}</main>')})
    assert _rodar(ub, us) == 1
    assert "Página inicial publicada COM campo em branco" in capsys.readouterr().out


def test_404_padrao_do_firebase_e_robots_ausente_sao_avisos_nao_falhas(servidores, capsys):
    ub, us = servidores(site={("GET", "/pagina-que-nao-existe-showup"): (404, "Site Not Found"), ("GET", "/robots.txt"): (404, "x")})
    assert _rodar(ub, us) == 0
    saida = capsys.readouterr().out
    assert "página de erro padrão do Firebase" in saida and "robots.txt não está publicado" in saida


def test_a_versao_da_pagina_continua_verificada_pela_meta_tag_sem_aparecer_na_tela(servidores, capsys):
    ub, us = servidores(site={("GET", "/agendar"): (200, AGENDAR_NOVO.replace("v2026.10.30", "v2025.01.01"))})
    assert _rodar(ub, us) == 1
    assert "não aparece na página" in capsys.readouterr().out


def test_relatorio_nao_quebra_no_terminal_do_windows():
    """cp1252 (terminal padrão do Windows) não tem "→": o relatório quebrava no fim, com tudo já verificado."""
    import os
    import subprocess
    import sys
    codigo = (
        "import importlib.util, sys\n"
        f"spec = importlib.util.spec_from_file_location('vp', r'{RAIZ / 'lancamento' / 'verificar-producao.py'}')\n"
        "vp = importlib.util.module_from_spec(spec); spec.loader.exec_module(vp)\n"
        "vp._saida_que_nao_quebra()\n"
        "r = vp.Relatorio(); r.ok('Backend no ar (GET /api/ → ok).'); r.atencao('Exclusão'); r.imprimir()\n"
    )
    r = subprocess.run([sys.executable, "-c", codigo], capture_output=True, env={**os.environ, "PYTHONIOENCODING": "cp1252"})
    assert r.returncode == 0, r.stderr.decode("cp1252", "replace")
    assert b"[OK] Backend no ar" in r.stdout and b"TUDO CERTO" in r.stdout
