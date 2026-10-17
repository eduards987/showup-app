"""O verificador de configuração: erros típicos de quem monta o ambiente pela primeira vez."""
import importlib.util
import re
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("verificar_config", RAIZ / "lancamento" / "verificar-config.py")
vc = importlib.util.module_from_spec(spec)
spec.loader.exec_module(vc)

SK = "sk_test_" + "A1b2C3d4E5f6G7h8I9j0K1l2M3n4O5p6Q7r8"
PK = "pk_test_" + "Z9y8X7w6V5u4T3s2R1q0P9o8N7m6L5k4"
BASE_BACKEND = {
    "MONGO_URL": "mongodb+srv://usuario:S3nh4Segura@cluster.mongodb.net/?retryWrites=true",
    "DB_NAME": "holdbooked", "INTERNAL_SERVICE_TOKEN": "a" * 64,
    "GOOGLE_WEB_CLIENT_ID": "123-abc.apps.googleusercontent.com", "GOOGLE_CLIENT_SECRET": "GOCSPX-segredoDoGoogle12345",
    "GOOGLE_OAUTH_REDIRECT_URI": "https://api.exemplo.com/api/auth/google/callback",
    "STRIPE_API_KEY": SK, "STRIPE_WEBHOOK_SECRET": "whsec_" + "k" * 32,
    "STRIPE_PRICE_ID_PROFISSIONAL": "price_1ABC", "STRIPE_PRICE_ID_ULTRA": "price_2DEF",
    "ALLOWED_ORIGINS": "http://localhost:8081,https://site.exemplo.com", "PUBLIC_WEB_BASE_URL": "https://site.exemplo.com",
}
BASE_FRONTEND = {"EXPO_PUBLIC_BACKEND_URL": "https://api.exemplo.com", "EXPO_PUBLIC_STRIPE_PUBLISHABLE_KEY": PK,
                 "EXPO_PUBLIC_GOOGLE_WEB_CLIENT_ID": "123-abc.apps.googleusercontent.com"}


def gravar(tmp_path, nome, valores, aspas=True):
    caminho = tmp_path / nome
    caminho.write_text("# comentário\n\n" + "\n".join(f'{k}="{v}"' if aspas else f"{k}={v}" for k, v in valores.items()), encoding="utf-8")
    return caminho


def rodar(tmp_path, capsys, backend=None, frontend=None, modo="teste"):
    b = gravar(tmp_path, ".env.render", {**BASE_BACKEND, **(backend or {})})
    f = gravar(tmp_path, "frontend.env", {**BASE_FRONTEND, **(frontend or {})})
    codigo = vc.main(["--backend", str(b), "--frontend", str(f), "--modo", modo])
    return codigo, capsys.readouterr().out


def test_configuracao_de_teste_completa_e_coerente_passa(tmp_path, capsys):
    codigo, saida = rodar(tmp_path, capsys)
    assert codigo == 0 and "CONFIGURAÇÃO OK" in saida and "[FALTA]" not in saida and "[ERRO]" not in saida


def test_nunca_imprime_os_valores_dos_segredos(tmp_path, capsys):
    codigo, saida = rodar(tmp_path, capsys, backend={"MICROSOFT_CLIENT_ID": "11111111-2222-3333-4444-555555555555",
                                                    "MICROSOFT_CLIENT_SECRET": "segredo-da-microsoft-xyz",
                                                    "MICROSOFT_OAUTH_REDIRECT_URI": "https://api.exemplo.com/api/auth/microsoft/callback",
                                                    "SMTP_HOST": "smtp.exemplo.com", "SMTP_FROM": "ShowUp <x@exemplo.com>",
                                                    "SMTP_USER": "usuario-smtp", "SMTP_PASSWORD": "senha-do-smtp-qwerty"})
    for segredo in (SK, PK, "S3nh4Segura", "segredoDoGoogle12345", "a" * 64, "k" * 32, "segredo-da-microsoft-xyz", "senha-do-smtp-qwerty"):
        assert segredo not in saida, f"vazou: {segredo[:8]}…"


def test_variavel_obrigatoria_faltando_e_acusada(tmp_path, capsys):
    b = {k: v for k, v in BASE_BACKEND.items() if k not in ("GOOGLE_CLIENT_SECRET", "INTERNAL_SERVICE_TOKEN", "PUBLIC_WEB_BASE_URL")}
    caminho = gravar(tmp_path, ".env.render", b)
    codigo = vc.main(["--backend", str(caminho), "--frontend", str(tmp_path / "nao-existe")])
    saida = capsys.readouterr().out
    assert codigo == 1
    for nome in ("GOOGLE_CLIENT_SECRET", "INTERNAL_SERVICE_TOKEN", "PUBLIC_WEB_BASE_URL"):
        assert f"[FALTA] {nome}" in saida


@pytest.mark.parametrize("chave,valor,trecho", [
    ("STRIPE_API_KEY", "sk_test_...", "RECUSA subir"),
    ("STRIPE_API_KEY", "sk_prod_" + "x" * 30, "RECUSA subir"),
    ("STRIPE_WEBHOOK_SECRET", "abc123", "whsec_"),
    ("MONGO_URL", "mongodb+srv://usuario:<db_password>@c.mongodb.net/", "texto de exemplo"),
    ("MONGO_URL", "postgres://x", "mongodb://"),
    ("GOOGLE_OAUTH_REDIRECT_URI", "https://api.exemplo.com/api/auth/google", "/api/auth/google/callback"),
    ("GOOGLE_OAUTH_REDIRECT_URI", "http://api.exemplo.com/api/auth/google/callback", "https://"),
    ("STRIPE_PRICE_ID_ULTRA", "prod_123", "price_"),
    ("ALLOWED_ORIGINS", "http://localhost:8081", "não inclui o site"),
])
def test_valores_errados_comuns_sao_acusados(tmp_path, capsys, chave, valor, trecho):
    codigo, saida = rodar(tmp_path, capsys, backend={chave: valor})
    assert codigo == 1 and trecho in saida


def test_stripe_vazio_so_avisa_modo_simulado(tmp_path, capsys):
    codigo, saida = rodar(tmp_path, capsys, backend={"STRIPE_API_KEY": "", "STRIPE_WEBHOOK_SECRET": ""})
    assert codigo == 0 and "SIMULADO" in saida and "[ERRO]" not in saida and "[FALTA]" not in saida


def test_chave_de_producao_no_modo_teste_e_modos_misturados(tmp_path, capsys):
    codigo, saida = rodar(tmp_path, capsys, backend={"STRIPE_API_KEY": "sk_live_" + "x" * 40})
    assert codigo == 1 and "é de producao, mas você está conferindo o modo teste" in saida and "MODOS MISTURADOS" in saida


def test_modo_producao_exige_chaves_reais_e_recomenda_travas(tmp_path, capsys):
    codigo, saida = rodar(tmp_path, capsys, modo="producao")
    assert codigo == 1 and "STRIPE_API_KEY é de teste" in saida and "publicável do Stripe é de teste" in saida
    assert "EXIGIR_RECEBIMENTO_ATIVO não está em 1" in saida and "PLANOS_COMPRA_HABILITADA está ligada" in saida
    ok_prod = {"STRIPE_API_KEY": "sk_live_" + "x" * 40, "EXIGIR_RECEBIMENTO_ATIVO": "1", "PLANOS_COMPRA_HABILITADA": "0",
               "ALLOWED_ORIGINS": "https://site.exemplo.com"}
    codigo, saida = rodar(tmp_path, capsys, backend=ok_prod, frontend={"EXPO_PUBLIC_STRIPE_PUBLISHABLE_KEY": "pk_live_" + "y" * 30}, modo="producao")
    assert codigo == 0, saida


def test_microsoft_e_email_sao_tudo_ou_nada(tmp_path, capsys):
    codigo, saida = rodar(tmp_path, capsys, backend={"MICROSOFT_CLIENT_ID": "11111111-2222-3333-4444-555555555555", "SMTP_HOST": "smtp.exemplo.com"})
    assert codigo == 1
    assert "Login com Microsoft INCOMPLETO: falta MICROSOFT_CLIENT_SECRET, MICROSOFT_OAUTH_REDIRECT_URI" in saida
    assert "precisa de SMTP_HOST **e** SMTP_FROM" in saida
    codigo, saida = rodar(tmp_path, capsys)
    assert codigo == 0 and "Login com Microsoft DESLIGADO" in saida and "Cadastro por e-mail DESLIGADO" in saida


def test_remetente_gmail_avisa_e_microsoft_com_uri_errada_erra(tmp_path, capsys):
    codigo, saida = rodar(tmp_path, capsys, backend={"SMTP_HOST": "smtp.exemplo.com", "SMTP_FROM": "ShowUp <meuemail@gmail.com>", "SMTP_USER": "u", "SMTP_PASSWORD": "p"})
    assert codigo == 0 and "@gmail.com" in saida and "cair no spam" in saida
    codigo, saida = rodar(tmp_path, capsys, backend={"MICROSOFT_CLIENT_ID": "11111111-2222-3333-4444-555555555555", "MICROSOFT_CLIENT_SECRET": "s",
                                                    "MICROSOFT_OAUTH_REDIRECT_URI": "https://api.exemplo.com/api/auth/microsoft"})
    assert codigo == 1 and "/api/auth/microsoft/callback" in saida


def test_codigos_no_log_so_em_teste_local(tmp_path, capsys):
    codigo, saida = rodar(tmp_path, capsys, backend={"EMAIL_CODIGOS_NO_LOG": "1"})
    assert codigo == 0 and "NUNCA no Render" in saida
    codigo, saida = rodar(tmp_path, capsys, backend={"EMAIL_CODIGOS_NO_LOG": "1", "STRIPE_API_KEY": "sk_live_" + "x" * 40,
                                                    "EXIGIR_RECEBIMENTO_ATIVO": "1", "PLANOS_COMPRA_HABILITADA": "0",
                                                    "ALLOWED_ORIGINS": "https://site.exemplo.com"},
                          frontend={"EXPO_PUBLIC_STRIPE_PUBLISHABLE_KEY": "pk_live_" + "y" * 30}, modo="producao")
    assert codigo == 1 and "em PRODUÇÃO" in saida


def test_app_apontando_pra_maquina_local_avisa_do_login_social(tmp_path, capsys):
    codigo, saida = rodar(tmp_path, capsys, frontend={"EXPO_PUBLIC_BACKEND_URL": "http://10.0.2.2:8001"})
    assert "NÃO funciona assim" in saida and "10.0.2.2" in saida


def test_app_e_servidor_com_client_id_diferente_ou_servidores_diferentes(tmp_path, capsys):
    codigo, saida = rodar(tmp_path, capsys, frontend={"EXPO_PUBLIC_GOOGLE_WEB_CLIENT_ID": "outro.apps.googleusercontent.com"})
    assert codigo == 1 and "diferente do GOOGLE_WEB_CLIENT_ID" in saida
    codigo, saida = rodar(tmp_path, capsys, frontend={"EXPO_PUBLIC_BACKEND_URL": "https://outro-servidor.onrender.com"})
    assert codigo == 1 and "o login não vai fechar" in saida


def test_segredo_dentro_do_app_e_barrado(tmp_path, capsys):
    codigo, saida = rodar(tmp_path, capsys, frontend={"EXPO_PUBLIC_STRIPE_SECRET": "x", "EXPO_PUBLIC_ALGO": "sk_test_" + "z" * 30})
    assert codigo == 1 and saida.count("parece um SEGREDO") == 2 and "sk_test_" + "z" * 30 not in saida


def test_le_formatos_de_env_variados(tmp_path):
    arq = tmp_path / ".env"
    arq.write_text('# c\nexport A="com aspas"\nB=sem-aspas\nC=\'simples\'\nD = com espaços # comentário\n\nE=a=b=c\nLIXO\n', encoding="utf-8")
    assert vc.ler_env(arq) == {"A": "com aspas", "B": "sem-aspas", "C": "simples", "D": "com espaços", "E": "a=b=c"}


def test_arquivo_com_bom_do_windows_e_lido(tmp_path):
    arq = tmp_path / ".env"
    arq.write_bytes(b'\xef\xbb\xbfDB_NAME="holdbooked"\r\nMONGO_URL=mongodb://x\r\n')
    assert vc.ler_env(arq) == {"DB_NAME": "holdbooked", "MONGO_URL": "mongodb://x"}


def test_gerar_segredos_sao_longos_e_diferentes_a_cada_vez(capsys):
    assert vc.main(["--gerar-segredos"]) == 0
    a = dict(re.findall(r"^(\w+)=([0-9a-f]+)$", capsys.readouterr().out, flags=re.M))
    assert vc.main(["--gerar-segredos"]) == 0
    b = dict(re.findall(r"^(\w+)=([0-9a-f]+)$", capsys.readouterr().out, flags=re.M))
    assert set(a) == {"INTERNAL_SERVICE_TOKEN", "AUTH_CODE_PEPPER"} and all(len(v) == 64 for v in a.values())
    assert a["INTERNAL_SERVICE_TOKEN"] != a["AUTH_CODE_PEPPER"] and a != b


def test_sem_nenhum_arquivo_orienta(tmp_path, capsys):
    assert vc.main(["--backend", str(tmp_path / "x"), "--frontend", str(tmp_path / "y")]) == 1
    assert "Copie o .env.example" in capsys.readouterr().out


def test_o_env_example_do_projeto_passa_pelo_leitor_e_nao_tem_segredo_real():
    exemplo = vc.ler_env(RAIZ / "backend" / ".env.example")
    assert "MONGO_URL" in exemplo and "SMTP_HOST" in exemplo and "MICROSOFT_CLIENT_ID" in exemplo
    assert all(not re.match(r"^(sk_(test|live)_[A-Za-z0-9]{20,}|whsec_[A-Za-z0-9]{20,})", v) for v in exemplo.values())


def test_nao_diz_que_o_cors_esta_ok_quando_nao_ha_site_para_comparar(tmp_path, capsys):
    b = {k: v for k, v in BASE_BACKEND.items() if k != "PUBLIC_WEB_BASE_URL"}
    caminho = gravar(tmp_path, ".env.render", b)
    assert vc.main(["--backend", str(caminho), "--frontend", str(tmp_path / "x")]) == 1
    saida = capsys.readouterr().out
    assert "[FALTA] PUBLIC_WEB_BASE_URL" in saida and "ALLOWED_ORIGINS inclui o site" not in saida


# ------------------------------------------------------------------ análise da MONGO_URL
@pytest.mark.parametrize("url,trecho", [
    ("mongodb+srv://USUARIO:SENHA@cluster0.abc.mongodb.net/", "texto de exemplo"),          # o exemplo do próprio roteiro, em maiúsculas
    ("mongodb+srv://eduardo:<db_password>@cluster0.abc.mongodb.net/", "entre < >"),
    ("mongodb+srv://eduardo:<minhasenha>@cluster0.abc.mongodb.net/", "entre < >"),
    ("mongodb+srv://eduardo:p@ss123@cluster0.abc.mongodb.net/", "caractere @"),
    ("mongodb+srv://eduardo:ab/cd@cluster0.abc.mongodb.net/", "caractere especial"),
    ("mongodb+srv://eduardo:pa:ss@cluster0.abc.mongodb.net/", "caractere especial"),
    ("mongodb+srv://eduardo:p%zzss@cluster0.abc.mongodb.net/", "% que não é uma codificação"),
    ("mongodb+srv://eduardo@cluster0.abc.mongodb.net/", "falta a senha"),
    ("mongodb+srv://eduardo:@cluster0.abc.mongodb.net/", "falta a senha"),
    ("mongodb+srv://cluster0.abc.mongodb.net/", "não tem usuário e senha"),
    ("postgres://x:y@z/", "não começa com mongodb"),
])
def test_url_do_mongo_com_erro_tipico_e_explicada(url, trecho):
    achados = vc.problemas_mongo_url(url)
    assert achados and any(trecho in a for a in achados), achados
    for achado in achados:                       # a explicação nunca repete a senha
        for pedaco in ("p@ss123", "ab/cd", "pa:ss", "minhasenha"):
            assert pedaco not in achado


@pytest.mark.parametrize("url", [
    "mongodb+srv://eduardo:Abc123xyz@cluster0.abc.mongodb.net/?retryWrites=true&w=majority",
    "mongodb+srv://eduardo:p%40ss%2Fcd@cluster0.abc.mongodb.net/",                        # caracteres especiais JÁ codificados
    "mongodb://localhost:27017", "mongodb://127.0.0.1:27017/holdbooked",                  # banco local, sem senha
    "mongodb://admin:Senha9988@10.0.0.5:27017/?authSource=admin",
])
def test_url_do_mongo_correta_nao_gera_falso_alarme(url):
    assert vc.problemas_mongo_url(url) == []


def test_verificador_de_config_acusa_o_exemplo_do_roteiro_em_maiusculas(tmp_path, capsys):
    codigo, saida = rodar(tmp_path, capsys, backend={"MONGO_URL": "mongodb+srv://USUARIO:SENHA@cluster0.xxxxx.mongodb.net/?retryWrites=true"})
    assert codigo == 1 and "texto de exemplo" in saida and "SENHA@" not in saida


@pytest.mark.parametrize("valor,codigo_esperado,trecho", [("60", 0, "60 min antes"), ("0", 0, "desligado"), ("1h", 1, "número de minutos"), ("-5", 1, "número de minutos")])
def test_lembrete_do_proximo_atendimento_precisa_ser_um_numero(tmp_path, capsys, valor, codigo_esperado, trecho):
    codigo, saida = rodar(tmp_path, capsys, backend={"LEMBRETE_PROFISSIONAL_MIN": valor})
    assert codigo == codigo_esperado and trecho in saida
