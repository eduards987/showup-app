"""Gateway da assinatura de plano com objetos REAIS da biblioteca do Stripe
(StripeObject), sem rede: monta as respostas com `construct_from` e troca só a
chamada HTTP. Objetos do Stripe não são dicts — já deu problema aqui antes."""
import asyncio
import os
import sys
from pathlib import Path

os.environ.setdefault("TESTING", "1")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import stripe

from stripe_gateway import StripeGateway


def _gw():
    return StripeGateway.__new__(StripeGateway)


def _sub(**campos):
    base = {"id": "sub_1", "status": "trialing", "trial_end": 1_800_000_000, "metadata": {"user_id": "u1"},
            "pending_setup_intent": None, "latest_invoice": None}
    base.update(campos)
    return stripe.Subscription.construct_from(base, "sk_test")


def test_trial_pede_14_dias_cancela_sem_cartao_e_devolve_o_setup_intent(monkeypatch):
    visto = {}

    def fake_create(**kw):
        visto.update(kw)
        return _sub(pending_setup_intent={"id": "seti_1", "client_secret": "seti_secret_x"})

    monkeypatch.setattr(stripe.Subscription, "create", staticmethod(fake_create))
    r = asyncio.run(_gw().create_plano_subscription("cus_1", "price_p", "u1", trial_days=14))
    assert r == {"subscription_id": "sub_1", "payment_intent_client_secret": None,
                 "setup_intent_client_secret": "seti_secret_x", "setup_intent_id": "seti_1"}
    assert visto["trial_period_days"] == 14
    assert visto["trial_settings"] == {"end_behavior": {"missing_payment_method": "cancel"}}
    assert visto["payment_behavior"] == "default_incomplete"
    assert "pending_setup_intent" in visto["expand"] and "latest_invoice.confirmation_secret" in visto["expand"]
    assert visto["metadata"] == {"user_id": "u1"}


def test_sem_trial_nao_manda_parametros_de_teste_e_usa_o_payment_intent(monkeypatch):
    visto = {}

    def fake_create(**kw):
        visto.update(kw)
        return _sub(status="incomplete", latest_invoice={"id": "in_1", "confirmation_secret": {"client_secret": "pi_secret_x"}})

    monkeypatch.setattr(stripe.Subscription, "create", staticmethod(fake_create))
    r = asyncio.run(_gw().create_plano_subscription("cus_1", "price_p", "u1"))
    assert r["payment_intent_client_secret"] == "pi_secret_x" and r["setup_intent_client_secret"] is None
    assert "trial_period_days" not in visto and "trial_settings" not in visto


def test_trial_sem_pending_setup_intent_devolve_vazio_pra_quem_chamou_decidir(monkeypatch):
    monkeypatch.setattr(stripe.Subscription, "create", staticmethod(lambda **kw: _sub()))
    r = asyncio.run(_gw().create_plano_subscription("cus_1", "price_p", "u1", trial_days=14))
    assert r["setup_intent_client_secret"] is None and r["setup_intent_id"] is None


def test_detalhes_da_assinatura_leem_status_fim_do_teste_e_dono(monkeypatch):
    monkeypatch.setattr(stripe.Subscription, "retrieve", staticmethod(lambda sid: _sub()))
    d = asyncio.run(_gw().get_subscription_details("sub_1"))
    assert d == {"status": "trialing", "trial_end": 1_800_000_000, "user_id": "u1"}


def test_detalhes_sem_metadata_nao_quebram(monkeypatch):
    monkeypatch.setattr(stripe.Subscription, "retrieve", staticmethod(lambda sid: _sub(metadata={}, trial_end=None)))
    d = asyncio.run(_gw().get_subscription_details("sub_1"))
    assert d["user_id"] is None and d["trial_end"] is None


def test_status_do_setup_intent(monkeypatch):
    si = stripe.SetupIntent.construct_from({"id": "seti_1", "status": "succeeded"}, "sk_test")
    monkeypatch.setattr(stripe.SetupIntent, "retrieve", staticmethod(lambda i: si))
    assert asyncio.run(_gw().get_setup_intent_status("seti_1")) == "succeeded"
