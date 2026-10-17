"""Notificações push para o PROFISSIONAL: novo agendamento, próximo atendimento e o teste de notificação.

Reúne o texto das mensagens e a lógica de "avisar uma única vez". O envio em si (Expo) fica em expo_push.py.
O registro do agendamento no banco NÃO guarda o nome do cliente nem do serviço (só os ids), então os nomes são
buscados aqui na hora de montar a mensagem.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Optional
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from expo_push import push_para_usuario

log = logging.getLogger("notificacoes")

TIMEZONE_PADRAO = "America/Sao_Paulo"
_DIAS = ("seg", "ter", "qua", "qui", "sex", "sáb", "dom")


def _utc(dt: datetime) -> datetime:
    """O Mongo devolve datas sem fuso (UTC); datas com fuso são só convertidas."""
    return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt.astimezone(timezone.utc)


def _fuso(nome: Optional[str]) -> ZoneInfo:
    try:
        return ZoneInfo(nome or TIMEZONE_PADRAO)
    except (ZoneInfoNotFoundError, ValueError):
        return ZoneInfo(TIMEZONE_PADRAO)


def formatar_quando(inicio: datetime, tz_nome: Optional[str], agora: Optional[datetime] = None) -> str:
    """"hoje às 14:30", "amanhã às 09:00" ou "qua, 22/10 às 09:00" — no fuso do PROFISSIONAL."""
    fuso = _fuso(tz_nome)
    local = _utc(inicio).astimezone(fuso)
    hoje = _utc(agora or datetime.now(timezone.utc)).astimezone(fuso).date()
    hora = local.strftime("%H:%M")
    if local.date() == hoje:
        return f"hoje às {hora}"
    if local.date() == hoje + timedelta(days=1):
        return f"amanhã às {hora}"
    return f"{_DIAS[local.weekday()]}, {local:%d/%m} às {hora}"


def faltam_texto(minutos: int) -> str:
    if minutos <= 1:
        return "Agora"
    if minutos < 60:
        return f"Em {minutos} min"
    if minutos == 60:
        return "Em 1 hora"
    horas, resto = divmod(minutos, 60)
    return f"Em {horas} h" if resto == 0 else f"Em {horas} h {resto} min"


async def dados_do_agendamento(db, ag: dict) -> dict:
    """Nome do cliente, nome do serviço e fuso do profissional, com valores de reserva se algo sumiu."""
    cli = await db.users.find_one({"user_id": ag.get("cliente_id")}, {"_id": 0, "name": 1})
    svc = await db.servicos.find_one({"servico_id": ag.get("servico_id")}, {"_id": 0, "nome": 1})
    prof = await db.users.find_one({"user_id": ag.get("profissional_id")}, {"_id": 0, "timezone": 1})
    return {
        "cliente_nome": (cli or {}).get("name") or "Um cliente",
        "servico_nome": (svc or {}).get("nome") or "atendimento",
        "timezone": (prof or {}).get("timezone") or TIMEZONE_PADRAO,
    }


async def avisar_novo_agendamento(db, agendamento_id: str, agora: Optional[datetime] = None) -> bool:
    """Avisa o profissional que entrou um agendamento. Só uma vez por agendamento: o campo
    push_novo_enviado_em é "reivindicado" de forma atômica antes de enviar (um reenvio do webhook
    do Stripe ou uma chamada repetida não duplica o aviso). Nunca levanta: falha no aviso não pode
    derrubar uma reserva que já foi paga."""
    try:
        agora = agora or datetime.now(timezone.utc)
        ag = await db.agendamentos.find_one_and_update(
            {"agendamento_id": agendamento_id, "push_novo_enviado_em": None},
            {"$set": {"push_novo_enviado_em": agora}},
        )
        if not ag:
            return False
        d = await dados_do_agendamento(db, ag)
        quando = formatar_quando(ag["horario_inicio"], d["timezone"], agora)
        resultado = await push_para_usuario(
            db, ag["profissional_id"], "Novo agendamento",
            f"{d['cliente_nome']} agendou {d['servico_nome']} para {quando}.",
            {"type": "novo_agendamento", "agendamento_id": agendamento_id},
        )
        log.info("novo agendamento %s: aviso ao profissional -> %s", agendamento_id, resultado)
        return True
    except Exception:
        log.exception("falha ao avisar novo agendamento %s", agendamento_id)
        return False


async def avisar_proximo_atendimento(db, ag: dict, agora: Optional[datetime] = None) -> bool:
    """Lembrete de que o atendimento está chegando. Quem chama já reivindicou o registro."""
    try:
        agora = agora or datetime.now(timezone.utc)
        d = await dados_do_agendamento(db, ag)
        minutos = max(0, round((_utc(ag["horario_inicio"]) - _utc(agora)).total_seconds() / 60))
        hora = _utc(ag["horario_inicio"]).astimezone(_fuso(d["timezone"])).strftime("%H:%M")
        resultado = await push_para_usuario(
            db, ag["profissional_id"], "Próximo atendimento",
            f"{faltam_texto(minutos)}, às {hora}: {d['cliente_nome']} — {d['servico_nome']}.",
            {"type": "proximo_atendimento", "agendamento_id": ag["agendamento_id"]},
        )
        log.info("próximo atendimento %s: aviso ao profissional -> %s", ag.get("agendamento_id"), resultado)
        return True
    except Exception:
        log.exception("falha ao avisar próximo atendimento %s", ag.get("agendamento_id"))
        return False


def explicar_erro_push(codigo: Optional[str], mensagem: str = "") -> str:
    """Traduz o erro que a Expo devolve (no ticket ou no recibo) no que a pessoa deve fazer."""
    if codigo == "DeviceNotRegistered":
        return ("A Expo diz que este aparelho não está mais registrado para notificações. Feche e abra o app para registrar de novo.")
    if codigo == "InvalidCredentials":
        return ("A Expo recusou o envio: falta a chave do Firebase (FCM V1) no projeto da Expo, ou ela está errada. "
                "Veja lancamento/NOTIFICACOES.md, passo 2.")
    if codigo == "MismatchSenderId":
        return ("A chave do Firebase enviada à Expo é de OUTRO projeto do Firebase que o google-services.json do app. "
                "Use o mesmo projeto nos dois (lancamento/NOTIFICACOES.md, passo 2).")
    if codigo == "MessageRateExceeded":
        return "Muitas notificações em pouco tempo. Espere um minuto e tente de novo."
    if codigo == "MessageTooBig":
        return "A mensagem de notificação ficou grande demais."
    return f"A Expo devolveu o erro {codigo or 'desconhecido'}. {mensagem[:160]}".strip()
