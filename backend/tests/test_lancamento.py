"""Testes OFFLINE das proteções de lançamento: estado do Connect, painel do
Stripe, trava de recebimento, exclusão de conta e webhooks de cobrança do plano.
Banco, gateway e push são falsos — roda em qualquer lugar."""
import asyncio
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import offline_env  # noqa: E402,F401  (variáveis FALSAS, antes de importar o server)

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

import server
import webhooks
from payment_errors import CardDeclinedError, GatewayUnavailableError, InvalidPaymentRequestError


# ------------------------------------------------------------------ banco falso
def _match(doc, q):
    for k, cond in q.items():
        if k == "$and":
            if not all(_match(doc, c) for c in cond):
                return False
        elif k == "$or":
            if not any(_match(doc, c) for c in cond):
                return False
        else:
            v = doc.get(k)
            if isinstance(cond, dict) and any(op.startswith("$") for op in cond):
                for op, arg in cond.items():
                    if op == "$in":
                        ok = v in arg
                    elif op == "$nin":
                        ok = v not in arg
                    elif op == "$ne":
                        ok = v != arg
                    elif op == "$gt":
                        ok = v is not None and v > arg
                    elif op == "$gte":
                        ok = v is not None and v >= arg
                    elif op == "$exists":
                        ok = (k in doc) == arg
                    else:
                        raise NotImplementedError(op)
                    if not ok:
                        return False
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

    def find(self, q, proj=None):
        return _Cursor([dict(d) for d in self.docs if _match(d, q)])

    async def find_one(self, q, proj=None):
        return next((dict(d) for d in self.docs if _match(d, q)), None)

    def _aplicar(self, d, upd):
        d.update(upd.get("$set", {}))
        for k in upd.get("$unset", {}):
            d.pop(k, None)

    async def update_one(self, q, upd):
        for d in self.docs:
            if _match(d, q):
                self._aplicar(d, upd)
                return

    async def update_many(self, q, upd):
        for d in self.docs:
            if _match(d, q):
                self._aplicar(d, upd)

    async def find_one_and_update(self, q, upd):
        for d in self.docs:
            if _match(d, q):
                antes = dict(d)
                self._aplicar(d, upd)
                return antes
        return None

    async def delete_many(self, q):
        self.docs[:] = [d for d in self.docs if not _match(d, q)]

    async def delete_one(self, q):
        for i, d in enumerate(self.docs):
            if _match(d, q):
                del self.docs[i]
                return


class FakeDB:
    def __init__(self, users, **cols):
        self.users = _Col(users)
        for nome in ("agendamentos", "user_sessions", "device_tokens", "customer_cards", "servicos",
                     "email_codes", "login_attempts"):
            setattr(self, nome, _Col(cols.get(nome)))


class FakeGW:
    def __init__(self):
        self.status = {"charges_enabled": False, "payouts_enabled": False, "details_submitted": True,
                       "pendencias": [], "vencidas": [], "em_verificacao": [], "motivo_bloqueio": None}
        self.status_erro = None
        self.login_erro = None
        self.cancelados, self.clientes_apagados = [], []
        self.cancel_erro = None
        self.status_chamadas = 0

    async def account_status(self, acct):
        self.status_chamadas += 1
        if self.status_erro:
            raise self.status_erro
        return dict(self.status)

    async def create_login_link(self, acct):
        if self.login_erro:
            raise self.login_erro
        return "https://connect.stripe.com/express/abc"

    async def cancel_subscription(self, sub_id):
        if self.cancel_erro:
            raise self.cancel_erro
        self.cancelados.append(sub_id)

    async def delete_customer(self, cid):
        self.clientes_apagados.append(cid)

    async def ensure_customer(self, user_id, email, name):
        return "cus_1"

    async def authorize(self, **kw):
        raise CardDeclinedError("recusado")  # sentinela: chegou ao pagamento = passou pela trava


def _prof(**extra):
    base = {"user_id": "u1", "email": "ana@example.com", "name": "Ana Lima", "role": "profissional",
            "moeda": "BRL", "plano": "free", "created_at": datetime.now(timezone.utc),
            "stripe_account_id": "acct_1"}
    base.update(extra)
    return base


@pytest.fixture
def ctx(monkeypatch):
    def montar(user=None, **cols):
        db, gw = FakeDB([user or _prof()], **cols), FakeGW()

        async def fake_user(auth):
            return await db.users.find_one({"user_id": "u1"})

        monkeypatch.setattr(server, "db", db)
        monkeypatch.setattr(server, "gateway", gw)
        monkeypatch.setattr(server, "GATEWAY_KIND", "stripe")
        monkeypatch.setattr(server, "_current_user", fake_user)
        return TestClient(server.app), db, gw
    return montar


# ------------------------------------------------------------------ estado do Connect
@pytest.mark.parametrize("st,esperado", [
    ({"charges_enabled": True, "payouts_enabled": True, "details_submitted": True}, "ativa"),
    ({"details_submitted": True, "motivo_bloqueio": "rejected.fraud"}, "recusada"),
    ({"details_submitted": True, "motivo_bloqueio": "rejected.other", "pendencias": ["x"]}, "recusada"),
    ({"details_submitted": False}, "pendente_informacoes"),
    ({"details_submitted": True, "pendencias": ["individual.verification.document"]}, "pendente_informacoes"),
    ({"details_submitted": True, "vencidas": ["business_profile.url"], "motivo_bloqueio": "under_review"}, "pendente_informacoes"),
    ({"details_submitted": True, "motivo_bloqueio": "under_review"}, "em_analise"),
    ({"details_submitted": True, "em_verificacao": ["individual.id_number"]}, "em_analise"),
    ({"details_submitted": True, "charges_enabled": True, "payouts_enabled": False}, "restrita"),
])
def test_estado_do_connect(st, esperado):
    assert server._estado_connect(st) == esperado


def test_rota_connect_explica_o_bloqueio(ctx):
    client, db, gw = ctx()
    gw.status.update(pendencias=["individual.verification.document"], motivo_bloqueio="requirements.past_due")
    r = client.get("/api/me/connect").json()
    assert r["estado"] == "pendente_informacoes"
    assert r["pendencias"] == ["individual.verification.document"]
    assert r["motivo_bloqueio"] == "requirements.past_due"
    assert db.users.docs[0]["connect_ready"] is False


def test_rota_connect_ativa_atualiza_o_cache(ctx):
    client, db, gw = ctx()
    gw.status.update(charges_enabled=True, payouts_enabled=True)
    assert client.get("/api/me/connect").json()["estado"] == "ativa"
    assert db.users.docs[0]["connect_ready"] is True


def test_rota_connect_sem_conta_e_com_stripe_fora_do_ar(ctx):
    client, db, gw = ctx(user=_prof(stripe_account_id=None))
    assert client.get("/api/me/connect").json()["estado"] == "nao_conectada"
    client, db, gw = ctx()
    gw.status_erro = GatewayUnavailableError("fora do ar")
    # tem conta mas não deu pra consultar: NÃO pode virar "não conectada" (mandaria
    # o profissional refazer um cadastro que já fez)
    assert client.get("/api/me/connect").json()["estado"] == "indisponivel"


# ------------------------------------------------------------------ painel do Stripe
def test_painel_devolve_o_link(ctx):
    client, db, gw = ctx()
    r = client.post("/api/me/connect/painel")
    assert r.status_code == 200 and r.json()["url"].startswith("https://connect.stripe.com/")


def test_painel_sem_conta_e_com_cadastro_incompleto(ctx):
    client, db, gw = ctx(user=_prof(stripe_account_id=None))
    assert client.post("/api/me/connect/painel").status_code == 409
    client, db, gw = ctx()
    gw.login_erro = InvalidPaymentRequestError("não concluiu o onboarding")
    assert client.post("/api/me/connect/painel").status_code == 409


def test_painel_falha_do_stripe_vira_502(ctx):
    client, db, gw = ctx()
    gw.login_erro = GatewayUnavailableError("timeout")
    assert client.post("/api/me/connect/painel").status_code == 502


# ------------------------------------------------------------------ trava de recebimento
def _run(coro):
    return asyncio.run(coro)


def test_trava_desligada_nao_bloqueia_nem_consulta_o_stripe(ctx, monkeypatch):
    client, db, gw = ctx()
    monkeypatch.setattr(server, "EXIGIR_RECEBIMENTO_ATIVO", False)
    _run(server._exigir_recebimento_ativo(_prof()))
    assert gw.status_chamadas == 0


def test_trava_ligada_bloqueia_quem_nao_esta_liberado(ctx, monkeypatch):
    client, db, gw = ctx()
    monkeypatch.setattr(server, "EXIGIR_RECEBIMENTO_ATIVO", True)
    with pytest.raises(HTTPException) as e:
        _run(server._exigir_recebimento_ativo(_prof(connect_ready=False)))
    assert e.value.status_code == 409
    with pytest.raises(HTTPException):
        _run(server._exigir_recebimento_ativo(None))
    with pytest.raises(HTTPException):   # sem conta conectada nenhuma
        _run(server._exigir_recebimento_ativo(_prof(stripe_account_id=None, connect_ready=True)))


def test_trava_ligada_libera_quem_esta_pronto_sem_consultar(ctx, monkeypatch):
    client, db, gw = ctx()
    monkeypatch.setattr(server, "EXIGIR_RECEBIMENTO_ATIVO", True)
    _run(server._exigir_recebimento_ativo(_prof(connect_ready=True)))
    assert gw.status_chamadas == 0


def test_trava_confere_no_stripe_quando_o_cache_esta_defasado(ctx, monkeypatch):
    client, db, gw = ctx()
    monkeypatch.setattr(server, "EXIGIR_RECEBIMENTO_ATIVO", True)
    gw.status.update(charges_enabled=True, payouts_enabled=True)   # liberou, mas o cache não sabe
    _run(server._exigir_recebimento_ativo(_prof(connect_ready=False)))
    assert db.users.docs[0]["connect_ready"] is True
    # e se o Stripe estiver fora do ar, bloqueia (não libera no escuro)
    gw.status_erro = GatewayUnavailableError("x")
    with pytest.raises(HTTPException):
        _run(server._exigir_recebimento_ativo(_prof(connect_ready=False)))


def _fakes_de_reserva(monkeypatch, prof):
    async def cliente(nome, tel):
        return {"user_id": "cli", "email": "c@x.com", "name": nome}

    async def valida(servico_id, horario, reserva_no_cartao=True):
        svc = {"servico_id": "svc_1", "profissional_id": "u1", "valor_centavos": 12000,
               "moeda": "BRL", "taxa_no_show_centavos": 3000}
        return svc, prof, horario + timedelta(hours=1)

    monkeypatch.setattr(server, "_find_or_create_cliente_por_telefone", cliente)
    monkeypatch.setattr(server, "_valida_servico_e_conflito", valida)


CORPO = {"profissional_id": "u1", "servico_id": "svc_1", "horario_inicio": "2026-10-20T11:00:00Z",
         "nome": "Maria Silva", "telefone": "11987654321"}


@pytest.mark.parametrize("rota,extra", [("/api/public/agendamentos/cartao", {"payment_method_id": "pm_1"}),
                                        ("/api/public/agendamentos/pix", {})])
def test_reserva_publica_recusada_se_profissional_nao_recebe(ctx, monkeypatch, rota, extra):
    client, db, gw = ctx()
    monkeypatch.setattr(server, "EXIGIR_RECEBIMENTO_ATIVO", True)
    _fakes_de_reserva(monkeypatch, _prof(connect_ready=False))
    r = client.post(rota, json={**CORPO, **extra})
    assert r.status_code == 409 and "recebimentos" in r.json()["detail"]


def test_reserva_publica_passa_pela_trava_quando_o_profissional_esta_liberado(ctx, monkeypatch):
    client, db, gw = ctx()
    monkeypatch.setattr(server, "EXIGIR_RECEBIMENTO_ATIVO", True)
    _fakes_de_reserva(monkeypatch, _prof(connect_ready=True))
    r = client.post("/api/public/agendamentos/cartao", json={**CORPO, "payment_method_id": "pm_1"})
    assert r.status_code == 402   # chegou no pagamento (a sentinela recusa o cartão)


def test_reserva_publica_com_trava_desligada_nao_exige_nada(ctx, monkeypatch):
    client, db, gw = ctx()
    monkeypatch.setattr(server, "EXIGIR_RECEBIMENTO_ATIVO", False)
    _fakes_de_reserva(monkeypatch, _prof(connect_ready=False))
    r = client.post("/api/public/agendamentos/cartao", json={**CORPO, "payment_method_id": "pm_1"})
    assert r.status_code == 402


def test_perfil_publico_avisa_se_nao_aceita_agendamentos(ctx, monkeypatch):
    user = _prof(connect_ready=False)
    client, db, gw = ctx(user=user)
    monkeypatch.setattr(server, "EXIGIR_RECEBIMENTO_ATIVO", True)
    assert client.get("/api/profissionais/u1").json()["aceita_agendamentos"] is False
    db.users.docs[0]["connect_ready"] = True
    assert client.get("/api/profissionais/u1").json()["aceita_agendamentos"] is True
    monkeypatch.setattr(server, "EXIGIR_RECEBIMENTO_ATIVO", False)
    db.users.docs[0]["connect_ready"] = False
    assert client.get("/api/profissionais/u1").json()["aceita_agendamentos"] is True


def test_job_libera_so_quem_o_stripe_aprovou(ctx):
    outro = {**_prof(user_id="u2", email="b@x.com", stripe_account_id="acct_2")}
    client, db, gw = ctx(user=_prof(connect_ready=False))
    db.users.docs.append(outro)
    gw.status.update(charges_enabled=True, payouts_enabled=True)
    assert _run(server._atualizar_connect_pendentes()) == 2
    assert all(d["connect_ready"] for d in db.users.docs)
    gw.status.update(charges_enabled=False)
    db.users.docs[0]["connect_ready"] = False
    db.users.docs[1]["connect_ready"] = True     # já liberado: nem é consultado
    chamadas = gw.status_chamadas
    assert _run(server._atualizar_connect_pendentes()) == 0
    assert gw.status_chamadas == chamadas + 1


# ------------------------------------------------------------------ exclusão de conta
def test_excluir_conta_cancela_a_assinatura_e_apaga_o_que_e_pessoal(ctx):
    user = _prof(plano="ultra", stripe_subscription_id="sub_1", stripe_customer_id="cus_a",
                 stripe_billing_customer_id="cus_b", plano_cobranca_pendente=True,
                 plano_pendente={"subscription_id": "sub_2"}, telefone="11999999999", picture="http://x/y.png")
    client, db, gw = ctx(user=user,
                         device_tokens=[{"user_id": "u1", "expo_push_token": "ExpoPushToken[x]"}],
                         customer_cards=[{"user_id": "u1", "last4": "4242"}])
    db.user_sessions.docs.append({"user_id": "u1", "token": "t"})
    r = client.delete("/api/me")
    assert r.status_code == 200
    assert sorted(gw.cancelados) == ["sub_1", "sub_2"]
    assert sorted(gw.clientes_apagados) == ["cus_a", "cus_b"]
    u = db.users.docs[0]
    assert u["name"] == "Usuário excluído" and u["email"].endswith("@showup.excluido")
    assert u["plano"] == "free" and u["picture"] is None and u["telefone"] is None and "deleted_at" in u
    for campo in ("stripe_subscription_id", "stripe_customer_id", "stripe_billing_customer_id",
                  "stripe_account_id", "plano_pendente", "plano_cobranca_pendente"):
        assert campo not in u
    assert db.device_tokens.docs == [] and db.customer_cards.docs == [] and db.user_sessions.docs == []


def test_excluir_conta_NAO_exclui_se_nao_conseguiu_cancelar_a_cobranca(ctx):
    client, db, gw = ctx(user=_prof(plano="ultra", stripe_subscription_id="sub_1"))
    gw.cancel_erro = RuntimeError("stripe fora do ar")
    r = client.delete("/api/me")
    assert r.status_code == 503 and "não foi excluída" in r.json()["detail"]
    assert db.users.docs[0]["name"] == "Ana Lima" and "deleted_at" not in db.users.docs[0]


def test_excluir_conta_continua_bloqueada_com_reserva_futura(ctx):
    futuro = datetime.now(timezone.utc) + timedelta(days=2)
    ag = {"profissional_id": "u1", "cliente_id": "c", "status_agendamento": "agendado",
          "hold_status": "capturado_total", "horario_inicio": futuro}
    client, db, gw = ctx(agendamentos=[ag])
    assert client.delete("/api/me").status_code == 409
    assert gw.cancelados == [] and db.users.docs[0]["name"] == "Ana Lima"


def test_excluir_conta_sem_plano_nem_cliente_no_stripe(ctx):
    client, db, gw = ctx(user=_prof(stripe_account_id=None))
    assert client.delete("/api/me").status_code == 200
    assert gw.cancelados == [] and gw.clientes_apagados == []


# ------------------------------------------------------------------ webhooks da cobrança do plano
class Push:
    def __init__(self, monkeypatch):
        self.enviados = []

        async def falso(db, user_id, title, body, data):
            self.enviados.append((user_id, title, data))

        monkeypatch.setattr(webhooks, "push_para_usuario", falso)


def _db_assinante(**extra):
    return FakeDB([_prof(plano="profissional", stripe_subscription_id="sub_1", **extra)])


def test_cobranca_falhou_avisa_uma_vez_so(monkeypatch):
    push, db = Push(monkeypatch), _db_assinante()
    sub = {"id": "sub_1", "status": "past_due"}
    _run(webhooks._handle_subscription_change(db, sub))
    _run(webhooks._handle_subscription_change(db, sub))   # o Stripe reenvia o evento
    assert db.users.docs[0]["plano_cobranca_pendente"] is True
    assert push.enviados == [("u1", "Não conseguimos cobrar o seu plano", {"tipo": "cobranca_plano_falhou"})]
    assert db.users.docs[0]["plano"] == "profissional"   # mantém o plano enquanto o Stripe tenta de novo


def test_cobranca_regularizada_limpa_o_aviso_e_pode_avisar_de_novo(monkeypatch):
    push, db = Push(monkeypatch), _db_assinante()
    _run(webhooks._handle_subscription_change(db, {"id": "sub_1", "status": "past_due"}))
    _run(webhooks._handle_subscription_change(db, {"id": "sub_1", "status": "active"}))
    assert "plano_cobranca_pendente" not in db.users.docs[0]
    _run(webhooks._handle_subscription_change(db, {"id": "sub_1", "status": "past_due"}))
    assert len(push.enviados) == 2


def test_assinatura_cancelada_reverte_pro_free_e_limpa_tudo(monkeypatch):
    Push(monkeypatch)
    db = _db_assinante(plano_cobranca_pendente=True, plano_trial_termina_em=datetime.now(timezone.utc))
    _run(webhooks._handle_subscription_change(db, {"id": "sub_1", "status": "canceled"}))
    u = db.users.docs[0]
    assert u["plano"] == "free"
    for campo in ("stripe_subscription_id", "plano_cobranca_pendente", "plano_trial_termina_em"):
        assert campo not in u


def test_aviso_de_fim_do_teste_gratis(monkeypatch):
    push, db = Push(monkeypatch), _db_assinante()
    _run(webhooks._handle_trial_will_end(db, {"id": "sub_1"}))
    assert push.enviados == [("u1", "Seu teste grátis está acabando", {"tipo": "trial_will_end"})]
    _run(webhooks._handle_trial_will_end(db, {"id": "sub_de_ninguem"}))   # assinatura desconhecida: ignora
    assert len(push.enviados) == 1


def test_resumo_do_plano_informa_cobranca_pendente(ctx):
    client, db, gw = ctx(user=_prof(plano="profissional", plano_cobranca_pendente=True))
    assert client.get("/api/me/plano/resumo").json()["cobranca_pendente"] is True
    db.users.docs[0]["plano"] = "free"      # no Free não faz sentido avisar de cobrança
    assert client.get("/api/me/plano/resumo").json()["cobranca_pendente"] is False


# ------------------------------------------------------------------ escolha do gateway pela chave do Stripe
CHAVE_LONGA = "A1b2C3d4E5f6G7h8I9j0K1l2M3n4"


@pytest.mark.parametrize("chave", [f"sk_test_{CHAVE_LONGA}", f"sk_live_{CHAVE_LONGA}",
                                   f"rk_test_{CHAVE_LONGA}", f"rk_live_{CHAVE_LONGA}", f"  sk_live_{CHAVE_LONGA}\\n"])
def test_chave_do_stripe_de_teste_ou_producao_liga_o_gateway_real(chave):
    assert server._gateway_para_chave(chave) == "stripe"


@pytest.mark.parametrize("chave", ["", "   ", None])
def test_sem_chave_usa_o_modo_simulado(chave):
    assert server._gateway_para_chave(chave) == "mock"


@pytest.mark.parametrize("chave", ["sk_test_...", "sk_live_curta", "abc123", f"pk_live_{CHAVE_LONGA}",
                                   f"sk_prod_{CHAVE_LONGA}"])
def test_chave_preenchida_mas_irreconhecivel_nao_cai_no_modo_simulado(chave):
    # o modo simulado "aprova" reservas sem cobrar nada: em produção isso seria silencioso e caro
    with pytest.raises(RuntimeError, match="STRIPE_API_KEY"):
        server._gateway_para_chave(chave)
