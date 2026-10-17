"""verificar-google.py: separa "segredo errado" de "credenciais certas", contra um servidor local que imita o Google."""
import http.server
import importlib.util
import json
import threading
import urllib.parse
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("verificar_google", RAIZ / "lancamento" / "verificar-google.py")
vg = importlib.util.module_from_spec(spec)
spec.loader.exec_module(vg)

SEGREDO_CERTO = "GOCSPX-segredoCorreto1234567890"
CLIENT_ID = "123456-abc.apps.googleusercontent.com"
REDIRECT = "https://api.exemplo.com/api/auth/google/callback"


@pytest.fixture
def google_falso():
    """Imita o endpoint de token do Google: segredo certo → invalid_grant (código falso); errado → invalid_client."""
    recebidos = []

    class H(http.server.BaseHTTPRequestHandler):
        def do_POST(self):
            dados = urllib.parse.parse_qs(self.rfile.read(int(self.headers["Content-Length"])).decode())
            recebidos.append({k: v[0] for k, v in dados.items()})
            if dados["client_id"][0] != CLIENT_ID or dados["client_secret"][0] != SEGREDO_CERTO:
                corpo, status = {"error": "invalid_client", "error_description": "Unauthorized"}, 401
            elif dados["redirect_uri"][0] != REDIRECT:
                corpo, status = {"error": "redirect_uri_mismatch"}, 400
            else:
                corpo, status = {"error": "invalid_grant", "error_description": "Malformed auth code."}, 400
            dados_json = json.dumps(corpo).encode()
            self.send_response(status)
            self.send_header("Content-Length", str(len(dados_json)))
            self.end_headers()
            self.wfile.write(dados_json)

        def log_message(self, *a):
            pass

    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_address[1]}/token", recebidos
    srv.shutdown()


def env(tmp_path, **sobrescrever):
    valores = {"GOOGLE_WEB_CLIENT_ID": CLIENT_ID, "GOOGLE_CLIENT_SECRET": SEGREDO_CERTO, "GOOGLE_OAUTH_REDIRECT_URI": REDIRECT, **sobrescrever}
    p = tmp_path / ".env.render"
    p.write_text("\n".join(f"{k}={v}" for k, v in valores.items()), encoding="utf-8")
    return str(p)


def test_credenciais_certas_sao_aceitas_e_o_codigo_falso_e_o_que_o_google_recusa(tmp_path, capsys, google_falso):
    url, recebidos = google_falso
    assert vg.main(["--arquivo", env(tmp_path)], url_token=url) == 0
    saida = capsys.readouterr().out
    assert "ACEITOU o ID e o segredo" in saida and SEGREDO_CERTO not in saida
    assert recebidos[0]["code"] == "codigo-falso-so-para-testar" and recebidos[0]["grant_type"] == "authorization_code"


def test_segredo_errado_e_o_caso_do_render_com_o_segredo_antigo(tmp_path, capsys, google_falso):
    url, _ = google_falso
    assert vg.main(["--arquivo", env(tmp_path, GOOGLE_CLIENT_SECRET="GOCSPX-segredoAntigoQueFoiTrocado")], url_token=url) == 1
    saida = capsys.readouterr().out
    assert "NÃO reconhece" in saida and "GOOGLE_CLIENT_SECRET no Render" in saida and "Save and deploy" in saida
    assert "segredoAntigo" not in saida


def test_id_do_cliente_errado_tambem_e_acusado(tmp_path, capsys, google_falso):
    url, _ = google_falso
    assert vg.main(["--arquivo", env(tmp_path, GOOGLE_WEB_CLIENT_ID="outro-id.apps.googleusercontent.com")], url_token=url) == 1
    assert "invalid_client" in capsys.readouterr().out


def test_endereco_de_retorno_diferente_e_explicado(tmp_path, capsys, google_falso):
    url, _ = google_falso
    assert vg.main(["--arquivo", env(tmp_path, GOOGLE_OAUTH_REDIRECT_URI="https://api.exemplo.com/outro")], url_token=url) == 1
    assert "URIs de redirecionamento" in capsys.readouterr().out


def test_segredo_de_exemplo_nem_chega_a_perguntar_ao_google(tmp_path, capsys, google_falso):
    url, recebidos = google_falso
    assert vg.main(["--arquivo", env(tmp_path, GOOGLE_CLIENT_SECRET="GOCSPX-...")], url_token=url) == 1
    assert "texto de exemplo" in capsys.readouterr().out and recebidos == []


def test_variavel_faltando_e_arquivo_inexistente(tmp_path, capsys):
    p = tmp_path / ".env"
    p.write_text("GOOGLE_WEB_CLIENT_ID=x\n", encoding="utf-8")
    assert vg.main(["--arquivo", str(p)]) == 1
    assert "GOOGLE_CLIENT_SECRET" in capsys.readouterr().out
    assert vg.main(["--arquivo", str(tmp_path / "nao-existe")]) == 1


def test_sem_rede_nao_estoura_e_orienta(tmp_path, capsys):
    assert vg.main(["--arquivo", env(tmp_path)], url_token="http://127.0.0.1:9/token") == 1
    assert "Não consegui falar com o Google" in capsys.readouterr().out


def test_interpretacao_das_respostas_do_google():
    assert vg.interpretar(400, {"error": "invalid_grant"})[0] is True
    assert vg.interpretar(401, {"error": "invalid_client"})[0] is False
    assert vg.interpretar(400, {"error": "unauthorized_client"})[0] is False
    ok, texto = vg.interpretar(500, {})
    assert ok is False and "inesperada" in texto


def test_modo_perguntar_nao_precisa_de_arquivo_e_usa_o_endereco_padrao(capsys, google_falso, monkeypatch):
    url, recebidos = google_falso
    respostas = iter([CLIENT_ID, ""])                       # id; Enter no endereço de retorno
    monkeypatch.setattr("builtins.input", lambda _: next(respostas))
    monkeypatch.setattr(vg.getpass, "getpass", lambda _: SEGREDO_CERTO)
    # o servidor falso espera outro endereço de retorno: confere que o padrão do Render foi usado
    assert vg.main(["--perguntar"], url_token=url) == 1
    assert recebidos[0]["redirect_uri"] == "https://showup-backend-s9y1.onrender.com/api/auth/google/callback"
    assert SEGREDO_CERTO not in capsys.readouterr().out


def test_avisa_quando_o_app_usa_outro_id_de_cliente_que_o_digitado(tmp_path, capsys, google_falso):
    url, _ = google_falso
    app = tmp_path / "app.env"
    app.write_text("EXPO_PUBLIC_GOOGLE_WEB_CLIENT_ID=63469089229-q8l0k5cs40ia3ri753erg77j101o1l18.apps.googleusercontent.com\n", encoding="utf-8")
    assert vg.main(["--arquivo", env(tmp_path), "--app-env", str(app)], url_token=url) == 0       # as credenciais em si estão certas
    saida = capsys.readouterr().out
    assert "OUTRO ID de cliente" in saida and "MESMO cliente" in saida and "q8l0k5" in saida


def test_sem_aviso_quando_app_e_servidor_usam_o_mesmo_id(tmp_path, capsys, google_falso):
    url, _ = google_falso
    app = tmp_path / "app.env"
    app.write_text(f"EXPO_PUBLIC_GOOGLE_WEB_CLIENT_ID={CLIENT_ID}\n", encoding="utf-8")
    assert vg.main(["--arquivo", env(tmp_path), "--app-env", str(app)], url_token=url) == 0
    saida = capsys.readouterr().out
    assert "OUTRO ID" not in saida and "MESMO ID e o MESMO segredo" in saida


def test_invalid_client_lembra_que_o_segredo_tem_que_ser_do_mesmo_cliente(tmp_path, capsys, google_falso):
    url, _ = google_falso
    assert vg.main(["--arquivo", env(tmp_path, GOOGLE_CLIENT_SECRET="GOCSPX-deOutroCliente123456789")], url_token=url) == 1
    assert "MAIS DE UM cliente" in capsys.readouterr().out
