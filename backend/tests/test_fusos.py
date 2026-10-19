"""Fusos horários: lista por grupo no servidor, tabela do app em sincronia, e o horário de verão do app conferido com a base oficial (tzdata)."""
import json
import os
import re
import shutil
import subprocess
import sys
import zoneinfo
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import offline_env  # noqa: E402,F401

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

import server

RAIZ = Path(__file__).resolve().parents[2]
FRONT = RAIZ / "frontend"
ORIGINAIS = ["America/Sao_Paulo", "America/Manaus", "America/Rio_Branco", "America/Noronha"]


def _tabela_do_app() -> dict[str, tuple[int, str, str]]:
    ts = (FRONT / "src" / "lib" / "fusos.ts").read_text(encoding="utf-8")
    return {z: (int(b), r, g) for z, b, r, g in re.findall(r'"([\w/]+)": \{ base: (-?\d+), regra: "(\w+)", grupo: "(\w+)"(?:, permanenteDesde: \d+)? \}', ts)}


def test_lista_do_servidor_e_bem_formada_e_cada_fuso_existe_na_base_oficial():
    assert len(server.TIMEZONES) >= 90 and len(set(server.TIMEZONES)) == len(server.TIMEZONES)
    assert set(ORIGINAIS) <= set(server.TIMEZONES)                                         # quem já escolheu um fuso do Brasil não perde
    assert server.TIMEZONES == [z for zs in server.TIMEZONES_POR_GRUPO.values() for z in zs]
    for zona in server.TIMEZONES:
        ZoneInfo(zona)                                                                      # levanta se o servidor não conseguir calcular com ele


def test_rota_lista_fusos_planos_e_por_grupo():
    r = TestClient(server.app).get("/api/timezones").json()
    assert r["timezones"] == server.TIMEZONES
    assert [g["grupo"] for g in r["grupos"]] == list(server.TIMEZONES_POR_GRUPO)
    assert [z for g in r["grupos"] for z in g["timezones"]] == r["timezones"]


@pytest.mark.parametrize("zona", ["America/New_York", "Europe/Lisbon", "Asia/Tokyo", "America/Sao_Paulo", "America/Argentina/Buenos_Aires"])
def test_profissional_pode_escolher_fusos_de_outros_paises(zona):
    assert server.TimezoneRequest(timezone=zona).timezone == zona


@pytest.mark.parametrize("zona", ["", "Marte/Olympus", "america/sao_paulo", "UTC", "Etc/GMT+3", "America/Havana"])
def test_fuso_fora_da_lista_e_recusado(zona):
    with pytest.raises(ValidationError):
        server.TimezoneRequest(timezone=zona)


def test_servidor_calcula_os_horarios_no_fuso_escolhido_mesmo_com_horario_de_verao():
    """O servidor usa ZoneInfo (sempre certo); o app é que precisava aprender o horário de verão."""
    for zona in ("America/New_York", "Australia/Sydney", "America/Santiago", "Europe/Madrid"):
        tz = server._tz_for({"timezone": zona})
        assert tz.key == zona
        verao = datetime(2026, 7, 15, 12, 0, tzinfo=timezone.utc).astimezone(tz).utcoffset()
        inverno = datetime(2026, 1, 15, 12, 0, tzinfo=timezone.utc).astimezone(tz).utcoffset()
        assert verao != inverno, zona                                                       # todos esses mudam durante o ano


def test_tabela_do_app_tem_exatamente_os_fusos_do_servidor_e_o_mesmo_grupo():
    app = _tabela_do_app()
    assert set(app) == set(server.TIMEZONES), set(app) ^ set(server.TIMEZONES)
    for grupo, zonas in server.TIMEZONES_POR_GRUPO.items():
        for zona in zonas:
            assert app[zona][2] == grupo, zona


def test_todo_fuso_e_todo_grupo_tem_nome_no_app_e_traducao():
    ts = (FRONT / "src" / "lib" / "fusos.ts").read_text(encoding="utf-8")
    nomes = dict(re.findall(r'case "([\w/]+)": return t\(("(?:[^"\\]|\\.)*")\);', ts.split("export function nomeDoGrupoFuso")[0]))
    grupos = dict(re.findall(r'case "(\w+)": return t\(("(?:[^"\\]|\\.)*")\);', ts.split("export function nomeDoGrupoFuso")[1]))
    assert set(nomes) == set(server.TIMEZONES) and set(grupos) == set(server.TIMEZONES_POR_GRUPO)
    texto_en = (FRONT / "src" / "i18n" / "en.ts").read_text(encoding="utf-8")
    texto_es = (FRONT / "src" / "i18n" / "es.ts").read_text(encoding="utf-8")
    for chave in list(nomes.values()) + list(grupos.values()):
        assert f"  {chave}: " in texto_en and f"  {chave}: " in texto_es, chave


def test_api_do_app_nao_usa_mais_a_tabela_fixa_de_fusos():
    fmt = (FRONT / "src" / "lib" / "format.ts").read_text(encoding="utf-8")
    assert "OFFSET_MINUTOS" not in fmt and "TIMEZONE_LABELS" not in fmt and "offsetMinutos(" in fmt


# ------------------------------------------------------------------ o cálculo do app contra a base oficial
def _amostras_da_base_oficial() -> list[list]:
    """[fuso, instante_utc_ms, deslocamento_em_minutos] nas datas de troca (minuto a minuto) e a cada semana de 2025 a 2032."""
    zoneinfo.reset_tzpath(to=[])                       # força o pacote `tzdata` (versão fixa e atual), não o /usr/share/zoneinfo do computador
    ZoneInfo.clear_cache()
    try:
        offset = lambda z, dt: int(dt.astimezone(ZoneInfo(z)).utcoffset().total_seconds() // 60)
        inicio, fim = datetime(2025, 1, 1, tzinfo=timezone.utc), datetime(2033, 1, 1, tzinfo=timezone.utc)      # o passado não importa: agendamento é para o futuro
        ms = lambda dt: int(dt.timestamp() * 1000)
        amostras = []
        for zona in server.TIMEZONES:
            t, anterior = inicio, offset(zona, inicio)
            while t < fim:
                proximo = t + timedelta(days=1)
                atual = offset(zona, proximo)
                if atual != anterior:                  # houve troca neste dia: acha o MINUTO exato por bisseção
                    lo, hi = t, proximo
                    while hi - lo > timedelta(minutes=1):
                        meio = lo + (hi - lo) / 2
                        lo, hi = (meio, hi) if offset(zona, meio) == anterior else (lo, meio)
                    for delta in (-60, -1, 0, 1, 60):  # 1 h antes, 1 min antes, o instante da troca, 1 min depois, 1 h depois
                        dt = hi + timedelta(minutes=delta)
                        amostras.append([zona, ms(dt), offset(zona, dt)])
                anterior, t = atual, proximo
            dt = inicio
            while dt < fim:                            # e uma amostra por semana (dias e horas variados)
                amostras.append([zona, ms(dt), offset(zona, dt)])
                dt += timedelta(days=7, hours=5)
        return amostras
    finally:
        zoneinfo.reset_tzpath()
        ZoneInfo.clear_cache()


def _node_novo_o_bastante() -> bool:
    exe = shutil.which("node")
    if not exe:
        return False
    versao = subprocess.run([exe, "--version"], capture_output=True, text=True).stdout.strip().lstrip("v").split(".")
    return (int(versao[0]), int(versao[1])) >= (22, 6)


def _tzdata_disponivel() -> bool:
    import importlib.util
    return importlib.util.find_spec("tzdata") is not None


@pytest.mark.skipif(not _node_novo_o_bastante() and not os.environ.get("CI"), reason="precisa de Node 22.6+ (executa TypeScript direto)")
@pytest.mark.skipif(not _tzdata_disponivel() and not os.environ.get("CI"), reason="precisa do pacote tzdata (requirements.txt)")
def test_horario_de_verao_do_app_bate_com_a_base_oficial_em_todos_os_fusos(tmp_path):
    amostras = _amostras_da_base_oficial()
    assert len(amostras) > 20_000
    (tmp_path / "amostras.json").write_text(json.dumps(amostras), encoding="utf-8")
    for pasta in ("i18n", "lib"):
        (tmp_path / pasta).mkdir()
    for arq in ("core", "en", "es"):
        shutil.copy(FRONT / "src" / "i18n" / f"{arq}.ts", tmp_path / "i18n" / f"{arq}.ts")
    for arq in ("format", "fusos"):
        shutil.copy(FRONT / "src" / "lib" / f"{arq}.ts", tmp_path / "lib" / f"{arq}.ts")
    for arq in tmp_path.rglob("*.ts"):
        texto = arq.read_text(encoding="utf-8")
        texto = re.sub(r'"@/src/i18n/(\w+)"', lambda m: f'"{"./" if arq.parent.name == "i18n" else "../i18n/"}{m.group(1)}.ts"', texto)
        texto = re.sub(r'"@/src/lib/([\w-]+)"', r'"./\1.ts"', texto)
        arq.write_text(texto, encoding="utf-8")
    shutil.copy(Path(__file__).parent / "node" / "fusos.test.mjs", tmp_path / "teste.mjs")
    r = subprocess.run([shutil.which("node"), "--experimental-strip-types", "teste.mjs", "amostras.json"], cwd=tmp_path, capture_output=True, text=True, timeout=120)
    assert r.returncode == 0 and "fusos: OK" in r.stdout, (r.stderr or r.stdout)[-2500:]


# ------------------------------------------------------------------ interface: dropdowns por grupo e o limite da escolha múltipla
def _ler_front(rel: str) -> str:
    return (FRONT / rel).read_text(encoding="utf-8")


def test_telas_usam_dropdowns_por_grupo_no_lugar_dos_botoes_soltos():
    config = _ler_front("app/(app)/configuracoes.tsx")
    assert "<DropdownMultiGrupos" in config and "maximo={maxCats}" in config and "valores={selectedCats}" in config
    assert "<DropdownGrupos" in config and "valor={selectedTz}" in config
    assert "toggleCat" not in config and "tz-${tz}" not in config and "cat-${c}" not in config          # os botões soltos saíram
    busca = _ler_front("app/(app)/search.tsx")
    assert "<DropdownGrupos" in busca and "cat-chip-" not in busca
    assert "rotuloDoFuso(svcQ.data.timezone)" in _ler_front("app/(app)/book/[servicoId].tsx")


def test_limite_de_categorias_vem_do_servidor_e_nao_de_um_numero_fixo_na_tela():
    config = _ler_front("app/(app)/configuracoes.tsx")
    assert "catsQ.data?.maximo ?? 3" in config and "prev.length >= 3" not in config
    assert 'CATEGORIAS (até {{max}})' in config


def test_dropdown_multiplo_usa_a_regra_testada_do_limite():
    dd = _ler_front("src/components/dropdown.tsx")
    assert "alternarComLimite(valores, v, maximo)" in dd and "textoMaximo" in dd and "opacity: 0.45" in dd


@pytest.mark.skipif(not _node_novo_o_bastante() and not os.environ.get("CI"), reason="precisa de Node 22.6+ (executa TypeScript direto)")
def test_regra_do_limite_da_escolha_multipla_no_node(tmp_path):
    (tmp_path / "lib").mkdir()
    shutil.copy(FRONT / "src" / "lib" / "selecao.ts", tmp_path / "lib" / "selecao.ts")
    shutil.copy(Path(__file__).parent / "node" / "selecao.test.mjs", tmp_path / "teste.mjs")
    r = subprocess.run([shutil.which("node"), "--experimental-strip-types", "teste.mjs"], cwd=tmp_path, capture_output=True, text=True, timeout=60)
    assert r.returncode == 0 and "selecao: OK" in r.stdout, (r.stderr or r.stdout)[-1500:]
