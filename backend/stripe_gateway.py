"""Stripe gateway — real PaymentIntent with capture_method='manual'.

Same interface as MockGateway so server.py stays untouched. When Connect is
enabled on the platform account and the professional has a `stripe_account_id`,
we pass `transfer_data.destination` and `application_fee_amount` for automatic
split. Otherwise we fall back to keeping funds on the platform and let the
internal ledger record what's owed.
"""

from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from typing import Any, Optional

import stripe

from payment_errors import CardDeclinedError, GatewayUnavailableError, InvalidPaymentRequestError

stripe.api_key = os.environ.get("STRIPE_API_KEY", "")
log = logging.getLogger("stripe_gateway")


def _translate_stripe_error(e: "stripe.error.StripeError") -> Exception:
    """Maps the Stripe SDK's exception tree to our own, so nothing above this
    module needs to import `stripe` just to handle a failure."""
    if isinstance(e, stripe.error.CardError):
        return CardDeclinedError(decline_code=e.code)
    if isinstance(e, (stripe.error.RateLimitError, stripe.error.APIConnectionError, stripe.error.APIError)):
        # These are transient by nature — same idempotency key makes a retry safe.
        return GatewayUnavailableError(str(e))
    if isinstance(e, stripe.error.InvalidRequestError):
        return InvalidPaymentRequestError(str(e))
    # Auth/permission errors, signature errors, etc. — not retryable, not the
    # customer's fault, so treat as an unavailable gateway rather than a card issue.
    return GatewayUnavailableError(str(e))


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _to_datetime(ts: Optional[int]) -> datetime:
    if not ts:
        return _now()
    return datetime.fromtimestamp(ts, tz=timezone.utc)


class StripeGateway:
    """Real Stripe implementation of the gateway interface."""

    def __init__(self, db):
        self.db = db

    # ------------------------------------------------------------------
    # Customer + card (coleta real via Payment Sheet — SetupIntent)
    # ------------------------------------------------------------------
    async def ensure_customer(self, user_id: str, email: str, name: str) -> str:
        """Idempotente por usuário — persiste em db.users.stripe_customer_id
        assim que criado, não só depois do cartão confirmado. Sem isso,
        cada chamada (setup-intent E confirm, no mesmo fluxo de coleta de
        cartão) criava um Customer novo e DIFERENTE, porque a única fonte
        de verdade antiga (customer_cards) só existe depois que o cartão já
        foi salvo — quebrando a própria confirmação do SetupIntent."""
        user = await self.db.users.find_one({"user_id": user_id}, {"_id": 0, "stripe_customer_id": 1})
        if user and user.get("stripe_customer_id"):
            return user["stripe_customer_id"]
        c = stripe.Customer.create(email=email, name=name, metadata={"user_id": user_id})
        await self.db.users.update_one({"user_id": user_id}, {"$set": {"stripe_customer_id": c.id}})
        return c.id

    async def create_setup_intent(self, customer_id: str) -> dict:
        """SetupIntent em vez de attach direto: o cartão nunca passa pelo
        nosso backend (PCI compliance), só o client_secret viaja até o app,
        que usa o Payment Sheet do Stripe pra coletar o cartão diretamente."""
        try:
            si = stripe.SetupIntent.create(
                customer=customer_id,
                payment_method_types=["card"],
                usage="off_session",  # é exatamente o que authorize() faz depois
            )
        except stripe.error.StripeError as e:
            log.warning("create_setup_intent falhou (customer=%s): %s", customer_id, e)
            raise _translate_stripe_error(e) from e
        return {"setup_intent_id": si.id, "client_secret": si.client_secret}

    async def create_ephemeral_key(self, customer_id: str) -> str:
        """Exigido pelo Payment Sheet pra listar/gerenciar os métodos de
        pagamento já salvos do customer com segurança (sem expor a secret
        key do backend pro app)."""
        try:
            key = stripe.EphemeralKey.create(customer=customer_id, stripe_version=stripe.api_version)
        except stripe.error.StripeError as e:
            raise _translate_stripe_error(e) from e
        return key.secret

    async def confirm_setup_intent_card(self, setup_intent_id: str, customer_id: str) -> dict:
        """Chamado DEPOIS que o Payment Sheet já confirmou no app. Nunca
        confiamos cegamente no que o cliente diz que aconteceu — buscamos o
        SetupIntent de volta no Stripe e conferimos status e dono antes de
        salvar qualquer coisa como cartão válido."""
        si = stripe.SetupIntent.retrieve(setup_intent_id)
        if si.status != "succeeded":
            raise InvalidPaymentRequestError(f"SetupIntent não confirmado (status={si.status})")
        if si.customer != customer_id:
            raise InvalidPaymentRequestError("SetupIntent pertence a outro customer")

        pm = stripe.PaymentMethod.retrieve(si.payment_method)
        stripe.Customer.modify(customer_id, invoice_settings={"default_payment_method": pm.id})
        card = pm.card
        return {
            "payment_method_id": pm.id,
            "brand": card["brand"],
            "last4": card["last4"],
            "exp_month": card["exp_month"],
            "exp_year": card["exp_year"],
        }

    # ------------------------------------------------------------------
    # Hold + capture
    # ------------------------------------------------------------------
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
        kwargs: dict[str, Any] = dict(
            amount=amount_centavos,
            currency=moeda.lower(),
            customer=customer_id,
            payment_method=payment_method_id,
            capture_method="manual",
            confirm=True,
            off_session=True,
            payment_method_types=["card"],
            metadata=metadata or {},
        )
        # Connect: if the pro is onboarded, split at capture time; passing
        # transfer_data here is enough for Stripe to route funds later.
        # fee_bps vem do plano ATUAL do profissional (ver PLANOS em
        # server.py) — cada chamada calcula com a taxa vigente no momento
        # do agendamento, então mudar de plano nunca afeta agendamentos
        # já criados, só os próximos.
        if destination_account_id:
            fee = (amount_centavos * fee_bps) // 10_000
            kwargs["transfer_data"] = {"destination": destination_account_id}
            kwargs["application_fee_amount"] = fee

        # idempotency_key: gerada pelo chamador a partir do agendamento_id
        # (ver server.py). Se a chamada de rede falhar depois do Stripe já
        # ter processado (timeout na nossa ponta, por exemplo), um retry com
        # a MESMA chave devolve o mesmo PaymentIntent em vez de criar um
        # segundo hold no cartão do cliente.
        try:
            pi = stripe.PaymentIntent.create(**kwargs, idempotency_key=idempotency_key)
        except stripe.error.StripeError as e:
            log.warning("authorize falhou (idempotency_key=%s): %s", idempotency_key, e)
            raise _translate_stripe_error(e) from e

        if pi.status != "requires_capture":
            raise InvalidPaymentRequestError(f"unexpected PI status: {pi.status}")

        # Charge holds the capture_before deadline; fall back to +7d if absent.
        hold_expira = _now()
        try:
            charge = pi.latest_charge and stripe.Charge.retrieve(pi.latest_charge)
            if charge and getattr(charge, "payment_method_details", None):
                cb = getattr(charge, "capture_before", None)
                if cb:
                    hold_expira = _to_datetime(cb)
        except Exception:
            log.warning("charge lookup failed", exc_info=True)
        if hold_expira <= _now():
            from datetime import timedelta
            hold_expira = _now() + timedelta(days=7)

        return {
            "payment_intent_id": pi.id,
            "status": "requires_capture",
            "hold_expira_em": hold_expira,
        }

    async def capture(
        self, payment_intent_id: str, amount_to_capture: Optional[int], idempotency_key: str
    ) -> dict:
        params: dict[str, Any] = {}
        if amount_to_capture is not None:
            params["amount_to_capture"] = amount_to_capture
        try:
            pi = stripe.PaymentIntent.capture(payment_intent_id, **params, idempotency_key=idempotency_key)
        except stripe.error.StripeError as e:
            log.warning("capture falhou (pi=%s, idempotency_key=%s): %s", payment_intent_id, idempotency_key, e)
            raise _translate_stripe_error(e) from e
        return {
            "payment_intent_id": pi.id,
            "status": pi.status,
            "amount_received": pi.amount_received,
            "amount_capturable": pi.amount_capturable,
        }

    async def create_pix_payment_intent(
        self,
        amount_centavos: int,
        idempotency_key: str,
        moeda: str = "BRL",
        fee_bps: int = 1000,
        metadata: Optional[dict[str, Any]] = None,
        destination_account_id: Optional[str] = None,
    ) -> dict:
        """Pix não suporta capture_method='manual' (confirmado na doc oficial
        da Stripe — é sempre instantâneo/irreversível, sem conceito de hold).
        Por isso este método cobra o valor TOTAL do serviço de uma vez, sem
        a proteção de no-show do fluxo de cartão — é um caminho
        deliberadamente diferente, não um "hold que ainda não implementamos".

        Confirma o PaymentIntent JÁ NA CRIAÇÃO (confirm=True,
        payment_method_data type=pix) — assim o código Pix "copia e cola" e
        o QR code vêm prontos na própria resposta, sem precisar do Stripe.js
        no navegador do cliente (que exigiria carregar script de um domínio
        fora da nossa lista de origens permitidas na página publicada)."""
        kwargs: dict[str, Any] = dict(
            amount=amount_centavos,
            currency=moeda.lower(),
            payment_method_types=["pix"],
            payment_method_data={"type": "pix"},
            confirm=True,
            metadata=metadata or {},
        )
        if destination_account_id:
            fee = (amount_centavos * fee_bps) // 10_000
            kwargs["transfer_data"] = {"destination": destination_account_id}
            kwargs["application_fee_amount"] = fee
        try:
            pi = stripe.PaymentIntent.create(**kwargs, idempotency_key=idempotency_key)
        except stripe.error.StripeError as e:
            log.warning("create_pix_payment_intent falhou (idempotency_key=%s): %s", idempotency_key, e)
            raise _translate_stripe_error(e) from e
        qr = None
        if pi.next_action and getattr(pi.next_action, "pix_display_qr_code", None):
            qr = pi.next_action.pix_display_qr_code
        return {
            "payment_intent_id": pi.id,
            "client_secret": pi.client_secret,
            "qr_code_data": qr.data if qr else None,
            "hosted_instructions_url": qr.hosted_instructions_url if qr else None,
        }

    async def void(self, payment_intent_id: str, idempotency_key: str) -> dict:
        try:
            pi = stripe.PaymentIntent.cancel(payment_intent_id, idempotency_key=idempotency_key)
        except stripe.error.InvalidRequestError as e:
            # Cancelar um PI que já foi capturado/cancelado antes não é uma
            # falha real do nosso lado — é um estado final legítimo.
            log.warning("void: PI já estava em estado final (%s): %s", payment_intent_id, e)
            return {"payment_intent_id": payment_intent_id, "status": "unknown"}
        except stripe.error.StripeError as e:
            raise _translate_stripe_error(e) from e
        return {"payment_intent_id": pi.id, "status": pi.status}

    async def expire(self, payment_intent_id: str, idempotency_key: str) -> dict:
        return await self.void(payment_intent_id, idempotency_key=idempotency_key)

    # ------------------------------------------------------------------
    # Connect
    # ------------------------------------------------------------------
    async def create_connect_account(
        self,
        email: str,
        name: str,
        country: str = "BR",
        profile_url: Optional[str] = None,
        product_description: Optional[str] = None,
    ) -> Optional[str]:
        """Cria a conta Express do profissional já com TUDO que a gente sabe
        pré-preenchido — o onboarding hospedado do Stripe não pergunta de
        novo o que já veio aqui (só pede uma confirmação no final). Isso
        tira do caminho: escolha do tipo de conta (fixamos pessoa física),
        nome, e-mail e o passo "Business information" (ramo/site).

        NÃO dá pra pré-preencher (e nem pedir pro profissional pular): data
        de nascimento, CPF, endereço, telefone e conta bancária. São a
        verificação de identidade que o Stripe exige de toda pessoa física
        pra liberar repasses — a gente não coleta nem guarda esses dados."""
        kwargs: dict[str, Any] = dict(
            type="express",
            country=country,
            email=email,
            business_type="individual",
            business_profile={"name": name, "mcc": "7299"},
            capabilities={
                "transfers": {"requested": True},
                "card_payments": {"requested": True},
            },
        )
        # Autônomo sem site próprio: a doc do Stripe manda usar a página
        # pública dele na plataforma como URL; sem URL, a descrição.
        if profile_url:
            kwargs["business_profile"]["url"] = profile_url
        if product_description:
            kwargs["business_profile"]["product_description"] = product_description
        partes = (name or "").split()
        individual: dict[str, Any] = {"email": email}
        if partes:
            individual["first_name"] = partes[0]
        if len(partes) > 1:
            individual["last_name"] = " ".join(partes[1:])
        kwargs["individual"] = individual
        try:
            acct = stripe.Account.create(**kwargs)
            return acct.id
        except stripe.error.InvalidRequestError as e:
            if "Connect" in str(e):
                log.warning("Connect not enabled on the platform account")
                return None
            raise _translate_stripe_error(e) from e
        except stripe.error.StripeError as e:
            raise _translate_stripe_error(e) from e

    async def prefill_connect_profile(
        self,
        account_id: str,
        profile_url: Optional[str],
        product_description: Optional[str],
    ) -> None:
        """Contas criadas ANTES desse pré-preenchimento existir (ou que o
        profissional deixou pela metade) ganham o perfil público aqui, na
        hora de gerar o link de onboarding. Só preenche o que ainda está
        vazio — nunca sobrescreve o que o profissional já digitou — e é
        best-effort: qualquer falha só vira log, nunca bloqueia o cadastro."""
        try:
            acct = stripe.Account.retrieve(account_id)
            bp = acct.get("business_profile") or {}
            novo: dict[str, Any] = {}
            if profile_url and not bp.get("url") and not bp.get("product_description"):
                novo["url"] = profile_url
            if product_description and not bp.get("product_description") and not bp.get("url"):
                novo["product_description"] = product_description
            if novo:
                stripe.Account.modify(account_id, business_profile=novo)
        except stripe.error.StripeError as e:
            log.warning("prefill_connect_profile falhou (acct=%s): %s", account_id, e)

    async def create_onboarding_link(
        self, account_id: str, return_url: str, refresh_url: str
    ) -> str:
        try:
            link = stripe.AccountLink.create(
                account=account_id,
                refresh_url=refresh_url,
                return_url=return_url,
                type="account_onboarding",
            )
        except stripe.error.StripeError as e:
            raise _translate_stripe_error(e) from e
        return link.url

    async def account_status(self, account_id: str) -> dict:
        acct = stripe.Account.retrieve(account_id)
        return {
            "details_submitted": acct.details_submitted,
            "charges_enabled": acct.charges_enabled,
            "payouts_enabled": acct.payouts_enabled,
        }

    # ------------------------------------------------------------------
    # Assinatura de plano (o profissional paga A PLATAFORMA, ao contrário
    # do fluxo acima onde o CLIENTE paga o profissional) — por isso um
    # Customer separado (`ensure_billing_customer`), nunca o mesmo objeto
    # usado quando esse mesmo profissional reserva um serviço de outra
    # pessoa como cliente.
    # ------------------------------------------------------------------
    async def ensure_billing_customer(self, user_id: str, email: str, name: str) -> str:
        c = stripe.Customer.create(email=email, name=name, metadata={"user_id": user_id, "billing": "plano"})
        return c.id

    async def create_plano_subscription(
        self, billing_customer_id: str, price_id: str, user_id: str
    ) -> dict:
        """Cria a assinatura DIRETO via API (sem Checkout hospedado) — o
        pagamento em si é coletado pelo Payment Sheet nativo do app, igual
        já fazemos pro cartão do cliente no fluxo de no-show. `payment_
        behavior='default_incomplete'` deixa a assinatura criada mas
        pendente até o Payment Sheet confirmar o pagamento; sem isso, o
        Stripe tentaria cobrar imediatamente com um método de pagamento
        que ainda não existe.

        Expandimos `latest_invoice.confirmation_secret`, não `.payment_
        intent` — a partir da versão "Basil" da API (mudança de 31/03/2025)
        o Stripe removeu o campo payment_intent do objeto Invoice de
        propósito (parte do suporte a pagamentos parciais múltiplos por
        fatura). confirmation_secret.client_secret é o substituto oficial,
        e a própria doc da Stripe pro SDK React Native usa exatamente esse
        client_secret com initPaymentSheet — funciona igual."""
        try:
            subscription = stripe.Subscription.create(
                customer=billing_customer_id,
                items=[{"price": price_id}],
                payment_behavior="default_incomplete",
                payment_settings={"save_default_payment_method": "on_subscription"},
                expand=["latest_invoice.confirmation_secret"],
                metadata={"user_id": user_id},
            )
        except stripe.error.StripeError as e:
            # Cobre "No such price" (Price ID de outro modo/apagado), entre
            # outros — sem isso, isso derrubava a requisição com um 500 e
            # traceback cru em vez de uma mensagem clara pro cliente.
            raise _translate_stripe_error(e) from e
        client_secret = subscription.latest_invoice.confirmation_secret.client_secret
        # Mantemos a chave "payment_intent_client_secret" no dict de retorno
        # (mesmo o valor agora vindo de confirmation_secret, não mais de um
        # PaymentIntent expandido diretamente) — o frontend já espera esse
        # nome de campo e passa pro parâmetro paymentIntentClientSecret do
        # Payment Sheet, que funciona igual com esse client_secret novo.
        return {
            "subscription_id": subscription.id,
            "payment_intent_client_secret": client_secret,
        }

    async def get_subscription_status(self, subscription_id: str) -> str:
        sub = stripe.Subscription.retrieve(subscription_id)
        return sub.status

    async def cancel_subscription(self, subscription_id: str) -> None:
        try:
            stripe.Subscription.cancel(subscription_id)
        except stripe.error.InvalidRequestError as e:
            # Já cancelada/inexistente — não é erro do nosso lado.
            log.warning("cancel_subscription: já em estado final (%s): %s", subscription_id, e)
