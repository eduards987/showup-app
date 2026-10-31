"""Avisos ao CLIENTE sobre o próprio agendamento: confirmação na hora da reserva e lembretes antes do horário.

Por onde vai:
- push, para quem usa o app (cliente com aparelho registrado). O texto do push fica em português (regra do projeto);
- e-mail, quando o push não chegou e há um e-mail de verdade: o da conta do app ou o que o cliente informou no link.
  Sai no idioma que ele usou na página (campo `idioma` da reserva: pt, en ou es).

Cada aviso sai UMA vez por agendamento: o campo é "reivindicado" de forma atômica antes de enviar. Nunca levanta:
aviso é melhor esforço e não pode derrubar uma reserva que já foi paga.
Dinheiro em centavos inteiros (sem float), formatado só na hora de escrever.
"""
from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Optional

from emailer import email_configurado, enviar_email
from expo_push import push_para_usuario
from notificacoes import _fuso, _utc

log = logging.getLogger("avisos_cliente")

# E-mails que o ShowUp gera e ninguém lê: cliente do link sem e-mail e conta excluída.
_DOMINIOS_FALSOS = ("@showup.cliente", "@showup.excluido")
_SIMBOLOS = {"BRL": "R$", "USD": "US$", "EUR": "€", "GBP": "£", "MXN": "MX$", "ARS": "ARS", "COP": "COP", "CAD": "CA$", "AUD": "A$"}
_DIAS = {
    "pt": ("seg", "ter", "qua", "qui", "sex", "sáb", "dom"),
    "en": ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"),
    "es": ("lun", "mar", "mié", "jue", "vie", "sáb", "dom"),
}
STATUS_CONFIRMADOS = ("autorizado", "pago_integral")      # cartão reservado ou Pix pago: há atendimento marcado


def antecedencias_dos_lembretes() -> list[int]:
    """Horas antes do atendimento em que o cliente recebe lembrete (LEMBRETE_CLIENTE_HORAS, padrão "24,2").
    Vazio ou "0" desliga. Da menor para a maior: ver enviar_lembretes."""
    bruto = os.environ.get("LEMBRETE_CLIENTE_HORAS", "24,2")
    horas = set()
    for parte in bruto.split(","):
        parte = parte.strip()
        if parte.isdigit() and 0 < int(parte) <= 72:
            horas.add(int(parte))
    return sorted(horas)


def campo_do_lembrete(horas: int) -> str:
    return f"aviso_cliente_{horas}h_em"


def email_de_verdade(email: Optional[str]) -> Optional[str]:
    email = (email or "").strip().lower()
    if not email or "@" not in email or email.endswith(_DOMINIOS_FALSOS):
        return None
    return email


def formatar_valor(centavos: int, moeda: str, idioma: str = "pt") -> str:
    """12000 BRL -> "R$ 120,00" (pt/es) ou "R$ 120.00" (en). Só inteiros: nada de float com dinheiro."""
    centavos = int(centavos or 0)
    sinal = "-" if centavos < 0 else ""
    inteiro, resto = divmod(abs(centavos), 100)
    sep_mil, sep_dec = (",", ".") if idioma == "en" else (".", ",")
    milhar = f"{inteiro:,}".replace(",", sep_mil)
    return f"{sinal}{_SIMBOLOS.get(moeda, moeda)} {milhar}{sep_dec}{resto:02d}"


def quando(inicio: datetime, tz_nome: Optional[str], idioma: str = "pt", agora: Optional[datetime] = None) -> str:
    """"amanhã às 09:00" / "tomorrow at 09:00" / "mañana a las 09:00", no fuso do PROFISSIONAL (onde é o atendimento)."""
    fuso = _fuso(tz_nome)
    local = _utc(inicio).astimezone(fuso)
    hoje = _utc(agora or datetime.now(timezone.utc)).astimezone(fuso).date()
    hora = local.strftime("%H:%M")
    if idioma == "en":
        dia = "today" if local.date() == hoje else "tomorrow" if local.date() == hoje + timedelta(days=1) else f"{_DIAS['en'][local.weekday()]}, {local:%m/%d}"
        return f"{dia} at {hora}"
    if idioma == "es":
        dia = "hoy" if local.date() == hoje else "mañana" if local.date() == hoje + timedelta(days=1) else f"{_DIAS['es'][local.weekday()]}, {local:%d/%m}"
        return f"{dia} a las {hora}"
    dia = "hoje" if local.date() == hoje else "amanhã" if local.date() == hoje + timedelta(days=1) else f"{_DIAS['pt'][local.weekday()]}, {local:%d/%m}"
    return f"{dia} às {hora}"


def _cidade(tz_nome: Optional[str]) -> str:
    return (tz_nome or "America/Sao_Paulo").split("/")[-1].replace("_", " ")


# ------------------------------------------------------------------ textos
_T = {
    "pt": {
        "assunto_confirmado": "Agendamento confirmado: {servico}, {quando}",
        "assunto_lembrete": "Lembrete: {servico}, {quando}",
        "abertura_confirmado": "Olá, {nome}! Seu agendamento está confirmado:",
        "abertura_lembrete": "Olá, {nome}! Passando para lembrar do seu agendamento:",
        "linha": "{servico} com {prof}\n{quando} (horário de {cidade})",
        "cartao": "O valor de {valor} fica só reservado no seu cartão e é cobrado depois do atendimento.",
        "taxa": "Se faltar sem avisar, é cobrada só a taxa de falta: {taxa}.",
        "pix": "Pagamento por Pix confirmado: {valor}.",
        "cancelar_app": "Não vai poder ir? Cancele pelo app ShowUp antes do horário: a reserva é liberada sem custo.",
        "cancelar_link": "Não vai poder ir? Avise {prof} antes do horário.",
        "fim": "Até lá!\nEquipe ShowUp",
    },
    "en": {
        "assunto_confirmado": "Booking confirmed: {servico}, {quando}",
        "assunto_lembrete": "Reminder: {servico}, {quando}",
        "abertura_confirmado": "Hi, {nome}! Your booking is confirmed:",
        "abertura_lembrete": "Hi, {nome}! A quick reminder about your booking:",
        "linha": "{servico} with {prof}\n{quando} ({cidade} time)",
        "cartao": "The {valor} is only held on your card and is charged after the appointment.",
        "taxa": "If you don't show up without notice, only the no-show fee is charged: {taxa}.",
        "pix": "Pix payment confirmed: {valor}.",
        "cancelar_app": "Can't make it? Cancel in the ShowUp app before the time: the hold is released at no cost.",
        "cancelar_link": "Can't make it? Let {prof} know before the time.",
        "fim": "See you soon!\nThe ShowUp team",
    },
    "es": {
        "assunto_confirmado": "Reserva confirmada: {servico}, {quando}",
        "assunto_lembrete": "Recordatorio: {servico}, {quando}",
        "abertura_confirmado": "¡Hola, {nome}! Tu reserva está confirmada:",
        "abertura_lembrete": "¡Hola, {nome}! Te recordamos tu reserva:",
        "linha": "{servico} con {prof}\n{quando} (hora de {cidade})",
        "cartao": "El valor de {valor} solo queda reservado en tu tarjeta y se cobra después de la atención.",
        "taxa": "Si faltas sin avisar, solo se cobra la tarifa por falta: {taxa}.",
        "pix": "Pago por Pix confirmado: {valor}.",
        "cancelar_app": "¿No puedes ir? Cancela en la app ShowUp antes del horario: la reserva se libera sin costo.",
        "cancelar_link": "¿No puedes ir? Avisa a {prof} antes del horario.",
        "fim": "¡Hasta pronto!\nEquipo ShowUp",
    },
}


def montar_email(tipo: str, d: dict, idioma: str = "pt") -> tuple[str, str]:
    """(assunto, texto) do e-mail. tipo: "confirmado" ou "lembrete". `d` vem de dados_do_aviso."""
    t = _T.get(idioma, _T["pt"])
    q = d["quando"][idioma] if idioma in d["quando"] else d["quando"]["pt"]
    partes = [
        t[f"abertura_{tipo}"].format(nome=d["cliente_nome"]),
        t["linha"].format(servico=d["servico_nome"], prof=d["prof_nome"], quando=q, cidade=d["cidade"]),
    ]
    if d["pix"]:
        partes.append(t["pix"].format(valor=formatar_valor(d["valor_centavos"], d["moeda"], idioma)))
    else:
        dinheiro = t["cartao"].format(valor=formatar_valor(d["valor_centavos"], d["moeda"], idioma))
        if d["taxa_centavos"] > 0:
            dinheiro += " " + t["taxa"].format(taxa=formatar_valor(d["taxa_centavos"], d["moeda"], idioma))
        partes.append(dinheiro)
    partes.append(t["cancelar_app" if d["usa_app"] else "cancelar_link"].format(prof=d["prof_nome"]))
    partes.append(t["fim"])
    assunto = t[f"assunto_{tipo}"].format(servico=d["servico_nome"], quando=q)
    return assunto, "\n\n".join(partes)


def montar_push(tipo: str, d: dict) -> tuple[str, str]:
    """(título, texto) do push, em português."""
    linha = f"{d['servico_nome']} com {d['prof_nome']}, {d['quando']['pt']}."
    if d["pix"]:
        resto = "Não pode ir? Fale com o profissional antes do horário."
    else:
        resto = "Não pode ir? Cancele pelo app antes do horário."
    titulo = "Agendamento confirmado" if tipo == "confirmado" else "Lembrete de agendamento"
    return titulo, f"{linha} {resto}"


async def dados_do_aviso(db, ag: dict, agora: Optional[datetime] = None) -> dict:
    cli = await db.users.find_one({"user_id": ag.get("cliente_id")}, {"_id": 0, "name": 1, "email": 1}) or {}
    prof = await db.users.find_one({"user_id": ag.get("profissional_id")}, {"_id": 0, "name": 1, "timezone": 1}) or {}
    svc = await db.servicos.find_one({"servico_id": ag.get("servico_id")}, {"_id": 0, "nome": 1}) or {}
    tz = prof.get("timezone") or "America/Sao_Paulo"
    usa_app = ag.get("origem") != "link_publico"
    return {
        "cliente_nome": (cli.get("name") or "").split(" ")[0] or "cliente",
        "prof_nome": prof.get("name") or "o profissional",
        "servico_nome": svc.get("nome") or "atendimento",
        "quando": {i: quando(ag["horario_inicio"], tz, i, agora) for i in ("pt", "en", "es")},
        "cidade": _cidade(tz),
        "pix": ag.get("hold_status") == "pago_integral",
        "valor_centavos": int(ag.get("valor_total_centavos") or 0),
        "taxa_centavos": int(ag.get("valor_no_show_centavos") or 0),
        "moeda": ag.get("moeda") or "BRL",
        "usa_app": usa_app,
        # o e-mail informado no link vale mais que o da conta (o do link do telefone é sintético)
        "email": email_de_verdade(ag.get("email_cliente")) or email_de_verdade(cli.get("email")),
    }


async def _entregar(db, ag: dict, tipo: str, agora: Optional[datetime]) -> str:
    """Push primeiro; se não chegou, e-mail. Devolve por onde foi: "push", "email" ou o motivo de não ter ido."""
    d = await dados_do_aviso(db, ag, agora)
    titulo, corpo = montar_push(tipo, d)
    resultado = await push_para_usuario(db, ag["cliente_id"], titulo, corpo,
                                        {"type": f"cliente_{tipo}", "agendamento_id": ag["agendamento_id"]})
    if resultado == "enviado":
        return "push"
    if not d["email"]:
        return "sem_contato"
    if not email_configurado():
        log.info("aviso %s de %s sem push e sem SMTP configurado: não enviado", tipo, ag["agendamento_id"])
        return "sem_smtp"
    assunto, texto = montar_email(tipo, d, ag.get("idioma") or "pt")
    try:
        await enviar_email(d["email"], assunto, texto)
    except Exception:
        log.exception("falha ao enviar o e-mail %s de %s", tipo, ag["agendamento_id"])
        return "falha_email"
    return "email"


async def avisar_cliente_confirmado(db, agendamento_id: str, agora: Optional[datetime] = None) -> str:
    """Confirmação ao cliente, uma vez só, quando a reserva vale (cartão reservado ou Pix pago)."""
    try:
        agora = agora or datetime.now(timezone.utc)
        ag = await db.agendamentos.find_one_and_update(
            {"agendamento_id": agendamento_id, "aviso_cliente_confirmado_em": None,
             "hold_status": {"$in": list(STATUS_CONFIRMADOS)}},
            {"$set": {"aviso_cliente_confirmado_em": agora}},
        )
        if not ag:
            return "ja_avisado_ou_nao_confirmado"
        via = await _entregar(db, ag, "confirmado", agora)
        log.info("confirmação ao cliente %s -> %s", agendamento_id, via)
        return via
    except Exception:
        log.exception("falha ao confirmar ao cliente %s", agendamento_id)
        return "erro"


async def enviar_lembretes(db, agora: Optional[datetime] = None) -> dict:
    """Job: lembra o cliente LEMBRETE_CLIENTE_HORAS antes (padrão 24 h e 2 h).

    Da MENOR antecedência para a maior, e quem recebe um lembrete fica marcado também nos maiores: se o servidor
    ficou fora e voltou a 1 h do horário, sai UM lembrete (o de 2 h), não dois. Reserva feita depois do momento do
    lembrete não recebe aquele lembrete (a confirmação acabou de dizer o horário)."""
    agora = agora or datetime.now(timezone.utc)
    horas = antecedencias_dos_lembretes()
    enviados = ignorados = 0
    for i, h in enumerate(horas):
        antecedencia = timedelta(hours=h)
        maiores = horas[i:]
        cursor = db.agendamentos.find({
            "status_agendamento": "agendado",
            "hold_status": {"$in": list(STATUS_CONFIRMADOS)},
            "horario_inicio": {"$gt": agora, "$lte": agora + antecedencia},
            campo_do_lembrete(h): None,
        }, {"_id": 0})
        async for ag in cursor:
            ag = await db.agendamentos.find_one_and_update(
                {"agendamento_id": ag["agendamento_id"], campo_do_lembrete(h): None},
                {"$set": {campo_do_lembrete(x): agora for x in maiores}},
            )
            if ag is None:
                continue
            criado = _utc(ag.get("criado_em") or agora)
            if criado >= _utc(ag["horario_inicio"]) - antecedencia:
                ignorados += 1
                continue
            try:
                via = await _entregar(db, ag, "lembrete", agora)
            except Exception:
                log.exception("falha no lembrete %sh de %s", h, ag.get("agendamento_id"))
                continue
            log.info("lembrete %sh ao cliente %s -> %s", h, ag["agendamento_id"], via)
            enviados += 1
    return {"lembretes": enviados, "ignorados": ignorados}
