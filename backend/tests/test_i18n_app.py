"""Idiomas do app (português, inglês, espanhol): todo texto passado a t() tem tradução, e o comportamento real funciona."""
import glob
import json
import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parents[2]
FRONT = RAIZ / "frontend"


def _ler_dicionario(nome: str) -> dict[str, str]:
    """Lê frontend/src/i18n/<nome>.ts (linhas "chave": "valor", — o arquivo é gerado, um par por linha)."""
    texto = (FRONT / "src" / "i18n" / f"{nome}.ts").read_text(encoding="utf-8")
    return {json.loads(k): json.loads(v) for k, v in re.findall(r'^\s+("(?:[^"\\]|\\.)*"): ("(?:[^"\\]|\\.)*"),$', texto, flags=re.M)}


def _arquivos_do_app():
    achados = glob.glob(str(FRONT / "app" / "**" / "*.ts*"), recursive=True) + glob.glob(str(FRONT / "src" / "**" / "*.ts*"), recursive=True)
    return [Path(a) for a in achados if "/i18n/" not in a.replace("\\", "/")]


def _chaves_usadas() -> dict[str, set[str]]:
    usadas: dict[str, set[str]] = {}
    for arq in _arquivos_do_app():
        for m in re.finditer(r'\bt\(\s*("(?:[^"\\]|\\.)*")', arq.read_text(encoding="utf-8")):
            usadas.setdefault(json.loads(m.group(1)), set()).add(arq.name)
    return usadas


EN, ES = _ler_dicionario("en"), _ler_dicionario("es")
USADAS = _chaves_usadas()
ph = lambda s: sorted(re.findall(r"\{\{\s*\w+\s*\}\}", s))


def test_o_app_tem_centenas_de_textos_traduziveis():
    assert len(USADAS) >= 340 and len(EN) == len(ES) == len(USADAS), (len(USADAS), len(EN), len(ES))


def test_todo_texto_do_app_tem_traducao_em_ingles_e_espanhol():
    faltam_en = sorted(k for k in USADAS if k not in EN)
    faltam_es = sorted(k for k in USADAS if k not in ES)
    assert faltam_en == [] and faltam_es == [], f"sem tradução — en: {faltam_en[:5]} | es: {faltam_es[:5]}"


def test_nao_sobra_traducao_de_texto_que_nao_existe_mais():
    assert sorted(set(EN) - set(USADAS)) == [] and sorted(set(ES) - set(USADAS)) == []


def test_traducoes_mantem_variaveis_quebras_de_linha_e_espacos_das_pontas():
    for pt in USADAS:
        for idioma, dic in (("en", EN), ("es", ES)):
            tr = dic[pt]
            assert tr.strip(), f"{idioma}: vazio para {pt!r}"
            assert ph(pt) == ph(tr), f"{idioma}: variáveis diferentes em {pt!r}"
            assert pt.count("\n") == tr.count("\n"), f"{idioma}: quebras de linha diferentes em {pt!r}"
            assert (pt[:1].isspace(), pt[-1:].isspace()) == (tr[:1].isspace(), tr[-1:].isspace()), f"{idioma}: espaço da ponta perdido em {pt!r}"


# traduções que ficam IGUAIS ao português de propósito (nomes, siglas, palavras parecidas nas duas línguas)
IGUAL_EN = {"Coaching", "Euro", "Fitness", "min", "Pets"}
IGUAL_ES = {"Acupuntura", "Dentista", "Fisioterapeuta", "Fonoaudiólogo(a)", "Médico(a)", "Psicólogo(a)", "(código: {{codigo}})", "Agenda", "Buscar", "Cancelado", "Cancelar", "Cancelar reserva", "Coaching", "Cobrado (100%)", "Conectar Stripe",
            "Confirmar reserva", "Continuar", "Copiar", "Código de 6 dígitos", "Documento adicional", "Dom", "Dólar australiano", "Enviar código", "Estética",
            "Euro", "Fitness", "IDIOMA", "Idioma", "Libra esterlina", "Mínimo 8 caracteres", "Perfil", "Peso argentino", "Peso colombiano", "Peso mexicano",
            "Reservas", "Sáb", "Terapia", "Todos", "Valor", "Valor ({{moeda}})", "Ver todos", "Ver →", "min"}


def _nomes_de_lugares() -> set[str]:
    """Cidades e grupos de fusos (Paris, Lima, Denver...): nome próprio, pode ser igual nos três idiomas."""
    ts = (FRONT / "src" / "lib" / "fusos.ts").read_text(encoding="utf-8")
    return {json.loads(m) for m in re.findall(r'return t\(("(?:[^"\\]|\\.)*")\);', ts)}


def test_nenhuma_traducao_ficou_igual_ao_portugues_sem_querer():
    lugares = _nomes_de_lugares()
    assert len(lugares) >= 100
    assert sorted(k.strip() for k in EN if EN[k] == k and k.strip() not in lugares) == sorted(IGUAL_EN)
    assert {k.strip() for k in ES if ES[k] == k} - lugares <= IGUAL_ES


def test_nao_ha_texto_solto_na_tela_sem_t():
    """Texto escrito direto no JSX (entre > e <) escaparia da tradução. Só 'api'/'Promise' (código genérico) e a marca SHOWUP passam."""
    soltos = {}
    for arq in glob.glob(str(FRONT / "app" / "**" / "*.tsx"), recursive=True) + glob.glob(str(FRONT / "src" / "components" / "*.tsx")):
        for m in re.finditer(r">\s*([A-Za-zÀ-ú][^<>{}=;()\n]*[A-Za-zÀ-ú.!?:…])\s*<", Path(arq).read_text(encoding="utf-8")):
            soltos.setdefault(m.group(1).strip(), set()).add(Path(arq).name)
    assert set(soltos) <= {"api", "Promise", "SHOWUP"}, soltos


def test_toda_tela_que_traduz_se_redesenha_ao_trocar_de_idioma():
    """Sem useIdioma(), a tela ficaria no idioma antigo até ser recriada. Telas e componentes (menos classe e os seletores) precisam chamá-lo."""
    sem_hook = []
    for arq in glob.glob(str(FRONT / "app" / "**" / "*.tsx"), recursive=True) + glob.glob(str(FRONT / "src" / "components" / "*.tsx")):
        texto = Path(arq).read_text(encoding="utf-8")
        if re.search(r'\bt\("', texto) and not re.search(r"\buseIdioma\(\)", texto) and "class ErrorBoundary" not in texto and "seletor-" not in arq:
            sem_hook.append(Path(arq).name)
    assert sem_hook == [], sem_hook


def test_seletores_de_idioma_e_moeda_estao_nas_telas_certas():
    assert "<SeletorIdioma" in (FRONT / "app" / "welcome.tsx").read_text(encoding="utf-8")          # antes de entrar na conta
    assert "<SeletorIdioma" in (FRONT / "app" / "(app)" / "perfil.tsx").read_text(encoding="utf-8")
    config = (FRONT / "app" / "(app)" / "configuracoes.tsx").read_text(encoding="utf-8")
    assert "<SeletorMoeda" in config and "chipsRow}>\n          {(moedasQ" not in config                 # moeda é dropdown, não botões soltos
    core = (FRONT / "src" / "i18n" / "core.ts").read_text(encoding="utf-8")
    assert [c for c in re.findall(r'codigo: "([^"]+)"', core)] == ["pt-BR", "en", "es"]


def test_api_do_app_avisa_o_idioma_ao_servidor():
    assert '"Accept-Language": getIdioma()' in (FRONT / "src" / "lib" / "api.ts").read_text(encoding="utf-8")


def _node_novo_o_bastante() -> bool:
    exe = shutil.which("node")
    if not exe:
        return False
    versao = subprocess.run([exe, "--version"], capture_output=True, text=True).stdout.strip().lstrip("v").split(".")
    return (int(versao[0]), int(versao[1])) >= (22, 6)


@pytest.mark.skipif(not _node_novo_o_bastante() and not os.environ.get("CI"), reason="precisa de Node 22.6+ (executa TypeScript direto)")
def test_comportamento_real_em_portugues_ingles_e_espanhol(tmp_path):
    """Roda o código de verdade no Node: detecção do idioma, datas, moedas, estados do Stripe, mensagens (pt idêntico ao de antes)."""
    for pasta in ("i18n", "lib"):
        (tmp_path / pasta).mkdir()
    for arq in ("core", "en", "es"):
        shutil.copy(FRONT / "src" / "i18n" / f"{arq}.ts", tmp_path / "i18n" / f"{arq}.ts")
    for arq in ("format", "fusos", "moedas", "categorias", "auth-email", "connect-estado", "notificacoes-erros", "agenda-janela"):
        shutil.copy(FRONT / "src" / "lib" / f"{arq}.ts", tmp_path / "lib" / f"{arq}.ts")
    for arq in tmp_path.rglob("*.ts"):
        texto = arq.read_text(encoding="utf-8")
        texto = re.sub(r'"@/src/i18n/(\w+)"', lambda m: f'"{"./" if arq.parent.name == "i18n" else "../i18n/"}{m.group(1)}.ts"', texto)
        texto = re.sub(r'"@/src/lib/([\w-]+)"', r'"./\1.ts"', texto)
        arq.write_text(texto, encoding="utf-8")
    shutil.copy(Path(__file__).parent / "node" / "i18n_app.test.mjs", tmp_path / "teste.mjs")
    r = subprocess.run([shutil.which("node"), "--experimental-strip-types", "teste.mjs"], cwd=tmp_path, capture_output=True, text=True, timeout=60)
    assert r.returncode == 0 and "i18n do app: OK" in r.stdout, r.stderr[-1500:]
