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
    assert set(trocas) == {"termos.html", "excluir-conta.html", "privacidade.html", "index.html"}
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


# ------------------------------------------------------------------ lembrar os dados e reaplicar depois de um zip novo
@pytest.fixture
def dados_locais(tmp_path, monkeypatch):
    arquivo = tmp_path / "dados-site.local.json"
    monkeypatch.setattr(ps, "DADOS_LOCAIS", arquivo)
    return arquivo


def test_preencher_guarda_os_dados_e_reaplicar_refaz_depois_de_um_zip_novo(pasta, dados_locais):
    assert ps.main(["--responsavel", "Ana Lima", "--email", "oi@ana.com", "--sem-documento", "--pasta", str(pasta)]) == 0
    import json
    assert json.loads(dados_locais.read_text(encoding="utf-8")) == {"responsavel": "Ana Lima", "email": "oi@ana.com", "sem_documento": True}
    # um zip novo devolve as páginas com os campos em branco...
    shutil.rmtree(pasta)
    shutil.copytree(SITE, pasta)
    assert ps.verificar(pasta) != []
    # ...e um comando só refaz tudo
    assert ps.main(["--reaplicar", "--pasta", str(pasta)]) == 0
    assert ps.verificar(pasta) == [] and "Ana Lima" in (pasta / "termos.html").read_text(encoding="utf-8")


def test_reaplicar_sem_dados_guardados_orienta_e_nao_altera_nada(pasta, dados_locais, capsys):
    antes = (pasta / "termos.html").read_text(encoding="utf-8")
    assert ps.main(["--reaplicar", "--pasta", str(pasta)]) == 1
    assert "Não há dados guardados" in capsys.readouterr().out
    assert (pasta / "termos.html").read_text(encoding="utf-8") == antes


def test_trocar_de_sem_documento_para_documento_atualiza_o_que_foi_guardado(pasta, dados_locais):
    import json
    ps.main(["--responsavel", "Ana", "--email", "a@b.co", "--sem-documento", "--pasta", str(pasta)])
    shutil.rmtree(pasta); shutil.copytree(SITE, pasta)
    ps.main(["--responsavel", "Ana", "--email", "a@b.co", "--documento", "CNPJ 1", "--pasta", str(pasta)])
    guardado = json.loads(dados_locais.read_text(encoding="utf-8"))
    assert guardado["documento"] == "CNPJ 1" and "sem_documento" not in guardado
    shutil.rmtree(pasta); shutil.copytree(SITE, pasta)
    assert ps.main(["--reaplicar", "--pasta", str(pasta)]) == 0 and "CNPJ 1" in (pasta / "termos.html").read_text(encoding="utf-8")


def test_dados_guardados_nao_vao_para_o_git():
    gitignore = (RAIZ / ".gitignore").read_text(encoding="utf-8")
    assert "lancamento/dados-site.local.json" in gitignore


# ------------------------------------------------------------------ site profissional: início, 404, link legível, pré-visualização
def _ler(nome):
    return (SITE / nome).read_text(encoding="utf-8")


def test_arquivos_do_site_profissional_existem():
    for nome in ("index.html", "404.html", "agendar.html", "logo.png", "favicon.ico", "favicon-32.png", "apple-touch-icon.png", "og.png", "robots.txt", "sitemap.xml"):
        assert (SITE / nome).exists(), nome
    assert (SITE / "og.png").read_bytes()[:8] == b"\x89PNG\r\n\x1a\n" and (SITE / "og.png").stat().st_size > 5_000


def test_pagina_inicial_tem_o_essencial_e_so_os_campos_que_o_script_preenche():
    import re
    html = _ler("index.html")
    assert 'id="conteudo"' in html and "<h1>Cliente reservou? Então ele aparece.</h1>" in html
    assert set(re.findall(r"\{\{[A-Z_]+\}\}", html)) == {"{{EMAIL_CONTATO}}", "{{RESPONSAVEL}}"}      # nenhum campo que o script não saiba preencher
    for link in ('href="/termos"', 'href="/privacidade"', 'href="/excluir-conta"', "mailto:{{EMAIL_CONTATO}}"):
        assert link in html
    assert html.count("<details>") >= 5                                                                    # dúvidas frequentes


def test_pagina_inicial_nao_promete_o_que_o_produto_nao_faz():
    """Pix está desligado, o app é só Android e as taxas/planos podem mudar: a página não pode afirmar o contrário."""
    import re
    texto = re.sub(r"<style.*?</style>", "", _ler("index.html").lower(), flags=re.S)          # só o texto da página, sem o CSS
    for proibido in (r"\bpix\b", r"\biphone\b", r"\bios\b", r"app store", r"\b\d{1,2}\s?%", r"r\$\s?(19|59)", r"grátis para sempre", r"garantimos"):
        assert not re.search(proibido, texto), f"a página inicial menciona algo proibido: {proibido}"


def test_pre_visualizacao_do_link_no_whatsapp_em_todas_as_paginas_publicas():
    import re
    for nome in ("index.html", "agendar.html", "termos.html", "privacidade.html", "excluir-conta.html"):
        html = _ler(nome)
        for tag in ('name="description"', 'property="og:title"', 'property="og:description"', 'property="og:image"', 'rel="icon"', 'name="theme-color"'):
            assert tag in html, f"{nome} sem {tag}"
        imagem = re.search(r'property="og:image" content="([^"]+)"', html).group(1)
        assert imagem.startswith("https://") and imagem.endswith("/og.png")                                  # o WhatsApp exige endereço absoluto


def test_pagina_de_agendamento_nao_e_indexada_e_nao_mostra_a_versao_ao_cliente():
    html = _ler("agendar.html")
    assert 'name="robots" content="noindex, nofollow"' in html
    assert 'name="versao-da-pagina" content="v2026.10.15"' in html                                         # o verificador continua achando
    assert 'id="versaoPagina"' not in html and ">v2026.10.15<" not in html                                  # mas o cliente não vê


def test_pagina_de_agendamento_le_o_endereco_legivel_e_o_link_antigo():
    html = _ler("agendar.html")
    assert r"/^\/p\/([^/]+)\/?$/" in html and 'params.get("prof")' in html
    assert "profissionalId = data.user_id" in html                      # depois de carregar, tudo usa o id interno
    assert "/profissionais/${encodeURIComponent(identificador)}" in html
    assert "/profissionais/${profissionalId}/slots" in html and html.count("profissional_id: profissionalId") == 2


def test_pagina_de_agendamento_explica_a_garantia_antes_de_pedir_o_cartao():
    html = _ler("agendar.html")
    assert "só é cobrado depois do atendimento" in html and "processado pelo Stripe" in html


def test_firebase_redireciona_p_para_a_pagina_de_agendamento_e_protege_a_pagina():
    import json
    h = json.loads((RAIZ / "firebase-hosting" / "firebase.json").read_text(encoding="utf-8"))["hosting"]
    assert {"source": "/p/**", "destination": "/agendar.html"} in h["rewrites"]
    cabecalhos = {c["key"]: c["value"] for bloco in h["headers"] for c in bloco["headers"]}
    assert cabecalhos["X-Frame-Options"] == "DENY" and cabecalhos["X-Content-Type-Options"] == "nosniff"
    assert "Referrer-Policy" in cabecalhos and cabecalhos["Cache-Control"] == "no-cache"


def test_sitemap_so_lista_paginas_que_existem_e_o_robots_aponta_para_ele():
    import re
    paginas = {m.rsplit("/", 1)[-1] or "index" for m in re.findall(r"<loc>https://[^/<]+(/[^<]*)</loc>", _ler("sitemap.xml"))}
    assert paginas == {"index", "termos", "privacidade", "excluir-conta"}
    for p in paginas:
        assert (SITE / f"{p}.html").exists()
    robots = _ler("robots.txt")
    assert "Sitemap: https://" in robots and "Disallow: /p/" in robots and "Disallow: /agendar" in robots


def test_todo_endereco_absoluto_do_site_usa_o_mesmo_dominio():
    """Se alguém digitar outro domínio numa página, o trocar-dominio.py não o encontraria: todas as páginas têm que concordar."""
    import re
    hosts = set()
    for arq in list(SITE.glob("*.html")) + [SITE / "sitemap.xml", SITE / "robots.txt"]:
        hosts |= set(re.findall(r"https://([a-z0-9.-]+\.(?:web\.app|com\.br|com|app))/(?:og\.png|sitemap\.xml|termos|privacidade|excluir-conta|\"|$)", arq.read_text(encoding="utf-8")))
    assert hosts <= {"showup-509120.web.app"}, hosts


# ------------------------------------------------------------------ a identidade do site é a MESMA do aplicativo
def test_todas_as_paginas_usam_a_logo_do_app_e_nenhuma_marca_inventada():
    for nome in ("index.html", "agendar.html", "404.html", "termos.html", "privacidade.html", "excluir-conta.html", "stripe-bounce.html"):
        html = _ler(nome)
        assert 'src="/logo.png"' in html, f"{nome} sem a logo do app"
        assert "brand-mark" not in html and 'class="mark"' not in html, f"{nome} ainda tem a marca inventada"
        assert "favicon.svg" not in html, nome


def test_paleta_do_site_vem_do_tema_do_app():
    """O azul de marca do app (frontend/src/theme.ts) é o theme-color do site, e nenhuma cor do tema antigo (verde/bege) sobrou."""
    import re
    tema = (RAIZ / "frontend" / "src" / "theme.ts").read_text(encoding="utf-8")
    brand = re.search(r'brand:\s*"(#[0-9A-Fa-f]{6})"', tema).group(1).upper()
    secundaria = re.search(r'brandSecondary:\s*"(#[0-9A-Fa-f]{6})"', tema).group(1).upper()
    assert brand == "#4C97C1" and secundaria == "#7FB667"
    for nome in ("index.html", "agendar.html", "404.html", "termos.html", "privacidade.html", "excluir-conta.html"):
        assert f'name="theme-color" content="{brand}"' in _ler(nome), f"{nome}: theme-color diferente do azul do app"
    for nome in ("index.html", "agendar.html", "404.html", "termos.html", "privacidade.html", "excluir-conta.html", "stripe-bounce.html"):
        html = _ler(nome).upper()
        for velha in ("#345940", "#213B29", "#F5F1E8", "#1C2E22", "#16211A", "#6FA482"):
            assert velha not in html, f"{nome} ainda usa a cor antiga {velha}"


def test_logo_do_site_e_a_mesma_imagem_do_app():
    """Se alguém trocar a logo do app e esquecer o site, este teste avisa (precisa do Pillow; sem ele, é pulado)."""
    PIL = pytest.importorskip("PIL.Image")
    app = PIL.open(RAIZ / "frontend" / "assets" / "images" / "splash-image.png").convert("RGBA")
    x0, y0, x1, y1 = app.getbbox()
    recorte = app.crop((max(0, x0 - 16), max(0, y0 - 16), min(app.width, x1 + 16), min(app.height, y1 + 16))).resize((64, 51))
    site = PIL.open(SITE / "logo.png").convert("RGBA")
    assert site.mode == "RGBA" and site.getchannel("A").getextrema()[0] == 0                   # fundo transparente
    site = site.resize((64, 51))
    diferenca = sum(abs(a - b) for pa, pb in zip(recorte.getdata(), site.getdata()) for a, b in zip(pa, pb)) / (64 * 51 * 4)
    assert diferenca < 6, f"a logo do site difere da do app (diferença média {diferenca:.1f})"


# ------------------------------------------------------------------ página de agendamento em português, inglês e espanhol
def _dicionarios_da_pagina():
    import json
    import re
    html = _ler("agendar.html")
    bloco = html[html.index("const DICIONARIO = {"):html.index("const IDIOMAS_OK")]
    parte_en, parte_es = bloco.split("    es: {")
    pares = lambda trecho: {json.loads(k): json.loads(v) for k, v in re.findall(r'^\s+("(?:[^"\\]|\\.)*"): ("(?:[^"\\]|\\.)*"),$', trecho, flags=re.M)}
    return pares(parte_en), pares(parte_es)


def _textos_estaticos_da_pagina():
    """Todo texto visível no HTML (fora de script, style e option) e os placeholders/aria-label."""
    import re
    from html.parser import HTMLParser

    class Coletor(HTMLParser):
        def __init__(self):
            super().__init__()
            self.pilha, self.textos, self.attrs, self.no_body = [], [], [], False

        def handle_starttag(self, tag, attrs):
            if tag == "body":
                self.no_body = True
            if tag not in ("meta", "link", "br", "input", "img"):
                self.pilha.append(tag)
            for k, v in attrs:
                if k in ("placeholder", "aria-label") and v:
                    self.attrs.append(v)

        def handle_endtag(self, tag):
            if tag in self.pilha:
                while self.pilha and self.pilha.pop() != tag:
                    pass

        def handle_data(self, data):
            if self.no_body and not ({"script", "style", "option"} & set(self.pilha)):
                t = re.sub(r"\s+", " ", data).strip()
                if re.search(r"[A-Za-zÀ-ú]", t):                       # qualquer texto com letra (até "e a" entre dois links)
                    self.textos.append(t)

    c = Coletor()
    c.feed(_ler("agendar.html"))
    return c.textos, [a for a in c.attrs if a != "Idioma / Language" and re.search(r"[A-Za-zÀ-ú]", a)]


def test_pagina_todo_texto_do_html_tem_traducao_em_ingles_e_espanhol():
    en, es = _dicionarios_da_pagina()
    estaticos, atributos = _textos_estaticos_da_pagina()
    marcas = {"ShowUp", "Pix"}
    faltam = sorted({t for t in estaticos + atributos if t not in marcas and (t not in en or t not in es)})
    assert faltam == [], f"textos do HTML sem tradução: {faltam}"


def test_pagina_todo_T_do_javascript_tem_traducao_em_ingles_e_espanhol():
    import json
    import re
    en, es = _dicionarios_da_pagina()
    usados = {json.loads(m) for m in re.findall(r'\bT\(\s*("(?:[^"\\]|\\.)*")', _ler("agendar.html"))}
    assert len(usados) >= 25, "esperava achar os T(...) do JavaScript"
    assert sorted(usados - set(en)) == [] and sorted(usados - set(es)) == []


def test_pagina_dicionarios_sem_sobras_variaveis_iguais_e_sem_vazios():
    import re
    en, es = _dicionarios_da_pagina()
    estaticos, atributos = _textos_estaticos_da_pagina()
    import json
    usados = {json.loads(m) for m in re.findall(r'\bT\(\s*("(?:[^"\\]|\\.)*")', _ler("agendar.html"))} | set(estaticos) | set(atributos)
    assert set(en) == set(es), "inglês e espanhol com chaves diferentes"
    assert sorted(set(en) - usados) == [], "tradução de um texto que não existe mais na página"
    ph = lambda s: sorted(re.findall(r"\\{\\{\\w+\\}\\}", s))
    for pt, tr_en in en.items():
        for tr in (tr_en, es[pt]):
            assert tr.strip() and ph(pt) == ph(tr), f"variáveis ou texto vazio em {pt!r}"


def test_pagina_detecta_idioma_do_navegador_com_escolha_guardada_e_pede_erros_no_mesmo_idioma():
    html = _ler("agendar.html")
    for trecho in ('localStorage.getItem("idioma")', "navigator.languages", 'IDIOMAS_OK = ["pt", "en", "es"]', 'const CAB = { "Accept-Language": IDIOMA }',
                   'id="idiomaSelect"', 'classList.toggle("hidden", n !== 1)', "new Intl.NumberFormat(LOCALE"):
        assert trecho in html, trecho
    assert html.count("...CAB") == 3 and html.count("{ headers: CAB }") == 3          # todas as chamadas ao servidor levam o idioma
    assert 'toLocaleString("pt-BR"' not in html                                          # o valor não é mais sempre formatado em português
