"""Backend tests for ShowUp full booking flow (iteration 2).

Covers: role toggle, card lifecycle, servicos CRUD/ownership,
profissionais discovery, agendamento create+confirmar+cancelar,
expirar-janela job, mongo indexes.

Sessions are seeded directly in Mongo (no real Google OAuth).
"""
from __future__ import annotations

import os
import uuid
from datetime import datetime, timedelta, timezone

import pytest
import requests
from pymongo import MongoClient
from conftest import attach_test_card

BASE_URL = os.environ.get("EXPO_PUBLIC_BACKEND_URL", "http://127.0.0.1:8001").rstrip("/")
MONGO_URL = os.environ.get("MONGO_URL", "mongodb://localhost:27017")
DB_NAME = os.environ.get("DB_NAME", "test_database")


# ---------------------------------------------------------------------------
# Fixtures & helpers
# ---------------------------------------------------------------------------
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
    return {"users": [], "servicos": [], "agendamentos": [], "cards": [], "sessions": []}


@pytest.fixture(scope="module")
def cliente(mongo_db, created_ids):
    u = _make_user(mongo_db, role="cliente", name_prefix="TEST_Cli")
    created_ids["users"].append(u["user_id"])
    created_ids["sessions"].append(u["token"])
    # Pre-create card so downstream booking tests don't depend on TestCard ordering.
    attach_test_card(BASE_URL, u["headers"])
    return u


@pytest.fixture(scope="module")
def profissional(mongo_db, created_ids):
    u = _make_user(mongo_db, role="profissional", name_prefix="TEST_Prof_Alice")
    created_ids["users"].append(u["user_id"])
    created_ids["sessions"].append(u["token"])
    return u


@pytest.fixture(scope="module")
def profissional2(mongo_db, created_ids):
    u = _make_user(mongo_db, role="profissional", name_prefix="TEST_Prof_Bob")
    created_ids["users"].append(u["user_id"])
    created_ids["sessions"].append(u["token"])
    return u


@pytest.fixture(scope="module", autouse=True)
def cleanup(request, mongo_db, created_ids):
    yield
    # Teardown
    if created_ids["users"]:
        mongo_db.users.delete_many({"user_id": {"$in": created_ids["users"]}})
        mongo_db.customer_cards.delete_many({"user_id": {"$in": created_ids["users"]}})
        mongo_db.servicos.delete_many({"profissional_id": {"$in": created_ids["users"]}})
        mongo_db.agendamentos.delete_many({
            "$or": [
                {"profissional_id": {"$in": created_ids["users"]}},
                {"cliente_id": {"$in": created_ids["users"]}},
            ]
        })
    if created_ids["sessions"]:
        mongo_db.user_sessions.delete_many({"session_token": {"$in": created_ids["sessions"]}})


# ---------------------------------------------------------------------------
# Auth: role toggle
# ---------------------------------------------------------------------------
class TestRoleToggle:
    def test_toggle_between_cliente_and_profissional(self, mongo_db, created_ids):
        u = _make_user(mongo_db, role=None)
        created_ids["users"].append(u["user_id"])
        created_ids["sessions"].append(u["token"])

        r = requests.post(f"{BASE_URL}/api/auth/role", json={"role": "cliente"}, headers=u["headers"])
        assert r.status_code == 200, r.text
        assert r.json()["user"]["role"] == "cliente"

        r = requests.post(f"{BASE_URL}/api/auth/role", json={"role": "profissional"}, headers=u["headers"])
        assert r.status_code == 200
        assert r.json()["user"]["role"] == "profissional"

        r = requests.post(f"{BASE_URL}/api/auth/role", json={"role": "cliente"}, headers=u["headers"])
        assert r.status_code == 200
        assert r.json()["user"]["role"] == "cliente"


# ---------------------------------------------------------------------------
# Card (cliente only)
# ---------------------------------------------------------------------------
class TestCard:
    def test_cliente_can_create_card_and_has_card_true(self, cliente):
        r = attach_test_card(BASE_URL, cliente["headers"])
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["brand"] == "visa"
        assert body["last4"] == "4242"

        r = requests.get(f"{BASE_URL}/api/me/card", headers=cliente["headers"])
        assert r.status_code == 200
        assert r.json()["has_card"] is True
        assert r.json()["last4"] == "4242"

    def test_profissional_forbidden_from_creating_card(self, profissional):
        r = attach_test_card(BASE_URL, profissional["headers"])
        assert r.status_code == 403, r.text


# ---------------------------------------------------------------------------
# Servicos (profissional only)
# ---------------------------------------------------------------------------
class TestServicos:
    def test_profissional_creates_servico(self, profissional, created_ids):
        payload = {"nome": "TEST_Corte", "descricao": "Corte de cabelo",
                   "valor_centavos": 10000, "taxa_no_show_centavos": 3000, "duracao_min": 60}
        r = requests.post(f"{BASE_URL}/api/servicos", json=payload, headers=profissional["headers"])
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["servico_id"].startswith("srv_")
        assert body["ativo"] is True
        assert body["profissional_id"] == profissional["user_id"]
        created_ids["servicos"].append(body["servico_id"])

    def test_taxa_greater_than_valor_returns_422(self, profissional):
        payload = {"nome": "TEST_Bad", "valor_centavos": 1000,
                   "taxa_no_show_centavos": 2000, "duracao_min": 30}
        r = requests.post(f"{BASE_URL}/api/servicos", json=payload, headers=profissional["headers"])
        assert r.status_code == 422, r.text

    def test_cliente_forbidden_from_creating_servico(self, cliente):
        payload = {"nome": "TEST_x", "valor_centavos": 100,
                   "taxa_no_show_centavos": 50, "duracao_min": 10}
        r = requests.post(f"{BASE_URL}/api/servicos", json=payload, headers=cliente["headers"])
        assert r.status_code == 403

    def test_list_only_own_servicos(self, profissional, profissional2, created_ids):
        # Create service for profissional2
        r = requests.post(f"{BASE_URL}/api/servicos", json={
            "nome": "TEST_Bob_Servico", "valor_centavos": 5000,
            "taxa_no_show_centavos": 1000, "duracao_min": 30,
        }, headers=profissional2["headers"])
        assert r.status_code == 200
        bob_svc = r.json()["servico_id"]
        created_ids["servicos"].append(bob_svc)

        r = requests.get(f"{BASE_URL}/api/servicos", headers=profissional["headers"])
        assert r.status_code == 200
        alice_list = r.json()
        alice_ids = {s["servico_id"] for s in alice_list}
        assert bob_svc not in alice_ids
        assert all(s["profissional_id"] == profissional["user_id"] for s in alice_list)

    def test_delete_soft_deletes_and_second_call_404(self, profissional, created_ids):
        r = requests.post(f"{BASE_URL}/api/servicos", json={
            "nome": "TEST_ToDelete", "valor_centavos": 1000,
            "taxa_no_show_centavos": 500, "duracao_min": 15,
        }, headers=profissional["headers"])
        sid = r.json()["servico_id"]
        created_ids["servicos"].append(sid)

        r = requests.delete(f"{BASE_URL}/api/servicos/{sid}", headers=profissional["headers"])
        assert r.status_code == 200

        r = requests.get(f"{BASE_URL}/api/servicos", headers=profissional["headers"])
        assert sid not in {s["servico_id"] for s in r.json()}

        r = requests.delete(f"{BASE_URL}/api/servicos/{sid}", headers=profissional["headers"])
        assert r.status_code == 404


# ---------------------------------------------------------------------------
# Profissionais discovery
# ---------------------------------------------------------------------------
class TestProfissionais:
    def test_list_only_profissionais_with_active_servicos(self, profissional, mongo_db, created_ids):
        # Profissional without services shouldn't show up
        empty = _make_user(mongo_db, role="profissional", name_prefix="TEST_Prof_Empty")
        created_ids["users"].append(empty["user_id"])
        created_ids["sessions"].append(empty["token"])

        r = requests.get(f"{BASE_URL}/api/profissionais")
        assert r.status_code == 200
        ids = {p["user_id"] for p in r.json()}
        assert profissional["user_id"] in ids
        assert empty["user_id"] not in ids

    def test_regex_case_insensitive_filter(self, profissional):
        # profissional name is TEST_Prof_Alice_xxxx
        r = requests.get(f"{BASE_URL}/api/profissionais", params={"q": "alice"})
        assert r.status_code == 200
        names = [p["name"].lower() for p in r.json()]
        assert any("alice" in n for n in names)

    def test_detalhe_profissional_lists_servicos(self, profissional):
        r = requests.get(f"{BASE_URL}/api/profissionais/{profissional['user_id']}")
        assert r.status_code == 200
        body = r.json()
        assert body["user_id"] == profissional["user_id"]
        assert isinstance(body["servicos"], list)
        assert all(s["ativo"] for s in body["servicos"])

    def test_detalhe_profissional_nonexistent_404(self):
        r = requests.get(f"{BASE_URL}/api/profissionais/user_nonexistent_xyz")
        assert r.status_code == 404


# ---------------------------------------------------------------------------
# Agendamentos
# ---------------------------------------------------------------------------
@pytest.fixture(scope="module")
def servico_ativo(profissional, created_ids):
    r = requests.post(f"{BASE_URL}/api/servicos", json={
        "nome": "TEST_ServicoBooking", "valor_centavos": 20000,
        "taxa_no_show_centavos": 5000, "duracao_min": 60,
    }, headers=profissional["headers"])
    assert r.status_code == 200
    sid = r.json()["servico_id"]
    created_ids["servicos"].append(sid)
    return {"servico_id": sid, "valor": 20000, "taxa": 5000, "duracao": 60}


class TestAgendamentoCreate:
    def test_422_when_no_card(self, mongo_db, servico_ativo, created_ids):
        # Fresh cliente without card
        u = _make_user(mongo_db, role="cliente", name_prefix="TEST_ClientNoCard")
        created_ids["users"].append(u["user_id"])
        created_ids["sessions"].append(u["token"])
        horario = (_now() + timedelta(days=2)).isoformat()
        r = requests.post(f"{BASE_URL}/api/agendamentos",
                          json={"servico_id": servico_ativo["servico_id"], "horario_inicio": horario},
                          headers=u["headers"])
        assert r.status_code == 422, r.text

    def test_422_when_horario_in_past(self, cliente, servico_ativo):
        past = (_now() - timedelta(hours=1)).isoformat()
        r = requests.post(f"{BASE_URL}/api/agendamentos",
                          json={"servico_id": servico_ativo["servico_id"], "horario_inicio": past},
                          headers=cliente["headers"])
        assert r.status_code == 422, r.text

    def test_404_when_servico_nonexistent(self, cliente):
        future = (_now() + timedelta(days=1)).isoformat()
        r = requests.post(f"{BASE_URL}/api/agendamentos",
                          json={"servico_id": "srv_does_not_exist", "horario_inicio": future},
                          headers=cliente["headers"])
        assert r.status_code == 404

    def test_success_creates_hold(self, cliente, servico_ativo, mongo_db, created_ids):
        horario = _now() + timedelta(days=3)
        horario_iso = horario.isoformat()
        r = requests.post(f"{BASE_URL}/api/agendamentos",
                          json={"servico_id": servico_ativo["servico_id"], "horario_inicio": horario_iso},
                          headers=cliente["headers"])
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["hold_status"] == "autorizado"
        assert body["status_confirmacao"] == "pendente"
        assert body["payment_intent_id"].startswith("pi_")
        assert not body["payment_intent_id"].startswith("pi_mock_")
        assert body["valor_total_centavos"] == servico_ativo["valor"]
        assert body["valor_no_show_centavos"] == servico_ativo["taxa"]

        # Verify janela = horario_fim + 24h
        fim = datetime.fromisoformat(body["horario_fim"].replace("Z", "+00:00"))
        janela = datetime.fromisoformat(body["janela_confirmacao_expira_em"].replace("Z", "+00:00"))
        delta = janela - fim
        assert abs(delta.total_seconds() - 24 * 3600) < 5

        # Verify transacao inserted
        tx = mongo_db.transacoes.find_one({"agendamento_id": body["agendamento_id"], "tipo": "authorization"})
        assert tx is not None
        assert tx["valor_centavos"] == servico_ativo["valor"]

        created_ids["agendamentos"].append(body["agendamento_id"])

    def test_listar_cliente_sees_only_own(self, cliente, profissional):
        r = requests.get(f"{BASE_URL}/api/agendamentos", headers=cliente["headers"])
        assert r.status_code == 200
        items = r.json()
        assert all(a["cliente_id"] == cliente["user_id"] for a in items)
        # ordered by horario_inicio asc
        starts = [a["horario_inicio"] for a in items]
        assert starts == sorted(starts)

    def test_listar_profissional_sees_only_own(self, profissional):
        r = requests.get(f"{BASE_URL}/api/agendamentos", headers=profissional["headers"])
        assert r.status_code == 200
        assert all(a["profissional_id"] == profissional["user_id"] for a in r.json())


@pytest.fixture(scope="module")
def _cliente_with_card(cliente):
    # ensure card exists
    attach_test_card(BASE_URL, cliente["headers"])
    return cliente


def _create_ag(cliente, servico_id, offset_days=3):
    horario = (_now() + timedelta(days=offset_days)).isoformat()
    r = requests.post(f"{BASE_URL}/api/agendamentos",
                      json={"servico_id": servico_id, "horario_inicio": horario},
                      headers=cliente["headers"])
    assert r.status_code == 200, r.text
    return r.json()


class TestConfirmar:
    def test_compareceu_captura_total(self, _cliente_with_card, profissional, servico_ativo, mongo_db, created_ids):
        ag = _create_ag(_cliente_with_card, servico_ativo["servico_id"], offset_days=4)
        created_ids["agendamentos"].append(ag["agendamento_id"])

        r = requests.post(f"{BASE_URL}/api/agendamentos/{ag['agendamento_id']}/confirmar",
                          json={"resultado": "compareceu"}, headers=profissional["headers"])
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["hold_status"] == "capturado_total"
        assert body["status_confirmacao"] == "compareceu"
        assert body["valor_capturado_centavos"] == servico_ativo["valor"]

        tx = mongo_db.transacoes.find_one({"agendamento_id": ag["agendamento_id"], "tipo": "capture"})
        assert tx is not None
        assert tx["valor_centavos"] == servico_ativo["valor"]

        # Second call → 409
        r = requests.post(f"{BASE_URL}/api/agendamentos/{ag['agendamento_id']}/confirmar",
                          json={"resultado": "compareceu"}, headers=profissional["headers"])
        assert r.status_code == 409

    def test_nao_compareceu_captura_taxa(self, _cliente_with_card, profissional, servico_ativo, mongo_db, created_ids):
        ag = _create_ag(_cliente_with_card, servico_ativo["servico_id"], offset_days=5)
        created_ids["agendamentos"].append(ag["agendamento_id"])

        r = requests.post(f"{BASE_URL}/api/agendamentos/{ag['agendamento_id']}/confirmar",
                          json={"resultado": "nao_compareceu"}, headers=profissional["headers"])
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["hold_status"] == "capturado_taxa"
        assert body["status_confirmacao"] == "nao_compareceu"
        assert body["valor_capturado_centavos"] == servico_ativo["taxa"]

        tx = mongo_db.transacoes.find_one({"agendamento_id": ag["agendamento_id"], "tipo": "partial_capture"})
        assert tx is not None
        assert tx["valor_centavos"] == servico_ativo["taxa"]

    def test_cliente_confirmar_403(self, _cliente_with_card, servico_ativo, created_ids):
        ag = _create_ag(_cliente_with_card, servico_ativo["servico_id"], offset_days=6)
        created_ids["agendamentos"].append(ag["agendamento_id"])
        r = requests.post(f"{BASE_URL}/api/agendamentos/{ag['agendamento_id']}/confirmar",
                          json={"resultado": "compareceu"}, headers=_cliente_with_card["headers"])
        assert r.status_code == 403

    def test_other_profissional_confirmar_403(self, _cliente_with_card, servico_ativo,
                                              profissional2, created_ids):
        ag = _create_ag(_cliente_with_card, servico_ativo["servico_id"], offset_days=7)
        created_ids["agendamentos"].append(ag["agendamento_id"])
        r = requests.post(f"{BASE_URL}/api/agendamentos/{ag['agendamento_id']}/confirmar",
                          json={"resultado": "compareceu"}, headers=profissional2["headers"])
        assert r.status_code == 403


class TestCancelar:
    def test_cancelar_hold_autorizado(self, _cliente_with_card, servico_ativo, mongo_db, created_ids):
        ag = _create_ag(_cliente_with_card, servico_ativo["servico_id"], offset_days=8)
        created_ids["agendamentos"].append(ag["agendamento_id"])
        r = requests.post(f"{BASE_URL}/api/agendamentos/{ag['agendamento_id']}/cancelar",
                          headers=_cliente_with_card["headers"])
        assert r.status_code == 200
        updated = mongo_db.agendamentos.find_one({"agendamento_id": ag["agendamento_id"]})
        assert updated["hold_status"] == "cancelado"

    def test_cancelar_hold_capturado_409(self, _cliente_with_card, profissional, servico_ativo, created_ids):
        ag = _create_ag(_cliente_with_card, servico_ativo["servico_id"], offset_days=9)
        created_ids["agendamentos"].append(ag["agendamento_id"])
        # Capture first
        r = requests.post(f"{BASE_URL}/api/agendamentos/{ag['agendamento_id']}/confirmar",
                          json={"resultado": "compareceu"}, headers=profissional["headers"])
        assert r.status_code == 200
        r = requests.post(f"{BASE_URL}/api/agendamentos/{ag['agendamento_id']}/cancelar",
                          headers=_cliente_with_card["headers"])
        assert r.status_code == 409


# ---------------------------------------------------------------------------
# Expirar janela job
# ---------------------------------------------------------------------------
class TestExpirarJanela:
    def test_job_marks_expired(self, _cliente_with_card, profissional, servico_ativo, mongo_db, created_ids):
        # Create an agendamento then force janela into the past via Mongo
        ag = _create_ag(_cliente_with_card, servico_ativo["servico_id"], offset_days=10)
        created_ids["agendamentos"].append(ag["agendamento_id"])
        past = _now() - timedelta(hours=1)
        mongo_db.agendamentos.update_one(
            {"agendamento_id": ag["agendamento_id"]},
            {"$set": {"janela_confirmacao_expira_em": past}},
        )

        headers = {"X-Internal-Token": os.environ["INTERNAL_SERVICE_TOKEN"]}
        r = requests.post(f"{BASE_URL}/api/internal/jobs/expirar-janela", headers=headers)
        assert r.status_code == 200
        body = r.json()
        assert "expirados" in body
        assert body["expirados"] >= 1

        updated = mongo_db.agendamentos.find_one({"agendamento_id": ag["agendamento_id"]})
        assert updated["hold_status"] == "expirado"
        assert updated["status_confirmacao"] == "sem_resposta"

        # Second call: this one should NOT be re-counted (already sem_resposta)
        r2 = requests.post(f"{BASE_URL}/api/internal/jobs/expirar-janela", headers=headers)
        assert r2.status_code == 200


# ---------------------------------------------------------------------------
# Mongo indexes required by spec
# ---------------------------------------------------------------------------
class TestIndexes:
    def test_servicos_servico_id_unique(self, mongo_db):
        idx = mongo_db.servicos.index_information()
        match = [v for v in idx.values() if v.get("key") == [("servico_id", 1)]]
        assert match and match[0].get("unique") is True

    def test_agendamentos_agendamento_id_unique(self, mongo_db):
        idx = mongo_db.agendamentos.index_information()
        match = [v for v in idx.values() if v.get("key") == [("agendamento_id", 1)]]
        assert match and match[0].get("unique") is True

    def test_customer_cards_user_id_unique(self, mongo_db):
        idx = mongo_db.customer_cards.index_information()
        match = [v for v in idx.values() if v.get("key") == [("user_id", 1)]]
        assert match and match[0].get("unique") is True
