"""Envio de e-mail por SMTP (biblioteca padrão). Funciona com qualquer provedor que ofereça SMTP
(Brevo, SendGrid, Amazon SES, Mailgun, Gmail com senha de app...). Configuração por variáveis:

  SMTP_HOST   servidor (ex.: smtp-relay.brevo.com)
  SMTP_PORT   porta (padrão 587, com STARTTLS; use 465 com SMTP_SSL=1)
  SMTP_USER / SMTP_PASSWORD   credenciais (opcionais se o servidor não pedir)
  SMTP_FROM   remetente (ex.: ShowUp <nao-responda@seudominio.com>) — obrigatório
  SMTP_SSL    "1" para conexão SSL direta (porta 465)

Sem SMTP_HOST e SMTP_FROM o e-mail é considerado NÃO configurado e os fluxos que dependem dele
(cadastro e recuperação de senha) ficam desligados — nunca "fingem" que enviaram.
"""
import asyncio
import os
import smtplib
import ssl
from email.message import EmailMessage
from email.utils import formatdate, make_msgid

TIMEOUT_SEG = 15


def email_configurado() -> bool:
    return bool(os.environ.get("SMTP_HOST") and os.environ.get("SMTP_FROM"))


def _enviar_sincrono(para: str, assunto: str, texto: str) -> None:
    msg = EmailMessage()
    msg["From"] = os.environ["SMTP_FROM"]
    msg["To"] = para
    msg["Subject"] = assunto
    msg["Date"] = formatdate(localtime=False)
    msg["Message-ID"] = make_msgid()
    msg.set_content(texto)

    host = os.environ["SMTP_HOST"]
    usuario = os.environ.get("SMTP_USER")
    senha = os.environ.get("SMTP_PASSWORD", "")
    contexto = ssl.create_default_context()
    if os.environ.get("SMTP_SSL") == "1":
        with smtplib.SMTP_SSL(host, int(os.environ.get("SMTP_PORT", "465")), timeout=TIMEOUT_SEG, context=contexto) as s:
            if usuario:
                s.login(usuario, senha)
            s.send_message(msg)
        return
    with smtplib.SMTP(host, int(os.environ.get("SMTP_PORT", "587")), timeout=TIMEOUT_SEG) as s:
        s.starttls(context=contexto)
        if usuario:
            s.login(usuario, senha)
        s.send_message(msg)


async def enviar_email(para: str, assunto: str, texto: str) -> None:
    """Envia sem travar o servidor (o SMTP é bloqueante). Levanta a exceção do smtplib se falhar."""
    await asyncio.to_thread(_enviar_sincrono, para, assunto, texto)
