"""Backend auth tests for ShowUp.
Covers: health, session with invalid id_token, /auth/me unauthenticated + bogus token,
/auth/role unauthenticated, /auth/logout idempotency, MongoDB indexes, CORS.
"""
import os
import pytest
import requests
from pymongo import MongoClient

BASE_URL = os.environ["EXPO_PUBLIC_BACKEND_URL"].rstrip("/")
MONGO_URL = os.environ.get("MONGO_URL", "mongodb://localhost:27017")
DB_NAME = os.environ.get("DB_NAME", "test_database")


@pytest.fixture(scope="module")
def api():
    s = requests.Session()
    s.headers.update({"Content-Type": "application/json"})
    return s


@pytest.fixture(scope="module")
def mongo_db():
    c = MongoClient(MONGO_URL)
    yield c[DB_NAME]
    c.close()


# ----- Health -----
def test_root_returns_service_status(api):
    r = api.get(f"{BASE_URL}/api/")
    assert r.status_code == 200
    body = r.json()
    assert body.get("service") == "ShowUp API"
    assert body.get("status") == "ok"


# ----- /auth/session -----
def test_auth_session_invalid_id_token_returns_401(api):
    r = api.post(f"{BASE_URL}/api/auth/session", json={"id_token": "TEST_bogus_id_token_xyz"})
    assert r.status_code == 401, r.text
    assert "Token do Google inválido" in r.json().get("detail", "")


def test_auth_session_missing_body_returns_422(api):
    r = api.post(f"{BASE_URL}/api/auth/session", json={})
    assert r.status_code == 422


# ----- /auth/me -----
def test_auth_me_without_header_returns_401(api):
    # Explicitly strip default Content-Type-only session headers; only care about Authorization absence.
    r = requests.get(f"{BASE_URL}/api/auth/me")
    assert r.status_code == 401, f"Expected 401, got {r.status_code}: {r.text}"
    assert "bearer" in r.json().get("detail", "").lower() or r.json().get("detail")


def test_auth_me_with_bogus_bearer_returns_401(api):
    r = requests.get(
        f"{BASE_URL}/api/auth/me",
        headers={"Authorization": "Bearer TEST_bogus_token_xyz"},
    )
    assert r.status_code == 401
    assert r.json().get("detail") == "Invalid session"


def test_auth_me_with_malformed_header_returns_401(api):
    r = requests.get(f"{BASE_URL}/api/auth/me", headers={"Authorization": "NotBearer xxx"})
    assert r.status_code == 401


# ----- /auth/role -----
def test_auth_role_without_header_returns_401(api):
    r = requests.post(f"{BASE_URL}/api/auth/role", json={"role": "cliente"})
    assert r.status_code == 401


# ----- /auth/logout idempotency -----
def test_auth_logout_no_header_returns_ok(api):
    r = requests.post(f"{BASE_URL}/api/auth/logout")
    assert r.status_code == 200
    assert r.json() == {"ok": True}


def test_auth_logout_bogus_token_returns_ok(api):
    r = requests.post(
        f"{BASE_URL}/api/auth/logout",
        headers={"Authorization": "Bearer TEST_bogus_token_xyz"},
    )
    assert r.status_code == 200
    assert r.json() == {"ok": True}


# ----- CORS -----
def test_cors_allows_configured_origin(api):
    """Desde o Módulo 3, CORS usa uma allowlist explícita (ALLOWED_ORIGINS)
    em vez de aceitar qualquer origem — esse teste validava exatamente o
    comportamento antigo e inseguro que corrigimos, por isso testava o
    origin errado de propósito. Agora testa que uma origem CADASTRADA é
    aceita."""
    allowed_origin = os.environ.get("ALLOWED_ORIGINS", "").split(",")[0].strip()
    if not allowed_origin:
        pytest.skip("ALLOWED_ORIGINS não configurado no ambiente de teste")
    r = requests.options(
        f"{BASE_URL}/api/",
        headers={
            "Origin": allowed_origin,
            "Access-Control-Request-Method": "GET",
        },
    )
    assert r.status_code in (200, 204), r.status_code
    aco = r.headers.get("access-control-allow-origin", "")
    assert aco == allowed_origin, f"Origem cadastrada deveria ser aceita, veio: {aco!r}"


def test_cors_blocks_unlisted_origin(api):
    """O reverso do teste acima: uma origem QUALQUER, fora da allowlist,
    não deve receber o header de CORS liberado — é exatamente a proteção
    que o Módulo 3 adicionou."""
    r = requests.options(
        f"{BASE_URL}/api/",
        headers={
            "Origin": "https://site-nao-cadastrado-exemplo.com",
            "Access-Control-Request-Method": "GET",
        },
    )
    aco = r.headers.get("access-control-allow-origin", "")
    assert aco != "https://site-nao-cadastrado-exemplo.com", "CORS não deveria aceitar origem fora da allowlist"


# ----- MongoDB indexes -----
def test_users_email_unique_index(mongo_db):
    idx = mongo_db.users.index_information()
    match = [v for v in idx.values() if v.get("key") == [("email", 1)]]
    assert match, f"No email index found: {idx}"
    assert match[0].get("unique") is True


def test_users_user_id_unique_index(mongo_db):
    idx = mongo_db.users.index_information()
    match = [v for v in idx.values() if v.get("key") == [("user_id", 1)]]
    assert match, f"No user_id index found: {idx}"
    assert match[0].get("unique") is True


def test_user_sessions_session_token_unique_index(mongo_db):
    idx = mongo_db.user_sessions.index_information()
    match = [v for v in idx.values() if v.get("key") == [("session_token", 1)]]
    assert match, f"No session_token index found: {idx}"
    assert match[0].get("unique") is True


def test_user_sessions_expires_at_ttl_index(mongo_db):
    idx = mongo_db.user_sessions.index_information()
    match = [v for v in idx.values() if v.get("key") == [("expires_at", 1)]]
    assert match, f"No expires_at index found: {idx}"
    assert match[0].get("expireAfterSeconds") == 0
