"""Iteration 3 tests: Real Stripe gateway, categorias, disponibilidade,
slots, reminders, Connect onboarding (graceful).

Uses pymongo to seed sessions directly (no real Google OAuth).
Test data prefixed with TEST_ for easy cleanup.
"""
from __future__ import annotations

import os
import uuid
import time
from datetime import datetime, timedelta, timezone

import pytest
import requests
from pymongo import MongoClient
from conftest import attach_test_card

BASE_URL = os.environ.get("EXPO_PUBLIC_BACKEND_URL", "http://127.0.0.1:8001").rstrip("/")
MONGO_URL = os.environ.get("MONGO_URL", "mongodb://localhost:27017")
DB_NAME = os.environ.get("DB_NAME", "test_database")


def _now():
    return datetime.now(timezone.utc)


@pytest.fixture(scope="module")
def mongo_db():
    c = MongoClient(MONGO_URL)
    yield c[DB_NAME]
    c.close()


def _make_user(mongo_db, role=None, name_prefix="TEST_User"):
    uid = f"user_{uuid.uuid4().hex[:12]}"
    email = f"test_{uuid.uuid4().hex[:8]}@showup.example.com"
    mongo_db.users.insert_one({
        "user_id": uid,
        "email": email,
        "name": f"{name_prefix}_{uuid.uuid4().hex[:4]}",
        "picture": None,
        "role": role,
        "categorias": [],
        "created_at": _now(),
    })
    token = f"tok_test_{uuid.uuid4().hex}"
    mongo_db.user_sessions.insert_one({
        "session_token": token,
        "user_id": uid,
        "created_at": _now(),
        "expires_at": _now() + timedelta(days=7),
    })
    return {"user_id": uid, "email": email, "token": token,
            "headers": {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}}


@pytest.fixture(scope="module")
def created_ids():
    return {"users": [], "servicos": [], "agendamentos": [], "sessions": []}


@pytest.fixture(scope="module", autouse=True)
def cleanup(mongo_db, created_ids):
    yield
    if created_ids["users"]:
        mongo_db.users.delete_many({"user_id": {"$in": created_ids["users"]}})
        mongo_db.customer_cards.delete_many({"user_id": {"$in": created_ids["users"]}})
        mongo_db.servicos.delete_many({"profissional_id": {"$in": created_ids["users"]}})
        mongo_db.disponibilidade.delete_many({"profissional_id": {"$in": created_ids["users"]}})
        mongo_db.agendamentos.delete_many({
            "$or": [
                {"profissional_id": {"$in": created_ids["users"]}},
                {"cliente_id": {"$in": created_ids["users"]}},
            ]
        })
    if created_ids["sessions"]:
        mongo_db.user_sessions.delete_many({"session_token": {"$in": created_ids["sessions"]}})


@pytest.fixture(scope="module")
def cliente(mongo_db, created_ids):
    u = _make_user(mongo_db, role="cliente", name_prefix="TEST_Cli3")
    created_ids["users"].append(u["user_id"])
    created_ids["sessions"].append(u["token"])
    return u


@pytest.fixture(scope="module")
def profissional(mongo_db, created_ids):
    u = _make_user(mongo_db, role="profissional", name_prefix="TEST_Prof3")
    created_ids["users"].append(u["user_id"])
    created_ids["sessions"].append(u["token"])
    return u


@pytest.fixture(scope="module")
def profissional2(mongo_db, created_ids):
    u = _make_user(mongo_db, role="profissional", name_prefix="TEST_Prof3B")
    created_ids["users"].append(u["user_id"])
    created_ids["sessions"].append(u["token"])
    return u


# ---------------------------------------------------------------------------
# Root / gateway
# ---------------------------------------------------------------------------
class TestRoot:
    def test_gateway_is_stripe(self):
        r = requests.get(f"{BASE_URL}/api/")
        assert r.status_code == 200, r.text
        body = r.json()
        assert body.get("gateway") == "stripe"
        assert body.get("status") == "ok"


# ---------------------------------------------------------------------------
# Card - Real Stripe
# ---------------------------------------------------------------------------
class TestCardStripe:
    def test_cliente_saves_real_card(self, cliente, mongo_db):
        r = attach_test_card(BASE_URL, cliente["headers"])
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["brand"] == "visa"
        assert body["last4"] == "4242"

        # DB check: customer_id must be real (cus_...) not mock
        card = mongo_db.customer_cards.find_one({"user_id": cliente["user_id"]})
        assert card is not None
        assert card["customer_id"].startswith("cus_")
        assert not card["customer_id"].startswith("cus_mock_")
        assert card["payment_method_id"].startswith("pm_")
        assert not card["payment_method_id"].startswith("pm_mock_")

    def test_save_card_upsert_same_customer(self, cliente, mongo_db):
        card1 = mongo_db.customer_cards.find_one({"user_id": cliente["user_id"]})
        assert card1 is not None
        cust1 = card1["customer_id"]

        r = attach_test_card(BASE_URL, cliente["headers"])
        assert r.status_code == 200

        card2 = mongo_db.customer_cards.find_one({"user_id": cliente["user_id"]})
        assert card2["customer_id"] == cust1, "Second POST /me/card should reuse same Stripe customer"

    def test_get_card_has_card(self, cliente):
        r = requests.get(f"{BASE_URL}/api/me/card", headers=cliente["headers"])
        assert r.status_code == 200
        body = r.json()
        assert body["has_card"] is True
        assert body["brand"] == "visa"
        assert body["last4"] == "4242"

    def test_profissional_cannot_save_card(self, profissional):
        r = attach_test_card(BASE_URL, profissional["headers"])
        assert r.status_code == 403


# ---------------------------------------------------------------------------
# Categorias
# ---------------------------------------------------------------------------
class TestCategorias:
    def test_get_categorias_fixed_list(self):
        r = requests.get(f"{BASE_URL}/api/categorias")
        assert r.status_code == 200
        body = r.json()
        cats = body["categorias"]
        assert set(cats) == {"fitness", "terapia", "consultoria", "estetica", "coaching", "nutricao"}
        assert len(cats) == 6

    def test_profissional_sets_categorias(self, profissional):
        r = requests.put(f"{BASE_URL}/api/me/categorias",
                         json={"categorias": ["fitness", "coaching"]},
                         headers=profissional["headers"])
        assert r.status_code == 200, r.text
        body = r.json()
        assert set(body["user"]["categorias"]) == {"fitness", "coaching"}

    def test_categorias_empty_returns_422(self, profissional):
        r = requests.put(f"{BASE_URL}/api/me/categorias",
                         json={"categorias": []},
                         headers=profissional["headers"])
        assert r.status_code == 422

    def test_categorias_more_than_3_returns_422(self, profissional):
        r = requests.put(f"{BASE_URL}/api/me/categorias",
                         json={"categorias": ["fitness", "coaching", "terapia", "nutricao"]},
                         headers=profissional["headers"])
        assert r.status_code == 422

    def test_categorias_invalid_value_returns_422(self, profissional):
        r = requests.put(f"{BASE_URL}/api/me/categorias",
                         json={"categorias": ["invalid_cat"]},
                         headers=profissional["headers"])
        assert r.status_code == 422

    def test_cliente_cannot_set_categorias(self, cliente):
        r = requests.put(f"{BASE_URL}/api/me/categorias",
                         json={"categorias": ["fitness"]},
                         headers=cliente["headers"])
        assert r.status_code == 403


# ---------------------------------------------------------------------------
# Discovery com categoria filter
# ---------------------------------------------------------------------------
class TestDiscoveryCategoria:
    def test_filter_by_categoria(self, profissional, profissional2, created_ids):
        # Set up: prof1 => fitness, prof2 => terapia
        requests.put(f"{BASE_URL}/api/me/categorias",
                     json={"categorias": ["fitness"]},
                     headers=profissional["headers"])
        requests.put(f"{BASE_URL}/api/me/categorias",
                     json={"categorias": ["terapia"]},
                     headers=profissional2["headers"])

        # Both need active servicos to show up in discovery
        r1 = requests.post(f"{BASE_URL}/api/servicos", json={
            "nome": "TEST_S_Fit", "valor_centavos": 10000,
            "taxa_no_show_centavos": 3000, "duracao_min": 60,
        }, headers=profissional["headers"])
        assert r1.status_code == 200
        created_ids["servicos"].append(r1.json()["servico_id"])

        r2 = requests.post(f"{BASE_URL}/api/servicos", json={
            "nome": "TEST_S_Ter", "valor_centavos": 8000,
            "taxa_no_show_centavos": 2000, "duracao_min": 45,
        }, headers=profissional2["headers"])
        assert r2.status_code == 200
        created_ids["servicos"].append(r2.json()["servico_id"])

        r = requests.get(f"{BASE_URL}/api/profissionais", params={"categoria": "fitness"})
        assert r.status_code == 200
        ids = {p["user_id"] for p in r.json()}
        assert profissional["user_id"] in ids
        assert profissional2["user_id"] not in ids

    def test_invalid_categoria_ignored(self, profissional):
        r = requests.get(f"{BASE_URL}/api/profissionais", params={"categoria": "abracadabra"})
        assert r.status_code == 200
        # Just returns everyone (filter ignored). Our fitness prof should be present.
        ids = {p["user_id"] for p in r.json()}
        assert profissional["user_id"] in ids

    def test_categoria_combined_with_q(self, profissional):
        # profissional has name TEST_Prof3_xxxx
        r = requests.get(f"{BASE_URL}/api/profissionais",
                         params={"categoria": "fitness", "q": "prof3"})
        assert r.status_code == 200
        results = r.json()
        assert any(p["user_id"] == profissional["user_id"] for p in results)


# ---------------------------------------------------------------------------
# Disponibilidade + slots
# ---------------------------------------------------------------------------
class TestDisponibilidade:
    def test_cliente_cannot_set_disponibilidade(self, cliente):
        r = requests.put(f"{BASE_URL}/api/me/disponibilidade",
                         json={"slots": [{"weekday": 0, "hora_inicio": "09:00", "hora_fim": "12:00"}]},
                         headers=cliente["headers"])
        assert r.status_code == 403

    def test_prof_sets_and_gets_disponibilidade(self, profissional):
        slots = [
            {"weekday": 0, "hora_inicio": "09:00", "hora_fim": "12:00"},
            {"weekday": 1, "hora_inicio": "14:00", "hora_fim": "18:00"},
            {"weekday": 2, "hora_inicio": "09:00", "hora_fim": "12:00"},
            {"weekday": 3, "hora_inicio": "09:00", "hora_fim": "12:00"},
            {"weekday": 4, "hora_inicio": "09:00", "hora_fim": "12:00"},
            {"weekday": 5, "hora_inicio": "09:00", "hora_fim": "12:00"},
            {"weekday": 6, "hora_inicio": "09:00", "hora_fim": "12:00"},
        ]
        r = requests.put(f"{BASE_URL}/api/me/disponibilidade",
                         json={"slots": slots},
                         headers=profissional["headers"])
        assert r.status_code == 200, r.text
        assert r.json()["count"] == 7

        r = requests.get(f"{BASE_URL}/api/profissionais/{profissional['user_id']}/disponibilidade")
        assert r.status_code == 200
        got = r.json()["slots"]
        assert len(got) == 7
        weekdays = sorted([s["weekday"] for s in got])
        assert weekdays == [0, 1, 2, 3, 4, 5, 6]

    def test_disponibilidade_replace_semantics(self, profissional):
        # Replace with a smaller set
        r = requests.put(f"{BASE_URL}/api/me/disponibilidade",
                         json={"slots": [{"weekday": 0, "hora_inicio": "10:00", "hora_fim": "11:00"}]},
                         headers=profissional["headers"])
        assert r.status_code == 200
        assert r.json()["count"] == 1

        r = requests.get(f"{BASE_URL}/api/profissionais/{profissional['user_id']}/disponibilidade")
        assert r.status_code == 200
        got = r.json()["slots"]
        assert len(got) == 1


class TestSlots:
    def test_no_disponibilidade_returns_empty(self, profissional2, created_ids):
        # Autossuficiente de propósito: não depende de test_filter_by_categoria
        # (outra classe) ter criado um serviço antes. Sob pytest-xdist com
        # --dist loadscope, testes agrupados por CLASSE podem rodar em
        # workers diferentes em paralelo — depender de outra classe já ter
        # rodado é uma corrida, não uma garantia.
        r = requests.post(f"{BASE_URL}/api/servicos", json={
            "nome": "TEST_S_Slots", "descricao": "x", "valor_centavos": 9000,
            "taxa_no_show_centavos": 3000, "duracao_min": 30,
        }, headers=profissional2["headers"])
        assert r.status_code == 200, r.text
        sid = r.json()["servico_id"]
        created_ids["servicos"].append(sid)

        # Wipe disponibilidade explicitly
        requests.put(f"{BASE_URL}/api/me/disponibilidade",
                     json={"slots": []},
                     headers=profissional2["headers"])

        r = requests.get(f"{BASE_URL}/api/profissionais/{profissional2['user_id']}/slots",
                         params={"servico_id": sid})
        assert r.status_code == 200
        assert r.json() == []

    def test_slots_generated_for_14_days(self, profissional):
        # Set full-week disponibilidade
        slots_conf = [{"weekday": i, "hora_inicio": "09:00", "hora_fim": "17:00"} for i in range(7)]
        requests.put(f"{BASE_URL}/api/me/disponibilidade",
                     json={"slots": slots_conf},
                     headers=profissional["headers"])

        # Autossuficiente pelo mesmo motivo do teste acima — não depende de
        # outra classe ter criado um serviço antes.
        r = requests.post(f"{BASE_URL}/api/servicos", json={
            "nome": "TEST_S_14Dias", "descricao": "x", "valor_centavos": 9000,
            "taxa_no_show_centavos": 3000, "duracao_min": 30,
        }, headers=profissional["headers"])
        assert r.status_code == 200, r.text
        sid = r.json()["servico_id"]

        r = requests.get(f"{BASE_URL}/api/profissionais/{profissional['user_id']}/slots",
                         params={"servico_id": sid})
        assert r.status_code == 200
        slots = r.json()
        assert len(slots) > 0
        # Each slot has iso/day_label/time_label
        for s in slots[:3]:
            assert "iso" in s and "day_label" in s and "time_label" in s
        # All slots within next 14 days
        for s in slots:
            dt = datetime.fromisoformat(s["iso"].replace("Z", "+00:00"))
            assert dt <= _now() + timedelta(days=15)
            assert dt >= _now()

    def test_slots_servico_not_found_404(self, profissional):
        r = requests.get(f"{BASE_URL}/api/profissionais/{profissional['user_id']}/slots",
                         params={"servico_id": "srv_notreal"})
        assert r.status_code == 404


# ---------------------------------------------------------------------------
# Real Stripe agendamento flow
# ---------------------------------------------------------------------------
@pytest.fixture(scope="module")
def servico_pago(profissional, created_ids):
    r = requests.post(f"{BASE_URL}/api/servicos", json={
        "nome": "TEST_ServicoStripe", "valor_centavos": 15000,
        "taxa_no_show_centavos": 5000, "duracao_min": 60,
    }, headers=profissional["headers"])
    assert r.status_code == 200, r.text
    sid = r.json()["servico_id"]
    created_ids["servicos"].append(sid)
    return {"servico_id": sid, "valor": 15000, "taxa": 5000}


class TestAgendamentoStripe:
    def test_criar_agendamento_real_pi(self, cliente, servico_pago, mongo_db, created_ids):
        # ensure card exists
        attach_test_card(BASE_URL, cliente["headers"])
        horario = (_now() + timedelta(days=3)).isoformat()
        r = requests.post(f"{BASE_URL}/api/agendamentos",
                          json={"servico_id": servico_pago["servico_id"],
                                "horario_inicio": horario},
                          headers=cliente["headers"])
        assert r.status_code == 200, r.text
        body = r.json()
        # Real Stripe PI
        assert body["payment_intent_id"].startswith("pi_"), body["payment_intent_id"]
        assert not body["payment_intent_id"].startswith("pi_mock_"), body["payment_intent_id"]
        assert body["hold_status"] == "autorizado"
        assert body["valor_total_centavos"] == 15000

        # transacao gravada como authorization
        tx = mongo_db.transacoes.find_one({"agendamento_id": body["agendamento_id"],
                                            "tipo": "authorization"})
        assert tx is not None
        assert tx["status"] == "requires_capture"
        assert tx["valor_centavos"] == 15000

        created_ids["agendamentos"].append(body["agendamento_id"])
        # Save PI for downstream Stripe checks
        pytest.pi_agendamento = body

    def test_stripe_pi_status_requires_capture(self):
        """Query Stripe directly to check the PI is really in requires_capture."""
        import stripe
        stripe.api_key = os.environ.get("STRIPE_API_KEY", "")
        ag = pytest.pi_agendamento
        pi = stripe.PaymentIntent.retrieve(ag["payment_intent_id"])
        assert pi.status == "requires_capture", pi.status
        assert pi.amount_capturable == 15000
        assert pi.capture_method == "manual"


class TestConfirmarStripe:
    def test_compareceu_captura_total_real(self, cliente, profissional, servico_pago, mongo_db, created_ids):
        attach_test_card(BASE_URL, cliente["headers"])
        horario = (_now() + timedelta(days=4)).isoformat()
        r = requests.post(f"{BASE_URL}/api/agendamentos",
                          json={"servico_id": servico_pago["servico_id"],
                                "horario_inicio": horario},
                          headers=cliente["headers"])
        assert r.status_code == 200, r.text
        ag = r.json()
        created_ids["agendamentos"].append(ag["agendamento_id"])

        r = requests.post(f"{BASE_URL}/api/agendamentos/{ag['agendamento_id']}/confirmar",
                          json={"resultado": "compareceu"},
                          headers=profissional["headers"])
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["hold_status"] == "capturado_total"
        assert body["valor_capturado_centavos"] == 15000

        # Verify in Stripe
        import stripe
        stripe.api_key = os.environ.get("STRIPE_API_KEY", "")
        pi = stripe.PaymentIntent.retrieve(ag["payment_intent_id"])
        assert pi.status == "succeeded"
        assert pi.amount_received == 15000

        # Second confirm => 409
        r2 = requests.post(f"{BASE_URL}/api/agendamentos/{ag['agendamento_id']}/confirmar",
                           json={"resultado": "compareceu"},
                           headers=profissional["headers"])
        assert r2.status_code == 409

    def test_nao_compareceu_captura_parcial_real(self, cliente, profissional, servico_pago, mongo_db, created_ids):
        attach_test_card(BASE_URL, cliente["headers"])
        horario = (_now() + timedelta(days=5)).isoformat()
        r = requests.post(f"{BASE_URL}/api/agendamentos",
                          json={"servico_id": servico_pago["servico_id"],
                                "horario_inicio": horario},
                          headers=cliente["headers"])
        assert r.status_code == 200, r.text
        ag = r.json()
        created_ids["agendamentos"].append(ag["agendamento_id"])

        r = requests.post(f"{BASE_URL}/api/agendamentos/{ag['agendamento_id']}/confirmar",
                          json={"resultado": "nao_compareceu"},
                          headers=profissional["headers"])
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["hold_status"] == "capturado_taxa"
        assert body["valor_capturado_centavos"] == 5000

        # Verify Stripe: PI succeeded, amount_received=5000, rest released
        import stripe
        stripe.api_key = os.environ.get("STRIPE_API_KEY", "")
        pi = stripe.PaymentIntent.retrieve(ag["payment_intent_id"])
        assert pi.status == "succeeded"
        assert pi.amount_received == 5000

    def test_cancelar_void_real(self, cliente, servico_pago, mongo_db, created_ids):
        attach_test_card(BASE_URL, cliente["headers"])
        horario = (_now() + timedelta(days=6)).isoformat()
        r = requests.post(f"{BASE_URL}/api/agendamentos",
                          json={"servico_id": servico_pago["servico_id"],
                                "horario_inicio": horario},
                          headers=cliente["headers"])
        assert r.status_code == 200
        ag = r.json()
        created_ids["agendamentos"].append(ag["agendamento_id"])

        r = requests.post(f"{BASE_URL}/api/agendamentos/{ag['agendamento_id']}/cancelar",
                          headers=cliente["headers"])
        assert r.status_code == 200

        # Verify Stripe cancel
        import stripe
        stripe.api_key = os.environ.get("STRIPE_API_KEY", "")
        pi = stripe.PaymentIntent.retrieve(ag["payment_intent_id"])
        assert pi.status == "canceled"

        updated = mongo_db.agendamentos.find_one({"agendamento_id": ag["agendamento_id"]})
        assert updated["hold_status"] == "cancelado"


# ---------------------------------------------------------------------------
# Reminders janela
# ---------------------------------------------------------------------------
class TestRemindersJanela:
    def test_cliente_forbidden(self, cliente):
        r = requests.get(f"{BASE_URL}/api/reminders/janela",
                         params={"horas": 6},
                         headers=cliente["headers"])
        assert r.status_code == 403

    def test_profissional_lists_pending(self, cliente, profissional, servico_pago, mongo_db, created_ids):
        # Create an appointment whose janela ends in <= 6h and horario_fim in past
        attach_test_card(BASE_URL, cliente["headers"])
        horario = (_now() + timedelta(days=7)).isoformat()
        r = requests.post(f"{BASE_URL}/api/agendamentos",
                          json={"servico_id": servico_pago["servico_id"],
                                "horario_inicio": horario},
                          headers=cliente["headers"])
        assert r.status_code == 200, r.text
        ag = r.json()
        created_ids["agendamentos"].append(ag["agendamento_id"])

        # Force janela to expire in 3h and horario_fim into the past
        mongo_db.agendamentos.update_one(
            {"agendamento_id": ag["agendamento_id"]},
            {"$set": {
                "horario_fim": _now() - timedelta(hours=1),
                "janela_confirmacao_expira_em": _now() + timedelta(hours=3),
            }},
        )

        r = requests.get(f"{BASE_URL}/api/reminders/janela",
                         params={"horas": 6},
                         headers=profissional["headers"])
        assert r.status_code == 200, r.text
        body = r.json()
        ids = [it["agendamento_id"] for it in body["items"]]
        assert ag["agendamento_id"] in ids
        assert body["count"] >= 1


# ---------------------------------------------------------------------------
# Connect (Stripe Express) - graceful degradation
# ---------------------------------------------------------------------------
class TestConnect:
    def test_cliente_cannot_start_onboarding(self, cliente):
        r = requests.post(f"{BASE_URL}/api/me/connect/onboarding",
                          params={"return_url": "https://example.com/r",
                                  "refresh_url": "https://example.com/f"},
                          headers=cliente["headers"])
        assert r.status_code == 403

    def test_connect_status_no_account(self, profissional):
        r = requests.get(f"{BASE_URL}/api/me/connect", headers=profissional["headers"])
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["account_id"] is None
        assert body["charges_enabled"] is False
        assert body["payouts_enabled"] is False

    def test_onboarding_fails_gracefully_when_connect_disabled(self, profissional):
        r = requests.post(f"{BASE_URL}/api/me/connect/onboarding",
                          params={"return_url": "https://example.com/r",
                                  "refresh_url": "https://example.com/f"},
                          headers=profissional["headers"])
        # Since Connect is NOT enabled on the platform account, expect 400
        # with a helpful message.
        assert r.status_code == 400, r.text
        detail = r.json().get("detail", "")
        assert "Connect" in detail and "habilitado" in detail.lower(), detail


# ---------------------------------------------------------------------------
# Indexes
# ---------------------------------------------------------------------------
class TestIndexesIt3:
    def test_disponibilidade_index(self, mongo_db):
        idx = mongo_db.disponibilidade.index_information()
        match = [v for v in idx.values() if v.get("key") == [("profissional_id", 1), ("weekday", 1)]]
        assert match, f"expected (profissional_id, weekday) index. got: {list(idx.values())}"
