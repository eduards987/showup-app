"""Até quando o cliente pode agendar: a regra da janela da agenda, sem banco de dados (puro, fácil de testar).

REGRA DO PRODUTO: o cliente vê os próximos N DIAS EM QUE O PROFISSIONAL ATENDE, onde N é quantos dias da semana ele
cadastrou na disponibilidade (seg a sex = 5 dias; seg a dom = 7 dias). "Hoje" só conta se ainda restar expediente.

LIMITE TÉCNICO (dinheiro): a reserva no cartão (pré-autorização) vale 7 dias, e o profissional tem 24 h depois do fim do
atendimento para confirmar se o cliente compareceu. Depois de o prazo da reserva passar, não dá mais para cobrar. Por isso
nenhum atendimento pode TERMINAR depois de agora + 7 dias - 24 h - margem. Para quem atende 7 dias por semana isso corta um
pouco o último dia (ele aparece aos poucos, conforme o tempo passa).
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from typing import Optional
from zoneinfo import ZoneInfo

HOLD_MAX_DIAS = 7            # validade máxima da reserva no cartão (Stripe: 7 dias na maioria dos cartões)
HOLD_DIAS_MERCADOPAGO = 5    # Mercado Pago (Brasil): a reserva não capturada é cancelada em 5 dias
JANELA_CONFIRMACAO_H = 24    # tempo que o profissional tem, depois do fim do atendimento, para confirmar
MARGEM_H = 2                 # folga de segurança (relógio, processamento)
MARGEM_HOLD_H = 1            # folga antes do vencimento real que o Stripe informou

MENSAGENS = {
    "sem_agenda": "Este profissional ainda não abriu horários para agendamento.",
    "fora_da_janela": "Esse horário ainda não está aberto para agendamento. Escolha um dos horários disponíveis.",
    "alem_da_validade": "Esse horário está distante demais: a reserva no cartão vale por 7 dias. Escolha um horário mais próximo.",
    "alem_da_validade_5": "Esse horário está distante demais: a reserva no cartão vale por 5 dias. Escolha um horário mais próximo.",
    "fora_do_expediente": "Esse horário não está disponível. Escolha um dos horários mostrados.",
}
ANTECEDENCIA_MIN = 15        # o cliente não agenda para daqui a menos de 15 minutos


def _minutos(hhmm: str) -> int:
    h, m = hhmm.split(":")
    return int(h) * 60 + int(m)


def dias_de_atendimento(weekly: list[dict]) -> set[int]:
    """Dias da semana (0 = segunda) em que ele atende. Vários horários no mesmo dia contam como um dia só."""
    return {s["weekday"] for s in weekly}


def ultimo_dia_de_atendimento(weekly: list[dict], agora: datetime, tz: ZoneInfo) -> Optional[date]:
    """O último dia (no calendário LOCAL do profissional) que o cliente pode escolher; None se ele não tem horários."""
    dias = dias_de_atendimento(weekly)
    if not dias:
        return None
    local = agora.astimezone(tz)
    hoje_ainda_atende = any(
        s["weekday"] == local.weekday() and _minutos(s["hora_fim"]) > local.hour * 60 + local.minute for s in weekly
    )
    contados = 0
    dia = local.date()
    for i in range(30):                      # N <= 7: no máximo ~14 dias à frente; 30 é só uma trava contra laço infinito
        if dia.weekday() in dias and (i > 0 or hoje_ainda_atende):
            contados += 1
            if contados == len(dias):
                return dia
        dia += timedelta(days=1)
    return None                              # inalcançável com dados válidos


def inicios_possiveis(weekly: list[dict], duracao: timedelta, agora: datetime, tz: ZoneInfo, dias: int = 14) -> list[datetime]:
    """Todos os inícios de atendimento que o EXPEDIENTE cadastrado oferece nos próximos `dias` (horário local do profissional).

    A grade começa em cada `hora_inicio` e avança de `duracao` em `duracao` (serviço de 60 min = 11:00, 12:00, 13:00...), e o
    atendimento inteiro tem que caber antes do `hora_fim`. É a ÚNICA fonte da lista de horários (/slots) e da conferência na
    hora de reservar: o que a lista nunca oferece, o servidor também recusa. Não considera reservas já feitas nem a janela de
    dias (isso é de quem chama)."""
    local = agora.astimezone(tz)
    minimo = agora + timedelta(minutes=ANTECEDENCIA_MIN)
    saida: list[datetime] = []
    for i in range(dias):
        dia = local.date() + timedelta(days=i)
        for s in weekly:
            if s["weekday"] != dia.weekday():
                continue
            hi, mi = s["hora_inicio"].split(":")
            hf, mf = s["hora_fim"].split(":")
            cursor = datetime.combine(dia, time(int(hi), int(mi)), tzinfo=tz)
            fim_expediente = datetime.combine(dia, time(int(hf), int(mf)), tzinfo=tz)
            while cursor + duracao <= fim_expediente:
                if cursor > minimo:
                    saida.append(cursor)
                cursor += duracao
    return saida


def limite_do_fim_do_atendimento(agora: datetime, hold_dias: int = HOLD_MAX_DIAS) -> datetime:
    """Nenhum atendimento pago no cartão pode terminar depois disso (dá tempo de o profissional confirmar e cobrar).
    `hold_dias`: validade da reserva de quem recebe o dinheiro (Stripe 7, Mercado Pago 5)."""
    return agora + timedelta(days=hold_dias) - timedelta(hours=JANELA_CONFIRMACAO_H + MARGEM_H)


@dataclass(frozen=True)
class Janela:
    ultimo_dia: Optional[date]
    limite_fim_cartao: datetime
    tz: ZoneInfo
    hold_dias: int = HOLD_MAX_DIAS

    def motivo_recusa(self, inicio: datetime, fim: datetime, reserva_no_cartao: bool = True) -> Optional[str]:
        """None se o horário pode ser agendado; senão o código do motivo (chave de MENSAGENS)."""
        if self.ultimo_dia is None:
            return "sem_agenda"
        if inicio.astimezone(self.tz).date() > self.ultimo_dia:
            return "fora_da_janela"
        if reserva_no_cartao and fim > self.limite_fim_cartao:      # Pix é pago na hora: não tem prazo de reserva
            return "alem_da_validade" if self.hold_dias == HOLD_MAX_DIAS else f"alem_da_validade_{self.hold_dias}"
        return None


def montar_janela(weekly: list[dict], agora: datetime, tz: ZoneInfo, hold_dias: int = HOLD_MAX_DIAS) -> Janela:
    return Janela(ultimo_dia_de_atendimento(weekly, agora, tz), limite_do_fim_do_atendimento(agora, hold_dias), tz, hold_dias)


def janela_de_confirmacao(horario_fim: datetime, hold_expira_em: datetime) -> Optional[datetime]:
    """Até quando o profissional pode confirmar. Normalmente fim + 24 h, mas nunca depois de o Stripe soltar a reserva
    (hold_expira_em): alguns cartões vencem antes de 7 dias. None = a reserva venceria antes de o atendimento acabar."""
    limite_hold = hold_expira_em - timedelta(hours=MARGEM_HOLD_H)
    if limite_hold <= horario_fim:
        return None
    return min(horario_fim + timedelta(hours=JANELA_CONFIRMACAO_H), limite_hold)
