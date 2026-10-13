"""Payment gateway abstraction.

MockGateway simulates Stripe's manual-capture PaymentIntent state machine
directly in MongoDB. Its interface matches what a real Stripe gateway would
expose so it can be swapped in later without changing server.py.

MOCKED: no real card is charged. All state transitions are deterministic
and persisted so the app behaves end-to-end.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Optional


def _now() -> datetime:
    return datetime.now(timezone.utc)


class MockGateway:
    def __init__(self, db):
        self.db = db
        self.pi = db.gateway_payment_intents  # in-DB PI store
        self._seen_idempotency_keys: dict[str, dict] = {}
        self._setup_intents: dict[str, dict] = {}

    # ------------------------------------------------------------------
    # Customer + card (simulado — nenhum Stripe real envolvido)
    # ------------------------------------------------------------------
    async def ensure_customer(self, user_id: str, email: str, name: str) -> str:
        """Mesma correção de idempotência do StripeGateway real — ver
        comentário lá. Persiste em db.users.stripe_customer_id."""
        user = await self.db.users.find_one({"user_id": user_id}, {"_id": 0, "stripe_customer_id": 1})
        if user and user.get("stripe_customer_id"):
            return user["stripe_customer_id"]
        cid = f"cus_mock_{uuid.uuid4().hex[:10]}"
        await self.db.users.update_one({"user_id": user_id}, {"$set": {"stripe_customer_id": cid}})
        return cid

    async def create_setup_intent(self, customer_id: str) -> dict:
        si_id = f"seti_mock_{uuid.uuid4().hex[:14]}"
        self._setup_intents[si_id] = {"customer_id": customer_id, "status": "succeeded"}
        return {"setup_intent_id": si_id, "client_secret": f"{si_id}_secret_mock"}

    async def create_ephemeral_key(self, customer_id: str) -> str:
        return f"ek_mock_{uuid.uuid4().hex[:14]}"

    async def confirm_setup_intent_card(self, setup_intent_id: str, customer_id: str) -> dict:
        # Modo mock: aceita qualquer setup_intent_id que a gente mesmo gerou
        # em create_setup_intent, sem exigir um app real rodando o Payment
        # Sheet (não há SDK nativo em ambiente de teste headless).
        si = self._setup_intents.get(setup_intent_id)
        if not si or si["customer_id"] != customer_id:
            raise ValueError("setup_intent_id inválido ou de outro customer")
        return {
            "payment_method_id": f"pm_mock_{uuid.uuid4().hex[:10]}",
            "brand": "visa", "last4": "4242", "exp_month": 12, "exp_year": 2030,
        }

    async def authorize(
        self,
        customer_id: str,
        payment_method_id: str,
        amount_centavos: int,
        idempotency_key: str,
        moeda: str = "BRL",
        fee_bps: int = 1000,
        metadata: Optional[dict[str, Any]] = None,
        destination_account_id: Optional[str] = None,
    ) -> dict:
        # Simula o comportamento de idempotência do Stripe: mesma chave =
        # mesmo resultado, sem criar um segundo PaymentIntent.
        if idempotency_key in self._seen_idempotency_keys:
            return self._seen_idempotency_keys[idempotency_key]
        pi_id = f"pi_mock_{uuid.uuid4().hex[:14]}"
        # Simulates Stripe's typical 7-day authorization window.
        hold_expira_em = _now() + timedelta(days=7)
        doc = {
            "payment_intent_id": pi_id,
            "customer_id": customer_id,
            "payment_method_id": payment_method_id,
            "amount": amount_centavos,
            "amount_capturable": amount_centavos,
            "amount_received": 0,
            "currency": moeda.lower(),
            "status": "requires_capture",
            "capture_method": "manual",
            "metadata": metadata or {},
            "hold_expira_em": hold_expira_em,
            "criado_em": _now(),
        }
        await self.pi.insert_one(dict(doc))
        result = {"payment_intent_id": pi_id, "status": "requires_capture",
                   "hold_expira_em": hold_expira_em}
        self._seen_idempotency_keys[idempotency_key] = result
        return result

    async def capture(
        self,
        payment_intent_id: str,
        amount_to_capture: Optional[int],
        idempotency_key: str,
        fee_bps: Optional[int] = None,  # o simulado não calcula taxa; só mantém a assinatura igual à do real
    ) -> dict:
        if idempotency_key in self._seen_idempotency_keys:
            return self._seen_idempotency_keys[idempotency_key]
        pi = await self.pi.find_one({"payment_intent_id": payment_intent_id}, {"_id": 0})
        if not pi:
            raise ValueError("PI not found")
        if pi["status"] != "requires_capture":
            raise ValueError(f"PI status is {pi['status']}")
        take = pi["amount"] if amount_to_capture is None else amount_to_capture
        if take <= 0 or take > pi["amount_capturable"]:
            raise ValueError("invalid capture amount")
        await self.pi.update_one(
            {"payment_intent_id": payment_intent_id},
            {"$set": {
                "status": "succeeded",
                "amount_received": take,
                "amount_capturable": 0,
                "capturado_em": _now(),
            }},
        )
        result = {"payment_intent_id": payment_intent_id, "status": "succeeded",
                   "amount_received": take, "amount_capturable": 0}
        self._seen_idempotency_keys[idempotency_key] = result
        return result

    async def void(self, payment_intent_id: str, idempotency_key: str) -> dict:
        await self.pi.update_one(
            {"payment_intent_id": payment_intent_id},
            {"$set": {"status": "canceled", "amount_capturable": 0, "canceled_em": _now()}},
        )
        return {"payment_intent_id": payment_intent_id, "status": "canceled"}

    async def expire(self, payment_intent_id: str, idempotency_key: str) -> dict:
        await self.pi.update_one(
            {"payment_intent_id": payment_intent_id},
            {"$set": {"status": "canceled", "amount_capturable": 0,
                       "cancellation_reason": "expired", "canceled_em": _now()}},
        )
        return {"payment_intent_id": payment_intent_id, "status": "canceled"}
