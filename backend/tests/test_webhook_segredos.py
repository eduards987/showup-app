"""O webhook aceita eventos assinados com o segredo da plataforma OU com o do endpoint de
Connect — e recusa qualquer outra assinatura. Assinaturas reais (HMAC), sem rede."""
import hashlib
import hmac
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import offline_env  # noqa: E402,F401  (variáveis FALSAS, antes de importar o server)

import pytest
from fastapi.testclient import TestClient

import server
import webhooks

PLATAFORMA, CONNECT = "whsec_plataforma", "whsec_connect"


class _Col:
    def __init__(self, docs=None):
        self.docs = docs if docs is not None else []

    async def find_one(self, q, proj=None):
        return next((dict(d) for d in self.docs if all(d.get(k) == v for k, v in q.items())), None)

    async def insert_one(self, doc):
        self.docs.append(dict(doc))

    async def update_one(self, q, upd):
        for d in self.docs:
            if all(d.get(k) == v for k, v in q.items()):
                d.update(upd.get("$set", {}))
                for k in upd.get("$unset", {}):
                    d.pop(k, None)
                return

    async def find_one_and_update(self, q, upd):
        for d in self.docs:
            if all((d.get(k) != v["$ne"]) if isinstance(v, dict) else d.get(k) == v for k, v in q.items()):
                antes = dict(d)
                d.update(upd.get("$set", {}))
                return antes
        return None


class _DB:
    def __init__(self):
        self.webhook_events = _Col()
        self.users = _Col([{"user_id": "u1", "stripe_account_id": "acct_1", "connect_ready": False}])


def _assinar(corpo: bytes, segredo: str) -> str:
    t = int(time.time())
    v1 = hmac.new(segredo.encode(), f"{t}.".encode() + corpo, hashlib.sha256).hexdigest()
    return f"t={t},v1={v1}"


def _evento(evento_id="evt_1"):
    return json.dumps({
        "id": evento_id, "object": "event", "type": "account.updated",
        "data": {"object": {"id": "acct_1", "charges_enabled": True, "payouts_enabled": True}},
    }).encode()


@pytest.fixture
def cliente(monkeypatch):
    db = _DB()
    monkeypatch.setattr(webhooks, "_get_db", lambda: db)
    monkeypatch.setattr(webhooks, "_WEBHOOK_SECRET", PLATAFORMA)
    monkeypatch.setattr(webhooks, "_CONNECT_WEBHOOK_SECRET", CONNECT)
    return TestClient(server.app), db


def _enviar(client, corpo, assinatura):
    return client.post("/api/webhooks/stripe", content=corpo, headers={"stripe-signature": assinatura})


def test_aceita_assinatura_do_endpoint_da_plataforma(cliente):
    client, db = cliente
    corpo = _evento()
    assert _enviar(client, corpo, _assinar(corpo, PLATAFORMA)).status_code == 200
    assert db.users.docs[0]["connect_ready"] is True


def test_aceita_assinatura_do_endpoint_de_connect(cliente):
    client, db = cliente
    corpo = _evento("evt_2")
    assert _enviar(client, corpo, _assinar(corpo, CONNECT)).status_code == 200
    assert db.users.docs[0]["connect_ready"] is True


def test_recusa_assinatura_de_um_terceiro(cliente):
    client, db = cliente
    corpo = _evento("evt_3")
    assert _enviar(client, corpo, _assinar(corpo, "whsec_falsificado")).status_code == 400
    assert db.users.docs[0]["connect_ready"] is False and db.webhook_events.docs == []


def test_sem_segredo_de_connect_a_assinatura_dele_e_recusada(cliente, monkeypatch):
    client, db = cliente
    monkeypatch.setattr(webhooks, "_CONNECT_WEBHOOK_SECRET", "")
    corpo = _evento("evt_4")
    assert _enviar(client, corpo, _assinar(corpo, CONNECT)).status_code == 400
    assert _enviar(client, corpo, _assinar(corpo, PLATAFORMA)).status_code == 200   # o da plataforma segue valendo


def test_sem_nenhum_segredo_configurado_recusa_tudo(cliente, monkeypatch):
    client, db = cliente
    monkeypatch.setattr(webhooks, "_WEBHOOK_SECRET", "")
    monkeypatch.setattr(webhooks, "_CONNECT_WEBHOOK_SECRET", "")
    corpo = _evento("evt_5")
    assert _enviar(client, corpo, _assinar(corpo, PLATAFORMA)).status_code == 500


def test_payload_que_nao_e_json_e_recusado(cliente):
    client, db = cliente
    corpo = b"isso nao e json"
    assert _enviar(client, corpo, _assinar(corpo, PLATAFORMA)).status_code == 400


def test_mesmo_evento_reenviado_e_processado_uma_vez_so(cliente):
    client, db = cliente
    corpo = _evento("evt_6")
    assert _enviar(client, corpo, _assinar(corpo, CONNECT)).status_code == 200
    assert _enviar(client, corpo, _assinar(corpo, CONNECT)).status_code == 200
    assert [e["event_id"] for e in db.webhook_events.docs] == ["evt_6"]


def test_eventos_chegam_como_objeto_do_stripe_e_nao_como_dict(cliente, monkeypatch):
    """O bug que este arquivo pegou: o objeto do evento não é dict, e `.get()` nele levanta
    AttributeError. Aqui o evento passa pelo caminho REAL (assinatura -> construct_event)."""
    client, db = cliente
    db.users.docs.append({"user_id": "u2", "stripe_subscription_id": "sub_9", "plano": "profissional"})
    enviados = []

    async def push(db_, user_id, title, body, data):
        enviados.append((user_id, data["tipo"]))

    monkeypatch.setattr(webhooks, "push_para_usuario", push)
    corpo = json.dumps({
        "id": "evt_sub", "object": "event", "type": "customer.subscription.updated",
        "data": {"object": {"id": "sub_9", "status": "past_due"}},
    }).encode()
    assert _enviar(client, corpo, _assinar(corpo, PLATAFORMA)).status_code == 200
    assert db.users.docs[1]["plano_cobranca_pendente"] is True and enviados == [("u2", "cobranca_plano_falhou")]

    corpo = json.dumps({
        "id": "evt_fim", "object": "event", "type": "customer.subscription.trial_will_end",
        "data": {"object": {"id": "sub_9"}},
    }).encode()
    assert _enviar(client, corpo, _assinar(corpo, PLATAFORMA)).status_code == 200
    assert enviados[-1] == ("u2", "trial_will_end")
