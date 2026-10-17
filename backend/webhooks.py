"""Stripe webhook handler.

Why this matters for ShowUp specifically: our hold/capture state machine
in `agendamentos` is only as correct as the last synchronous call we made to
Stripe. Anything that happens asynchronously on Stripe's side — a card that
gets disputed after capture, a Connect account that gets restricted, a
payment_intent that fails after we thought it succeeded — never reaches our
database without this listener. This endpoint is the single source of truth
reconciliation point; nothing here should be re-derivable purely from our own
synchronous code paths.
"""

from __future__ import annotations

import logging
import os

import stripe
from fastapi import APIRouter, Request, Response

from expo_push import push_para_usuario
from notificacoes import avisar_novo_agendamento

log = logging.getLogger("webhooks")
router = APIRouter(prefix="/api/webhooks")

_WEBHOOK_SECRET = os.environ.get("STRIPE_WEBHOOK_SECRET", "")
# O endpoint de Connect ("escutar eventos em contas conectadas", que traz o
# account.updated dos profissionais) é OUTRO endpoint no Stripe e tem o SEU
# próprio segredo. Opcional: sem ele, só o endpoint da plataforma é aceito.
_CONNECT_WEBHOOK_SECRET = os.environ.get("STRIPE_CONNECT_WEBHOOK_SECRET", "")


def _get_db():
    # Imported lazily to avoid a circular import with server.py at module load.
    from server import db
    return db


def _como_dict(obj):
    """O objeto do evento NÃO é um dict nas versões novas do stripe-python (o
    `.get()` dele levanta AttributeError) e todos os tratadores abaixo usam
    `.get()`. Converte uma vez, na entrada. Em versões antigas (que ainda são
    dict) devolve o próprio objeto."""
    para_dict = getattr(obj, "to_dict", None)
    return para_dict() if callable(para_dict) else obj


@router.post("/stripe")
async def stripe_webhook(request: Request):
    payload = await request.body()
    sig_header = request.headers.get("stripe-signature", "")

    segredos = [s for s in (_WEBHOOK_SECRET, _CONNECT_WEBHOOK_SECRET) if s]
    if not segredos:
        log.error("STRIPE_WEBHOOK_SECRET ausente — recusando webhook por segurança")
        return Response(status_code=500)

    # Aceita se a assinatura bater com QUALQUER um dos segredos configurados
    # (plataforma ou Connect); se não bater com nenhum, é tentativa de forjar.
    event = None
    for segredo in segredos:
        try:
            event = stripe.Webhook.construct_event(payload, sig_header, segredo)
            break
        except ValueError:
            log.warning("Webhook payload inválido")
            return Response(status_code=400)
        except stripe.error.SignatureVerificationError:
            continue
    if event is None:
        # Someone tried to call this endpoint without a valid Stripe signature.
        log.warning("Assinatura de webhook inválida — possível tentativa de forjar evento")
        return Response(status_code=400)

    db = _get_db()
    obj = _como_dict(event["data"]["object"])
    event_type = event["type"]

    # Idempotency: Stripe may deliver the same event more than once. We keep a
    # log of processed event IDs so a redelivery is a safe no-op.
    already = await db.webhook_events.find_one({"event_id": event["id"]}, {"_id": 0})
    if already:
        return Response(status_code=200)
    await db.webhook_events.insert_one({"event_id": event["id"], "type": event_type})

    if event_type == "payment_intent.payment_failed":
        await _handle_payment_failed(db, obj)
    elif event_type == "charge.dispute.created":
        await _handle_dispute(db, obj)
    elif event_type == "account.updated":
        await _handle_account_updated(db, obj)
    elif event_type == "payment_intent.canceled":
        await _handle_canceled(db, obj)
    elif event_type == "payment_intent.succeeded":
        await _handle_pix_succeeded(db, obj)
    elif event_type in ("customer.subscription.deleted", "customer.subscription.updated"):
        await _handle_subscription_change(db, obj)
    elif event_type == "customer.subscription.trial_will_end":
        await _handle_trial_will_end(db, obj)
    else:
        log.info("Evento não tratado (ignorado de propósito): %s", event_type)

    return Response(status_code=200)


async def _handle_payment_failed(db, payment_intent: dict) -> None:
    """Card was authorized but Stripe later couldn't confirm it (rare, but
    happens with delayed-notification payment methods). We must not leave the
    agendamento thinking the hold is still valid."""
    pi_id = payment_intent["id"]
    ag = await db.agendamentos.find_one({"payment_intent_id": pi_id}, {"_id": 0})
    if not ag:
        return
    await db.agendamentos.update_one(
        {"agendamento_id": ag["agendamento_id"], "hold_status": "autorizado"},
        {"$set": {"hold_status": "falhou", "status_agendamento": "pagamento_falhou"}},
    )
    log.warning("payment_intent.payment_failed sincronizado para agendamento %s", ag["agendamento_id"])


async def _handle_dispute(db, charge: dict) -> None:
    """A client disputed a captured charge (chargeback). We flag the
    agendamento for manual review — never auto-resolve money disputes."""
    pi_id = charge.get("payment_intent")
    if not pi_id:
        return
    ag = await db.agendamentos.find_one({"payment_intent_id": pi_id}, {"_id": 0})
    if not ag:
        return
    await db.agendamentos.update_one(
        {"agendamento_id": ag["agendamento_id"]},
        {"$set": {"em_disputa": True}},
    )
    log.warning("Disputa registrada para agendamento %s — revisão manual necessária", ag["agendamento_id"])


async def _handle_account_updated(db, account: dict) -> None:
    """Keeps our cached connect_ready flag honest — a professional's Connect
    account can be restricted by Stripe (compliance, risk) independently of
    anything our app does."""
    connect_ready = bool(account.get("charges_enabled") and account.get("payouts_enabled"))
    await db.users.update_one(
        {"stripe_account_id": account["id"]},
        {"$set": {"connect_ready": connect_ready}},
    )


async def _handle_canceled(db, payment_intent: dict) -> None:
    """Covers holds that Stripe itself expires/cancels outside of our own
    /internal/jobs/expirar-janela run (e.g. issuer-side expiry)."""
    pi_id = payment_intent["id"]
    await db.agendamentos.update_one(
        {"payment_intent_id": pi_id, "hold_status": "autorizado"},
        {"$set": {"hold_status": "expirado", "status_confirmacao": "sem_resposta"}},
    )


async def _handle_pix_succeeded(db, payment_intent: dict) -> None:
    """Único jeito de saber que um Pix do link público foi pago — acontece
    no app do banco do cliente, fora do nosso controle. Só mexe em
    agendamentos que ainda estão 'aguardando_pix' (idempotente: se o
    webhook chegar duplicado, o segundo update_one não encontra nada pra
    mudar e não faz nada de mal)."""
    pi_id = payment_intent["id"]
    result = await db.agendamentos.update_one(
        {"payment_intent_id": pi_id, "hold_status": "aguardando_pix"},
        {"$set": {"hold_status": "pago_integral", "valor_capturado_centavos": payment_intent.get("amount", 0)}},
    )
    if result.modified_count:
        log.info("Pix confirmado via webhook para payment_intent %s", pi_id)
        # Só agora o horário está garantido: avisa o profissional (uma vez; falha aqui nunca derruba o webhook).
        ag = await db.agendamentos.find_one({"payment_intent_id": pi_id}, {"_id": 0, "agendamento_id": 1})
        if ag:
            await avisar_novo_agendamento(db, ag["agendamento_id"])



async def _handle_subscription_change(db, subscription: dict) -> None:
    """Cobre cancelamento feito DIRETO no dashboard do Stripe (não pelo
    endpoint /me/plano/cancelar) e falha de cobrança recorrente (cartão do
    profissional expirou, etc.) — em ambos os casos, sem assinatura ativa
    não faz sentido continuar com a taxa reduzida."""
    status = subscription.get("status")
    if status in ("canceled", "unpaid", "incomplete_expired"):
        await db.users.update_one(
            {"stripe_subscription_id": subscription["id"]},
            {
                "$set": {"plano": "free"},
                "$unset": {"stripe_subscription_id": "", "plano_cobranca_pendente": "", "plano_trial_termina_em": ""},
            },
        )
        log.info("Assinatura %s -> %s, revertido pro plano free", subscription["id"], status)
    elif status == "past_due":
        # A cobrança do plano falhou (fim do teste grátis ou renovação). O Stripe
        # tenta de novo por um tempo antes de desistir; até lá o profissional
        # mantém o plano, mas precisa saber. `find_one_and_update` devolve o
        # documento ANTES da mudança só se ainda não estava marcado, então o
        # aviso sai uma vez só, mesmo com o Stripe reenviando o evento.
        user = await db.users.find_one_and_update(
            {"stripe_subscription_id": subscription["id"], "plano_cobranca_pendente": {"$ne": True}},
            {"$set": {"plano_cobranca_pendente": True}},
        )
        if user:
            await push_para_usuario(
                db, user["user_id"], "Não conseguimos cobrar o seu plano",
                "O Stripe não conseguiu cobrar o cartão. Abra o app e confira seu plano para não perder a taxa reduzida.",
                {"tipo": "cobranca_plano_falhou"},
            )
    elif status in ("active", "trialing"):
        await db.users.update_one(
            {"stripe_subscription_id": subscription["id"]},
            {"$unset": {"plano_cobranca_pendente": ""}},
        )


async def _handle_trial_will_end(db, subscription: dict) -> None:
    """O Stripe manda este evento ~3 dias antes do fim do teste grátis. Avisa o
    profissional ANTES de a cobrança acontecer — cobrar sem aviso é o que mais
    gera estorno e reclamação em teste grátis."""
    user = await db.users.find_one({"stripe_subscription_id": subscription["id"]}, {"_id": 0, "user_id": 1})
    if not user:
        return
    await push_para_usuario(
        db, user["user_id"], "Seu teste grátis está acabando",
        "Em 3 dias o plano passa a ser cobrado no cartão salvo. Se não quiser continuar, cancele no app antes disso.",
        {"tipo": "trial_will_end"},
    )
