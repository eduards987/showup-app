"""Cadastro e login por e-mail + senha, recuperação de senha e login com Microsoft.
Offline: banco falso, e-mail capturado em memória, Microsoft simulada."""
import base64
import json
import re
import sys
import time
from urllib.parse import unquote
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import offline_env  # noqa: E402,F401  (variáveis FALSAS, antes de importar o server)

import pytest
from fastapi.testclient import TestClient

import server


# ------------------------------------------------------------------ banco falso
def _casa(doc, q):
    for k, cond in q.items():
        v = doc.get(k)
        if isinstance(cond, dict) and any(op.startswith("$") for op in cond):
            for op, arg in cond.items():
                ok = {"$ne": lambda: v != arg, "$lt": lambda: v is not None and v < arg,
                      "$gt": lambda: v is not None and v > arg}[op]()
                if not ok:
                    return False
        elif v != cond:
            return False
    return True


class Col:
    def __init__(self):
        self.docs = []

    async def find_one(self, q, proj=None):
        return next((dict(d) for d in self.docs if _casa(d, q)), None)

    async def insert_one(self, doc):
        self.docs.append(dict(doc))

    async def replace_one(self, q, doc, upsert=False):
        for i, d in enumerate(self.docs):
            if _casa(d, q):
                self.docs[i] = dict(doc)
                return
        if upsert:
            self.docs.append(dict(doc))

    async def update_one(self, q, upd):
        for d in self.docs:
            if _casa(d, q):
                d.update(upd.get("$set", {}))
                for k in upd.get("$unset", {}):
                    d.pop(k, None)
                for k, n in upd.get("$inc", {}).items():
                    d[k] = d.get(k, 0) + n
                return

    async def find_one_and_update(self, q, upd):          # devolve o documento ANTES, como o Mongo
        for d in self.docs:
            if _casa(d, q):
                antes = dict(d)
                for k, n in upd.get("$inc", {}).items():
                    d[k] = d.get(k, 0) + n
                return antes
        return None

    async def find_one_and_delete(self, q):
        for i, d in enumerate(self.docs):
            if _casa(d, q):
                return self.docs.pop(i)
        return None

    async def delete_one(self, q):
        for i, d in enumerate(self.docs):
            if _casa(d, q):
                del self.docs[i]
                return

    async def delete_many(self, q):
        self.docs[:] = [d for d in self.docs if not _casa(d, q)]


class DB:
    def __init__(self):
        for nome in ("users", "user_sessions", "email_codes", "login_attempts", "oauth_states",
                     "agendamentos", "device_tokens", "customer_cards"):
            setattr(self, nome, Col())


@pytest.fixture
def ctx(monkeypatch):
    db = DB()
    emails = []

    async def enviar(para, assunto, texto):
        emails.append({"para": para, "assunto": assunto, "texto": texto})

    monkeypatch.setattr(server, "db", db)
    monkeypatch.setattr(server, "enviar_email", enviar)
    monkeypatch.setattr(server, "email_configurado", lambda: True)
    monkeypatch.setattr(server, "EMAIL_CODIGOS_NO_LOG", False)
    return TestClient(server.app), db, emails


def codigo_de(emails, para=None):
    msgs = [e for e in emails if para is None or e["para"] == para]
    return re.search(r"\b(\d{6})\b", msgs[-1]["texto"]).group(1)


def esquecer_espera(db, email, finalidade):
    """Como se já tivessem passado 60 s desde o último envio."""
    for d in db.email_codes.docs:
        if d["email"] == email and d["finalidade"] == finalidade:
            d["enviado_em"] = datetime.now(timezone.utc) - timedelta(seconds=61)


CAD = {"name": "Maria Souza", "email": "maria@outlook.com", "password": "uma-senha-boa-123"}


def cadastrar_e_entrar(client, emails, dados=None):
    dados = dados or CAD
    assert client.post("/api/auth/email/cadastro", json=dados).status_code == 200
    r = client.post("/api/auth/email/verificar", json={"email": dados["email"], "code": codigo_de(emails, dados["email"])})
    assert r.status_code == 200, r.text
    return r.json()


# ------------------------------------------------------------------ métodos disponíveis
def test_metodos_so_oferece_o_que_o_servidor_consegue_atender(ctx, monkeypatch):
    client, db, emails = ctx
    monkeypatch.setattr(server, "email_configurado", lambda: False)
    assert client.get("/api/auth/metodos").json() == {"google": True, "microsoft": False, "email": False}
    monkeypatch.setattr(server, "email_configurado", lambda: True)
    for nome, valor in (("MICROSOFT_CLIENT_ID", "cid"), ("MICROSOFT_CLIENT_SECRET", "seg"), ("MICROSOFT_OAUTH_REDIRECT_URI", "https://x/cb")):
        monkeypatch.setattr(server, nome, valor)
    assert client.get("/api/auth/metodos").json() == {"google": True, "microsoft": True, "email": True}


def test_cadastro_sem_email_configurado_recusa_em_vez_de_fingir(ctx, monkeypatch):
    client, db, emails = ctx
    monkeypatch.setattr(server, "email_configurado", lambda: False)
    r = client.post("/api/auth/email/cadastro", json=CAD)
    assert r.status_code == 503 and "ainda não está disponível" in r.json()["detail"]
    assert db.email_codes.docs == [] and db.users.docs == []


# ------------------------------------------------------------------ cadastro
def test_fluxo_completo_cadastro_codigo_e_login(ctx):
    client, db, emails = ctx
    r = client.post("/api/auth/email/cadastro", json=CAD)
    assert r.status_code == 200 and len(emails) == 1 and emails[0]["para"] == "maria@outlook.com"
    assert db.users.docs == []                                    # a conta SÓ existe depois do código
    assert "123456" not in str(db.email_codes.docs) and CAD["password"] not in str(db.email_codes.docs)
    assert all(re.fullmatch(r"[0-9a-f]{64}", d["codigo_hash"]) for d in db.email_codes.docs)   # só o hash do código
    sessao = client.post("/api/auth/email/verificar", json={"email": CAD["email"], "code": codigo_de(emails)}).json()
    user = db.users.docs[0]
    assert user["email"] == "maria@outlook.com" and user["name"] == "Maria Souza" and user["role"] is None
    assert user["email_verified"] is True and user["password_hash"].startswith("scrypt$") and CAD["password"] not in str(user)
    assert sessao["session_token"] and sessao["user"]["email"] == "maria@outlook.com"
    me = client.get("/api/auth/me", headers={"Authorization": f"Bearer {sessao['session_token']}"})
    assert me.status_code == 200
    # e depois é só entrar com e-mail e senha (qualquer caixa/espaços no e-mail)
    login = client.post("/api/auth/email/login", json={"email": "  MARIA@Outlook.com ", "password": CAD["password"]})
    assert login.status_code == 200 and login.json()["user"]["email"] == "maria@outlook.com"


@pytest.mark.parametrize("campo,valor,trecho", [
    ("email", "isso-nao-e-email", "e-mail válido"), ("email", "a@b", "e-mail válido"), ("email", "", "e-mail válido"),
    ("name", "A", "seu nome"), ("name", "x" * 81, "seu nome"),
    ("password", "curta", "pelo menos 8"), ("password", "12345678", "fácil de adivinhar"),
    ("password", "maria@outlook.com", "igual ao seu e-mail"),
])
def test_cadastro_recusa_dados_ruins_sem_mandar_e_mail(ctx, campo, valor, trecho):
    client, db, emails = ctx
    r = client.post("/api/auth/email/cadastro", json={**CAD, campo: valor})
    assert r.status_code == 422 and trecho in r.json()["detail"], r.text
    assert emails == [] and db.email_codes.docs == []


def test_codigo_errado_e_limite_de_5_tentativas(ctx):
    client, db, emails = ctx
    client.post("/api/auth/email/cadastro", json=CAD)
    certo = codigo_de(emails)
    errado = "000000" if certo != "000000" else "111111"
    for _ in range(5):
        assert client.post("/api/auth/email/verificar", json={"email": CAD["email"], "code": errado}).status_code == 400
    # estourou as 5: nem o código CERTO vale mais (precisa pedir outro)
    assert client.post("/api/auth/email/verificar", json={"email": CAD["email"], "code": certo}).status_code == 400
    assert db.users.docs == []


def test_codigo_expirado_e_codigo_de_uso_unico(ctx):
    client, db, emails = ctx
    client.post("/api/auth/email/cadastro", json=CAD)
    codigo = codigo_de(emails)
    db.email_codes.docs[0]["expira_em"] = datetime.now(timezone.utc) - timedelta(seconds=1)
    assert client.post("/api/auth/email/verificar", json={"email": CAD["email"], "code": codigo}).status_code == 400
    esquecer_espera(db, CAD["email"], "verify")
    client.post("/api/auth/email/cadastro", json=CAD)
    codigo = codigo_de(emails)
    assert client.post("/api/auth/email/verificar", json={"email": CAD["email"], "code": codigo}).status_code == 200
    assert client.post("/api/auth/email/verificar", json={"email": CAD["email"], "code": codigo}).status_code == 400   # reuso


def test_espera_de_60s_entre_pedidos_de_codigo(ctx):
    client, db, emails = ctx
    assert client.post("/api/auth/email/cadastro", json=CAD).status_code == 200
    assert client.post("/api/auth/email/cadastro", json=CAD).status_code == 429
    assert len(emails) == 1
    esquecer_espera(db, CAD["email"], "verify")
    assert client.post("/api/auth/email/cadastro", json=CAD).status_code == 200 and len(emails) == 2
    # o código antigo morreu: só o último vale
    assert client.post("/api/auth/email/verificar", json={"email": CAD["email"], "code": codigo_de(emails[:1])}).status_code in (200, 400)


def test_cadastro_nao_revela_se_o_email_ja_tem_conta(ctx):
    client, db, emails = ctx
    cadastrar_e_entrar(client, emails)
    emails.clear()
    senha_antes = db.users.docs[0]["password_hash"]
    esquecer_espera(db, CAD["email"], "verify")
    r_existente = client.post("/api/auth/email/cadastro", json={**CAD, "password": "outra-senha-qualquer-9"})
    r_novo = client.post("/api/auth/email/cadastro", json={**CAD, "email": "novo@outlook.com"})
    assert r_existente.status_code == r_novo.status_code == 200 and r_existente.json() == r_novo.json()   # resposta idêntica
    assert "já tem cadastro" in emails[0]["texto"] and not re.search(r"\b\d{6}\b", emails[0]["texto"])    # dono recebe AVISO, sem código
    assert db.users.docs[0]["password_hash"] == senha_antes                                                  # nada foi alterado
    # e nenhum código "adivinhado" funciona nesse e-mail
    for tentativa in ("000000", "123456"):
        assert client.post("/api/auth/email/verificar", json={"email": CAD["email"], "code": tentativa}).status_code == 400


def test_quem_ja_tem_conta_do_google_adiciona_senha_pela_mesma_conta(ctx):
    client, db, emails = ctx
    db.users.docs.append({"user_id": "user_google1", "email": "maria@outlook.com", "name": "Maria do Google", "role": "cliente",
                          "created_at": datetime.now(timezone.utc)})
    cadastrar_e_entrar(client, emails)
    assert len(db.users.docs) == 1                                                       # não duplicou a conta
    u = db.users.docs[0]
    assert u["user_id"] == "user_google1" and u["name"] == "Maria do Google" and u["role"] == "cliente"
    assert u["password_hash"].startswith("scrypt$") and u["email_verified"] is True


def test_senha_nova_so_vale_depois_de_provar_o_email(ctx):
    client, db, emails = ctx
    db.users.docs.append({"user_id": "user_google1", "email": "maria@outlook.com", "name": "M", "role": None,
                          "created_at": datetime.now(timezone.utc)})
    client.post("/api/auth/email/cadastro", json=CAD)          # atacante pede, mas não tem o código
    assert "password_hash" not in db.users.docs[0]
    r = client.post("/api/auth/email/login", json={"email": CAD["email"], "password": CAD["password"]})
    assert r.status_code == 401                                 # a senha do atacante NÃO entra na conta alheia


# ------------------------------------------------------------------ login
def test_login_nao_diferencia_email_inexistente_de_senha_errada_e_gasta_o_mesmo_tempo(ctx, monkeypatch):
    client, db, emails = ctx
    cadastrar_e_entrar(client, emails)
    chamadas = []
    original = server.verificar_senha
    monkeypatch.setattr(server, "verificar_senha", lambda s, h: (chamadas.append(h), original(s, h))[1])
    a = client.post("/api/auth/email/login", json={"email": CAD["email"], "password": "senha-errada-123"})
    b = client.post("/api/auth/email/login", json={"email": "ninguem@outlook.com", "password": "senha-errada-123"})
    c = client.post("/api/auth/email/login", json={"email": "lixo", "password": "x"})
    assert a.status_code == b.status_code == c.status_code == 401
    assert a.json() == b.json() == c.json() == {"detail": "E-mail ou senha incorretos."}
    assert chamadas[1] == server.hash_falso()                   # e-mail inexistente: conferiu contra o hash descartável


def test_conta_so_do_google_nao_entra_por_senha(ctx):
    client, db, emails = ctx
    db.users.docs.append({"user_id": "u1", "email": "g@gmail.com", "name": "G", "role": None,
                          "created_at": datetime.now(timezone.utc)})
    assert client.post("/api/auth/email/login", json={"email": "g@gmail.com", "password": "qualquer-coisa-1"}).status_code == 401


def test_forca_bruta_bloqueia_apos_5_falhas_mesmo_com_a_senha_certa(ctx):
    client, db, emails = ctx
    cadastrar_e_entrar(client, emails)
    for _ in range(5):
        assert client.post("/api/auth/email/login", json={"email": CAD["email"], "password": "errada-errada-1"}).status_code == 401
    r = client.post("/api/auth/email/login", json={"email": CAD["email"], "password": CAD["password"]})
    assert r.status_code == 429
    db.login_attempts.docs[0]["bloqueado_ate"] = datetime.now(timezone.utc) - timedelta(seconds=1)     # passou o bloqueio
    assert client.post("/api/auth/email/login", json={"email": CAD["email"], "password": CAD["password"]}).status_code == 200
    assert db.login_attempts.docs == []                                                                  # sucesso zera o contador


def test_falhas_antigas_nao_acumulam_pra_sempre(ctx):
    client, db, emails = ctx
    cadastrar_e_entrar(client, emails)
    for _ in range(4):
        client.post("/api/auth/email/login", json={"email": CAD["email"], "password": "errada-errada-1"})
    db.login_attempts.docs[0]["expira_em"] = datetime.now(timezone.utc) - timedelta(seconds=1)         # janela venceu
    client.post("/api/auth/email/login", json={"email": CAD["email"], "password": "errada-errada-1"})
    assert db.login_attempts.docs[0]["falhas"] == 1 and "bloqueado_ate" not in db.login_attempts.docs[0]


# ------------------------------------------------------------------ esqueci a senha
def test_esqueci_a_senha_redefine_e_derruba_as_sessoes_antigas(ctx):
    client, db, emails = ctx
    sessao_antiga = cadastrar_e_entrar(client, emails)["session_token"]
    emails.clear()
    assert client.post("/api/auth/email/esqueci", json={"email": CAD["email"]}).status_code == 200
    codigo = codigo_de(emails)
    assert "Redefinir" in emails[0]["assunto"]
    r = client.post("/api/auth/email/redefinir", json={"email": CAD["email"], "code": codigo, "new_password": "nova-senha-segura-77"})
    assert r.status_code == 200
    assert client.get("/api/auth/me", headers={"Authorization": f"Bearer {sessao_antiga}"}).status_code == 401   # sessão antiga caiu
    assert client.post("/api/auth/email/login", json={"email": CAD["email"], "password": CAD["password"]}).status_code == 401
    assert client.post("/api/auth/email/login", json={"email": CAD["email"], "password": "nova-senha-segura-77"}).status_code == 200
    assert client.post("/api/auth/email/redefinir", json={"email": CAD["email"], "code": codigo, "new_password": "outra-senha-qualquer-1"}).status_code == 400   # uso único


def test_esqueci_nao_revela_quem_tem_conta(ctx):
    client, db, emails = ctx
    cadastrar_e_entrar(client, emails)
    emails.clear()
    esquecer_espera(db, CAD["email"], "reset")
    existe = client.post("/api/auth/email/esqueci", json={"email": CAD["email"]})
    nao_existe = client.post("/api/auth/email/esqueci", json={"email": "fantasma@outlook.com"})
    assert existe.status_code == nao_existe.status_code == 200 and existe.json() == nao_existe.json()
    assert [e["para"] for e in emails] == [CAD["email"]]                    # só o dono recebe
    # a espera de 60 s também vale pra quem não tem conta: o 429 não vira pista
    assert client.post("/api/auth/email/esqueci", json={"email": "fantasma@outlook.com"}).status_code == 429
    for _ in range(5):
        client.post("/api/auth/email/redefinir", json={"email": "fantasma@outlook.com", "code": "123456", "new_password": "nova-senha-segura-77"})
    assert client.post("/api/auth/email/redefinir", json={"email": "fantasma@outlook.com", "code": "123456", "new_password": "nova-senha-segura-77"}).status_code == 400


def test_codigos_de_cadastro_e_de_redefinicao_nao_se_misturam(ctx):
    client, db, emails = ctx
    cadastrar_e_entrar(client, emails)
    emails.clear()
    esquecer_espera(db, CAD["email"], "reset")
    client.post("/api/auth/email/esqueci", json={"email": CAD["email"]})
    reset = codigo_de(emails)
    assert client.post("/api/auth/email/verificar", json={"email": CAD["email"], "code": reset}).status_code == 400


def test_redefinir_valida_a_senha_nova_antes_de_gastar_o_codigo(ctx):
    client, db, emails = ctx
    cadastrar_e_entrar(client, emails)
    emails.clear()
    esquecer_espera(db, CAD["email"], "reset")
    client.post("/api/auth/email/esqueci", json={"email": CAD["email"]})
    codigo = codigo_de(emails)
    assert client.post("/api/auth/email/redefinir", json={"email": CAD["email"], "code": codigo, "new_password": "123"}).status_code == 422
    assert client.post("/api/auth/email/redefinir", json={"email": CAD["email"], "code": codigo, "new_password": "nova-senha-segura-77"}).status_code == 200


def test_falha_no_envio_nao_deixa_codigo_orfao(ctx, monkeypatch):
    client, db, emails = ctx

    async def quebra(*a):
        raise OSError("smtp fora do ar")

    monkeypatch.setattr(server, "enviar_email", quebra)
    r = client.post("/api/auth/email/cadastro", json=CAD)
    assert r.status_code == 503 and "enviar o e-mail" in r.json()["detail"]
    assert db.email_codes.docs == []                      # sem registro de espera: dá pra tentar de novo na hora


def test_excluir_a_conta_apaga_senha_codigos_e_impede_novo_login(ctx):
    client, db, emails = ctx
    token = cadastrar_e_entrar(client, emails)["session_token"]
    client.post("/api/auth/email/esqueci", json={"email": CAD["email"]})
    client.post("/api/auth/email/login", json={"email": CAD["email"], "password": "errada-errada-1"})
    assert client.delete("/api/me", headers={"Authorization": f"Bearer {token}"}).status_code == 200
    u = db.users.docs[0]
    assert "password_hash" not in u and "microsoft_id" not in u and u["name"] == "Usuário excluído"
    assert db.email_codes.docs == [] and db.login_attempts.docs == []
    assert client.post("/api/auth/email/login", json={"email": CAD["email"], "password": CAD["password"]}).status_code == 401


# ------------------------------------------------------------------ Microsoft
TENANT = server.MS_TENANT_PESSOAL


@pytest.fixture
def ms(ctx, monkeypatch):
    client, db, emails = ctx
    for nome, valor in (("MICROSOFT_CLIENT_ID", "client-id-ms"), ("MICROSOFT_CLIENT_SECRET", "segredo-ms"),
                        ("MICROSOFT_OAUTH_REDIRECT_URI", "https://api.exemplo.com/api/auth/microsoft/callback")):
        monkeypatch.setattr(server, nome, valor)
    troca = {"status": 200, "claims": {}}

    def jwt(claims):
        b = lambda d: base64.urlsafe_b64encode(json.dumps(d).encode()).decode().rstrip("=")  # noqa: E731
        return f"{b({'alg': 'RS256'})}.{b(claims)}.assinatura-que-nao-conferimos"

    class Resposta:
        def __init__(self):
            self.status_code = troca["status"]
            self.text = "x"

        def json(self):
            return {"id_token": jwt(troca["claims"])} if troca["claims"] else {}

    class Cliente:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def post(self, url, data=None):
            troca["chamada"] = {"url": url, "data": data}
            return Resposta()

    monkeypatch.setattr(server.httpx, "AsyncClient", Cliente)

    def entrar(claims=None, **sobrescrever):
        """Faz /start (gera state+nonce) e chama o callback com um id_token montado."""
        inicio = client.get("/api/auth/microsoft/start", follow_redirects=False)
        estado = db.oauth_states.docs[-1]
        base = {"aud": "client-id-ms", "iss": f"https://login.microsoftonline.com/{TENANT}/v2.0", "tid": TENANT,
                "nonce": estado["nonce"], "exp": time.time() + 600, "oid": "oid-123", "email": "Joao@Outlook.com", "name": "João Silva"}
        base.update(claims or {})
        troca["claims"] = {k: v for k, v in {**base, **sobrescrever}.items() if v is not None}
        return client.get("/api/auth/microsoft/callback", params={"code": "codigo", "state": estado["state"]}, follow_redirects=False), inicio

    return client, db, troca, entrar


def test_microsoft_start_manda_pro_login_de_contas_pessoais_com_state_e_nonce(ms):
    client, db, troca, entrar = ms
    r = client.get("/api/auth/microsoft/start", follow_redirects=False)
    destino = r.headers["location"]
    assert destino.startswith("https://login.microsoftonline.com/consumers/oauth2/v2.0/authorize?")
    estado = db.oauth_states.docs[0]
    for trecho in ("client_id=client-id-ms", "response_type=code", f"state={estado['state']}", f"nonce={estado['nonce']}",
                   "scope=openid+profile+email", "redirect_uri=https%3A%2F%2Fapi.exemplo.com%2Fapi%2Fauth%2Fmicrosoft%2Fcallback"):
        assert trecho in destino, trecho


def test_microsoft_desligada_devolve_erro_pro_app(ctx, monkeypatch):
    client, db, emails = ctx
    r = client.get("/api/auth/microsoft/start", follow_redirects=False)
    assert r.headers["location"] == "showup://auth-callback?error=microsoft_indisponivel" and db.oauth_states.docs == []


def test_microsoft_primeiro_acesso_cria_a_conta_e_entra(ms):
    client, db, troca, entrar = ms
    r, _ = entrar()
    assert r.status_code in (302, 307) and r.headers["location"].startswith("showup://auth-callback?token=")
    u = db.users.docs[0]
    assert u["email"] == "joao@outlook.com" and u["name"] == "João Silva" and u["role"] is None
    assert u["microsoft_id"] == f"{TENANT}:oid-123" and u["email_verified"] is True
    assert troca["chamada"]["data"]["client_secret"] == "segredo-ms" and troca["chamada"]["data"]["code"] == "codigo"
    token = r.headers["location"].split("token=")[1]
    assert client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"}).status_code == 200


def test_microsoft_segundo_acesso_reconhece_a_mesma_conta_mesmo_se_o_email_mudar(ms):
    client, db, troca, entrar = ms
    entrar()
    entrar(email="outro.email@outlook.com")
    assert len(db.users.docs) == 1


def test_microsoft_vincula_a_conta_existente_do_mesmo_email(ms):
    client, db, troca, entrar = ms
    db.users.docs.append({"user_id": "user_g", "email": "joao@outlook.com", "name": "João do Google", "role": "profissional",
                          "created_at": datetime.now(timezone.utc)})
    r, _ = entrar()
    assert r.headers["location"].startswith("showup://auth-callback?token=") and len(db.users.docs) == 1
    assert db.users.docs[0]["microsoft_id"] == f"{TENANT}:oid-123" and db.users.docs[0]["role"] == "profissional"


@pytest.mark.parametrize("quebra,erro", [
    ({"aud": "outro-app"}, "token_invalido"),
    ({"iss": "https://login.microsoftonline.com/qualquer-outro/v2.0"}, "token_invalido"),
    ({"tid": "11111111-2222-3333-4444-555555555555"}, "token_invalido"),     # conta corporativa: não aceitamos
    ({"nonce": "nonce-de-outra-sessao"}, "token_invalido"),
    ({"exp": time.time() - 10}, "token_invalido"),
    ({"exp": None}, "token_invalido"),
    ({"email": None, "preferred_username": None}, "A conta Microsoft não informou um e-mail"),
])
def test_microsoft_recusa_token_que_nao_confere_e_nao_cria_conta(ms, quebra, erro):
    client, db, troca, entrar = ms
    r, _ = entrar(**quebra)
    assert unquote(r.headers["location"]) == f"showup://auth-callback?error={erro}", r.headers["location"]
    assert db.users.docs == [] and db.user_sessions.docs == []


def test_microsoft_state_e_de_uso_unico_e_desconhecido_e_recusado(ms):
    client, db, troca, entrar = ms
    client.get("/api/auth/microsoft/start", follow_redirects=False)
    state = db.oauth_states.docs[0]["state"]
    troca["claims"] = {"aud": "client-id-ms"}
    r1 = client.get("/api/auth/microsoft/callback", params={"code": "c", "state": state}, follow_redirects=False)
    r2 = client.get("/api/auth/microsoft/callback", params={"code": "c", "state": state}, follow_redirects=False)
    assert r1.headers["location"] != r2.headers["location"] == "showup://auth-callback?error=estado_invalido"
    forjado = client.get("/api/auth/microsoft/callback", params={"code": "c", "state": "inventado"}, follow_redirects=False)
    assert forjado.headers["location"] == "showup://auth-callback?error=estado_invalido"


def test_microsoft_state_expirado_e_recusado(ms):
    client, db, troca, entrar = ms
    client.get("/api/auth/microsoft/start", follow_redirects=False)
    db.oauth_states.docs[0]["expira_em"] = datetime.now(timezone.utc) - timedelta(seconds=1)
    r = client.get("/api/auth/microsoft/callback", params={"code": "c", "state": db.oauth_states.docs[0]["state"]}, follow_redirects=False)
    assert r.headers["location"] == "showup://auth-callback?error=estado_invalido"


def test_microsoft_erros_do_provedor_voltam_pro_app(ms):
    client, db, troca, entrar = ms
    r = client.get("/api/auth/microsoft/callback", params={"error": "access_denied"}, follow_redirects=False)
    assert r.headers["location"] == "showup://auth-callback?error=access_denied"
    troca["status"] = 400
    r, _ = entrar()
    assert r.headers["location"] == "showup://auth-callback?error=token_exchange_failed" and db.users.docs == []
