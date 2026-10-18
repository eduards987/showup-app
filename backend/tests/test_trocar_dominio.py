"""trocar-dominio.py: troca o endereço do site em todos os arquivos certos, sem mexer no resto."""
import importlib.util
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("trocar_dominio", RAIZ / "lancamento" / "trocar-dominio.py")
td = importlib.util.module_from_spec(spec)
spec.loader.exec_module(td)

ANTIGO = "showup-509120.web.app"


@pytest.fixture
def projeto(tmp_path):
    arqs = {
        "firebase-hosting/public/index.html": f'<link rel="canonical" href="https://{ANTIGO}/"><meta property="og:image" content="https://{ANTIGO}/og.png">',
        "firebase-hosting/public/termos.html": f'<meta property="og:image" content="https://{ANTIGO}/og.png"> Termos çãõ',
        "firebase-hosting/public/sitemap.xml": f"<loc>https://{ANTIGO}/</loc><loc>https://{ANTIGO}/termos</loc>",
        "firebase-hosting/public/robots.txt": f"Sitemap: https://{ANTIGO}/sitemap.xml",
        "frontend/src/lib/legal.ts": f'const WEB = (process.env.EXPO_PUBLIC_WEB_URL ?? "https://{ANTIGO}")',
        "frontend/.env.example": f'# EXPO_PUBLIC_WEB_URL="https://{ANTIGO}"',
        "backend/server.py": f'PUBLIC_WEB_BASE_URL = os.environ.get("PUBLIC_WEB_BASE_URL", "https://{ANTIGO}")',
        # arquivos que NÃO podem ser tocados:
        "frontend/.env": f"EXPO_PUBLIC_WEB_URL=https://{ANTIGO}",
        "backend/.env": f"PUBLIC_WEB_BASE_URL=https://{ANTIGO}",
        "lancamento/DEPLOY.md": f"https://{ANTIGO}",
        "frontend/node_modules/x/index.js": ANTIGO,
    }
    for nome, conteudo in arqs.items():
        p = tmp_path / nome
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(conteudo, encoding="utf-8")
    return tmp_path, arqs


def rodar(raiz, *args):
    return td.main(["--raiz", str(raiz), *args])


def test_troca_so_os_arquivos_certos_e_conta_cada_um(projeto, capsys):
    raiz, originais = projeto
    assert rodar(raiz, "--para", "meusite.com.br") == 0
    saida = capsys.readouterr().out
    for nome in ("index.html", "termos.html", "sitemap.xml", "robots.txt", "legal.ts", ".env.example", "server.py"):
        assert nome in saida
    assert "index.html: 2 ocorrência(s)" in saida and "sitemap.xml: 2 ocorrência(s)" in saida
    assert "https://meusite.com.br/" in (raiz / "firebase-hosting/public/sitemap.xml").read_text(encoding="utf-8")
    assert "Termos çãõ" in (raiz / "firebase-hosting/public/termos.html").read_text(encoding="utf-8")        # acentos preservados
    for nome in ("frontend/.env", "backend/.env", "lancamento/DEPLOY.md", "frontend/node_modules/x/index.js"):
        assert (raiz / nome).read_text(encoding="utf-8") == originais[nome], f"{nome} não podia mudar"
    for nome in ("firebase-hosting/public/index.html", "frontend/src/lib/legal.ts", "backend/server.py"):
        assert ANTIGO not in (raiz / nome).read_text(encoding="utf-8")


def test_simular_nao_altera_nada(projeto, capsys):
    raiz, originais = projeto
    assert rodar(raiz, "--para", "meusite.com.br", "--simular") == 0
    assert "Mudaria" in capsys.readouterr().out
    for nome, conteudo in originais.items():
        assert (raiz / nome).read_text(encoding="utf-8") == conteudo


def test_rodar_de_novo_nao_faz_nada(projeto, capsys):
    raiz, _ = projeto
    rodar(raiz, "--para", "meusite.com.br")
    capsys.readouterr()
    assert rodar(raiz, "--para", "meusite.com.br") == 0                       # mesmo comando outra vez
    assert "Nada a trocar" in capsys.readouterr().out                         # o endereço antigo não existe mais nos arquivos
    assert "meusite.com.br" in (raiz / "backend/server.py").read_text(encoding="utf-8")


def test_dominio_igual_ao_atual_nao_faz_nada(projeto, capsys):
    raiz, originais = projeto
    assert rodar(raiz, "--para", ANTIGO) == 0 and "nada a trocar" in capsys.readouterr().out
    assert (raiz / "backend/server.py").read_text(encoding="utf-8") == originais["backend/server.py"]


@pytest.mark.parametrize("ruim", ["https://meusite.com.br", "meusite.com.br/", "meu site.com.br", "semponto", "-x.com.br", "x..com", "", "a" * 70 + ".com"])
def test_dominios_invalidos_sao_recusados_e_nada_muda(projeto, capsys, ruim):
    raiz, originais = projeto
    assert rodar(raiz, f"--para={ruim}") == 1
    assert "não é um domínio válido" in capsys.readouterr().out
    assert (raiz / "backend/server.py").read_text(encoding="utf-8") == originais["backend/server.py"]


def test_maiusculas_sao_normalizadas(projeto):
    raiz, _ = projeto
    assert rodar(raiz, "--para", "MeuSite.COM.br") == 0
    robots = (raiz / "firebase-hosting/public/robots.txt").read_text(encoding="utf-8")
    assert "https://meusite.com.br/sitemap.xml" in robots and "MeuSite" not in robots


def test_depois_de_trocar_lista_o_que_falta_fora_do_codigo(projeto, capsys):
    raiz, _ = projeto
    rodar(raiz, "--para", "meusite.com.br")
    saida = capsys.readouterr().out
    for esperado in ("PUBLIC_WEB_BASE_URL=https://meusite.com.br", "ALLOWED_ORIGINS", "EXPO_PUBLIC_WEB_URL=https://meusite.com.br", "firebase deploy", "verificar-producao.py"):
        assert esperado in saida


def test_o_projeto_real_so_tem_o_dominio_antigo_nos_arquivos_que_o_script_conhece():
    """Se alguém gravar o endereço em outro arquivo, o script não o trocaria: este teste avisa."""
    conhecidos = {p.resolve() for p in td.arquivos(RAIZ)}
    achados = []
    for ext in ("*.html", "*.xml", "*.txt", "*.py", "*.ts", "*.tsx", "*.js", "*.json"):
        for arq in RAIZ.rglob(ext):
            partes = set(arq.parts)
            if partes & {"node_modules", ".git", "tests", "android", "dist", ".venv"} or arq.resolve() in conhecidos:
                continue
            try:
                if ANTIGO in arq.read_text(encoding="utf-8"):
                    achados.append(str(arq.relative_to(RAIZ)))
            except (UnicodeDecodeError, OSError):
                pass
    # exemplos em documentação do próprio lancamento/ são aceitos; código real, não
    assert [a for a in achados if not a.startswith("lancamento/")] == [], achados
