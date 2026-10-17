"""Expo Push API client.

Sends push notifications to devices registered via /api/me/push-token.
No SDK dependency needed — Expo's push service is a plain HTTPS JSON API.
Docs: https://docs.expo.dev/push-notifications/sending-notifications/
"""

import logging
from typing import Any, Optional

import httpx

log = logging.getLogger("expo_push")

_EXPO_PUSH_URL = "https://exp.host/--/api/v2/push/send"
_EXPO_RECIBOS_URL = "https://exp.host/--/api/v2/push/getReceipts"


async def send_push(
    expo_push_token: str,
    title: str,
    body: str,
    data: Optional[dict[str, Any]] = None,
) -> dict:
    """Sends a single push message. Returns Expo's receipt dict.

    Does not raise on delivery failure (invalid/expired token, etc.) — the
    caller decides what to do with the receipt (e.g. unregister a dead
    token). Raises only on network/transport failure talking to Expo itself,
    which the scheduler job treats as "try again next tick".
    """
    payload = {
        "to": expo_push_token,
        "title": title,
        "body": body,
        "data": data or {},
        "sound": "default",
        "priority": "high",
        # channelId "default" must exist on the Android side (created by the
        # expo-notifications plugin at build time) or the OS silently drops
        # high-priority delivery guarantees.
        "channelId": "default",
    }
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.post(
            _EXPO_PUSH_URL,
            json=payload,
            headers={"Content-Type": "application/json", "Accept": "application/json"},
        )
        resp.raise_for_status()
        result = resp.json()

    ticket = (result.get("data") or {})
    status = ticket.get("status")
    if status == "error":
        log.warning("Expo push recusado para %s...: %s", expo_push_token[:20], ticket.get("message"))
    return ticket


def is_device_not_registered(ticket: dict) -> bool:
    """True when Expo says this token will never work again — safe to
    delete it so we stop wasting sends on it."""
    details = ticket.get("details") or {}
    return ticket.get("status") == "error" and details.get("error") == "DeviceNotRegistered"


async def push_para_usuario(db, user_id: str, title: str, body: str, data: dict) -> str:
    """Envia push pro dispositivo registrado do usuário. Token morto (app desinstalado, permissão revogada) é
    apagado pra não continuar gastando chamadas à Expo. Nunca levanta: push é "melhor esforço".

    Devolve o que aconteceu — "enviado", "sem_token", "erro:<codigo da Expo>" ou "falha_rede" — e deixa uma linha no log
    do servidor. Antes, "o usuário não tem aparelho registrado" não deixava pista nenhuma: era impossível saber por que um
    aviso não chegou."""
    token_doc = await db.device_tokens.find_one({"user_id": user_id}, {"_id": 0})
    if not token_doc:
        log.info("push '%s' NÃO enviado: %s não tem aparelho registrado (precisa abrir o app e permitir notificações)", title, user_id)
        return "sem_token"
    try:
        ticket = await send_push(token_doc["expo_push_token"], title, body, data)
    except Exception:
        log.exception("push '%s': falha de rede falando com a Expo (usuário %s)", title, user_id)
        return "falha_rede"
    if is_device_not_registered(ticket):
        await db.device_tokens.delete_one({"user_id": user_id})
        log.warning("push '%s': a Expo diz que o aparelho de %s não está mais registrado; token apagado", title, user_id)
        return "erro:DeviceNotRegistered"
    if ticket.get("status") == "error":
        codigo = (ticket.get("details") or {}).get("error") or "desconhecido"
        log.warning("push '%s' recusado pela Expo para %s: %s", title, user_id, codigo)
        return f"erro:{codigo}"
    log.info("push '%s' enviado a %s (ticket %s)", title, user_id, ticket.get("id"))
    return "enviado"


async def buscar_recibo(ticket_id: str) -> Optional[dict]:
    """Recibo de um envio: o que o Firebase/APNs respondeu à Expo. O "ticket" só diz que a Expo recebeu o pedido;
    erros de credencial (InvalidCredentials, MismatchSenderId) e aparelho inválido aparecem AQUI. Devolve None
    enquanto a Expo ainda não tem o recibo."""
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.post(
            _EXPO_RECIBOS_URL, json={"ids": [ticket_id]},
            headers={"Content-Type": "application/json", "Accept": "application/json"},
        )
        resp.raise_for_status()
        return (resp.json().get("data") or {}).get(ticket_id)
