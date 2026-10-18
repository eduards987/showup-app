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
from datetime import date, datetime, timedelta
from typing import Optional
from zoneinfo import ZoneInfo

HOLD_MAX_DIAS = 7            # validade máxima da reserva no cartão (Stripe: 7 dias na maioria dos cartões)
JANELA_CONFIRMACAO_H = 24    # tempo que o profissional tem, depois do fim do atendimento, para confirmar
MARGEM_H = 2                 # folga de segurança (relógio, processamento)
MARGEM_HOLD_H = 1            # folga antes do vencimento real que o Stripe informou

MENSAGENS = {
    "sem_agenda": "Este profissional ainda não abriu horários para agendamento.",
    "fora_da_janela": "Esse horário ainda não está aberto para agendamento. Escolha um dos horários disponíveis.",
    "alem_da_validade": "Esse horário está distante demais: a reserva no cartão vale por 7 dias. Escolha um horário mais próximo.",
}


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


def limite_do_fim_do_atendimento(agora: datetime) -> datetime:
    """Nenhum atendimento pago no cartão pode terminar depois disso (dá tempo de o profissional confirmar e cobrar)."""
    return agora + timedelta(days=HOLD_MAX_DIAS) - timedelta(hours=JANELA_CONFIRMACAO_H + MARGEM_H)


@dataclass(frozen=True)
class Janela:
    ultimo_dia: Optional[date]
    limite_fim_cartao: datetime
    tz: ZoneInfo

    def motivo_recusa(self, inicio: datetime, fim: datetime, reserva_no_cartao: bool = True) -> Optional[str]:
        """None se o horário pode ser agendado; senão o código do motivo (chave de MENSAGENS)."""
        if self.ultimo_dia is None:
            return "sem_agenda"
        if inicio.astimezone(self.tz).date() > self.ultimo_dia:
            return "fora_da_janela"
        if reserva_no_cartao and fim > self.limite_fim_cartao:      # Pix é pago na hora: não tem prazo de reserva
            return "alem_da_validade"
        return None


def montar_janela(weekly: list[dict], agora: datetime, tz: ZoneInfo) -> Janela:
    return Janela(ultimo_dia_de_atendimento(weekly, agora, tz), limite_do_fim_do_atendimento(agora), tz)


def janela_de_confirmacao(horario_fim: datetime, hold_expira_em: datetime) -> Optional[datetime]:
    """Até quando o profissional pode confirmar. Normalmente fim + 24 h, mas nunca depois de o Stripe soltar a reserva
    (hold_expira_em): alguns cartões vencem antes de 7 dias. None = a reserva venceria antes de o atendimento acabar."""
    limite_hold = hold_expira_em - timedelta(hours=MARGEM_HOLD_H)
    if limite_hold <= horario_fim:
        return None
    return min(horario_fim + timedelta(hours=JANELA_CONFIRMACAO_H), limite_hold)
