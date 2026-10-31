"""Avisos ao CLIENTE: confirmação da reserva e lembretes (24 h e 2 h antes), por push no app ou e-mail; e a brecha de
cancelar depois do horário. Hoje nos testes: terça 20/10/2026, 12:00 em São Paulo (fixture ctx de test_notificacoes)."""
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import offline_env  # noqa: E402,F401

import pytest
from fastapi.testclient import TestClient

import avisos_cliente as ac
import notificacoes
import server
import webhooks
from test_notificacoes import AGORA, _assinar, _evento_pix, agendamento, ctx, rodar  # noqa: F401  (ctx é fixture)


@pytest.fixture
def cliente(ctx, monkeypatch):
    """Push e e-mail falsos, contando tudo o que sai. O cliente cli1 NÃO tem aparelho registrado (só o profissional)."""
    db, push_prof = ctx
    saida = {"push": [], "email": []}

    async def push(db_, user_id, title, body, data):
        saida["push"].append({"user_id": user_id, "title": title, "body": body, "data": data})
        tem = any(t["user_id"] == user_id for t in db_.device_tokens.docs)
        return "enviado" if tem else "sem_token"

    async def email(para, assunto, texto):
        saida["email"].append({"para": para, "assunto": assunto, "texto": texto})

    monkeypatch.setattr(ac, "push_para_usuario", push)
    monkeypatch.setattr(ac, "enviar_email", email)
    monkeypatch.setattr(ac, "email_configurado", lambda: True)
    monkeypatch.delenv("LEMBRETE_CLIENTE_HORAS", raising=False)
    return db, saida


def do_cliente(saida):
    return [p for p in saida["push"] if p["user_id"] == "cli1"]


# ------------------------------------------------------------------ textos e dinheiro
def test_valor_em_centavos_inteiros_no_formato_de_cada_idioma():
    assert ac.formatar_valor(12000, "BRL") == "R$ 120,00"
    assert ac.formatar_valor(12000, "BRL", "en") == "R$ 120.00"
    assert ac.formatar_valor(123456789, "BRL") == "R$ 1.234.567,89"
    assert ac.formatar_valor(123456789, "USD", "en") == "US$ 1,234,567.89"
    assert ac.formatar_valor(5, "EUR", "es") == "€ 0,05"
    assert ac.formatar_valor(29, "BRL") == "R$ 0,29"                     # 0.29 em float viraria 0,28
    assert ac.formatar_valor(-1500, "BRL") == "-R$ 15,00"


def test_quando_no_fuso_do_profissional_em_cada_idioma():
    amanha = datetime(2026, 10, 21, 13, 30, tzinfo=timezone.utc)          # 10:30 em São Paulo
    assert ac.quando(amanha, "America/Sao_Paulo", "pt", AGORA) == "amanhã às 10:30"
    assert ac.quando(amanha, "America/Sao_Paulo", "en", AGORA) == "tomorrow at 10:30"
    assert ac.quando(amanha, "America/Sao_Paulo", "es", AGORA) == "mañana a las 10:30"
    sexta = datetime(2026, 10, 23, 13, 30, tzinfo=timezone.utc)
    assert ac.quando(sexta, "America/Sao_Paulo", "pt", AGORA) == "sex, 23/10 às 10:30"
    assert ac.quando(sexta, "America/Sao_Paulo", "en", AGORA) == "Fri, 10/23 at 10:30"
    assert ac.quando(sexta, "Europe/Lisbon", "pt", AGORA) == "sex, 23/10 às 14:30"


def test_email_inventado_pelo_showup_nunca_recebe_aviso():
    assert ac.email_de_verdade("Maria@X.com ") == "maria@x.com"
    for falso in ("tel_11987654321@showup.cliente", "deleted_u1@showup.excluido", "", None, "sem-arroba"):
        assert ac.email_de_verdade(falso) is None


@pytest.mark.parametrize("valor,esperado", [(None, [2, 24]), ("24,2", [2, 24]), ("2, 24, 2", [2, 24]), ("48", [48]),
                                            ("", []), ("0", []), ("abc,3", [3]), ("100", [])])
def test_antecedencias_configuraveis(monkeypatch, valor, esperado):
    if valor is None:
        monkeypatch.delenv("LEMBRETE_CLIENTE_HORAS", raising=False)
    else:
        monkeypatch.setenv("LEMBRETE_CLIENTE_HORAS", valor)
    assert ac.antecedencias_dos_lembretes() == esperado


def _dados(**extra):
    d = {"cliente_nome": "Maria", "prof_nome": "Eduardo", "servico_nome": "Corte", "cidade": "Sao Paulo",
         "quando": {"pt": "amanhã às 10:30", "en": "tomorrow at 10:30", "es": "mañana a las 10:30"},
         "pix": False, "valor_centavos": 12000, "taxa_centavos": 3000, "moeda": "BRL", "usa_app": True, "email": "m@x.com"}
    d.update(extra)
    return d


def test_email_do_cartao_diz_que_so_reserva_a_taxa_e_como_cancelar():
    assunto, texto = ac.montar_email("confirmado", _dados())
    assert assunto == "Agendamento confirmado: Corte, amanhã às 10:30"
    assert "Corte com Eduardo\namanhã às 10:30 (horário de Sao Paulo)" in texto
    assert "R$ 120,00 fica só reservado" in texto and "taxa de falta: R$ 30,00" in texto
    assert "Cancele pelo app ShowUp antes do horário" in texto


def test_email_do_link_manda_avisar_o_profissional_e_do_pix_nao_fala_em_taxa():
    _, texto = ac.montar_email("lembrete", _dados(usa_app=False, pix=True, taxa_centavos=0))
    assert "Pagamento por Pix confirmado: R$ 120,00." in texto
    assert "taxa" not in texto and "reservado" not in texto
    assert "Avise Eduardo antes do horário" in texto and "app" not in texto


def test_email_sai_no_idioma_do_cliente():
    assunto, texto = ac.montar_email("lembrete", _dados(), "es")
    assert assunto == "Recordatorio: Corte, mañana a las 10:30" and "Corte con Eduardo" in texto and "R$ 120,00" in texto
    assunto, texto = ac.montar_email("confirmado", _dados(), "en")
    assert assunto.startswith("Booking confirmed") and "R$ 120.00" in texto and "no-show fee is charged: R$ 30.00" in texto
    assert ac.montar_email("confirmado", _dados(), "fr")[0].startswith("Agendamento confirmado")    # sem tradução: português


# ------------------------------------------------------------------ confirmação
def test_confirmacao_vai_por_push_quando_o_cliente_tem_o_app(cliente):
    db, saida = cliente
    db.device_tokens.docs.append({"user_id": "cli1", "expo_push_token": "ExponentPushToken[cli]"})
    db.agendamentos.docs.append(agendamento())
    assert rodar(ac.avisar_cliente_confirmado(db, "agd_1", AGORA)) == "push"
    p = do_cliente(saida)[0]
    assert p["title"] == "Agendamento confirmado" and p["data"] == {"type": "cliente_confirmado", "agendamento_id": "agd_1"}
    assert p["body"] == "Personal Trainer com Eduardo, amanhã às 12:00. Não pode ir? Cancele pelo app antes do horário."
    assert saida["email"] == []                                              # o push chegou: sem e-mail repetido


def test_sem_push_vai_por_email_e_so_uma_vez(cliente):
    db, saida = cliente
    db.agendamentos.docs.append(agendamento())
    assert rodar(ac.avisar_cliente_confirmado(db, "agd_1", AGORA)) == "email"
    assert rodar(ac.avisar_cliente_confirmado(db, "agd_1", AGORA)) == "ja_avisado_ou_nao_confirmado"
    assert len(saida["email"]) == 1 and saida["email"][0]["para"] == "m@x.com"


def test_email_informado_no_link_vale_mais_que_o_da_conta(cliente):
    db, saida = cliente
    db.users.docs[1]["email"] = "tel_11987654321@showup.cliente"
    db.agendamentos.docs.append(agendamento(origem="link_publico", email_cliente="maria@gmail.com", idioma="es"))
    assert rodar(ac.avisar_cliente_confirmado(db, "agd_1", AGORA)) == "email"
    e = saida["email"][0]
    assert e["para"] == "maria@gmail.com" and e["assunto"].startswith("Reserva confirmada")
    assert "Avisa a Eduardo" in e["texto"]


def test_cliente_do_link_sem_email_e_sem_smtp_nao_quebram(cliente, monkeypatch):
    db, saida = cliente
    db.users.docs[1]["email"] = "tel_11987654321@showup.cliente"
    db.agendamentos.docs.append(agendamento(origem="link_publico"))
    assert rodar(ac.avisar_cliente_confirmado(db, "agd_1", AGORA)) == "sem_contato"
    db.users.docs[1]["email"] = "m@x.com"
    db.agendamentos.docs.append(agendamento("agd_2"))
    monkeypatch.setattr(ac, "email_configurado", lambda: False)
    assert rodar(ac.avisar_cliente_confirmado(db, "agd_2", AGORA)) == "sem_smtp"
    assert saida["email"] == []


def test_falha_no_email_nao_derruba_nada(cliente, monkeypatch):
    db, _ = cliente
    db.agendamentos.docs.append(agendamento())

    async def quebra(*a):
        raise OSError("smtp fora")
    monkeypatch.setattr(ac, "enviar_email", quebra)
    assert rodar(ac.avisar_cliente_confirmado(db, "agd_1", AGORA)) == "falha_email"


def test_pix_ainda_nao_pago_nao_confirma(cliente):
    db, saida = cliente
    db.agendamentos.docs.append(agendamento(hold_status="aguardando_pix"))
    assert rodar(ac.avisar_cliente_confirmado(db, "agd_1", AGORA)) == "ja_avisado_ou_nao_confirmado"
    assert saida["email"] == [] and do_cliente(saida) == []


def test_reserva_pelo_link_guarda_email_e_idioma_e_confirma_ao_cliente(cliente, monkeypatch):
    db, saida = cliente
    from test_notificacoes import _fakes_de_reserva
    _fakes_de_reserva(monkeypatch, db)
    monkeypatch.setattr(server, "EXIGIR_RECEBIMENTO_ATIVO", False)
    inicio = (AGORA + timedelta(days=1)).replace(minute=0)
    corpo = {"profissional_id": "u1", "servico_id": "svc_1", "horario_inicio": inicio.isoformat(), "nome": "Maria Souza",
             "telefone": "11987654321", "payment_method_id": "pm_1", "email": "Maria@Gmail.com"}
    r = TestClient(server.app).post("/api/public/agendamentos/cartao", json=corpo, headers={"Accept-Language": "es-MX"})
    assert r.status_code == 200, r.text
    ag = db.agendamentos.docs[-1]
    assert ag["email_cliente"] == "maria@gmail.com" and ag["idioma"] == "es" and ag["origem"] == "link_publico"
    assert ag.get("aviso_cliente_confirmado_em") is not None
    assert [e["para"] for e in saida["email"]] == ["maria@gmail.com"] and saida["email"][0]["assunto"].startswith("Reserva confirmada")


def test_pix_pago_pelo_webhook_confirma_ao_cliente_uma_vez(cliente, monkeypatch):
    db, saida = cliente
    db.agendamentos.docs.append(agendamento("agd_pix", hold_status="aguardando_pix", payment_intent_id="pi_pix",
                                            origem="link_publico", email_cliente="maria@gmail.com", valor_no_show_centavos=0))
    monkeypatch.setattr(webhooks, "_get_db", lambda: db)
    monkeypatch.setattr(webhooks, "_WEBHOOK_SECRET", "whsec_teste")
    monkeypatch.setattr(webhooks, "_CONNECT_WEBHOOK_SECRET", "")
    monkeypatch.setattr(webhooks, "avisar_novo_agendamento", notificacoes.avisar_novo_agendamento)
    client = TestClient(server.app)
    for evento in ("evt_1", "evt_1", "evt_2"):
        corpo = _evento_pix(evento)
        assert client.post("/api/webhooks/stripe", content=corpo, headers={"stripe-signature": _assinar(corpo, "whsec_teste")}).status_code == 200
    assert len(saida["email"]) == 1 and "Pagamento por Pix confirmado: R$ 120,00." in saida["email"][0]["texto"]


# ------------------------------------------------------------------ lembretes
def em(horas, **extra):
    return agendamento(f"agd_{horas}", inicio=AGORA + timedelta(hours=horas), **extra)


def test_lembrete_de_24h_e_de_2h_uma_vez_cada(cliente):
    db, saida = cliente
    db.agendamentos.docs.append(em(23.5))
    assert rodar(ac.enviar_lembretes(db, AGORA)) == {"lembretes": 1, "ignorados": 0}
    assert rodar(ac.enviar_lembretes(db, AGORA)) == {"lembretes": 0, "ignorados": 0}          # não repete
    assert saida["email"][0]["assunto"].startswith("Lembrete: Personal Trainer")
    depois = AGORA + timedelta(hours=22)                                                      # faltam 1,5 h
    assert rodar(ac.enviar_lembretes(db, depois)) == {"lembretes": 1, "ignorados": 0}
    assert rodar(ac.enviar_lembretes(db, depois)) == {"lembretes": 0, "ignorados": 0}
    assert len(saida["email"]) == 2


def test_dois_jobs_lendo_o_mesmo_agendamento_mandam_um_lembrete_so(cliente):
    """Dois processos do servidor (ou um job atrasado) leem a MESMA lista: só quem reivindica primeiro envia."""
    db, saida = cliente
    db.agendamentos.docs.append(em(1))
    original = db.agendamentos.find

    def lista_lida_antes(q, proj=None):
        cursor = original(q, proj)
        cursor.docs = cursor.docs * 2                      # o mesmo agendamento aparece duas vezes
        return cursor
    db.agendamentos.find = lista_lida_antes
    assert rodar(ac.enviar_lembretes(db, AGORA))["lembretes"] == 1
    assert len(saida["email"]) == 1


def test_servidor_fora_do_ar_manda_um_lembrete_so(cliente):
    """Voltou a 1 h do horário sem ter mandado o de 24 h: sai UM lembrete, não dois."""
    db, saida = cliente
    db.agendamentos.docs.append(em(1))
    assert rodar(ac.enviar_lembretes(db, AGORA)) == {"lembretes": 1, "ignorados": 0}
    assert rodar(ac.enviar_lembretes(db, AGORA)) == {"lembretes": 0, "ignorados": 0}
    assert len(saida["email"]) == 1


def test_reserva_feita_depois_do_momento_do_lembrete_nao_o_recebe(cliente):
    """Reservou 5 h antes: a confirmação acabou de dizer o horário; o de 24 h não sai, o de 2 h sai."""
    db, saida = cliente
    db.agendamentos.docs.append(em(5, criado=AGORA - timedelta(minutes=10)))
    assert rodar(ac.enviar_lembretes(db, AGORA)) == {"lembretes": 0, "ignorados": 1}
    assert rodar(ac.enviar_lembretes(db, AGORA + timedelta(hours=3, minutes=30))) == {"lembretes": 1, "ignorados": 0}


@pytest.mark.parametrize("extra", [{"hold_status": "cancelado", "status_agendamento": "cancelado_cliente"},
                                   {"hold_status": "aguardando_pix"}, {"hold_status": "expirado"}])
def test_sem_lembrete_para_o_que_nao_esta_confirmado(cliente, extra):
    db, saida = cliente
    db.agendamentos.docs.append(em(1, **extra))
    assert rodar(ac.enviar_lembretes(db, AGORA))["lembretes"] == 0 and saida["email"] == []


def test_pix_pago_tambem_recebe_lembrete_e_lembretes_podem_ser_desligados(cliente, monkeypatch):
    db, saida = cliente
    db.agendamentos.docs.append(em(1, hold_status="pago_integral"))
    monkeypatch.setenv("LEMBRETE_CLIENTE_HORAS", "0")
    assert rodar(ac.enviar_lembretes(db, AGORA))["lembretes"] == 0
    monkeypatch.setenv("LEMBRETE_CLIENTE_HORAS", "2")
    assert rodar(ac.enviar_lembretes(db, AGORA))["lembretes"] == 1


def test_o_servidor_agenda_o_job_de_lembretes_do_cliente():
    fonte = Path(server.__file__).read_text(encoding="utf-8")
    import re
    assert re.search(r'^    _scheduler\.add_job\(_enviar_lembretes_cliente, "interval", minutes=5', fonte, re.M)
    assert "await enviar_lembretes_cliente(db, _now())" in fonte


# ------------------------------------------------------------------ brecha: cancelar depois do horário
def _como(monkeypatch, db, uid):
    async def eu(auth):
        return next(u for u in db.users.docs if u["user_id"] == uid)
    monkeypatch.setattr(server, "_current_user", eu)


def test_cliente_nao_cancela_depois_que_o_horario_comecou(ctx, monkeypatch):
    db, _ = ctx
    db.agendamentos.docs.append(agendamento(inicio=AGORA - timedelta(minutes=30)))
    desfeitas = []

    async def desfazer(*a):
        desfeitas.append(a)
    monkeypatch.setattr(server, "_desfazer_reserva", desfazer)
    monkeypatch.setattr(server, "_now", lambda: AGORA)
    _como(monkeypatch, db, "cli1")
    r = TestClient(server.app).post("/api/agendamentos/agd_1/cancelar")
    assert r.status_code == 409 and "já começou" in r.json()["detail"]
    assert desfeitas == [] and db.agendamentos.docs[0]["hold_status"] == "autorizado"      # a taxa de falta continua garantida
    _como(monkeypatch, db, "u1")                                                             # o profissional pode
    assert TestClient(server.app).post("/api/agendamentos/agd_1/cancelar").status_code == 200


def test_cliente_cancela_antes_do_horario(ctx, monkeypatch):
    db, _ = ctx
    db.agendamentos.docs.append(agendamento(inicio=AGORA + timedelta(minutes=5)))

    async def desfazer(*a):
        pass
    monkeypatch.setattr(server, "_desfazer_reserva", desfazer)
    monkeypatch.setattr(server, "_now", lambda: AGORA)
    _como(monkeypatch, db, "cli1")
    assert TestClient(server.app).post("/api/agendamentos/agd_1/cancelar").status_code == 200
    assert db.agendamentos.docs[0]["status_agendamento"] == "cancelado_cliente"


def test_excluir_a_conta_apaga_o_email_informado_nas_reservas():
    fonte = Path(server.__file__).read_text(encoding="utf-8")
    exclusao = fonte.split('"name": "Usuário excluído"', 1)[1][:3000]
    assert 'update_many({"cliente_id": user_id}, {"$unset": {"email_cliente": ""}})' in exclusao
