"""Moedas aceitas e país da conta Stripe do profissional."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import offline_env  # noqa: E402,F401

import server

# Moedas "sem centavos" do Stripe (valor inteiro, sem x100): https://docs.stripe.com/currencies#zero-decimal
SEM_CENTAVOS = {"BIF", "CLP", "DJF", "GNF", "JPY", "KMF", "KRW", "MGA", "PYG", "RWF", "UGX", "VND", "VUV", "XAF", "XOF", "XPF"}


def test_nenhuma_moeda_sem_centavos_na_lista():
    """O app guarda centavos (x100): numa moeda sem centavos o Stripe cobraria 100 vezes o valor digitado."""
    assert SEM_CENTAVOS.isdisjoint(server.MOEDAS_SUPORTADAS), SEM_CENTAVOS & set(server.MOEDAS_SUPORTADAS)


def test_lista_de_moedas_e_o_que_o_app_mostra_no_dropdown():
    nomes_no_app = (Path(__file__).resolve().parents[2] / "frontend" / "src" / "lib" / "moedas.ts").read_text(encoding="utf-8")
    for moeda in server.MOEDAS_SUPORTADAS:
        assert f'case "{moeda}"' in nomes_no_app, f"o app não tem o nome da moeda {moeda}"


def test_conta_stripe_do_profissional_e_sempre_no_pais_da_plataforma():
    assert server.CONNECT_PAIS == "BR"
    fonte = (Path(server.__file__)).read_text(encoding="utf-8")
    assert "MOEDA_PAIS_CONNECT" not in fonte                       # o país não é mais inferido da moeda
    assert fonte.count("country=CONNECT_PAIS") == 2                # os dois pontos que abrem a conta Connect


# ------------------------------------------------------------------ em que moedas o dinheiro CHEGA sem conversão
def test_lista_de_moedas_informa_em_quais_o_stripe_deposita_sem_converter(monkeypatch):
    from fastapi.testclient import TestClient
    client = TestClient(server.app)
    r = client.get("/api/moedas").json()
    assert r["moedas"] == server.MOEDAS_SUPORTADAS and r["moedas_de_recebimento"] == ["BRL"]          # conta brasileira: só reais
    monkeypatch.setattr(server, "MOEDAS_RECEBIMENTO", ["BRL", "USD"])                                 # depois que o Stripe liberar dólar
    assert client.get("/api/moedas").json()["moedas_de_recebimento"] == ["BRL", "USD"]
    monkeypatch.setattr(server, "MOEDAS_RECEBIMENTO", ["XXX", "USD"])                                 # moeda desconhecida é ignorada
    assert client.get("/api/moedas").json()["moedas_de_recebimento"] == ["USD"]
    monkeypatch.setattr(server, "MOEDAS_RECEBIMENTO", [])                                             # configuração vazia nunca deixa sem nenhuma
    assert client.get("/api/moedas").json()["moedas_de_recebimento"] == ["BRL"]


def test_variavel_de_ambiente_das_moedas_de_recebimento_e_lida_sem_espacos_nem_minusculas(monkeypatch):
    import importlib
    monkeypatch.setenv("MOEDAS_RECEBIMENTO", " brl , usd ,")
    recarregado = importlib.reload(server)
    try:
        assert recarregado.MOEDAS_RECEBIMENTO == ["BRL", "USD"]
    finally:
        monkeypatch.delenv("MOEDAS_RECEBIMENTO")
        importlib.reload(server)


def test_telas_do_profissional_mostram_o_aviso_de_conversao():
    import re
    front = Path(__file__).resolve().parents[2] / "frontend"
    config = (front / "app/(app)/configuracoes.tsx").read_text(encoding="utf-8")
    servico = (front / "app/(app)/novo-servico.tsx").read_text(encoding="utf-8")
    # o aviso precisa estar ligado a uma condição VERDADEIRA de verdade (não "false", não só a palavra no arquivo)
    assert re.search(r"\{avisoDeConversao\(selectedMoeda, moedasQ\.data\?\.moedas_de_recebimento, moedasQ\.data\?\.adicional_conversao_bps\) \?", config) and 'testID="aviso-conversao"' in config
    assert re.search(r"const aviso = avisoDeConversao\(moeda, moedasQ\.data\?\.moedas_de_recebimento, moedasQ\.data\?\.adicional_conversao_bps\);", servico)
    assert re.search(r"\{aviso \? <Text testID=\"aviso-conversao\"", servico)


def test_o_padrao_do_adicional_no_app_e_o_mesmo_do_servidor():
    """Enquanto o /api/moedas não responde, o app usa um padrão: ele não pode contar outra história."""
    import re
    import server
    moedas_ts = (Path(__file__).resolve().parents[2] / "frontend/src/lib/moedas.ts").read_text(encoding="utf-8")
    padrao = int(re.search(r"export const ADICIONAL_CONVERSAO_BPS_PADRAO = (\d+);", moedas_ts).group(1))
    assert padrao == server.ADICIONAL_CONVERSAO_BPS
    assert "não cobra nada a mais" not in moedas_ts   # o aviso antigo dizia que a taxa não mudava
