"""agenda.py: o cliente vê os próximos N dias de atendimento (N = dias da semana que o profissional atende), limitado pela
validade da reserva no cartão. Calendário de referência: 19/10/2026 é segunda-feira."""
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest

import agenda

SP = ZoneInfo("America/Sao_Paulo")
SEG, TER, QUA, QUI, SEX, SAB, DOM = range(7)


def semana(dias, ini="09:00", fim="18:00"):
    return [{"weekday": d, "hora_inicio": ini, "hora_fim": fim} for d in dias]


def local(dia, hora=10, minuto=0, tz=SP):
    """Um instante UTC a partir de uma data/hora de parede no fuso do profissional."""
    return datetime(2026, 10, dia, hora, minuto, tzinfo=tz).astimezone(timezone.utc)


# ------------------------------------------------------------------ os dois exemplos pedidos
def test_atende_de_segunda_a_sexta_o_cliente_ve_5_dias_de_atendimento():
    # quarta-feira 21/10 às 10:00: qua, qui, sex, seg, ter = 5 dias de atendimento
    ultimo = agenda.ultimo_dia_de_atendimento(semana([SEG, TER, QUA, QUI, SEX]), local(21), SP)
    assert ultimo == date(2026, 10, 27)
    dias_vistos = [date(2026, 10, 21) + timedelta(days=i) for i in range((ultimo - date(2026, 10, 21)).days + 1)]
    assert sum(1 for d in dias_vistos if d.weekday() <= SEX) == 5


def test_atende_de_segunda_a_domingo_o_cliente_ve_7_dias():
    ultimo = agenda.ultimo_dia_de_atendimento(semana(range(7)), local(21), SP)
    assert ultimo == date(2026, 10, 27)                                       # hoje + 6 = 7 dias
    assert (ultimo - date(2026, 10, 21)).days + 1 == 7


# ------------------------------------------------------------------ "hoje" só conta se ainda tem expediente
@pytest.mark.parametrize("dia,hora,dias,esperado", [
    (21, 10, [SEG, TER, QUA, QUI, SEX], date(2026, 10, 27)),     # qua de manhã: hoje conta
    (21, 19, [SEG, TER, QUA, QUI, SEX], date(2026, 10, 28)),     # qua à noite (expediente acabou 18:00): hoje NÃO conta
    (24, 10, [SEG, TER, QUA, QUI, SEX], date(2026, 10, 30)),     # sábado (folga): seg a sex da semana seguinte
    (23, 10, [SEG, TER, QUA, QUI, SEX], date(2026, 10, 29)),     # sexta de manhã: sex, seg, ter, qua, qui
    (21, 19, list(range(7)), date(2026, 10, 28)),                # 7 dias, depois do expediente: os 7 dias seguintes
    (24, 8, [SAB], date(2026, 10, 24)),                          # só sábado, sábado cedo: hoje
    (24, 13, [SAB], date(2026, 10, 24)),                         # só sábado, 13:00 ainda está dentro de 09-18: hoje conta
    (24, 19, [SAB], date(2026, 10, 31)),                         # só sábado, 19:00 já passou das 18:00: o próximo sábado
    (21, 10, [SAB], date(2026, 10, 24)),                         # só sábado, numa quarta: o próximo sábado
    (20, 10, [SEG, QUA], date(2026, 10, 26)),                    # seg+qua, numa terça: qua 21, seg 26
])
def test_ultimo_dia_de_atendimento(dia, hora, dias, esperado):
    assert agenda.ultimo_dia_de_atendimento(semana(dias), local(dia, hora), SP) == esperado


def test_so_sabado_depois_do_expediente_pula_para_o_proximo_sabado():
    assert agenda.ultimo_dia_de_atendimento(semana([SAB], "09:00", "12:00"), local(24, 13), SP) == date(2026, 10, 31)


def test_varios_horarios_no_mesmo_dia_contam_como_um_dia_so():
    weekly = [{"weekday": SEG, "hora_inicio": "08:00", "hora_fim": "12:00"}, {"weekday": SEG, "hora_inicio": "14:00", "hora_fim": "18:00"},
              {"weekday": TER, "hora_inicio": "08:00", "hora_fim": "12:00"}]
    assert agenda.dias_de_atendimento(weekly) == {SEG, TER}
    assert agenda.ultimo_dia_de_atendimento(weekly, local(19, 7), SP) == date(2026, 10, 20)      # N = 2: seg e ter


def test_sem_horarios_cadastrados_nao_ha_janela():
    assert agenda.ultimo_dia_de_atendimento([], local(21), SP) is None
    janela = agenda.montar_janela([], local(21), SP)
    assert janela.motivo_recusa(local(22), local(22) + timedelta(hours=1)) == "sem_agenda"


def test_o_calendario_e_o_do_profissional_nao_o_do_utc():
    """02:30 UTC de quarta é 23:30 de TERÇA em São Paulo. Quem atende à noite (20:00-23:59) ainda atende hoje (terça), então a
    terça conta: ter, qua, qui, sex, seg = último dia 26/10. Se o código usasse a data UTC (quarta), contaria qua..ter e daria 27/10."""
    noite = semana([SEG, TER, QUA, QUI, SEX], "20:00", "23:59")
    agora = datetime(2026, 10, 21, 2, 30, tzinfo=timezone.utc)
    assert agenda.ultimo_dia_de_atendimento(noite, agora, SP) == date(2026, 10, 26)
    assert agenda.ultimo_dia_de_atendimento(noite, agora, ZoneInfo("America/Manaus")) == date(2026, 10, 26)     # 22:30 de terça lá
    # e fora do horário noturno (expediente 09-18) a terça NÃO conta: qua, qui, sex, seg, ter = 27/10
    assert agenda.ultimo_dia_de_atendimento(semana([SEG, TER, QUA, QUI, SEX]), agora, SP) == date(2026, 10, 27)


@pytest.mark.parametrize("dias", [[SEG, TER, QUA, QUI, SEX], list(range(7)), [SAB], [SEG, QUA, SEX], [TER, QUI], [SEG, TER, QUA, QUI, SEX, SAB]])
def test_a_janela_sempre_tem_exatamente_n_dias_de_atendimento(dias):
    """Propriedade: de qualquer momento da semana, os dias de atendimento entre hoje e o último dia são exatamente N."""
    weekly = semana(dias)
    for dia in range(19, 33):                                   # duas semanas (19/10 a 1/11)
        for hora in (7, 12, 17, 19, 23):
            d = min(dia, 31)
            agora = datetime(2026, 10, d, hora, 0, tzinfo=SP).astimezone(timezone.utc) if dia <= 31 else datetime(2026, 11, dia - 31, hora, 0, tzinfo=SP).astimezone(timezone.utc)
            ultimo = agenda.ultimo_dia_de_atendimento(weekly, agora, SP)
            hoje = agora.astimezone(SP).date()
            assert ultimo >= hoje
            hoje_conta = any(s["weekday"] == hoje.weekday() and int(s["hora_fim"][:2]) * 60 > hora * 60 for s in weekly)
            percorridos = [hoje + timedelta(days=i) for i in range((ultimo - hoje).days + 1)]
            contados = sum(1 for p in percorridos if p.weekday() in set(dias) and (p != hoje or hoje_conta))
            assert contados == len(set(dias)), (dias, agora, ultimo)
            assert (ultimo - hoje).days <= 13


# ------------------------------------------------------------------ recusa de horário
def janela_seg_a_sex():
    return agenda.montar_janela(semana([SEG, TER, QUA, QUI, SEX]), local(21), SP)          # quarta 10:00; vai até terça 27/10


def test_horario_dentro_da_janela_e_aceito():
    j = janela_seg_a_sex()
    assert j.motivo_recusa(local(22, 9), local(22, 10)) is None
    assert j.motivo_recusa(local(26, 9), local(26, 10)) is None


def test_horario_depois_do_ultimo_dia_e_recusado_e_o_dia_inteiro_do_ultimo_dia_vale():
    j = janela_seg_a_sex()
    assert j.motivo_recusa(local(28, 9), local(28, 10)) == "fora_da_janela"                # quarta 28: depois do último dia
    assert j.motivo_recusa(local(27, 0, 1), local(27, 1)) is None                          # 27/10 00:01: ainda é o último dia
    assert j.motivo_recusa(local(27, 8), local(27, 9)) == "alem_da_validade"                # mas termina depois do prazo da reserva (27/10 08:00)
    assert j.motivo_recusa(local(29, 9), local(29, 10)) == "fora_da_janela"
    assert j.motivo_recusa(local(11 + 20, 9), local(11 + 20, 10)) == "fora_da_janela"       # 31/10, longe


def test_limite_pela_validade_da_reserva_no_cartao():
    agora = local(21, 10)
    limite = agenda.limite_do_fim_do_atendimento(agora)
    assert limite == agora + timedelta(days=5, hours=22)                                    # 7 dias - 24 h de confirmação - 2 h de folga
    j = agenda.montar_janela(semana(range(7)), agora, SP)                                   # 7 dias: a janela chegaria até 27/10 23:59
    assert j.motivo_recusa(limite - timedelta(hours=1), limite) is None                      # termina exatamente no limite: ok
    assert j.motivo_recusa(limite - timedelta(hours=1), limite + timedelta(seconds=1)) == "alem_da_validade"
    assert j.motivo_recusa(limite, limite + timedelta(hours=1)) == "alem_da_validade"


def test_pix_nao_tem_prazo_de_reserva_mas_respeita_a_janela():
    agora = local(21, 10)
    j = agenda.montar_janela(semana(range(7)), agora, SP)
    tarde = agenda.limite_do_fim_do_atendimento(agora) + timedelta(hours=3)
    assert j.motivo_recusa(tarde - timedelta(hours=1), tarde, reserva_no_cartao=True) == "alem_da_validade"
    assert j.motivo_recusa(tarde - timedelta(hours=1), tarde, reserva_no_cartao=False) is None
    assert j.motivo_recusa(local(29, 9), local(29, 10), reserva_no_cartao=False) == "fora_da_janela"


def test_mensagens_em_portugues_para_cada_motivo():
    for motivo in ("sem_agenda", "fora_da_janela", "alem_da_validade"):
        assert agenda.MENSAGENS[motivo].endswith(".")
    assert "7 dias" in agenda.MENSAGENS["alem_da_validade"]


# ------------------------------------------------------------------ prazo de confirmação respeita o vencimento real do Stripe
FIM = datetime(2026, 10, 22, 12, 0, tzinfo=timezone.utc)


def test_confirmacao_normal_e_fim_mais_24h():
    assert agenda.janela_de_confirmacao(FIM, FIM + timedelta(days=5)) == FIM + timedelta(hours=24)


def test_confirmacao_encurta_quando_a_reserva_vence_antes():
    assert agenda.janela_de_confirmacao(FIM, FIM + timedelta(hours=10)) == FIM + timedelta(hours=9)       # 1 h antes de vencer


def test_confirmacao_impossivel_quando_a_reserva_vence_antes_do_atendimento_acabar():
    assert agenda.janela_de_confirmacao(FIM, FIM + timedelta(hours=1)) is None                           # sobraria 0
    assert agenda.janela_de_confirmacao(FIM, FIM - timedelta(hours=3)) is None
    assert agenda.janela_de_confirmacao(FIM, FIM + timedelta(hours=1, seconds=1)) == FIM + timedelta(seconds=1)


# ------------------------------------------------------------------ grade de horários do expediente (única fonte da lista e da reserva)
def horas(lista):
    return [d.astimezone(SP).strftime("%d %H:%M") for d in lista]


def test_grade_de_60_minutos_no_expediente_09_a_12():
    agora = local(21, 8, 0)                                                    # quarta 08:00
    r = agenda.inicios_possiveis(semana([QUA], "09:00", "12:00"), timedelta(minutes=60), agora, SP, dias=1)
    assert horas(r) == ["21 09:00", "21 10:00", "21 11:00"]                    # 12:00 NÃO: o atendimento acabaria às 13:00


def test_grade_so_oferece_inicios_em_que_o_atendimento_inteiro_cabe_no_expediente():
    agora = local(21, 7, 0)
    weekly = semana([QUA], "09:00", "12:00")
    assert horas(agenda.inicios_possiveis(weekly, timedelta(minutes=60), agora, SP, dias=1)) == ["21 09:00", "21 10:00", "21 11:00"]
    assert horas(agenda.inicios_possiveis(weekly, timedelta(minutes=90), agora, SP, dias=1)) == ["21 09:00", "21 10:30"]      # 10:30 + 90 = 12:00 cabe
    assert horas(agenda.inicios_possiveis(weekly, timedelta(minutes=45), agora, SP, dias=1)) == ["21 09:00", "21 09:45", "21 10:30", "21 11:15"]
    assert agenda.inicios_possiveis(weekly, timedelta(minutes=200), agora, SP, dias=1) == []                                 # serviço maior que o expediente


def test_grade_com_dois_periodos_no_mesmo_dia_e_dia_de_folga():
    agora = local(21, 7, 0)
    weekly = [{"weekday": QUA, "hora_inicio": "08:00", "hora_fim": "10:00"}, {"weekday": QUA, "hora_inicio": "14:00", "hora_fim": "16:00"}]
    assert sorted(horas(agenda.inicios_possiveis(weekly, timedelta(minutes=60), agora, SP, dias=2))) == ["21 08:00", "21 09:00", "21 14:00", "21 15:00"]   # quinta (22) é folga


def test_grade_exige_15_minutos_de_antecedencia():
    weekly = semana([QUA], "09:00", "12:00")
    assert horas(agenda.inicios_possiveis(weekly, timedelta(minutes=60), local(21, 8, 40), SP, dias=1)) == ["21 09:00", "21 10:00", "21 11:00"]   # 20 min: pode
    assert horas(agenda.inicios_possiveis(weekly, timedelta(minutes=60), local(21, 8, 45), SP, dias=1)) == ["21 10:00", "21 11:00"]               # exatamente 15 min: NÃO (precisa passar de 15)
    assert horas(agenda.inicios_possiveis(weekly, timedelta(minutes=60), local(21, 8, 50), SP, dias=1)) == ["21 10:00", "21 11:00"]


def test_grade_usa_o_horario_de_parede_do_profissional_nao_o_utc():
    agora = datetime(2026, 10, 21, 10, 0, tzinfo=timezone.utc)                  # 07:00 em São Paulo
    r = agenda.inicios_possiveis(semana([QUA], "09:00", "11:00"), timedelta(minutes=60), agora, SP, dias=1)
    assert [d.astimezone(timezone.utc).strftime("%H:%M") for d in r] == ["12:00", "13:00"]                # 09:00 e 10:00 locais = 12:00 e 13:00 UTC
    manaus = agenda.inicios_possiveis(semana([QUA], "09:00", "11:00"), timedelta(minutes=60), agora, ZoneInfo("America/Manaus"), dias=1)
    assert [d.astimezone(timezone.utc).strftime("%H:%M") for d in manaus] == ["13:00", "14:00"]           # o mesmo "09:00" em Manaus é outro instante
