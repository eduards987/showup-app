"""A calculadora de preços (lancamento/calcular-precos.py) é a base da decisão das faixas de taxa: a conta tem de estar certa."""
import importlib.util
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import offline_env  # noqa: E402,F401

RAIZ = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("calcular_precos", RAIZ / "lancamento" / "calcular-precos.py")
cp = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cp)


def test_um_atendimento_de_100_reais_no_free_conta_todos_os_custos_do_stripe():
    # receita 10% = 1000; cartão 3,99% + 0,39 = 438; conta ativa 600; repasse 0,25% de 9000 = 22; 4 repasses x 67 = 268
    assert cp.sobra_mensal((0, 1000, 0), 1, 10_000) == 1000 - 438 - 600 - 22 - 268


def test_mensalidade_sem_atendimento_paga_cartao_e_billing_mas_nao_o_connect():
    # 2990 - (3,99% de 2990 = 119, + 39) - 0,7% de 2990 = 20
    assert cp.sobra_mensal((2990, 700, 0), 0, 10_000) == 2990 - 158 - 20


def test_cobranca_internacional_soma_cartao_estrangeiro_conversao_e_o_adicional():
    # taxa 10% + 4% = 1400; cartão 3,99% + 2% + 2% = 799 + 39; repasse 0,25% de 8600 = 21
    assert cp.sobra_mensal((0, 1000, 400), 1, 10_000, internacional=True, outra_moeda=True) == 1400 - 838 - 600 - 21 - 268


def test_a_proposta_nao_da_prejuizo_em_nenhum_perfil():
    for _, n, valor in cp.PERFIS:
        for kw in ({}, {"internacional": True, "outra_moeda": True}):
            for nome, plano in cp.PROPOSTA.items():
                assert cp.sobra_mensal(plano, n, valor, **kw) > 0, (nome, n, valor, kw)


def test_atuais_da_calculadora_sao_os_planos_do_servidor():
    import server
    nomes = {p["nome"]: p for p in server.PLANOS.values()}
    assert set(cp.ATUAIS) == set(nomes)
    for nome, (mensalidade, taxa, adicional) in cp.ATUAIS.items():
        assert (mensalidade, taxa, adicional) == (nomes[nome]["preco_centavos"], nomes[nome]["fee_bps"], server.ADICIONAL_CONVERSAO_BPS), nome


def test_os_planos_em_vigor_nao_dao_prejuizo_em_nenhum_perfil():
    for _, n, valor in cp.PERFIS:
        for kw in ({}, {"internacional": True, "outra_moeda": True}):
            for nome, plano in cp.ATUAIS.items():
                assert cp.sobra_mensal(plano, n, valor, **kw) > 0, (nome, n, valor, kw)
