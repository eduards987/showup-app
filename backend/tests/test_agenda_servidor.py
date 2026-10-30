"""A janela da agenda no servidor: lista de horários (/slots) e recusa de reservas fora da regra nos 3 fluxos, antes de tocar no cartão.
Hoje nos testes: quarta-feira 21/10/2026, 10:00 em São Paulo."""
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import offline_env  # noqa: E402,F401

import asyncio

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

import server
from test_notificacoes import DB

SP = ZoneInfo("America/Sao_Paulo")
AGORA = datetime(2026, 10, 21, 10, 0, tzinfo=SP).astimezone(timezone.utc)


def usuario(uid, nome, papel="profissional", **extra):
    return {"user_id": uid, "name": nome, "role": papel, "email": f"{uid}@x.com", "created_at": AGORA, **extra}


def loc(dia, hora, minuto=0, mes=10):
    return datetime(2026, mes, dia, hora, minuto, tzinfo=SP).astimezone(timezone.utc)


class GW:
    def __init__(self):
        self.autorizacoes, self.voids, self.hold_expira = [], [], AGORA + timedelta(days=7)

    async def ensure_customer(self, *a):
        return "cus_1"

    async def authorize(self, **kw):
        self.autorizacoes.append(kw)
        return {"payment_intent_id": "pi_novo", "hold_expira_em": self.hold_expira}

    async def void(self, pi, idempotency_key=None):
        self.voids.append((pi, idempotency_key))

    async def create_pix_payment_intent(self, **kw):
        self.pix = getattr(self, "pix", []) + [kw]
        return {"payment_intent_id": "pi_pix", "client_secret": "cs_pix", "qr_code_data": "000201...", "hosted_instructions_url": None}


@pytest.fixture
def loja(monkeypatch):
    db = DB()
    db.users.docs += [usuario("u1", "Eduardo Cerqueira", timezone="America/Sao_Paulo"), usuario("cli1", "Maria Souza", papel="cliente")]
    db.servicos.docs.append({"servico_id": "svc_1", "profissional_id": "u1", "nome": "Corrida", "ativo": True, "duracao_min": 60, "valor_centavos": 12000,
                             "taxa_no_show_centavos": 3000, "moeda": "BRL", "criado_em": AGORA})
    db.customer_cards.docs.append({"user_id": "cli1", "customer_id": "cus_1", "payment_method_id": "pm_1"})
    gw = GW()

    async def cliente(nome, tel):
        return {"user_id": "cli1", "email": "m@x.com", "name": "Maria Souza"}

    async def usuario_atual(auth):
        return db.users.docs[1]

    monkeypatch.setattr(server, "db", db)
    monkeypatch.setattr(server, "gateway", gw)
    monkeypatch.setattr(server, "_now", lambda: AGORA)
    monkeypatch.setattr(server, "EXIGIR_RECEBIMENTO_ATIVO", False)
    monkeypatch.setattr(server, "_find_or_create_cliente_por_telefone", cliente)
    monkeypatch.setattr(server, "_current_user", usuario_atual)

    def atende(dias, ini="09:00", fim="12:00"):
        db.disponibilidade.docs[:] = [{"profissional_id": "u1", "weekday": d, "hora_inicio": ini, "hora_fim": fim} for d in dias]

    atende([0, 1, 2, 3, 4])
    return db, gw, atende


def rodar(c):
    return asyncio.run(c)


def slots(client):
    r = client.get("/api/profissionais/u1/slots", params={"servico_id": "svc_1"})
    assert r.status_code == 200, r.text
    return [datetime.fromisoformat(s["iso"]).astimezone(SP) for s in r.json()]


# ------------------------------------------------------------------ lista de horários
def test_seg_a_sex_oferece_so_os_proximos_5_dias_de_atendimento(loja):
    _, _, _ = loja
    dias = sorted({s.date() for s in slots(TestClient(server.app))})
    # 21 (qua), 22 (qui), 23 (sex), 26 (seg): nunca fim de semana, e nada além de ter 27 (o 5º dia, ainda não aberto pelo prazo da reserva)
    assert [d.day for d in dias] == [21, 22, 23, 26]
    assert max(dias).day <= 27


def test_com_o_passar_do_tempo_o_quinto_dia_abre(loja, monkeypatch):
    """Expediente 09-18, seg a sex. De manhã (10:00) a terça 27 ainda não cabe no prazo da reserva; à tarde (16:00) já cabe."""
    _, _, atende = loja
    atende(range(5), "09:00", "18:00")
    client = TestClient(server.app)
    assert sorted({s.day for s in slots(client)}) == [21, 22, 23, 26]                  # quarta 10:00: 4 dias (o 5º ainda não abriu)
    monkeypatch.setattr(server, "_now", lambda: loc(21, 16))
    assert sorted({s.day for s in slots(client)}) == [21, 22, 23, 26, 27]              # quarta 16:00: os 5 dias de atendimento


def test_atende_7_dias_oferece_7_dias_e_so_o_ultimo_e_aparado_pelo_prazo_da_reserva(loja):
    _, _, atende = loja
    atende(range(7))
    lista = slots(TestClient(server.app))
    assert sorted({s.day for s in lista}) == [21, 22, 23, 24, 25, 26]                 # 7º dia (27/10 de manhã) ainda além do prazo
    limite = AGORA + timedelta(days=5, hours=22)
    assert all(s.astimezone(timezone.utc) + timedelta(hours=1) <= limite for s in lista)   # nenhum atendimento termina depois do prazo


def test_atende_so_2_dias_oferece_so_2_dias(loja):
    _, _, atende = loja
    atende([2, 4])                                                      # quartas e sextas
    dias = sorted({s.day for s in slots(TestClient(server.app))})
    assert dias == [21, 23]                                             # qua (hoje, ainda há expediente) e sex: 2 dias de atendimento


def test_sem_horarios_cadastrados_nao_ha_o_que_oferecer(loja):
    _, _, atende = loja
    atende([])
    assert slots(TestClient(server.app)) == []


# ------------------------------------------------------------------ recusa de reservas fora da regra (sem tocar no cartão)
def corpo_publico(inicio):
    return {"profissional_id": "u1", "servico_id": "svc_1", "horario_inicio": inicio.isoformat(), "nome": "Maria", "telefone": "11987654321", "payment_method_id": "pm_1"}


def test_link_publico_recusa_data_longe_demais_sem_autorizar_o_cartao(loja):
    db, gw, _ = loja
    r = TestClient(server.app).post("/api/public/agendamentos/cartao", json=corpo_publico(loc(21, 9, mes=11)))     # 30 dias à frente
    assert r.status_code == 422 and "ainda não está aberto" in r.json()["detail"]
    assert gw.autorizacoes == [] and db.agendamentos.docs == []                          # o cartão do cliente nem foi consultado


def test_link_publico_recusa_horario_que_a_reserva_no_cartao_nao_cobriria(loja):
    db, gw, atende = loja
    atende(range(7), "00:00", "23:59")
    r = TestClient(server.app).post("/api/public/agendamentos/cartao", json=corpo_publico(loc(27, 12)))           # dentro dos 7 dias, mas fim > prazo
    assert r.status_code == 422 and "7 dias" in r.json()["detail"]
    assert gw.autorizacoes == [] and db.agendamentos.docs == []


def test_link_publico_aceita_horario_dentro_da_regra(loja):
    db, gw, _ = loja
    r = TestClient(server.app).post("/api/public/agendamentos/cartao", json=corpo_publico(loc(22, 10)))
    assert r.status_code == 200, r.text
    assert len(gw.autorizacoes) == 1 and len(db.agendamentos.docs) == 1
    assert db.agendamentos.docs[0]["janela_confirmacao_expira_em"] == loc(22, 11) + timedelta(hours=24)


def test_app_do_cliente_tambem_recusa_fora_da_janela(loja):
    db, gw, _ = loja
    r = TestClient(server.app).post("/api/agendamentos", json={"servico_id": "svc_1", "horario_inicio": loc(21, 9, mes=11).isoformat()})
    assert r.status_code == 422 and "ainda não está aberto" in r.json()["detail"]
    assert gw.autorizacoes == [] and db.agendamentos.docs == []
    ok = TestClient(server.app).post("/api/agendamentos", json={"servico_id": "svc_1", "horario_inicio": loc(22, 10).isoformat()})
    assert ok.status_code == 200, ok.text


def test_profissional_sem_horarios_nao_recebe_reservas(loja):
    db, gw, atende = loja
    atende([])
    r = TestClient(server.app).post("/api/public/agendamentos/cartao", json=corpo_publico(loc(22, 10)))
    assert r.status_code == 422 and "ainda não abriu horários" in r.json()["detail"]
    assert gw.autorizacoes == []


def test_pix_nao_tem_prazo_de_reserva_mas_a_janela_continua(loja):
    _, _, atende = loja
    atende(range(7), "00:00", "23:59")
    tarde = loc(27, 12)
    with pytest.raises(HTTPException) as e:
        rodar(server._valida_servico_e_conflito("svc_1", tarde))                          # cartão: além do prazo
    assert e.value.status_code == 422 and "7 dias" in e.value.detail
    svc, prof, fim = rodar(server._valida_servico_e_conflito("svc_1", tarde, reserva_no_cartao=False))   # Pix: pago na hora
    assert svc["servico_id"] == "svc_1"
    with pytest.raises(HTTPException) as e:
        rodar(server._valida_servico_e_conflito("svc_1", loc(31, 12), reserva_no_cartao=False))          # mas a janela vale
    assert "ainda não está aberto" in e.value.detail


def test_toda_hora_oferecida_na_lista_e_aceita_ao_reservar_e_a_seguinte_nao(loja):
    """A lista e a reserva usam a mesma regra: nunca oferecer o que será recusado."""
    _, _, atende = loja
    atende(range(7), "00:00", "23:59")
    for s in slots(TestClient(server.app)):
        rodar(server._exigir_horario_na_agenda("u1", s, s + timedelta(hours=1)))
    ultimo = max(slots(TestClient(server.app)))
    with pytest.raises(HTTPException):
        rodar(server._exigir_horario_na_agenda("u1", ultimo + timedelta(hours=1), ultimo + timedelta(hours=2)))


# ------------------------------------------------------------------ cartão que vence antes de 7 dias
def test_cartao_com_reserva_curta_demais_e_desfeito_e_recusado(loja):
    db, gw, _ = loja
    gw.hold_expira = loc(22, 10, 30).astimezone(timezone.utc)                          # vence antes de o atendimento (22/10 10:00-11:00) acabar
    r = TestClient(server.app).post("/api/public/agendamentos/cartao", json=corpo_publico(loc(22, 10)))
    assert r.status_code == 422 and "poucos dias" in r.json()["detail"]
    assert len(gw.voids) == 1 and gw.voids[0][1].startswith("void_curto_")             # o limite do cartão do cliente é liberado
    assert db.agendamentos.docs == []


def test_cartao_com_reserva_um_pouco_mais_curta_encurta_o_prazo_de_confirmacao(loja):
    db, gw, _ = loja
    fim = loc(22, 11)
    gw.hold_expira = fim + timedelta(hours=10)
    r = TestClient(server.app).post("/api/public/agendamentos/cartao", json=corpo_publico(loc(22, 10)))
    assert r.status_code == 200, r.text
    assert db.agendamentos.docs[0]["janela_confirmacao_expira_em"] == fim + timedelta(hours=9)      # 1 h antes de vencer, não fim + 24 h
    assert gw.voids == []


def test_app_do_cliente_tambem_respeita_o_vencimento_real_da_reserva(loja):
    db, gw, _ = loja
    gw.hold_expira = loc(22, 10, 30).astimezone(timezone.utc)
    r = TestClient(server.app).post("/api/agendamentos", json={"servico_id": "svc_1", "horario_inicio": loc(22, 10).isoformat()})
    assert r.status_code == 422 and len(gw.voids) == 1 and db.agendamentos.docs == []


# ------------------------------------------------------------------ a ROTA do Pix: pago na hora, sem prazo de reserva, mas dentro da janela
def test_rota_do_pix_aceita_horario_alem_do_prazo_do_cartao_mas_recusa_fora_da_janela(loja, monkeypatch):
    db, gw, atende = loja
    monkeypatch.setattr(server, "GATEWAY_KIND", "stripe")
    atende(range(7), "00:00", "23:59")
    client = TestClient(server.app)
    # terça 27/10 12:00: dentro dos 7 dias de atendimento, mas o cartão NÃO cobriria (reserva venceria); o Pix paga na hora e vale
    r = client.post("/api/public/agendamentos/pix", json=corpo_publico(loc(27, 12)))
    assert r.status_code == 200, r.text
    assert len(gw.pix) == 1 and len(db.agendamentos.docs) == 1
    # a janela continua valendo no Pix: 30 dias à frente é recusado sem gerar cobrança
    r = client.post("/api/public/agendamentos/pix", json=corpo_publico(loc(21, 12, mes=11)))
    assert r.status_code == 422 and "ainda não está aberto" in r.json()["detail"]
    assert len(gw.pix) == 1                                                       # nenhuma cobrança nova foi gerada


# ------------------------------------------------------------------ expediente: pedido montado à mão NÃO fura o horário de atendimento
FORA = "Esse horário não está disponível"


@pytest.mark.parametrize("inicio,porque", [
    (loc(22, 8), "antes do expediente (09-12)"),
    (loc(22, 3), "madrugada"),
    (loc(22, 12), "depois do expediente"),
    (loc(22, 9, 17), "fora da grade de 60 em 60 min"),
    (loc(22, 11, 30), "começa no expediente mas termina depois do fim (12:30)"),
    (loc(24, 10), "sábado, dia de folga (dentro da janela de dias)"),
])
def test_reserva_forjada_fora_do_expediente_e_recusada_antes_do_cartao(loja, inicio, porque):
    db, gw, _ = loja
    client = TestClient(server.app)
    r = client.post("/api/public/agendamentos/cartao", json=corpo_publico(inicio))
    assert r.status_code == 422 and FORA in r.json()["detail"], porque
    r = client.post("/api/agendamentos", json={"servico_id": "svc_1", "horario_inicio": inicio.isoformat()})
    assert r.status_code == 422 and FORA in r.json()["detail"], porque
    assert gw.autorizacoes == [] and db.agendamentos.docs == []                              # o cartão do cliente nunca foi consultado


def test_reserva_de_horario_que_a_lista_oferece_continua_funcionando(loja):
    db, gw, _ = loja
    client = TestClient(server.app)
    oferecidos = slots(client)
    assert oferecidos, "sem horários oferecidos"
    r = client.post("/api/public/agendamentos/cartao", json=corpo_publico(oferecidos[0]))
    assert r.status_code == 200, r.text


def test_servico_de_90_minutos_so_aceita_a_grade_de_90(loja):
    db, gw, _ = loja
    db.servicos.docs[0]["duracao_min"] = 90
    client = TestClient(server.app)
    assert client.post("/api/public/agendamentos/cartao", json=corpo_publico(loc(22, 10))).status_code == 422          # 09:00 e 10:30, não 10:00
    assert client.post("/api/public/agendamentos/cartao", json=corpo_publico(loc(22, 10, 30))).status_code == 200


def test_menos_de_15_minutos_de_antecedencia_e_recusado(loja, monkeypatch):
    db, gw, _ = loja
    monkeypatch.setattr(server, "_now", lambda: loc(22, 9, 50))                                  # 10:00 daqui a 10 minutos
    r = TestClient(server.app).post("/api/public/agendamentos/cartao", json=corpo_publico(loc(22, 10)))
    assert r.status_code == 422 and FORA in r.json()["detail"] and gw.autorizacoes == []


def test_rota_do_pix_tambem_confere_o_expediente(loja, monkeypatch):
    db, gw, _ = loja
    monkeypatch.setattr(server, "GATEWAY_KIND", "stripe")
    r = TestClient(server.app).post("/api/public/agendamentos/pix", json=corpo_publico(loc(22, 3)))
    assert r.status_code == 422 and FORA in r.json()["detail"]
    assert getattr(gw, "pix", []) == []                                                        # nenhuma cobrança Pix foi gerada


def test_expediente_alterado_depois_de_listar_derruba_o_horario_antigo(loja):
    """O cliente abriu a lista, o profissional mudou o expediente: o horário que sumiu é recusado, sem cobrar."""
    db, gw, atende = loja
    client = TestClient(server.app)
    escolhido = slots(client)[0]
    atende([0, 1, 2, 3, 4], "14:00", "18:00")
    r = client.post("/api/public/agendamentos/cartao", json=corpo_publico(escolhido))
    assert r.status_code == 422 and FORA in r.json()["detail"] and gw.autorizacoes == []


# ------------------------------------------------------------------ adicional de conversão: gravado na reserva nos 3 fluxos
@pytest.mark.parametrize("moeda, taxa", [("BRL", 1000), ("USD", 1400)])
def test_os_tres_fluxos_cobram_o_adicional_so_fora_do_real(loja, monkeypatch, moeda, taxa):
    db, gw, atende = loja
    monkeypatch.setattr(server, "GATEWAY_KIND", "stripe")
    db.servicos.docs[0]["moeda"] = moeda
    client = TestClient(server.app)
    assert client.post("/api/public/agendamentos/cartao", json=corpo_publico(loc(22, 9))).status_code == 200
    assert client.post("/api/agendamentos", json={"servico_id": "svc_1", "horario_inicio": loc(22, 10).isoformat()}).status_code == 200
    assert client.post("/api/public/agendamentos/pix", json=corpo_publico(loc(22, 11))).status_code == 200
    assert [a["fee_bps"] for a in gw.autorizacoes] == [taxa, taxa]
    assert gw.pix[0]["fee_bps"] == taxa
    assert [ag["fee_bps"] for ag in db.agendamentos.docs] == [taxa, taxa, taxa]
