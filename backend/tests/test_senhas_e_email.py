"""Hash de senha e envio de e-mail (SMTP falso de verdade, em socket local)."""
import asyncio
import os
import socketserver
import sys
import threading
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest

import emailer
import senhas


# ------------------------------------------------------------------ senhas
def test_hash_confere_e_nao_guarda_a_senha():
    h = senhas.hash_senha("uma senha boa 123")
    assert h.startswith("scrypt$15$8$3$") and "uma senha boa" not in h
    assert senhas.verificar_senha("uma senha boa 123", h) is True
    assert senhas.verificar_senha("uma senha boa 124", h) is False
    assert senhas.verificar_senha("", h) is False


def test_mesma_senha_gera_hashes_diferentes_por_causa_do_salt():
    assert senhas.hash_senha("repetida-123") != senhas.hash_senha("repetida-123")


def test_senha_com_acentos_e_emoji_funciona():
    h = senhas.hash_senha("ação-café-🔒-123")
    assert senhas.verificar_senha("ação-café-🔒-123", h) and not senhas.verificar_senha("acao-cafe-🔒-123", h)


@pytest.mark.parametrize("lixo", ["", "abc", "scrypt$x$y", "bcrypt$15$8$3$AAAA$AAAA", "scrypt$15$8$3$@@@$@@@",
                                  "scrypt$99$8$3$AAAA$AAAA", None])
def test_hash_armazenado_invalido_nunca_levanta_e_nunca_confere(lixo):
    assert senhas.verificar_senha("qualquer", lixo) is False


def test_parametros_ficam_no_texto_e_senhas_antigas_continuam_valendo():
    # um hash gerado com custo menor (como se o custo tivesse sido aumentado depois) ainda confere
    import base64
    salt = b"0123456789abcdef"
    d = senhas._derivar("antiga-123456", salt, 12, 8, 1)
    antigo = f"scrypt$12$8$1${base64.b64encode(salt).decode()}${base64.b64encode(d).decode()}"
    assert senhas.verificar_senha("antiga-123456", antigo)


@pytest.mark.parametrize("senha,email,tem_erro", [
    ("curta1", "", True), ("a" * 129, "", True), ("12345678", "", True), ("Password", "", True),
    ("aaaaaaaaaa", "", True), ("ana.lima@x.com", "ana.lima@x.com", True),
    ("analima2024", "analima@x.com", False), ("analima", "analima@x.com", True),
    ("uma frase longa e boa", "", False), ("Tr0ca-Isso-Aqui", "", False),
])
def test_regras_de_senha(senha, email, tem_erro):
    assert (senhas.validar_senha(senha, email) is not None) is tem_erro


def test_hash_falso_existe_e_nunca_confere_com_senha_real():
    assert senhas.hash_falso().startswith("scrypt$") and senhas.hash_falso() == senhas.hash_falso()
    assert not senhas.verificar_senha("12345678", senhas.hash_falso())


# ------------------------------------------------------------------ e-mail (SMTP de mentira, num socket local)
class _Smtp(socketserver.StreamRequestHandler):
    recebidos: list = []

    def _r(self, linha):
        self.wfile.write((linha + "\r\n").encode())

    def handle(self):
        self._r("220 teste")
        dados, em_dados = [], False
        while True:
            linha = self.rfile.readline().decode(errors="replace")
            if not linha:
                return
            cmd = linha.strip().upper()
            if em_dados:
                if linha.strip() == ".":
                    em_dados = False
                    _Smtp.recebidos.append("\n".join(dados))
                    self._r("250 ok")
                else:
                    dados.append(linha.rstrip("\r\n"))
            elif cmd.startswith("EHLO") or cmd.startswith("HELO"):
                self._r("250 teste")
            elif cmd.startswith("MAIL") or cmd.startswith("RCPT"):
                self._r("250 ok")
            elif cmd == "DATA":
                self._r("354 vai")
                em_dados = True
            elif cmd == "QUIT":
                self._r("221 tchau")
                return
            else:
                self._r("250 ok")


@pytest.fixture
def smtp(monkeypatch):
    _Smtp.recebidos = []
    srv = socketserver.ThreadingTCPServer(("127.0.0.1", 0), _Smtp)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    monkeypatch.setenv("SMTP_HOST", "127.0.0.1")
    monkeypatch.setenv("SMTP_FROM", "ShowUp <nao-responda@exemplo.com>")
    monkeypatch.setenv("SMTP_PORT", str(srv.server_address[1]))
    monkeypatch.delenv("SMTP_USER", raising=False)
    # o servidor de mentira não fala TLS: pula o STARTTLS só neste teste
    monkeypatch.setattr(emailer.smtplib.SMTP, "starttls", lambda self, **kw: (200, b"ok"))
    yield _Smtp
    srv.shutdown()


def test_email_so_e_considerado_configurado_com_host_e_remetente(monkeypatch):
    monkeypatch.delenv("SMTP_HOST", raising=False); monkeypatch.delenv("SMTP_FROM", raising=False)
    assert emailer.email_configurado() is False
    monkeypatch.setenv("SMTP_HOST", "smtp.exemplo.com")
    assert emailer.email_configurado() is False          # falta o remetente
    monkeypatch.setenv("SMTP_FROM", "x@exemplo.com")
    assert emailer.email_configurado() is True


def test_envia_de_verdade_pelo_smtp(smtp):
    asyncio.run(emailer.enviar_email("maria@exemplo.com", "Seu código do ShowUp", "Código: 123456\nVale 10 minutos."))
    assert len(smtp.recebidos) == 1
    import email
    from email.header import decode_header, make_header
    msg = email.message_from_string(smtp.recebidos[0])
    assert str(make_header(decode_header(msg["Subject"]))) == "Seu código do ShowUp"   # acento volta certo
    assert msg["To"] == "maria@exemplo.com" and "nao-responda@exemplo.com" in msg["From"]
    assert msg["Message-ID"] and msg["Date"]
    assert "Código: 123456" in msg.get_payload()          # corpo em UTF-8 chegou inteiro, com acento


def test_falha_de_conexao_levanta_pra_quem_chamou_decidir(monkeypatch):
    monkeypatch.setenv("SMTP_HOST", "127.0.0.1"); monkeypatch.setenv("SMTP_FROM", "x@exemplo.com")
    monkeypatch.setenv("SMTP_PORT", "9")                  # ninguém escutando
    with pytest.raises(OSError):
        asyncio.run(emailer.enviar_email("a@b.co", "x", "y"))
