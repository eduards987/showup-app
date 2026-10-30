"""Telas do app (revisão de 30/10/2026): sem internet nunca é "vazio", cobrar/cancelar/remover pedem confirmação e
explicam o erro, e Configurações não perde o que a pessoa está editando. Lê o código das telas (o comportamento puro
de estado-consulta.ts roda no Node, em node/i18n_app.test.mjs)."""
import re
from pathlib import Path

import pytest

APP = Path(__file__).resolve().parents[2] / "frontend" / "app"


def tela(nome: str) -> str:
    return (APP / nome).read_text(encoding="utf-8")


@pytest.mark.parametrize("nome", [
    "(app)/agendamentos.tsx", "(app)/home.tsx", "(app)/servicos.tsx", "(app)/search.tsx",
    "(app)/profissional/[id].tsx", "(app)/agendamento/[id].tsx", "(app)/book/[servicoId].tsx",
])
def test_tela_que_busca_dados_mostra_erro_com_tentar_de_novo(nome):
    s = tela(nome)
    assert "<ErroAoCarregar" in s and ".refetch()" in s, nome
    assert not re.search(r"if \(!\w+\.data\) return null", s), nome      # tela em branco, sem saída
    # quem espera os dados para desenhar a tela mostra o erro DAQUELA busca
    for m in re.finditer(r"if \(!(\w+)\.data\) \{", s):
        trecho = s[m.end():m.end() + 400]
        assert f"{m.group(1)}.isError ? <ErroAoCarregar onTentar={{() => {m.group(1)}.refetch()}}" in trecho, (nome, m.group(1))


def test_lista_de_agendamentos_separa_proximos_e_anteriores():
    s = tela("(app)/agendamentos.tsx")
    assert "separarAgendamentos(q.data ?? [], agora)" in s and "<SectionList" in s
    assert 'estado === "erro"' in s and 'estado === "vazio"' in s


def test_inicio_nao_le_o_relogio_no_meio_da_tela():
    s = tela("(app)/home.tsx")
    assert "Date.now()" not in s and "useAgora()" in s


def mutacao(s: str, nome: str) -> str:
    """O bloco `const nome = useMutation({ ... });` inteiro, e só ele."""
    return s.split(f"const {nome} = useMutation({{", 1)[1].split("\n  });", 1)[0]


def _corpo(s: str, inicio: str, fim: str) -> str:
    return s.split(inicio, 1)[1].split(fim, 1)[0]


def test_cobrar_o_comparecimento_pede_confirmacao_e_o_erro_aparece():
    s = tela("(app)/agendamento/[id].tsx")
    assert 'onPress={confirmarComparecimento}' in s                  # o botão não cobra direto
    assert s.count('confirmM.mutate("compareceu")') == 1
    alerta = _corpo(s, "const confirmarComparecimento = () =>", "const confirmarCancelamento")
    assert "Alert.alert(" in alerta and 'confirmM.mutate("compareceu")' in alerta
    assert 'onPress={confirmarCancelamento}' in s and s.count("cancelM.mutate()") == 1
    assert "cancelM.mutate()" in _corpo(s, "const confirmarCancelamento = () =>", "return (")
    # cobrar, falta e cancelar: falhou -> explica e recarrega (antes o botão só parava de girar)
    assert 'avisarErro(t("Não foi possível confirmar"))(err)' in mutacao(s, "confirmM").split("onError:", 1)[1]
    assert 'onError: avisarErro(t("Não foi possível cancelar"))' in mutacao(s, "cancelM")
    assert "Alert.alert(titulo, err instanceof ApiError ? err.message" in s


def test_remover_servico_pede_confirmacao_e_explica_o_erro():
    s = tela("(app)/servicos.tsx")
    assert "onPress={() => confirmarRemocao(item)}" in s and s.count("delM.mutate(") == 1
    assert "delM.mutate(servico.servico_id)" in _corpo(s, "const confirmarRemocao", "return (")
    assert "onError:" in mutacao(s, "delM")


def test_configuracoes_nao_apaga_o_que_esta_sendo_editado_e_avisa_se_nao_salvou():
    s = tela("(app)/configuracoes.tsx")
    # os horários do servidor entram uma vez só
    assert "if (!slotsCarregados && dispQ.data?.slots)" in s
    assert not re.search(r"useEffect\(\(\) => \{\s*if \(dispQ\.data", s)
    # salvar antes de carregar gravaria uma agenda vazia
    assert "disabled={saveDispM.isPending || !slotsCarregados}" in s
    for m in ("saveCatsM", "saveTzM", "saveMoedaM", "saveDispM"):
        assert "onError: avisarErroAoSalvar," in mutacao(s, m), m


def test_reserva_mostra_erro_nos_horarios_e_atualiza_quando_alguem_pega_o_horario_antes():
    s = tela("(app)/book/[servicoId].tsx")
    assert 'estadoDaConsulta(slotsQ) === "erro"' in s and "<ErroAoCarregar onTentar={() => slotsQ.refetch()}" in s
    erro = mutacao(s, "bookM").split("onError:", 1)[1]
    assert "slotsQ.refetch()" in erro and "setSelectedIso(null)" in erro


def test_escolher_o_papel_mostra_o_erro_e_sempre_chega_ao_inicio_com_o_tutorial():
    s = tela("role-select.tsx")
    assert 'if (auth.user.role && !saving) return <Redirect href="/(app)/home" />;' in s
    envio = s.split("const handleContinue = async () => {", 1)[1].split("\n  };", 1)[0]
    assert "catch (err)" in envio and "Alert.alert(" in envio.split("catch (err)", 1)[1]
