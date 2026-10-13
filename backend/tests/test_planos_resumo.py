"""Testes OFFLINE (sem Mongo nem Stripe reais) da conta "quanto eu pagaria em
cada plano", do teste grátis e da confirmação da assinatura.

Diferente dos outros arquivos de teste desta pasta (que falam com um servidor
rodando), aqui o banco e o gateway são falsos, então dá pra rodar em qualquer
lugar: `pytest tests/test_planos_resumo.py`.
"""
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

os.environ.setdefault("TESTING", "1")  # desliga o rate limit (precisa vir antes de importar o server)
os.environ.setdefault("GOOGLE_WEB_CLIENT_ID", "teste.apps.googleusercontent.com")
os.environ["STRIPE_PRICE_ID_PROFISSIONAL"] = "price_prof"
os.environ["STRIPE_PRICE_ID_ULTRA"] = "price_ultra"
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest
from fastapi.testclient import TestClient

import server


# ------------------------------------------------------------------ fakes
def _match(doc, query):
    for k, cond in query.items():
        v = doc.get(k)
        if isinstance(cond, dict):
            for op, arg in cond.items():
                if op == "$in":
                    if v not in arg:
                        return False
                elif op == "$gte":
                    if v is None or v < arg:
                        return False
                else:
                    raise NotImplementedError(op)
        elif v != cond:
            return False
    return True


class _Cursor:
    def __init__(self, docs):
        self.docs = docs

    async def to_list(self, n):
        return self.docs[:n]


class _Col:
    def __init__(self, docs=None):
        self.docs = docs if docs is not None else []

    def find(self, query, proj=None):
        return _Cursor([dict(d) for d in self.docs if _match(d, query)])

    async def find_one(self, query, proj=None):
        for d in self.docs:
            if _match(d, query):
                return dict(d)
        return None

    async def update_one(self, query, update):
        for d in self.docs:
            if _match(d, query):
                d.update(update.get("$set", {}))
                for k in update.get("$unset", {}):
                    d.pop(k, None)
                return


class FakeDB:
    def __init__(self, users, agendamentos):
        self.users = _Col(users)
        self.agendamentos = _Col(agendamentos)
        self.customer_cards = _Col()


class FakeGW:
    def __init__(self):
        self.trial_days_chamados = []
        self.cancelados = []
        self.setup_ok = True          # o Stripe devolveu o SetupIntent do teste?
        self.sub_status = "trialing"
        self.sub_user = "u1"
        self.si_status = "succeeded"
        self.quebrar_detalhes = False
        self.n_subs = 0

    async def ensure_billing_customer(self, user_id, email, name):
        return "cus_1"

    async def create_ephemeral_key(self, customer_id):
        return "ek_secret"

    async def create_plano_subscription(self, customer_id, price_id, user_id, trial_days=0):
        self.trial_days_chamados.append(trial_days)
        self.n_subs += 1
        sid = f"sub_{self.n_subs}"
        if trial_days:
            return {
                "subscription_id": sid, "payment_intent_client_secret": None,
                "setup_intent_client_secret": "seti_secret" if self.setup_ok else None,
                "setup_intent_id": "seti_1" if self.setup_ok else None,
            }
        return {"subscription_id": sid, "payment_intent_client_secret": "pi_secret",
                "setup_intent_client_secret": None, "setup_intent_id": None}

    async def get_subscription_details(self, sub_id):
        if self.quebrar_detalhes:
            raise AssertionError("não devia consultar o Stripe de novo")
        return {"status": self.sub_status, "trial_end": 1_800_000_000, "user_id": self.sub_user}

    async def get_setup_intent_status(self, si_id):
        return self.si_status

    async def cancel_subscription(self, sub_id):
        self.cancelados.append(sub_id)


def _agendamento(prof="u1", hold="capturado_total", valor=12000, capturado=12000, dias=2, moeda="BRL"):
    return {
        "profissional_id": prof, "hold_status": hold, "valor_total_centavos": valor,
        "valor_capturado_centavos": capturado, "moeda": moeda,
        "horario_inicio": datetime.now(timezone.utc) - timedelta(days=dias),
    }


def _user(**extra):
    base = {
        "user_id": "u1", "email": "ana@example.com", "name": "Ana Lima", "role": "profissional",
        "moeda": "BRL", "plano": "free", "created_at": datetime.now(timezone.utc),
    }
    base.update(extra)
    return base


@pytest.fixture
def ctx(monkeypatch):
    def montar(user=None, agendamentos=None):
        db = FakeDB([user or _user()], agendamentos or [])
        gw = FakeGW()

        async def fake_current_user(auth):
            return await db.users.find_one({"user_id": "u1"}, {"_id": 0})

        monkeypatch.setattr(server, "db", db)
        monkeypatch.setattr(server, "gateway", gw)
        monkeypatch.setattr(server, "GATEWAY_KIND", "stripe")
        monkeypatch.setattr(server, "_current_user", fake_current_user)
        return TestClient(server.app), db, gw

    return montar


def _usuario(db):
    return db.users.docs[0]


# ------------------------------------------------------------------ cálculo puro
def test_conta_dos_tres_planos_com_20_sessoes_de_120():
    linhas = {l["id"]: l for l in server.calcular_comparacao_planos([12000] * 20, "free")}
    assert linhas["free"]["custo_total_centavos"] == 24000
    assert linhas["profissional"]["custo_total_centavos"] == 12000 + 1990
    assert linhas["ultra"]["custo_total_centavos"] == 4800 + 5990
    assert linhas["profissional"]["economia_vs_atual_centavos"] == 10010
    assert linhas["ultra"]["economia_vs_atual_centavos"] == 13210


def test_taxa_arredonda_por_agendamento_como_na_cobranca():
    # 10% de 105 = 10,5 -> a cobrança real faz 10 em cada um (20), não 21
    free = server.calcular_comparacao_planos([105, 105], "free")[0]
    assert free["taxa_estimada_centavos"] == 20


def test_economia_e_relativa_ao_plano_atual():
    linhas = {l["id"]: l for l in server.calcular_comparacao_planos([12000] * 20, "profissional")}
    assert linhas["profissional"]["economia_vs_atual_centavos"] == 0
    assert linhas["free"]["economia_vs_atual_centavos"] == -10010
    assert linhas["ultra"]["economia_vs_atual_centavos"] == 13990 - 10790


def test_pontos_de_equilibrio():
    eq = server._equilibrios()
    assert eq["profissional"] == {"vs_free": 39800, "vs_anterior": 39800}      # R$ 398,00
    assert eq["ultra"]["vs_free"] == 74875                                      # R$ 748,75
    assert eq["ultra"]["vs_anterior"] == 133334                                 # R$ 1.333,34


def test_trial_so_pra_quem_nunca_testou_nem_pagou():
    assert server._trial_disponivel(_user())
    assert not server._trial_disponivel(_user(plano_trial_usado=True))
    assert not server._trial_disponivel(_user(plano_ja_pago=True))
    assert not server._trial_disponivel(_user(plano="profissional"))


# ------------------------------------------------------------------ /me/plano/resumo
def test_resumo_filtra_janela_profissional_moeda_e_status(ctx):
    ags = [
        _agendamento(dias=2),                                              # entra
        _agendamento(dias=5),                                              # entra
        _agendamento(hold="capturado_taxa", capturado=3000, dias=3),       # falta cobrada
        _agendamento(dias=40),                                             # fora dos 30 dias
        _agendamento(prof="u2"),                                           # outro profissional
        _agendamento(moeda="USD"),                                         # outra moeda
        _agendamento(hold="autorizado"),                                   # ainda não cobrado
    ]
    client, db, gw = ctx(agendamentos=ags)
    r = client.get("/api/me/plano/resumo").json()
    assert r["atendimentos_cobrados"] == 2
    assert r["servicos_cobrados_centavos"] == 24000
    assert r["faltas_cobradas_qtd"] == 1
    assert r["faltas_cobradas_centavos"] == 3000
    # base da taxa = o que foi de fato cobrado: 2 serviços inteiros + a taxa da falta
    assert r["base_taxa_centavos"] == 12000 + 12000 + 3000


def test_resumo_nao_recomenda_upgrade_que_sai_mais_caro(ctx):
    # 3 atendimentos de 120 (R$ 360): Free custa R$ 36; Profissional R$ 37,90
    client, db, gw = ctx(agendamentos=[_agendamento() for _ in range(3)])
    r = client.get("/api/me/plano/resumo").json()
    assert r["recomendado"] is None


def test_resumo_recomenda_o_mais_barato_quando_o_volume_justifica(ctx):
    client, db, gw = ctx(agendamentos=[_agendamento() for _ in range(20)])
    r = client.get("/api/me/plano/resumo").json()
    assert r["recomendado"] == "ultra"
    ultra = next(l for l in r["comparacao"] if l["id"] == "ultra")
    assert ultra["economia_vs_atual_centavos"] == 13210


def test_resumo_nao_recomenda_plano_indisponivel(ctx, monkeypatch):
    monkeypatch.delenv("STRIPE_PRICE_ID_ULTRA")
    client, db, gw = ctx(agendamentos=[_agendamento() for _ in range(20)])
    r = client.get("/api/me/plano/resumo").json()
    assert r["recomendado"] == "profissional"


def test_resumo_sem_movimento_traz_equilibrio_e_nenhuma_recomendacao(ctx):
    client, db, gw = ctx()
    r = client.get("/api/me/plano/resumo").json()
    assert r["atendimentos_cobrados"] == 0 and r["recomendado"] is None
    prof = next(l for l in r["comparacao"] if l["id"] == "profissional")
    assert prof["equilibrio_vs_free_centavos"] == 39800


def test_resumo_em_outra_moeda_nao_compara(ctx):
    client, db, gw = ctx(user=_user(moeda="USD"), agendamentos=[_agendamento(moeda="USD")])
    r = client.get("/api/me/plano/resumo").json()
    assert r["comparacao_disponivel"] is False and r["comparacao"] == []
    assert r["atendimentos_cobrados"] == 1 and r["trial_disponivel"] is False


# ------------------------------------------------------------------ teste grátis: abrir
def test_trial_cria_assinatura_com_14_dias_e_devolve_setup_intent(ctx):
    client, db, gw = ctx()
    r = client.post("/api/me/plano/subscription-intent", json={"plano": "profissional", "usar_trial": True})
    assert r.status_code == 200
    body = r.json()
    assert body["setup_intent_client_secret"] == "seti_secret"
    assert body["payment_intent_client_secret"] is None and body["trial_dias"] == 14
    assert gw.trial_days_chamados == [14]
    pend = _usuario(db)["plano_pendente"]
    assert pend == {"subscription_id": "sub_1", "plano": "profissional", "trial": True, "setup_intent_id": "seti_1"}


def test_assinatura_paga_normal_continua_igual(ctx):
    client, db, gw = ctx()
    body = client.post("/api/me/plano/subscription-intent", json={"plano": "ultra"}).json()
    assert body["payment_intent_client_secret"] == "pi_secret" and body["trial_dias"] == 0
    assert gw.trial_days_chamados == [0]
    assert _usuario(db)["plano_pendente"]["trial"] is False


def test_trial_negado_quando_ja_usou(ctx):
    client, db, gw = ctx(user=_user(plano_trial_usado=True))
    r = client.post("/api/me/plano/subscription-intent", json={"plano": "profissional", "usar_trial": True})
    assert r.status_code == 400 and gw.trial_days_chamados == []


def test_trial_sem_setup_intent_do_stripe_cancela_e_nao_libera(ctx):
    client, db, gw = ctx()
    gw.setup_ok = False
    r = client.post("/api/me/plano/subscription-intent", json={"plano": "profissional", "usar_trial": True})
    assert r.status_code == 502
    assert gw.cancelados == ["sub_1"] and "plano_pendente" not in _usuario(db)


# ------------------------------------------------------------------ confirmar
def _abrir(client, plano="profissional", trial=True):
    return client.post("/api/me/plano/subscription-intent", json={"plano": plano, "usar_trial": trial})


def _confirmar(client, sub="sub_1", plano="profissional"):
    return client.post("/api/me/plano/confirm", json={"subscription_id": sub, "plano": plano})


def test_confirmar_trial_com_cartao_salvo_libera_o_plano(ctx):
    client, db, gw = ctx()
    _abrir(client)
    r = _confirmar(client)
    assert r.status_code == 200 and r.json()["user"]["plano"] == "profissional"
    u = _usuario(db)
    assert u["plano_trial_usado"] is True and u["stripe_subscription_id"] == "sub_1"
    assert "plano_pendente" not in u
    assert u["plano_trial_termina_em"] == datetime.fromtimestamp(1_800_000_000, tz=timezone.utc)


def test_confirmar_trial_sem_cartao_salvo_NAO_libera(ctx):
    # o cenário do bug do SDK: assinatura já `trialing`, mas o cartão nunca foi salvo
    client, db, gw = ctx()
    _abrir(client)
    gw.si_status = "requires_payment_method"
    r = _confirmar(client)
    assert r.status_code == 402
    assert _usuario(db)["plano"] == "free" and "plano_trial_usado" not in _usuario(db)


def test_confirmar_trial_com_assinatura_ativa_em_vez_de_trialing_e_recusado(ctx):
    client, db, gw = ctx()
    _abrir(client)
    gw.sub_status = "active"
    assert _confirmar(client).status_code == 402


def test_confirmar_sem_nada_pendente(ctx):
    client, db, gw = ctx()
    assert _confirmar(client).status_code == 400


def test_confirmar_com_subscription_id_diferente_do_preparado(ctx):
    client, db, gw = ctx()
    _abrir(client)
    assert _confirmar(client, sub="sub_de_outro").status_code == 400
    assert _usuario(db)["plano"] == "free"


def test_confirmar_nao_aceita_plano_diferente_do_preparado(ctx):
    # prepara o Profissional (R$ 19,90) e tenta confirmar como Ultra (taxa de 2%)
    client, db, gw = ctx()
    _abrir(client, plano="profissional", trial=False)
    gw.sub_status = "active"
    r = _confirmar(client, plano="ultra")
    assert r.status_code == 400 and _usuario(db)["plano"] == "free"


def test_confirmar_assinatura_de_outro_usuario(ctx):
    client, db, gw = ctx()
    _abrir(client)
    gw.sub_user = "u2"
    assert _confirmar(client).status_code == 403


def test_confirmar_pago_ativo_libera_e_marca_que_ja_pagou(ctx):
    client, db, gw = ctx()
    _abrir(client, trial=False)
    gw.sub_status = "active"
    r = _confirmar(client)
    assert r.status_code == 200 and _usuario(db)["plano"] == "profissional"
    assert _usuario(db)["plano_ja_pago"] is True and "plano_trial_usado" not in _usuario(db)


def test_confirmar_pago_incompleto_e_recusado(ctx):
    client, db, gw = ctx()
    _abrir(client, trial=False)
    gw.sub_status = "incomplete"
    assert _confirmar(client).status_code == 402


def test_confirmar_duas_vezes_e_idempotente(ctx):
    client, db, gw = ctx()
    _abrir(client)
    assert _confirmar(client).status_code == 200
    gw.quebrar_detalhes = True   # a 2ª chamada não pode nem consultar o Stripe
    assert _confirmar(client).status_code == 200


# ------------------------------------------------------------------ cancelar durante o teste
def test_cancelar_no_teste_volta_pro_free_e_nao_devolve_novo_teste(ctx):
    client, db, gw = ctx()
    _abrir(client)
    _confirmar(client)
    r = client.post("/api/me/plano/cancelar")
    assert r.status_code == 200 and r.json()["user"]["plano"] == "free"
    assert gw.cancelados == ["sub_1"]
    u = _usuario(db)
    assert u["plano_trial_usado"] is True and "plano_trial_termina_em" not in u
    # e o resumo já avisa que não tem mais teste
    resumo = client.get("/api/me/plano/resumo").json()
    assert resumo["trial_disponivel"] is False
    assert _abrir(client).status_code == 400


def test_resumo_mostra_fim_do_teste_enquanto_ele_vale(ctx):
    client, db, gw = ctx()
    _abrir(client)
    _confirmar(client)
    r = client.get("/api/me/plano/resumo").json()
    assert r["plano_atual"] == "profissional" and r["trial_disponivel"] is False
    assert r["trial_termina_em"].startswith("2027-01-15")  # epoch 1_800_000_000


def test_tentar_de_novo_cancela_a_assinatura_pendente_anterior(ctx):
    client, db, gw = ctx()
    _abrir(client)                      # abriu o sheet e fechou sem salvar o cartão (sub_1 fica pendente)
    assert gw.cancelados == []
    _abrir(client)                      # tenta de novo
    assert gw.cancelados == ["sub_1"]
    assert _usuario(db)["plano_pendente"]["subscription_id"] == "sub_2"
    # a confirmação agora só vale pra assinatura nova
    assert _confirmar(client, sub="sub_1").status_code == 400
    assert _confirmar(client, sub="sub_2").status_code == 200


def test_falta_entra_na_conta_pelo_valor_cobrado_e_nao_pelo_valor_do_servico(ctx):
    # uma falta: serviço de R$ 120, cobrados R$ 30 -> taxa do Free = 10% de R$ 30
    client, db, gw = ctx(agendamentos=[_agendamento(hold="capturado_taxa", valor=12000, capturado=3000)])
    r = client.get("/api/me/plano/resumo").json()
    free = next(l for l in r["comparacao"] if l["id"] == "free")
    assert r["base_taxa_centavos"] == 3000 and free["taxa_estimada_centavos"] == 300
