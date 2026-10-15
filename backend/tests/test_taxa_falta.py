"""Taxa da plataforma na FALTA do cliente: tem que incidir sobre o valor
realmente cobrado, não sobre o valor total do serviço.

Contexto: o `application_fee_amount` é fixado no authorize sobre o valor TOTAL
(R$ 120 a 10% = R$ 12). Numa falta só a taxa de no-show é capturada (R$ 30), e o
Stripe só ajusta a taxa se ela for informada na captura. Sem isso a plataforma
ficaria com R$ 12 dos R$ 30 (40%) em vez de R$ 3 (10%).

Offline: Stripe e banco falsos (objetos reais da lib no gateway)."""
import asyncio
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

os.environ.setdefault("TESTING", "1")
os.environ.setdefault("GOOGLE_WEB_CLIENT_ID", "teste.apps.googleusercontent.com")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import offline_env  # noqa: E402,F401  (variáveis FALSAS, antes de importar o server)

import pytest
import stripe
from fastapi.testclient import TestClient

import server
from payment_errors import PaymentError
from stripe_gateway import StripeGateway


# ============================================================ gateway (Stripe falso)
def _gw():
    return StripeGateway.__new__(StripeGateway)


def _pi(amount=12000, fee=1200):
    return stripe.PaymentIntent.construct_from(
        {"id": "pi_1", "amount": amount, "application_fee_amount": fee}, "sk_test")


class FakeStripe:
    def __init__(self, monkeypatch, pi):
        self.retrieves = 0
        self.capturas = []

        def retrieve(pid):
            self.retrieves += 1
            if isinstance(pi, Exception):
                raise pi
            return pi

        def capture(pid, **kw):
            self.capturas.append(kw)
            return stripe.PaymentIntent.construct_from(
                {"id": pid, "status": "succeeded", "amount_received": kw.get("amount_to_capture", 0),
                 "amount_capturable": 0}, "sk_test")

        monkeypatch.setattr(stripe.PaymentIntent, "retrieve", staticmethod(retrieve))
        monkeypatch.setattr(stripe.PaymentIntent, "capture", staticmethod(capture))


def _capturar(monkeypatch, pi, valor, fee_bps=None):
    fake = FakeStripe(monkeypatch, pi)
    asyncio.run(_gw().capture("pi_1", valor, "idem_1", fee_bps=fee_bps))
    return fake


def test_falta_cobra_taxa_proporcional_com_o_percentual_gravado_na_reserva(monkeypatch):
    fake = _capturar(monkeypatch, _pi(12000, 1200), 3000, fee_bps=1000)
    assert fake.capturas == [{"amount_to_capture": 3000, "application_fee_amount": 300, "idempotency_key": "idem_1"}]


def test_usa_o_percentual_da_epoca_da_reserva_e_nao_o_do_plano_de_hoje(monkeypatch):
    # reserva feita no Profissional (5%): PI com taxa 600 sobre 12000
    fake = _capturar(monkeypatch, _pi(12000, 600), 3000, fee_bps=500)
    assert fake.capturas[0]["application_fee_amount"] == 150


def test_reserva_antiga_sem_percentual_gravado_usa_a_proporcao_da_taxa_ja_fixada(monkeypatch):
    fake = _capturar(monkeypatch, _pi(12000, 1200), 3000, fee_bps=None)
    assert fake.capturas[0]["application_fee_amount"] == 300
    # arredonda pra baixo, como a taxa original
    fake = _capturar(monkeypatch, _pi(9990, 999), 2997, fee_bps=None)
    assert fake.capturas[0]["application_fee_amount"] == 999 * 2997 // 9990


def test_cobranca_sem_repasse_nao_manda_taxa(monkeypatch):
    # sem Connect não existe application_fee_amount — mandar o parâmetro daria erro no Stripe
    pi = stripe.PaymentIntent.construct_from({"id": "pi_1", "amount": 12000, "application_fee_amount": None}, "sk_test")
    fake = _capturar(monkeypatch, pi, 3000, fee_bps=1000)
    assert "application_fee_amount" not in fake.capturas[0]


def test_captura_total_nao_mexe_na_taxa_nem_consulta_o_stripe(monkeypatch):
    fake = _capturar(monkeypatch, _pi(), None)
    assert fake.retrieves == 0
    assert "application_fee_amount" not in fake.capturas[0] and "amount_to_capture" not in fake.capturas[0]


def test_captura_do_valor_inteiro_mantem_a_taxa_do_authorize(monkeypatch):
    fake = _capturar(monkeypatch, _pi(12000, 1200), 12000, fee_bps=1000)
    assert "application_fee_amount" not in fake.capturas[0]


def test_falha_ao_ler_o_payment_intent_nao_captura(monkeypatch):
    fake = FakeStripe(monkeypatch, stripe.APIConnectionError("rede caiu"))
    with pytest.raises(PaymentError):
        asyncio.run(_gw().capture("pi_1", 3000, "idem_1", fee_bps=1000))
    assert fake.capturas == []


# ============================================================ rota /confirmar
def _match(doc, q):
    return all(doc.get(k) == v for k, v in q.items())


class _Col:
    def __init__(self, docs=None):
        self.docs = docs if docs is not None else []

    async def find_one(self, q, proj=None):
        return next((dict(d) for d in self.docs if _match(d, q)), None)

    async def find_one_and_update(self, q, upd):
        for d in self.docs:
            if _match(d, q):
                antes = dict(d)
                d.update(upd.get("$set", {}))
                return antes
        return None

    async def update_one(self, q, upd):
        for d in self.docs:
            if _match(d, q):
                d.update(upd.get("$set", {}))
                return

    async def insert_one(self, doc):
        self.docs.append(dict(doc))


class _DB:
    def __init__(self, ag):
        self.agendamentos = _Col([ag])
        self.users = _Col([
            {"user_id": "prof", "name": "Eduardo", "role": "profissional"},
            {"user_id": "cli", "name": "Maria", "role": "cliente"},
        ])
        self.servicos = _Col([{"servico_id": "svc_1", "nome": "Personal Trainer"}])
        self.transacoes = _Col()


class _GW:
    def __init__(self):
        self.capturas = []

    async def capture(self, pi_id, amount_to_capture=None, idempotency_key="", fee_bps=None):
        self.capturas.append({"amount_to_capture": amount_to_capture, "fee_bps": fee_bps})
        return {"payment_intent_id": pi_id, "status": "succeeded",
                "amount_received": amount_to_capture if amount_to_capture is not None else 12000,
                "amount_capturable": 0}


def _reserva(**extra):
    agora = datetime.now(timezone.utc)
    doc = {
        "agendamento_id": "agd_1", "profissional_id": "prof", "cliente_id": "cli", "servico_id": "svc_1",
        "horario_inicio": agora - timedelta(hours=2), "horario_fim": agora - timedelta(hours=1),
        "hold_expira_em": agora + timedelta(days=5), "janela_confirmacao_expira_em": agora + timedelta(hours=23),
        "criado_em": agora - timedelta(days=1), "status_agendamento": "agendado",
        "status_confirmacao": "pendente", "hold_status": "autorizado", "payment_intent_id": "pi_1",
        "valor_total_centavos": 12000, "valor_no_show_centavos": 3000, "moeda": "BRL",
        "valor_capturado_centavos": 0,
    }
    doc.update(extra)
    return doc


@pytest.fixture
def confirmar(monkeypatch):
    def montar(**extra):
        db, gw = _DB(_reserva(**extra)), _GW()

        async def fake_user(auth):
            return await db.users.find_one({"user_id": "prof"})

        monkeypatch.setattr(server, "db", db)
        monkeypatch.setattr(server, "gateway", gw)
        monkeypatch.setattr(server, "_current_user", fake_user)
        return TestClient(server.app), db, gw
    return montar


def test_rota_falta_manda_o_percentual_gravado_na_reserva(confirmar):
    client, db, gw = confirmar(fee_bps=500)
    r = client.post("/api/agendamentos/agd_1/confirmar", json={"resultado": "nao_compareceu"})
    assert r.status_code == 200
    assert gw.capturas == [{"amount_to_capture": 3000, "fee_bps": 500}]
    assert db.agendamentos.docs[0]["hold_status"] == "capturado_taxa"
    assert db.agendamentos.docs[0]["valor_capturado_centavos"] == 3000


def test_rota_falta_em_reserva_antiga_sem_percentual(confirmar):
    client, db, gw = confirmar()   # sem fee_bps no documento
    assert client.post("/api/agendamentos/agd_1/confirmar", json={"resultado": "nao_compareceu"}).status_code == 200
    assert gw.capturas == [{"amount_to_capture": 3000, "fee_bps": None}]


def test_rota_compareceu_continua_capturando_o_valor_inteiro_sem_mexer_na_taxa(confirmar):
    client, db, gw = confirmar(fee_bps=1000)
    assert client.post("/api/agendamentos/agd_1/confirmar", json={"resultado": "compareceu"}).status_code == 200
    assert gw.capturas == [{"amount_to_capture": None, "fee_bps": None}]
    assert db.agendamentos.docs[0]["hold_status"] == "capturado_total"
