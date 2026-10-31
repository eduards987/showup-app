"""Mercado Pago como segunda forma de o profissional receber (só Brasil): dinheiro exato, assinatura dos avisos, tokens
cifrados, agenda de 5 dias, taxa menor, cartão (reserva -> captura total ou só a taxa de falta), Pix e conexão por OAuth.
Tudo offline: banco, Mercado Pago e push falsos. Hoje nos testes: quarta-feira 21/10/2026, 10:00 em São Paulo."""
import asyncio
import hashlib
import hmac
import json
import sys
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import offline_env  # noqa: E402,F401

import httpx
import pytest
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient

import cofre
import mercadopago_gateway as mpg
import server
from payment_errors import CardDeclinedError, GatewayUnavailableError, InvalidPaymentRequestError

SP = ZoneInfo("America/Sao_Paulo")
AGORA = datetime(2026, 10, 21, 10, 0, tzinfo=SP).astimezone(timezone.utc)
CHAVE = Fernet.generate_key().decode()
SEGREDO_WEBHOOK = "segredo-de-teste-do-webhook"


def loc(dia, hora, minuto=0, mes=10):
    return datetime(2026, mes, dia, hora, minuto, tzinfo=SP).astimezone(timezone.utc)


def rodar(c):
    return asyncio.run(c)


# ======================================================================== 1. dinheiro: centavos <-> reais sem erro
def test_conversao_de_centavos_para_o_json_do_mercado_pago_e_exata():
    for c in list(range(0, 20_000)) + [99_999, 123_456_789, 10**9 + 7]:
        texto = json.dumps({"v": mpg.reais(c)})
        valor = Decimal(json.loads(texto, parse_float=Decimal)["v"])
        assert valor * 100 == c, (c, texto)                 # o número no JSON é exatamente c/100
        assert mpg.centavos(mpg.reais(c)) == c


def test_valor_que_volta_do_mercado_pago_vira_centavos_sem_float():
    assert mpg.centavos(0.1 + 0.2) == 30                    # 0.30000000000000004 -> 30, não 30.000...04
    assert mpg.centavos("123.45") == 12345 and mpg.centavos(120) == 12000
    assert mpg.centavos(0.29) == 29 and mpg.centavos(1.15) == 115      # float * 100 daria 28 e 114
    with pytest.raises(TypeError):
        mpg.reais(12.5)                                     # valor só entra em centavos inteiros


def test_taxa_arredonda_para_baixo_como_no_stripe():
    assert mpg.taxa_centavos(12000, 700) == 840
    assert mpg.taxa_centavos(3333, 700) == 233              # 233,31 -> 233 (a favor do profissional)


# ======================================================================== 2. assinatura dos avisos
def assinar(data_id, request_id="req-1", ts="1761051600", segredo=SEGREDO_WEBHOOK):
    manifesto = f"id:{str(data_id).lower()};request-id:{request_id};ts:{ts};"
    return f"ts={ts},v1={hmac.new(segredo.encode(), manifesto.encode(), hashlib.sha256).hexdigest()}"


def test_assinatura_correta_e_aceita_e_qualquer_mudanca_e_recusada():
    ok = assinar("123456")
    assert mpg.assinatura_valida(ok, "req-1", "123456", SEGREDO_WEBHOOK)
    assert not mpg.assinatura_valida(ok, "req-1", "123457", SEGREDO_WEBHOOK)        # outro pagamento
    assert not mpg.assinatura_valida(ok, "req-2", "123456", SEGREDO_WEBHOOK)        # outro request-id
    assert not mpg.assinatura_valida(ok, "req-1", "123456", "outro-segredo")
    assert not mpg.assinatura_valida("ts=1,v1=abc", "req-1", "123456", SEGREDO_WEBHOOK)
    assert not mpg.assinatura_valida("", "req-1", "123456", SEGREDO_WEBHOOK)
    assert not mpg.assinatura_valida(ok, "req-1", "123456", "")                     # sem segredo, nada passa


def test_assinatura_usa_o_id_em_minusculas_e_recusa_aviso_velho():
    assinatura = assinar("ABC123")
    assert mpg.assinatura_valida(assinatura, "req-1", "ABC123", SEGREDO_WEBHOOK)
    ts = 1_761_051_600
    assert mpg.assinatura_valida(assinatura, "req-1", "ABC123", SEGREDO_WEBHOOK, agora_s=ts + 60)
    assert not mpg.assinatura_valida(assinatura, "req-1", "ABC123", SEGREDO_WEBHOOK, agora_s=ts + 3600)   # reenvio de aviso antigo
    em_ms = assinar("ABC123", ts=str(ts * 1000))
    assert mpg.assinatura_valida(em_ms, "req-1", "ABC123", SEGREDO_WEBHOOK, agora_s=ts + 60)


# ======================================================================== 3. tokens cifrados
def test_cofre_cifra_e_so_a_mesma_chave_decifra():
    cifrado = cofre.cifrar("APP_USR-segredo", CHAVE)
    assert "APP_USR" not in cifrado and cofre.decifrar(cifrado, CHAVE) == "APP_USR-segredo"
    with pytest.raises(cofre.CofreIndisponivel):
        cofre.decifrar(cifrado, Fernet.generate_key().decode())
    assert not cofre.cofre_configurado("") and not cofre.cofre_configurado("curta-demais")
    assert cofre.cofre_configurado(CHAVE)


# ======================================================================== 4. chamadas HTTP do gateway (transporte falso)
class Transporte:
    def __init__(self, resposta=None, status=200):
        self.pedidos, self.resposta, self.status = [], resposta or {}, status

    def __call__(self):
        def tratar(req: httpx.Request):
            self.pedidos.append(req)
            corpo = self.resposta(req) if callable(self.resposta) else self.resposta
            return httpx.Response(self.status, json=corpo)
        return httpx.AsyncClient(base_url=mpg.API, transport=httpx.MockTransport(tratar))


def gw_http(transporte):
    return mpg.MercadoPagoGateway("cid", "csecret", "https://api.x/api/mercadopago/callback", "https://api.x/api/webhooks/mercadopago", http=transporte)


def corpo(req):
    return json.loads(req.content.decode(), parse_float=Decimal)


def reservar(g, **extra):
    kw = dict(valor_centavos=12000, taxa_centavos_=840, token_cartao="tok_cartao", payment_method_id="visa", issuer_id="25",
              email="m@x.com", identificacao={"type": "CPF", "number": "12345678909"}, descricao="ShowUp: Corrida",
              referencia="agd_1", idempotency_key="hold_agd_1")
    kw.update(extra)
    return rodar(g.reservar_cartao("TOKEN_DO_PROF", **kw))


def test_reserva_manda_valor_e_taxa_em_reais_sem_capturar_com_o_token_do_profissional():
    t = Transporte({"id": 987, "status": "authorized", "status_detail": "pending_capture"})
    r = reservar(gw_http(t))
    req = t.pedidos[0]
    b = corpo(req)
    assert req.url.path == "/v1/payments" and req.method == "POST"
    assert req.headers["Authorization"] == "Bearer TOKEN_DO_PROF" and req.headers["X-Idempotency-Key"] == "hold_agd_1"
    assert b["transaction_amount"] == Decimal("120") and b["application_fee"] == Decimal("8.4")
    assert b["capture"] is False and b["installments"] == 1 and b["binary_mode"] is True
    assert b["external_reference"] == "agd_1" and b["notification_url"].endswith("/api/webhooks/mercadopago")
    assert b["payer"]["identification"] == {"type": "CPF", "number": "12345678909"}
    assert r["payment_intent_id"] == "987" and r["hold_expira_em"] - mpg._agora() > timedelta(days=4, hours=23)


def test_cartao_recusado_vira_erro_de_cartao():
    with pytest.raises(CardDeclinedError):
        reservar(gw_http(Transporte({"id": 1, "status": "rejected", "status_detail": "cc_rejected_insufficient_amount"})))


def test_cobranca_capturada_sem_querer_e_devolvida_e_a_reserva_falha():
    """Se o Mercado Pago aprovar direto (sem reserva), o dinheiro não pode ficar cobrado sem agendamento."""
    t = Transporte(lambda req: {"id": 5, "status": "approved"} if req.url.path == "/v1/payments" else {"id": 1})
    with pytest.raises(InvalidPaymentRequestError):
        reservar(gw_http(t))
    assert [p.url.path for p in t.pedidos] == ["/v1/payments", "/v1/payments/5/refunds"]


def test_captura_parcial_manda_valor_e_taxa_proporcional_e_le_a_taxa_gravada():
    t = Transporte({"id": 987, "status": "approved", "transaction_amount": 30, "fee_details": [{"type": "application_fee", "amount": 2.1}]})
    cap = rodar(gw_http(t).capturar("TOKEN_DO_PROF", "987", 3000, 210, idempotency_key="capture_agd_1_noshow"))
    b = corpo(t.pedidos[0])
    assert t.pedidos[0].method == "PUT" and t.pedidos[0].url.path == "/v1/payments/987"
    assert b == {"capture": True, "transaction_amount": Decimal("30"), "application_fee": Decimal("2.1")}
    assert cap["amount_received"] == 3000 and cap["taxa_gravada_centavos"] == 210


def test_captura_total_nao_mexe_no_valor():
    t = Transporte({"id": 987, "status": "approved", "transaction_amount": 120})
    cap = rodar(gw_http(t).capturar("T", "987", None, None, idempotency_key="k"))
    assert corpo(t.pedidos[0]) == {"capture": True} and cap["amount_received"] == 12000


@pytest.mark.parametrize("status, erro", [(500, GatewayUnavailableError), (429, GatewayUnavailableError), (400, InvalidPaymentRequestError)])
def test_erros_http_viram_erros_de_pagamento(status, erro):
    with pytest.raises(erro):
        reservar(gw_http(Transporte({"message": "x"}, status=status)))


def test_pix_tem_validade_e_devolve_o_copia_e_cola():
    t = Transporte({"id": 55, "status": "pending", "point_of_interaction": {"transaction_data": {
        "qr_code": "00020126...", "qr_code_base64": "iVBOR...", "ticket_url": "https://mp/ticket"}}})
    expira = datetime(2026, 10, 21, 13, 30, tzinfo=timezone.utc)
    pix = rodar(gw_http(t).criar_pix("T", valor_centavos=12000, taxa_centavos_=840, email="m@x.com", descricao="ShowUp",
                                     expira_em=expira, referencia="agd_1", idempotency_key="pix_agd_1"))
    b = corpo(t.pedidos[0])
    assert b["payment_method_id"] == "pix" and b["date_of_expiration"] == "2026-10-21T13:30:00.000+00:00"
    assert b["application_fee"] == Decimal("8.4") and t.pedidos[0].headers["X-Idempotency-Key"] == "pix_agd_1"
    assert pix == {"payment_intent_id": "55", "qr_code_data": "00020126...", "qr_code_base64": "iVBOR...",
                   "hosted_instructions_url": "https://mp/ticket"}


def test_oauth_link_tem_o_state_e_o_retorno_cadastrado():
    url = gw_http(Transporte()).url_autorizacao("abc")
    assert url.startswith("https://auth.mercadopago.com/authorization?")
    assert "state=abc" in url and "platform_id=mp" in url and "redirect_uri=https%3A%2F%2Fapi.x%2Fapi%2Fmercadopago%2Fcallback" in url


# ======================================================================== 5. servidor: banco e Mercado Pago falsos
def _casa(doc, q):
    for k, cond in q.items():
        v = doc.get(k)
        if isinstance(cond, dict) and any(op.startswith("$") for op in cond):
            for op, arg in cond.items():
                ok = {
                    "$in": lambda: v in arg, "$nin": lambda: v not in arg, "$ne": lambda: v != arg,
                    "$gt": lambda: v is not None and v > arg, "$gte": lambda: v is not None and v >= arg,
                    "$lt": lambda: v is not None and v < arg, "$lte": lambda: v is not None and v <= arg,
                    "$exists": lambda: (k in doc) == arg,
                }[op]()
                if not ok:
                    return False
        elif v != cond:
            return False
    return True


class _R:
    def __init__(self, n):
        self.modified_count = n


class Cursor:
    def __init__(self, docs):
        self.docs = docs

    def __aiter__(self):
        self._it = iter(self.docs)
        return self

    async def __anext__(self):
        try:
            return dict(next(self._it))
        except StopIteration:
            raise StopAsyncIteration

    async def to_list(self, n):
        return [dict(d) for d in self.docs[:n]]


class Col:
    def __init__(self):
        self.docs = []

    @staticmethod
    def _aplicar(d, upd):
        d.update(upd.get("$set", {}))
        for k in upd.get("$unset", {}):
            d.pop(k, None)

    async def find_one(self, q, proj=None):
        return next((dict(d) for d in self.docs if _casa(d, q)), None)

    def find(self, q, proj=None):
        return Cursor([d for d in self.docs if _casa(d, q)])

    async def insert_one(self, doc):
        self.docs.append(dict(doc))

    async def update_one(self, q, upd):
        for d in self.docs:
            if _casa(d, q):
                self._aplicar(d, upd)
                return _R(1)
        return _R(0)

    async def update_many(self, q, upd):
        n = 0
        for d in self.docs:
            if _casa(d, q):
                self._aplicar(d, upd)
                n += 1
        return _R(n)

    async def find_one_and_update(self, q, upd):
        for d in self.docs:
            if _casa(d, q):
                antes = dict(d)
                self._aplicar(d, upd)
                return antes
        return None

    async def find_one_and_delete(self, q):
        for i, d in enumerate(self.docs):
            if _casa(d, q):
                return self.docs.pop(i)
        return None


class DB:
    def __init__(self):
        for nome in ("users", "servicos", "agendamentos", "transacoes", "device_tokens", "customer_cards", "disponibilidade", "mp_oauth_states"):
            setattr(self, nome, Col())


class MPFalso:
    """Faz o papel do Mercado Pago: guarda cada chamada e responde o que o teste mandar."""

    def __init__(self):
        self.chamadas, self.pagamentos, self.taxa_gravada = [], {}, None
        self.status_reserva = "authorized"
        self.tokens = {"access_token": "APP_USR-novo", "refresh_token": "TG-novo", "public_key": "APP_USR-pub-novo",
                       "user_id": "777", "expira_em": AGORA + timedelta(days=180)}

    def url_autorizacao(self, state):
        return f"https://auth.mercadopago.com/authorization?state={state}"

    async def trocar_codigo(self, code):
        self.chamadas.append(("trocar_codigo", code))
        return dict(self.tokens)

    async def renovar(self, refresh):
        self.chamadas.append(("renovar", refresh))
        return dict(self.tokens)

    async def reservar_cartao(self, access_token, **kw):
        self.chamadas.append(("reservar", access_token, kw))
        if self.status_reserva == "rejected":
            raise CardDeclinedError("cc_rejected")
        self.pagamentos["mp_1"] = {"status": "authorized", "referencia": kw["referencia"]}
        return {"payment_intent_id": "mp_1", "status": "requires_capture", "hold_expira_em": AGORA + timedelta(days=5)}

    async def capturar(self, token, pid, valor, taxa, idempotency_key):
        self.chamadas.append(("capturar", token, pid, valor, taxa, idempotency_key))
        return {"payment_intent_id": pid, "status": "succeeded", "amount_received": valor if valor is not None else 12000,
                "taxa_gravada_centavos": self.taxa_gravada}

    async def cancelar(self, token, pid, idempotency_key, estornar=False):
        self.chamadas.append(("cancelar", token, pid, idempotency_key))
        return {"payment_intent_id": pid, "status": "cancelled"}

    async def criar_pix(self, token, **kw):
        self.chamadas.append(("pix", token, kw))
        self.pagamentos["mp_pix"] = {"status": "pending", "referencia": kw["referencia"]}
        return {"payment_intent_id": "mp_pix", "qr_code_data": "0002pix", "qr_code_base64": "iVBOR", "hosted_instructions_url": None}

    async def consultar(self, token, pid):
        self.chamadas.append(("consultar", token, pid))
        p = self.pagamentos.get(pid, {})
        return {"status": p.get("status"), "valor_centavos": 12000, "referencia": p.get("referencia")}


class StripeFalso:
    def __init__(self):
        self.chamadas = []

    async def ensure_customer(self, *a):
        return "cus_1"

    async def authorize(self, **kw):
        self.chamadas.append(("authorize", kw))
        return {"payment_intent_id": "pi_1", "hold_expira_em": AGORA + timedelta(days=7)}

    async def void(self, pi, idempotency_key=None):
        self.chamadas.append(("void", pi))

    async def expire(self, pi, idempotency_key=None):
        self.chamadas.append(("expire", pi))

    async def capture(self, *a, **kw):
        self.chamadas.append(("capture", a, kw))
        return {"amount_received": 12000}


@pytest.fixture
def loja(monkeypatch):
    monkeypatch.setenv("MERCADOPAGO_TOKEN_KEY", CHAVE)
    db = DB()
    prof = {"user_id": "u1", "name": "Eduardo Cerqueira", "role": "profissional", "email": "p@x.com", "created_at": AGORA,
            "timezone": "America/Sao_Paulo", "moeda": "BRL", "plano": "free", "recebimento": "mercadopago", "mp_user_id": "555",
            "mp_public_key": "APP_USR-pub", "mp_access_token_cifrado": cofre.cifrar("APP_USR-token-do-prof", CHAVE),
            "mp_refresh_token_cifrado": cofre.cifrar("TG-refresh", CHAVE), "mp_token_expira_em": AGORA + timedelta(days=100), "slug": "eduardo"}
    db.users.docs += [prof, {"user_id": "cli1", "name": "Maria", "role": "cliente", "email": "m@x.com", "created_at": AGORA}]
    db.servicos.docs.append({"servico_id": "svc_1", "profissional_id": "u1", "nome": "Corrida", "ativo": True, "duracao_min": 60,
                             "valor_centavos": 12000, "taxa_no_show_centavos": 3000, "moeda": "BRL", "criado_em": AGORA})
    db.customer_cards.docs.append({"user_id": "cli1", "customer_id": "cus_1", "payment_method_id": "pm_1"})
    db.disponibilidade.docs += [{"profissional_id": "u1", "weekday": d, "hora_inicio": "00:00", "hora_fim": "23:59"} for d in range(7)]
    mp, st, avisos = MPFalso(), StripeFalso(), []
    eu = {"atual": db.users.docs[1]}

    async def cliente(nome, tel):
        return {"user_id": "cli1", "email": "m@x.com", "name": nome}

    async def usuario_atual(auth):
        return next(u for u in db.users.docs if u["user_id"] == eu["atual"]["user_id"])

    async def avisar(db_, agendamento_id):
        avisos.append(agendamento_id)

    monkeypatch.setattr(server, "db", db)
    monkeypatch.setattr(server, "gateway", st)
    monkeypatch.setattr(server, "mp_gateway", mp)
    monkeypatch.setattr(server, "MERCADOPAGO_ATIVO", True)
    monkeypatch.setattr(server, "MERCADOPAGO_WEBHOOK_SECRET", SEGREDO_WEBHOOK)
    monkeypatch.setattr(server, "GATEWAY_KIND", "stripe")
    monkeypatch.setattr(server, "EXIGIR_RECEBIMENTO_ATIVO", False)
    monkeypatch.setattr(server, "_now", lambda: AGORA)
    monkeypatch.setattr(server, "_find_or_create_cliente_por_telefone", cliente)
    monkeypatch.setattr(server, "_current_user", usuario_atual)
    monkeypatch.setattr(server, "avisar_novo_agendamento", avisar)

    def como(uid):
        eu["atual"] = next(u for u in db.users.docs if u["user_id"] == uid)

    return {"db": db, "mp": mp, "stripe": st, "avisos": avisos, "como": como, "prof": db.users.docs[0], "c": TestClient(server.app)}


def pedido(inicio, **extra):
    d = {"profissional_id": "u1", "servico_id": "svc_1", "horario_inicio": inicio.isoformat(), "nome": "Maria", "telefone": "11987654321"}
    d.update(extra)
    return d


def cartao_mp(inicio, **extra):
    return pedido(inicio, token="tok_cartao_123", payment_method_id="visa", issuer_id="25", email="m@x.com",
                  identificacao_tipo="CPF", identificacao_numero="123.456.789-09", **extra)


# ---------------------------------------------------------------- taxa
@pytest.mark.parametrize("plano, stripe_bps, mp_bps", [("free", 1000, 700), ("profissional", 700, 400), ("ultra", 550, 250)])
def test_quem_recebe_pelo_mercado_pago_tem_3_pontos_a_menos_em_todo_plano(loja, plano, stripe_bps, mp_bps):
    prof = {**loja["prof"], "plano": plano}
    assert server._fee_bps_for(prof, "BRL") == mp_bps
    assert server._fee_bps_for({**prof, "recebimento": "stripe"}, "BRL") == stripe_bps
    assert server._fee_bps_for({**prof, "mp_user_id": None}, "BRL") == stripe_bps        # escolheu, mas não conectou: Stripe


def test_comparacao_dos_planos_usa_a_taxa_do_mercado_pago():
    linhas = {l["id"]: l for l in server.calcular_comparacao_planos([10000] * 10, "free", desconto_bps=300)}
    assert linhas["free"]["taxa_estimada_centavos"] == 7000 and linhas["ultra"]["fee_percent"] == 2.5
    sem = {l["id"]: l for l in server.calcular_comparacao_planos([10000] * 10, "free")}
    assert sem["free"]["taxa_estimada_centavos"] == 10000


# ---------------------------------------------------------------- agenda: reserva de 5 dias
def _fins(loja):
    r = loja["c"].get("/api/profissionais/u1/slots", params={"servico_id": "svc_1"})
    assert r.status_code == 200, r.text
    return [datetime.fromisoformat(s["iso"]).astimezone(timezone.utc) + timedelta(hours=1) for s in r.json()]


def test_agenda_de_quem_recebe_pelo_mercado_pago_respeita_a_reserva_de_5_dias(loja):
    fins = _fins(loja)
    assert max(fins) <= AGORA + timedelta(days=5) - timedelta(hours=26)
    assert max(fins) > AGORA + timedelta(days=3)                                          # não corta mais do que precisa
    loja["prof"]["recebimento"] = "stripe"
    assert max(_fins(loja)) > AGORA + timedelta(days=5)                                   # pelo Stripe: 7 dias


def test_reserva_alem_dos_5_dias_e_recusada_antes_do_cartao(loja):
    r = loja["c"].post("/api/public/agendamentos/mercadopago/cartao", json=cartao_mp(loc(25, 12)))
    assert r.status_code == 422 and "5 dias" in r.json()["detail"]
    assert loja["mp"].chamadas == []


# ---------------------------------------------------------------- cartão
def test_reserva_no_cartao_pelo_mercado_pago(loja):
    r = loja["c"].post("/api/public/agendamentos/mercadopago/cartao", json=cartao_mp(loc(22, 10)))
    assert r.status_code == 200, r.text
    nome, token, kw = loja["mp"].chamadas[0]
    assert nome == "reservar" and token == "APP_USR-token-do-prof"                        # cobra COM O TOKEN do profissional
    assert kw["valor_centavos"] == 12000 and kw["taxa_centavos_"] == 840                   # 7% (Free menos 3 pontos)
    assert kw["identificacao"] == {"type": "CPF", "number": "12345678909"}
    ag = loja["db"].agendamentos.docs[0]
    assert ag["gateway"] == "mercadopago" and ag["fee_bps"] == 700 and ag["hold_status"] == "autorizado"
    assert ag["janela_confirmacao_expira_em"] == loc(22, 11) + timedelta(hours=24)
    assert loja["stripe"].chamadas == [] and loja["avisos"] == [ag["agendamento_id"]]


@pytest.mark.parametrize("bandeira", ["elo", "hipercard", "debelo"])
def test_bandeira_sem_cobranca_parcial_e_recusada_sem_tocar_no_cartao(loja, bandeira):
    r = loja["c"].post("/api/public/agendamentos/mercadopago/cartao", json={**cartao_mp(loc(22, 10)), "payment_method_id": bandeira})
    assert r.status_code == 422 and "Visa" in r.json()["detail"]
    assert loja["mp"].chamadas == [] and loja["db"].agendamentos.docs == []


def test_cartao_recusado_nao_cria_agendamento(loja):
    loja["mp"].status_reserva = "rejected"
    r = loja["c"].post("/api/public/agendamentos/mercadopago/cartao", json=cartao_mp(loc(22, 10)))
    assert r.status_code == 402 and loja["db"].agendamentos.docs == []


def test_fluxos_do_stripe_mandam_o_cliente_para_o_link(loja):
    r = loja["c"].post("/api/public/agendamentos/cartao", json=pedido(loc(22, 10), payment_method_id="pm_1"))
    assert r.status_code == 409 and "Mercado Pago" in r.json()["detail"]
    r = loja["c"].post("/api/agendamentos", json={"servico_id": "svc_1", "horario_inicio": loc(22, 10).isoformat()})
    assert r.status_code == 409 and "link" in r.json()["detail"]
    assert loja["stripe"].chamadas == []


def test_endpoint_do_mercado_pago_recusa_quem_recebe_pelo_stripe(loja):
    loja["prof"]["recebimento"] = "stripe"
    r = loja["c"].post("/api/public/agendamentos/mercadopago/cartao", json=cartao_mp(loc(22, 10)))
    assert r.status_code == 409 and loja["mp"].chamadas == []


def _agendamento_mp(loja, **extra):
    doc = {"agendamento_id": "agd_mp", "profissional_id": "u1", "cliente_id": "cli1", "servico_id": "svc_1",
           "horario_inicio": loc(20, 10), "horario_fim": loc(20, 11), "valor_total_centavos": 12000, "valor_no_show_centavos": 3000,
           "moeda": "BRL", "status_agendamento": "agendado", "status_confirmacao": "pendente", "payment_intent_id": "mp_1",
           "hold_status": "autorizado", "hold_expira_em": AGORA + timedelta(days=3), "janela_confirmacao_expira_em": AGORA + timedelta(hours=5),
           "valor_capturado_centavos": 0, "gateway": "mercadopago", "fee_bps": 700, "criado_em": AGORA - timedelta(days=2)}
    doc.update(extra)
    loja["db"].agendamentos.docs.append(doc)
    return doc


def test_compareceu_captura_o_valor_inteiro_no_mercado_pago(loja):
    _agendamento_mp(loja)
    loja["como"]("u1")
    r = loja["c"].post("/api/agendamentos/agd_mp/confirmar", json={"resultado": "compareceu"})
    assert r.status_code == 200, r.text
    assert loja["mp"].chamadas == [("capturar", "APP_USR-token-do-prof", "mp_1", None, None, "capture_agd_mp_total")]
    assert loja["db"].agendamentos.docs[0]["hold_status"] == "capturado_total" and loja["stripe"].chamadas == []


def test_falta_cobra_so_a_taxa_e_a_taxa_do_showup_e_proporcional(loja):
    _agendamento_mp(loja)
    loja["como"]("u1")
    r = loja["c"].post("/api/agendamentos/agd_mp/confirmar", json={"resultado": "nao_compareceu"})
    assert r.status_code == 200, r.text
    assert loja["mp"].chamadas[0][3:5] == (3000, 210)                                     # 7% de R$ 30, não de R$ 120
    ag = loja["db"].agendamentos.docs[0]
    assert ag["hold_status"] == "capturado_taxa" and ag["valor_capturado_centavos"] == 3000 and "taxa_a_devolver_centavos" not in ag


def test_se_o_mercado_pago_manter_a_taxa_cheia_o_agendamento_fica_marcado_para_acerto(loja):
    _agendamento_mp(loja)
    loja["mp"].taxa_gravada = 840
    loja["como"]("u1")
    assert loja["c"].post("/api/agendamentos/agd_mp/confirmar", json={"resultado": "nao_compareceu"}).status_code == 200
    assert loja["db"].agendamentos.docs[0]["taxa_a_devolver_centavos"] == 630


def test_cancelar_e_expirar_soltam_a_reserva_no_mercado_pago_e_nao_no_stripe(loja):
    _agendamento_mp(loja, horario_inicio=loc(22, 10), horario_fim=loc(22, 11))   # o cliente cancela ANTES do horário
    r = loja["c"].post("/api/agendamentos/agd_mp/cancelar")
    assert r.status_code == 200, r.text
    assert loja["mp"].chamadas == [("cancelar", "APP_USR-token-do-prof", "mp_1", "void_agd_mp")]
    _agendamento_mp(loja, agendamento_id="agd_velho", payment_intent_id="mp_2", janela_confirmacao_expira_em=AGORA - timedelta(minutes=1))
    assert rodar(server._expirar_janela()) == 1
    assert loja["mp"].chamadas[-1][0:3] == ("cancelar", "APP_USR-token-do-prof", "mp_2")
    assert loja["stripe"].chamadas == []


# ---------------------------------------------------------------- Pix
def test_pix_pelo_mercado_pago_pede_email(loja):
    r = loja["c"].post("/api/public/agendamentos/pix", json=pedido(loc(22, 10)))
    assert r.status_code == 422 and "e-mail" in r.json()["detail"] and loja["mp"].chamadas == []


def test_pix_pelo_mercado_pago_gera_o_codigo_com_30_minutos_e_a_taxa(loja):
    r = loja["c"].post("/api/public/agendamentos/pix", json=pedido(loc(22, 10), email="m@x.com"))
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["qr_code_data"] == "0002pix" and d["qr_code_base64"] == "iVBOR" and d["payment_intent_client_secret"] is None
    _, token, kw = loja["mp"].chamadas[0]
    assert token == "APP_USR-token-do-prof" and kw["taxa_centavos_"] == 840
    assert kw["expira_em"] == AGORA + timedelta(minutes=30)                                # mínimo aceito pelo Mercado Pago
    ag = loja["db"].agendamentos.docs[0]
    assert ag["hold_status"] == "aguardando_pix" and ag["gateway"] == "mercadopago" and ag["hold_expira_em"] > kw["expira_em"]
    assert loja["avisos"] == []                                                           # só avisa o profissional quando pagar


def test_pagina_descobre_que_o_pix_foi_pago_consultando_o_mercado_pago(loja):
    r = loja["c"].post("/api/public/agendamentos/pix", json=pedido(loc(22, 10), email="m@x.com"))
    aid = r.json()["agendamento_id"]
    assert loja["c"].get(f"/api/public/agendamentos/{aid}/status").json()["hold_status"] == "aguardando_pix"
    loja["mp"].pagamentos["mp_pix"]["status"] = "approved"
    assert loja["c"].get(f"/api/public/agendamentos/{aid}/status").json()["hold_status"] == "pago_integral"
    assert loja["avisos"] == [aid]
    loja["c"].get(f"/api/public/agendamentos/{aid}/status")
    assert loja["avisos"] == [aid]                                                        # avisa uma vez só


def test_pagamento_de_outro_agendamento_nunca_confirma_este(loja):
    r = loja["c"].post("/api/public/agendamentos/pix", json=pedido(loc(22, 10), email="m@x.com"))
    aid = r.json()["agendamento_id"]
    loja["mp"].pagamentos["mp_pix"] = {"status": "approved", "referencia": "agd_de_outra_pessoa"}
    assert loja["c"].get(f"/api/public/agendamentos/{aid}/status").json()["hold_status"] == "aguardando_pix"


def test_pix_pago_no_ultimo_minuto_nao_e_dado_como_expirado(loja, monkeypatch):
    loja["c"].post("/api/public/agendamentos/pix", json=pedido(loc(22, 10), email="m@x.com"))
    loja["mp"].pagamentos["mp_pix"]["status"] = "approved"
    monkeypatch.setattr(server, "_now", lambda: AGORA + timedelta(hours=1))
    rodar(server._expirar_pix_pendentes())
    assert loja["db"].agendamentos.docs[0]["hold_status"] == "pago_integral"


def test_pix_nao_pago_expira_e_solta_o_horario(loja, monkeypatch):
    loja["c"].post("/api/public/agendamentos/pix", json=pedido(loc(22, 10), email="m@x.com"))
    monkeypatch.setattr(server, "_now", lambda: AGORA + timedelta(hours=1))
    rodar(server._expirar_pix_pendentes())
    assert loja["db"].agendamentos.docs[0]["hold_status"] == "expirado"


# ---------------------------------------------------------------- avisos de pagamento (webhook)
def _aviso(loja, data_id, assinatura=None):
    return loja["c"].post(f"/api/webhooks/mercadopago?data.id={data_id}&type=payment",
                          json={"type": "payment", "action": "payment.updated", "data": {"id": data_id}},
                          headers={"x-signature": assinatura or assinar(data_id, ts=str(int(AGORA.timestamp()))), "x-request-id": "req-1"})


def test_aviso_com_assinatura_valida_confirma_o_pix_depois_de_consultar(loja):
    r = loja["c"].post("/api/public/agendamentos/pix", json=pedido(loc(22, 10), email="m@x.com"))
    loja["mp"].pagamentos["mp_pix"]["status"] = "approved"
    assert _aviso(loja, "mp_pix").status_code == 200
    assert loja["db"].agendamentos.docs[0]["hold_status"] == "pago_integral"
    assert ("consultar", "APP_USR-token-do-prof", "mp_pix") in loja["mp"].chamadas


def test_aviso_forjado_e_recusado_e_nada_muda(loja):
    loja["c"].post("/api/public/agendamentos/pix", json=pedido(loc(22, 10), email="m@x.com"))
    loja["mp"].pagamentos["mp_pix"]["status"] = "approved"
    assert _aviso(loja, "mp_pix", assinatura=assinar("mp_pix", segredo="chute")).status_code == 400
    assert loja["db"].agendamentos.docs[0]["hold_status"] == "aguardando_pix"
    assert not any(c[0] == "consultar" for c in loja["mp"].chamadas)


def test_sem_segredo_configurado_todo_aviso_e_recusado(loja, monkeypatch):
    monkeypatch.setattr(server, "MERCADOPAGO_WEBHOOK_SECRET", "")
    assert _aviso(loja, "mp_pix").status_code == 500


# ---------------------------------------------------------------- conectar a conta (OAuth) e escolher onde receber
def _novo_prof(loja, **extra):
    u = {"user_id": "u2", "name": "Ana", "role": "profissional", "email": "a@x.com", "created_at": AGORA, "moeda": "BRL"}
    u.update(extra)
    loja["db"].users.docs.append(u)
    loja["como"]("u2")
    return u


def test_conectar_gera_state_e_o_retorno_grava_os_tokens_cifrados(loja):
    _novo_prof(loja)
    r = loja["c"].post("/api/me/mercadopago/conectar")
    assert r.status_code == 200, r.text
    state = r.json()["url"].split("state=")[1]
    assert loja["db"].mp_oauth_states.docs[0]["user_id"] == "u2"
    r = loja["c"].get("/api/mercadopago/callback", params={"code": "TG-codigo", "state": state}, follow_redirects=False)
    assert r.headers["location"] == "showup://configuracoes?mercadopago=ok"
    u = next(x for x in loja["db"].users.docs if x["user_id"] == "u2")
    assert u["mp_user_id"] == "777" and u["recebimento"] == "mercadopago" and u["mp_public_key"] == "APP_USR-pub-novo"
    assert "APP_USR-novo" not in json.dumps(u, default=str) and "TG-novo" not in json.dumps(u, default=str)   # nada em texto puro
    assert cofre.decifrar(u["mp_access_token_cifrado"]) == "APP_USR-novo"
    assert loja["db"].mp_oauth_states.docs == []                                            # o state só vale uma vez


def test_retorno_com_state_desconhecido_ou_vencido_nao_grava_nada(loja):
    _novo_prof(loja)
    r = loja["c"].get("/api/mercadopago/callback", params={"code": "c", "state": "inventado"}, follow_redirects=False)
    assert r.headers["location"].endswith("mercadopago=expirado")
    loja["db"].mp_oauth_states.docs.append({"state": "velho", "user_id": "u2", "expira_em": AGORA - timedelta(seconds=1)})
    r = loja["c"].get("/api/mercadopago/callback", params={"code": "c", "state": "velho"}, follow_redirects=False)
    assert r.headers["location"].endswith("mercadopago=expirado")
    assert loja["mp"].chamadas == [] and "mp_user_id" not in loja["db"].users.docs[-1]


def test_mesma_conta_do_mercado_pago_nao_recebe_por_dois_profissionais(loja):
    _novo_prof(loja)
    loja["mp"].tokens["user_id"] = "555"                                                    # já é do u1
    loja["db"].mp_oauth_states.docs.append({"state": "s", "user_id": "u2", "expira_em": AGORA + timedelta(minutes=5)})
    r = loja["c"].get("/api/mercadopago/callback", params={"code": "c", "state": "s"}, follow_redirects=False)
    assert r.headers["location"].endswith("mercadopago=conta_em_uso")
    assert "mp_user_id" not in loja["db"].users.docs[-1]


def test_so_passa_a_receber_pelo_mercado_pago_conectado_e_em_reais(loja):
    _novo_prof(loja)
    assert loja["c"].put("/api/me/recebimento", json={"metodo": "mercadopago"}).status_code == 409        # não conectou
    u = loja["db"].users.docs[-1]
    u.update({"mp_user_id": "9", "mp_access_token_cifrado": cofre.cifrar("x")})
    loja["db"].servicos.docs.append({"servico_id": "svc_usd", "profissional_id": "u2", "ativo": True, "moeda": "USD"})
    r = loja["c"].put("/api/me/recebimento", json={"metodo": "mercadopago"})
    assert r.status_code == 409 and "reais" in r.json()["detail"]
    loja["db"].servicos.docs[-1]["ativo"] = False
    r = loja["c"].put("/api/me/recebimento", json={"metodo": "mercadopago"})
    assert r.status_code == 200 and r.json()["metodo"] == "mercadopago" and r.json()["reserva_dias"] == 5


def test_quem_recebe_pelo_mercado_pago_nao_troca_a_moeda(loja):
    loja["como"]("u1")
    r = loja["c"].put("/api/me/moeda", json={"moeda": "USD"})
    assert r.status_code == 409 and loja["prof"]["moeda"] == "BRL"


def test_nao_desconecta_com_reserva_aberta(loja):
    _agendamento_mp(loja)
    loja["como"]("u1")
    assert loja["c"].delete("/api/me/mercadopago").status_code == 409
    loja["db"].agendamentos.docs[0]["hold_status"] = "capturado_total"
    assert loja["c"].delete("/api/me/mercadopago").status_code == 200
    assert loja["prof"]["recebimento"] == "stripe" and "mp_access_token_cifrado" not in loja["prof"]


def test_token_perto_de_vencer_e_renovado_antes_de_cobrar(loja):
    loja["prof"]["mp_token_expira_em"] = AGORA + timedelta(days=2)
    assert loja["c"].post("/api/public/agendamentos/mercadopago/cartao", json=cartao_mp(loc(22, 10))).status_code == 200
    assert loja["mp"].chamadas[0] == ("renovar", "TG-refresh")
    assert loja["mp"].chamadas[1][1] == "APP_USR-novo"                                       # cobrou com o token novo
    assert cofre.decifrar(loja["prof"]["mp_access_token_cifrado"]) == "APP_USR-novo"


# ---------------------------------------------------------------- página pública
def test_pagina_publica_recebe_o_que_precisa_e_nunca_o_token(loja):
    r = loja["c"].get("/api/profissionais/u1")
    d = r.json()
    assert d["recebimento"] == "mercadopago" and d["mp_public_key"] == "APP_USR-pub" and d["pix_disponivel"] is True
    assert d["link_agendamento"].endswith("/p/eduardo") and d["aceita_agendamentos"] is True
    assert "cifrado" not in r.text and "APP_USR-token" not in r.text and "TG-refresh" not in r.text


def test_sem_o_mercado_pago_configurado_o_profissional_dele_nao_aceita_reserva(loja, monkeypatch):
    monkeypatch.setattr(server, "MERCADOPAGO_ATIVO", False)
    assert loja["c"].get("/api/profissionais/u1").json()["aceita_agendamentos"] is False


def test_profissional_do_stripe_continua_igual_na_pagina(loja, monkeypatch):
    loja["prof"]["recebimento"] = "stripe"
    d = loja["c"].get("/api/profissionais/u1").json()
    assert d["recebimento"] == "stripe" and d["mp_public_key"] is None and d["link_agendamento"] is None
    assert d["pix_disponivel"] is False                                                     # Pix do Stripe: só por convite
    monkeypatch.setattr(server, "PIX_STRIPE_HABILITADO", True)
    assert loja["c"].get("/api/profissionais/u1").json()["pix_disponivel"] is True
