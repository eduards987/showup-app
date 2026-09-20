"""Payment-layer exception hierarchy.

server.py should never catch raw `stripe.error.*` — that couples HTTP
handling to a specific gateway SDK. Instead, `stripe_gateway.py` (and
`gateway.py`, the mock) translate gateway-specific failures into these, so
server.py can map each to the right HTTP status and a message that's safe to
show the end user.
"""

from __future__ import annotations


class PaymentError(Exception):
    """Base class for anything that can go wrong talking to the gateway."""


class CardDeclinedError(PaymentError):
    """The issuer declined the card. Safe, user-facing message: ask for
    another card. Never expose the raw decline_code to the client — it can
    leak information useful for card testing/fraud."""

    def __init__(self, decline_code: str | None = None):
        self.decline_code = decline_code
        super().__init__(f"card declined ({decline_code or 'unknown'})")


class GatewayUnavailableError(PaymentError):
    """Network/timeout/rate-limit talking to the gateway. Transient — the
    caller may retry with the same idempotency key."""


class InvalidPaymentRequestError(PaymentError):
    """We sent the gateway something it rejects on principle (bad amount,
    unknown payment method, etc.) — retrying with the same input won't help;
    this is a bug or stale data on our side, not a transient failure."""
