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
