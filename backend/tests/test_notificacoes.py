"""Avisos ao profissional: novo agendamento, próximo atendimento, confirmação (correção) e teste de notificação.
Offline: banco falso (com cursor assíncrono), Expo e gateway falsos. Os registros de agendamento têm o MESMO formato do
banco real — só ids, sem nome de cliente nem de serviço — que é onde o código antigo quebrava."""
import hashlib
import hmac
import json
import re
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import offline_env  # noqa: E402,F401  (variáveis FALSAS, antes de importar o server)

import pytest
from fastapi.testclient import TestClient

import notificacoes
import server
import webhooks
from payment_errors import CardDeclinedError


# ------------------------------------------------------------------ banco falso
def _casa(doc, q):
    for k, cond in q.items():
        v = doc.get(k)
        if isinstance(cond, dict) and any(op.startswith("$") for op in cond):
            for op, arg in cond.items():
                ok = {
                    "$in": lambda: v in arg, "$ne": lambda: v != arg,
                    "$gt": lambda: v is not None and v > arg, "$gte": lambda: v is not None and v >= arg,
                    "$lt": lambda: v is not None and v < arg, "$lte": lambda: v is not None and v <= arg,
                    "$regex": lambda: v is not None and re.search(arg, v, re.I if "i" in cond.get("$options", "") else 0) is not None,
                    "$options": lambda: True,
                }[op]()
                if not ok:
                    return False
        elif v != cond:        # None também casa com campo AUSENTE, como no Mongo
            return False
    return True


class _Resultado:
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

    def sort(self, campo, direcao=1):
        self.docs = sorted(self.docs, key=lambda d: d.get(campo), reverse=direcao == -1)
        return self

    async def to_list(self, n):
        return [dict(d) for d in self.docs[:n]]


class Col:
    def __init__(self, docs=None):
        self.docs = docs if docs is not None else []

    async def find_one(self, q, proj=None):
        return next((dict(d) for d in self.docs if _casa(d, q)), None)

    def find(self, q, proj=None):
        return Cursor([d for d in self.docs if _casa(d, q)])

    async def insert_one(self, doc):
        self.docs.append(dict(doc))

    async def update_one(self, q, upd):
        for d in self.docs:
            if _casa(d, q):
                d.update(upd.get("$set", {}))
                return _Resultado(1)
        return _Resultado(0)

    async def find_one_and_update(self, q, upd):
        for d in self.docs:
            if _casa(d, q):
                antes = dict(d)
                d.update(upd.get("$set", {}))
                return antes
        return None

    async def delete_one(self, q):
        for i, d in enumerate(self.docs):
            if _casa(d, q):
                del self.docs[i]
                return


class DB:
    def __init__(self):
        for nome in ("users", "servicos", "agendamentos", "transacoes", "device_tokens", "customer_cards", "webhook_events", "disponibilidade"):
            setattr(self, nome, Col())


AGORA = datetime(2026, 10, 20, 15, 0, tzinfo=timezone.utc)          # 12:00 em São Paulo


def agendamento(id_="agd_1", inicio=None, criado=None, **extra):
    inicio = inicio or AGORA + timedelta(days=1)
    doc = {
        "agendamento_id": id_, "profissional_id": "u1", "cliente_id": "cli1", "servico_id": "svc_1",
        "horario_inicio": inicio, "horario_fim": inicio + timedelta(hours=1), "criado_em": criado or AGORA - timedelta(days=2),
        "status_agendamento": "agendado", "status_confirmacao": "pendente", "hold_status": "autorizado",
        "payment_intent_id": f"pi_{id_}", "valor_total_centavos": 12000, "valor_no_show_centavos": 3000, "moeda": "BRL",
        "hold_expira_em": inicio + timedelta(days=5), "janela_confirmacao_expira_em": inicio + timedelta(hours=25),
        "valor_capturado_centavos": 0,
        "push_pergunta_enviada_em": None, "push_urgencia_enviada_em": None,           # SEM cliente_nome/servico_nome: é assim no banco
    }
    doc.update(extra)
    return doc


@pytest.fixture
def ctx(monkeypatch):
    db = DB()
    db.users.docs += [
        {"user_id": "u1", "name": "Eduardo", "role": "profissional", "timezone": "America/Sao_Paulo",
         "email": "p@x.com", "created_at": AGORA},
        {"user_id": "cli1", "name": "Maria Souza", "role": "cliente", "email": "m@x.com", "created_at": AGORA},
    ]
    db.servicos.docs.append({"servico_id": "svc_1", "profissional_id": "u1", "nome": "Personal Trainer", "ativo": True,
                             "duracao_min": 60, "valor_centavos": 12000, "taxa_no_show_centavos": 3000, "moeda": "BRL"})
    db.device_tokens.docs.append({"user_id": "u1", "expo_push_token": "ExponentPushToken[abc]"})
    # atende todos os dias o dia inteiro: nestes testes a janela da agenda não pode ser o motivo de uma reserva falhar
    db.disponibilidade.docs += [{"profissional_id": "u1", "weekday": d, "hora_inicio": "00:00", "hora_fim": "23:59"} for d in range(7)]
    enviados = []

    async def espiao(db_, user_id, title, body, data):
        enviados.append({"user_id": user_id, "title": title, "body": body, "data": data})

    monkeypatch.setattr(server, "db", db)
    monkeypatch.setattr(notificacoes, "push_para_usuario", espiao)
    monkeypatch.setattr(server, "push_para_usuario", espiao)
    monkeypatch.setattr(server, "LEMBRETE_PROFISSIONAL_MIN", 60)
    return db, enviados


def rodar(coro):
    import asyncio
    return asyncio.run(coro)


# ------------------------------------------------------------------ texto e horário
@pytest.mark.parametrize("inicio,esperado", [
    (datetime(2026, 10, 20, 17, 30, tzinfo=timezone.utc), "hoje às 14:30"),
    (datetime(2026, 10, 21, 12, 0, tzinfo=timezone.utc), "amanhã às 09:00"),
    (datetime(2026, 10, 22, 12, 0, tzinfo=timezone.utc), "qui, 22/10 às 09:00"),
    (datetime(2026, 10, 21, 2, 30, tzinfo=timezone.utc), "hoje às 23:30"),       # 02:30 UTC de 21/10 ainda é 20/10 à noite em SP
    (datetime(2026, 10, 20, 17, 30), "hoje às 14:30"),                              # sem fuso (como o Mongo devolve) = UTC
])
def test_horario_e_mostrado_no_fuso_do_profissional_com_hoje_e_amanha(inicio, esperado):
    assert notificacoes.formatar_quando(inicio, "America/Sao_Paulo", AGORA) == esperado


def test_fuso_invalido_ou_ausente_cai_em_sao_paulo():
    inicio = datetime(2026, 10, 20, 17, 30, tzinfo=timezone.utc)
    assert notificacoes.formatar_quando(inicio, "Fuso/Inexistente", AGORA) == "hoje às 14:30"
    assert notificacoes.formatar_quando(inicio, None, AGORA) == "hoje às 14:30"


@pytest.mark.parametrize("minutos,texto", [(0, "Agora"), (1, "Agora"), (5, "Em 5 min"), (59, "Em 59 min"), (60, "Em 1 hora"),
                                            (90, "Em 1 h 30 min"), (120, "Em 2 h")])
def test_quanto_falta(minutos, texto):
    assert notificacoes.faltam_texto(minutos) == texto


# ------------------------------------------------------------------ novo agendamento
def test_novo_agendamento_avisa_o_profissional_com_nome_servico_e_horario(ctx):
    db, enviados = ctx
    db.agendamentos.docs.append(agendamento())
    assert rodar(notificacoes.avisar_novo_agendamento(db, "agd_1", AGORA)) is True
    assert enviados == [{"user_id": "u1", "title": "Novo agendamento", "data": {"type": "novo_agendamento", "agendamento_id": "agd_1"},
                         "body": "Maria Souza agendou Personal Trainer para amanhã às 12:00."}]
    assert db.agendamentos.docs[0]["push_novo_enviado_em"] == AGORA


def test_novo_agendamento_so_avisa_uma_vez(ctx):
    db, enviados = ctx
    db.agendamentos.docs.append(agendamento())
    assert rodar(notificacoes.avisar_novo_agendamento(db, "agd_1", AGORA)) is True
    assert rodar(notificacoes.avisar_novo_agendamento(db, "agd_1", AGORA)) is False
    assert len(enviados) == 1
    assert rodar(notificacoes.avisar_novo_agendamento(db, "nao_existe", AGORA)) is False


def test_cliente_ou_servico_que_sumiram_nao_derrubam_o_aviso(ctx):
    db, enviados = ctx
    db.agendamentos.docs.append(agendamento(cliente_id="apagado", servico_id="sumiu"))
    assert rodar(notificacoes.avisar_novo_agendamento(db, "agd_1", AGORA)) is True
    assert enviados[0]["body"] == "Um cliente agendou atendimento para amanhã às 12:00."


def test_falha_no_envio_nunca_derruba_quem_chamou(ctx, monkeypatch):
    db, enviados = ctx
    db.agendamentos.docs.append(agendamento())

    async def quebra(*a, **k):
        raise RuntimeError("expo fora do ar")

    monkeypatch.setattr(notificacoes, "push_para_usuario", quebra)
    assert rodar(notificacoes.avisar_novo_agendamento(db, "agd_1", AGORA)) is False       # devolve False, não levanta


def _fakes_de_reserva(monkeypatch, db, autorizar_ok=True):
    async def cliente(nome, tel):
        return {"user_id": "cli1", "email": "m@x.com", "name": "Maria Souza"}

    async def valida(servico_id, horario, reserva_no_cartao=True):
        return db.servicos.docs[0], db.users.docs[0], horario + timedelta(hours=1)

    class GW:
        async def ensure_customer(self, *a):
            return "cus_1"

        async def authorize(self, **kw):
            if not autorizar_ok:
                raise CardDeclinedError("recusado")
            return {"payment_intent_id": "pi_novo", "hold_expira_em": datetime.now(timezone.utc) + timedelta(days=6)}

    monkeypatch.setattr(server, "_find_or_create_cliente_por_telefone", cliente)
    monkeypatch.setattr(server, "_valida_servico_e_conflito", valida)
    monkeypatch.setattr(server, "gateway", GW())
    monkeypatch.setattr(server, "EXIGIR_RECEBIMENTO_ATIVO", False)


def _horario_futuro():
    return (datetime.now(timezone.utc) + timedelta(days=2)).replace(minute=0, second=0, microsecond=0)


def test_reserva_pelo_link_com_cartao_avisa_o_profissional(ctx, monkeypatch):
    db, enviados = ctx
    _fakes_de_reserva(monkeypatch, db)
    corpo = {"profissional_id": "u1", "servico_id": "svc_1", "horario_inicio": _horario_futuro().isoformat(),
             "nome": "Maria Souza", "telefone": "11987654321", "payment_method_id": "pm_1"}
    r = TestClient(server.app).post("/api/public/agendamentos/cartao", json=corpo)
    assert r.status_code == 200, r.text
    assert len(enviados) == 1 and enviados[0]["title"] == "Novo agendamento" and enviados[0]["user_id"] == "u1"
    assert enviados[0]["body"].startswith("Maria Souza agendou Personal Trainer para ")
    assert enviados[0]["data"]["agendamento_id"] == r.json()["agendamento_id"]


def test_cartao_recusado_nao_avisa_ninguem(ctx, monkeypatch):
    db, enviados = ctx
    _fakes_de_reserva(monkeypatch, db, autorizar_ok=False)
    corpo = {"profissional_id": "u1", "servico_id": "svc_1", "horario_inicio": _horario_futuro().isoformat(),
             "nome": "Maria", "telefone": "11987654321", "payment_method_id": "pm_1"}
    assert TestClient(server.app).post("/api/public/agendamentos/cartao", json=corpo).status_code == 402
    assert enviados == [] and db.agendamentos.docs == []


def test_reserva_dentro_do_app_avisa_o_profissional(ctx, monkeypatch):
    db, enviados = ctx
    _fakes_de_reserva(monkeypatch, db)
    db.customer_cards.docs.append({"user_id": "cli1", "customer_id": "cus_1", "payment_method_id": "pm_1"})

    async def usuario(auth):
        return db.users.docs[1]

    monkeypatch.setattr(server, "_current_user", usuario)
    r = TestClient(server.app).post("/api/agendamentos", json={"servico_id": "svc_1", "horario_inicio": _horario_futuro().isoformat()})
    assert r.status_code == 200, r.text
    assert len(enviados) == 1 and enviados[0]["title"] == "Novo agendamento"
    assert "Maria Souza agendou Personal Trainer" in enviados[0]["body"]


# ------------------------------------------------------------------ Pix pago
def _assinar(corpo: bytes, segredo: str) -> str:
    t = int(time.time())
    return f"t={t},v1=" + hmac.new(segredo.encode(), f"{t}.".encode() + corpo, hashlib.sha256).hexdigest()


def _evento_pix(evento_id):
    return json.dumps({"id": evento_id, "object": "event", "type": "payment_intent.succeeded",
                       "data": {"object": {"id": "pi_pix", "amount": 12000}}}).encode()


def test_pix_pago_avisa_o_profissional_uma_vez_so_mesmo_com_webhook_repetido(ctx, monkeypatch):
    db, enviados = ctx
    db.agendamentos.docs.append(agendamento("agd_pix", hold_status="aguardando_pix", payment_intent_id="pi_pix"))
    monkeypatch.setattr(webhooks, "_get_db", lambda: db)
    monkeypatch.setattr(webhooks, "_WEBHOOK_SECRET", "whsec_teste")
    monkeypatch.setattr(webhooks, "_CONNECT_WEBHOOK_SECRET", "")
    monkeypatch.setattr(webhooks, "avisar_novo_agendamento", notificacoes.avisar_novo_agendamento)
    client = TestClient(server.app)

    def enviar(evento_id):
        corpo = _evento_pix(evento_id)
        return client.post("/api/webhooks/stripe", content=corpo, headers={"stripe-signature": _assinar(corpo, "whsec_teste")})

    assert enviar("evt_1").status_code == 200
    assert db.agendamentos.docs[0]["hold_status"] == "pago_integral"
    assert [e["title"] for e in enviados] == ["Novo agendamento"] and enviados[0]["data"]["agendamento_id"] == "agd_pix"
    assert enviar("evt_1").status_code == 200            # o Stripe reenvia o MESMO evento
    assert enviar("evt_2").status_code == 200            # ou um evento novo para o mesmo pagamento
    assert len(enviados) == 1


def test_pix_ainda_nao_pago_nao_avisa(ctx):
    db, enviados = ctx
    db.agendamentos.docs.append(agendamento("agd_pix", hold_status="aguardando_pix", payment_intent_id="pi_pix"))
    assert enviados == []                                  # reservar o horário no Pix não é agendamento confirmado


# ------------------------------------------------------------------ correção: avisos de confirmação
def test_aviso_de_confirmacao_funciona_com_o_registro_real_do_banco_sem_nomes(ctx):
    """Antes: KeyError em ag['cliente_nome'] DEPOIS de marcar o aviso como enviado — o aviso nunca chegava."""
    db, enviados = ctx
    db.agendamentos.docs.append(agendamento("agd_p", inicio=datetime.now(timezone.utc) - timedelta(hours=3)))
    resultado = rodar(server._enviar_pushes_confirmacao())
    assert resultado["pergunta"] == 1
    assert enviados[0]["title"] == "Confirme o atendimento"
    assert enviados[0]["body"] == "Maria Souza tinha horário de Personal Trainer. Compareceu?"
    assert enviados[0]["data"] == {"type": "confirmacao_pendente", "agendamento_id": "agd_p"}
    assert rodar(server._enviar_pushes_confirmacao())["pergunta"] == 0 and len(enviados) == 1       # só uma vez


def test_aviso_de_ultima_chance_tambem_usa_o_nome_buscado(ctx):
    db, enviados = ctx
    agora = datetime.now(timezone.utc)
    db.agendamentos.docs.append(agendamento("agd_u", inicio=agora - timedelta(hours=20),
                                            janela_confirmacao_expira_em=agora + timedelta(hours=1), push_pergunta_enviada_em=agora))
    assert rodar(server._enviar_pushes_confirmacao())["urgencia"] == 1
    assert enviados[0]["title"] == "Última chance para confirmar" and "Maria Souza" in enviados[0]["body"]


# ------------------------------------------------------------------ próximo atendimento
def _agora_real():
    return datetime.now(timezone.utc)


def test_lembrete_avisa_o_proximo_atendimento_uma_vez(ctx):
    db, enviados = ctx
    inicio = _agora_real() + timedelta(minutes=45)
    db.agendamentos.docs.append(agendamento("agd_l", inicio=inicio, criado=_agora_real() - timedelta(days=3)))
    assert rodar(server._enviar_lembretes_proximo()) == {"lembretes": 1, "ignorados": 0}
    assert enviados[0]["title"] == "Próximo atendimento" and enviados[0]["data"] == {"type": "proximo_atendimento", "agendamento_id": "agd_l"}
    assert enviados[0]["body"].startswith("Em 4") and "Maria Souza — Personal Trainer." in enviados[0]["body"]       # "Em 44/45 min, às HH:MM: ..."
    assert rodar(server._enviar_lembretes_proximo()) == {"lembretes": 0, "ignorados": 0} and len(enviados) == 1


@pytest.mark.parametrize("extra,motivo", [
    ({"inicio": _agora_real() + timedelta(hours=3)}, "ainda falta muito"),
    ({"inicio": _agora_real() - timedelta(minutes=10)}, "já começou"),
    ({"inicio": _agora_real() + timedelta(minutes=30), "status_agendamento": "cancelado"}, "cancelado"),
    ({"inicio": _agora_real() + timedelta(minutes=30), "hold_status": "aguardando_pix"}, "Pix ainda não pago"),
    ({"inicio": _agora_real() + timedelta(minutes=30), "hold_status": "cancelado"}, "reserva cancelada"),
    ({"inicio": _agora_real() + timedelta(minutes=30), "hold_status": "expirado"}, "reserva expirada"),
])
def test_lembrete_ignora_o_que_nao_e_um_proximo_atendimento_confirmado(ctx, extra, motivo):
    db, enviados = ctx
    db.agendamentos.docs.append(agendamento("agd_x", criado=_agora_real() - timedelta(days=3), **extra))
    assert rodar(server._enviar_lembretes_proximo()) == {"lembretes": 0, "ignorados": 0}, motivo
    assert enviados == []


def test_lembrete_inclui_pix_pago(ctx):
    db, enviados = ctx
    db.agendamentos.docs.append(agendamento("agd_pix", inicio=_agora_real() + timedelta(minutes=30), hold_status="pago_integral",
                                            criado=_agora_real() - timedelta(days=1)))
    assert rodar(server._enviar_lembretes_proximo())["lembretes"] == 1


def test_reserva_feita_dentro_da_janela_nao_ganha_lembrete_repetido(ctx):
    """Reservou há 10 min para daqui a 40: o "Novo agendamento" acabou de dizer o horário."""
    db, enviados = ctx
    db.agendamentos.docs.append(agendamento("agd_c", inicio=_agora_real() + timedelta(minutes=40), criado=_agora_real() - timedelta(minutes=10)))
    assert rodar(server._enviar_lembretes_proximo()) == {"lembretes": 0, "ignorados": 1}
    assert enviados == [] and db.agendamentos.docs[0]["push_lembrete_enviado_em"] is not None       # marcado: não reavalia a cada 5 min
    assert rodar(server._enviar_lembretes_proximo()) == {"lembretes": 0, "ignorados": 0}


def test_cada_atendimento_tem_o_seu_lembrete_e_a_antecedencia_e_configuravel(ctx, monkeypatch):
    db, enviados = ctx
    db.agendamentos.docs += [
        agendamento("agd_a", inicio=_agora_real() + timedelta(minutes=30), criado=_agora_real() - timedelta(days=2)),
        agendamento("agd_b", inicio=_agora_real() + timedelta(minutes=100), criado=_agora_real() - timedelta(days=2)),
    ]
    assert rodar(server._enviar_lembretes_proximo())["lembretes"] == 1                 # janela de 60 min: só o primeiro
    monkeypatch.setattr(server, "LEMBRETE_PROFISSIONAL_MIN", 120)
    assert rodar(server._enviar_lembretes_proximo())["lembretes"] == 1                 # janela de 120 min: agora o segundo
    assert [e["data"]["agendamento_id"] for e in enviados] == ["agd_a", "agd_b"]


def test_lembrete_pode_ser_desligado(ctx, monkeypatch):
    db, enviados = ctx
    db.agendamentos.docs.append(agendamento("agd_a", inicio=_agora_real() + timedelta(minutes=30), criado=_agora_real() - timedelta(days=2)))
    monkeypatch.setattr(server, "LEMBRETE_PROFISSIONAL_MIN", 0)
    assert rodar(server._enviar_lembretes_proximo()) == {"lembretes": 0, "ignorados": 0} and enviados == []


# ------------------------------------------------------------------ teste de notificação
@pytest.fixture
def teste(ctx, monkeypatch):
    db, enviados = ctx
    estado = {"ticket": {"status": "ok", "id": "tk1"}, "recibo": {"status": "ok"}, "ticket_erro": None, "recibo_erro": None, "papel": "profissional"}

    async def usuario(auth):
        return {**db.users.docs[0], "role": estado["papel"]}

    async def send(token, title, body, data=None):
        if estado["ticket_erro"]:
            raise estado["ticket_erro"]
        return estado["ticket"]

    async def recibo(ticket_id):
        if estado["recibo_erro"]:
            raise estado["recibo_erro"]
        return estado["recibo"]

    monkeypatch.setattr(server, "_current_user", usuario)
    monkeypatch.setattr(server, "send_push", send)
    monkeypatch.setattr(server, "buscar_recibo", recibo)
    monkeypatch.setattr(server, "RECIBO_ESPERA_SEG", 0)
    return TestClient(server.app), db, estado


def test_teste_de_notificacao_com_tudo_certo(teste):
    client, db, estado = teste
    r = client.post("/api/me/notificacoes/teste")
    assert r.status_code == 200 and r.json() == {"enviado": True, "recibo": "ok", "etapa": None,
                                                "mensagem": "Notificação enviada. Ela deve aparecer no celular em instantes."}


def test_teste_sem_aparelho_registrado_explica_o_que_fazer(teste):
    client, db, estado = teste
    db.device_tokens.docs.clear()
    r = client.post("/api/me/notificacoes/teste")
    assert r.status_code == 409 and "permita as notificações" in r.json()["detail"]


def test_teste_so_para_profissional(teste):
    client, db, estado = teste
    estado["papel"] = "cliente"
    assert client.post("/api/me/notificacoes/teste").status_code == 403


def test_credencial_do_firebase_faltando_aparece_no_recibo_e_o_aparelho_continua_registrado(teste):
    client, db, estado = teste
    estado["recibo"] = {"status": "error", "message": "Unable to retrieve the FCM server key", "details": {"error": "InvalidCredentials"}}
    r = client.post("/api/me/notificacoes/teste").json()
    assert r["enviado"] is False and r["recibo"] == "erro" and "NOTIFICACOES.md" in r["mensagem"] and "FCM V1" in r["mensagem"]
    assert r["etapa"] == "recibo"                      # a Expo aceitou o pedido; quem não entregou foi o Firebase
    assert len(db.device_tokens.docs) == 1


@pytest.mark.parametrize("onde", ["ticket", "recibo"])
def test_aparelho_nao_registrado_na_expo_apaga_o_token_morto(teste, onde):
    client, db, estado = teste
    erro = {"status": "error", "message": "x", "details": {"error": "DeviceNotRegistered"}}
    estado["ticket" if onde == "ticket" else "recibo"] = erro
    r = client.post("/api/me/notificacoes/teste").json()
    assert r["enviado"] is False and "feche e abra o app" in r["mensagem"].lower()
    assert r["etapa"] == ("ticket" if onde == "ticket" else "recibo")
    assert db.device_tokens.docs == []


def test_recibo_ainda_nao_disponivel_diz_pendente_sem_dar_erro(teste):
    client, db, estado = teste
    estado["recibo"] = None
    r = client.post("/api/me/notificacoes/teste").json()
    assert r["enviado"] is True and r["recibo"] == "pendente" and "1 ou 2 minutos" in r["mensagem"]
    estado["recibo"] = {"status": "ok"}
    estado["recibo_erro"] = RuntimeError("rede")
    assert client.post("/api/me/notificacoes/teste").json()["recibo"] == "pendente"


def test_expo_fora_do_ar_vira_503_claro(teste):
    client, db, estado = teste
    estado["ticket_erro"] = RuntimeError("timeout")
    r = client.post("/api/me/notificacoes/teste")
    assert r.status_code == 503 and "serviço de notificações" in r.json()["detail"]


@pytest.mark.parametrize("codigo,trecho", [
    ("InvalidCredentials", "FCM V1"), ("MismatchSenderId", "OUTRO projeto"), ("DeviceNotRegistered", "registrado"),
    ("MessageRateExceeded", "Muitas notificações"), ("AlgoNovo", "AlgoNovo"), (None, "desconhecido"),
])
def test_erros_da_expo_viram_orientacao(codigo, trecho):
    assert trecho in notificacoes.explicar_erro_push(codigo, "detalhe")


def test_a_expo_recusar_o_pedido_e_etapa_ticket_e_nao_chega_a_pedir_recibo(teste):
    client, db, estado = teste
    estado["ticket"] = {"status": "error", "message": "Muitas", "details": {"error": "MessageRateExceeded"}}
    estado["recibo_erro"] = AssertionError("não devia buscar recibo de um pedido recusado")
    r = client.post("/api/me/notificacoes/teste").json()
    assert r["etapa"] == "ticket" and r["enviado"] is False and "Muitas notificações" in r["mensagem"]
