"""Brechas fechadas na revisão de 30/10/2026: horário ocupado por Pix, lista de agendamentos que perdia os novos,
busca que aceitava padrão em vez de texto, IP do limite de tentativas atrás do proxy e o índice único do banco.
Hoje nos testes: quarta-feira 21/10/2026, 10:00 em São Paulo (fixture `loja` de test_agenda_servidor)."""
import sys
from datetime import timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import offline_env  # noqa: E402,F401

import asyncio

import pytest
from fastapi.testclient import TestClient
from pymongo.errors import DuplicateKeyError, OperationFailure

import server
from test_agenda_servidor import AGORA, corpo_publico, loc, loja, slots, usuario  # noqa: F401  (loja é fixture)


def reserva(id_, inicio, minutos=60, hold="autorizado", **extra):
    return {"agendamento_id": id_, "profissional_id": "u1", "cliente_id": "cli1", "servico_id": "svc_1",
            "horario_inicio": inicio.astimezone(timezone.utc), "horario_fim": (inicio + timedelta(minutes=minutos)).astimezone(timezone.utc),
            "hold_status": hold, "status_agendamento": "agendado", "status_confirmacao": "pendente",
            "valor_total_centavos": 12000, "valor_no_show_centavos": 3000, "moeda": "BRL", "payment_intent_id": f"pi_{id_}",
            "hold_expira_em": AGORA + timedelta(days=7), "janela_confirmacao_expira_em": AGORA + timedelta(days=7),
            "criado_em": AGORA, **extra}


# ------------------------------------------------------------------ horário ocupado por Pix
@pytest.mark.parametrize("hold", ["pago_integral", "aguardando_pix"])
def test_horario_reservado_por_pix_nao_aparece_como_livre(loja, hold):
    db, _, _ = loja
    livres = slots(TestClient(server.app))
    assert loc(22, 10) in livres
    db.agendamentos.docs.append(reserva("agd_pix", loc(22, 10), hold=hold))
    assert loc(22, 10) not in slots(TestClient(server.app))


def test_atendimento_que_ja_comecou_continua_ocupando_o_horario(loja):
    """Das 09:00 às 11:30 (começou antes de agora, 10:00): as 11:00 ainda estão ocupadas."""
    db, _, _ = loja
    assert loc(21, 11) in slots(TestClient(server.app))
    db.agendamentos.docs.append(reserva("agd_longo", loc(21, 9), minutos=150))
    assert loc(21, 11) not in slots(TestClient(server.app))


@pytest.mark.parametrize("hold", ["pago_integral", "aguardando_pix"])
def test_app_nao_reserva_por_cima_de_um_horario_do_pix(loja, hold):
    db, gw, _ = loja
    db.agendamentos.docs.append(reserva("agd_pix", loc(22, 10), hold=hold))
    r = TestClient(server.app).post("/api/agendamentos", json={"servico_id": "svc_1", "horario_inicio": loc(22, 10).isoformat()})
    assert r.status_code == 409, r.text
    assert gw.autorizacoes == []                                   # nem chegou a reservar no cartão


@pytest.mark.parametrize("hold", ["pago_integral", "aguardando_pix"])
def test_link_nao_reserva_por_cima_de_um_horario_do_pix(loja, hold):
    db, gw, _ = loja
    db.agendamentos.docs.append(reserva("agd_pix", loc(22, 10), hold=hold))
    r = TestClient(server.app).post("/api/public/agendamentos/cartao", json=corpo_publico(loc(22, 10)))
    assert r.status_code == 409, r.text
    assert gw.autorizacoes == []


def test_todas_as_checagens_usam_a_mesma_lista_de_estados():
    """Uma lista só (STATUS_OCUPAM_HORARIO): se alguém reescrever a lista à mão num lugar, o Pix volta a escapar."""
    fonte = Path(server.__file__).read_text(encoding="utf-8")
    assert {"pago_integral", "aguardando_pix", "autorizado", "cancelando"} <= set(server.STATUS_OCUPAM_HORARIO)
    assert fonte.count('"hold_status": {"$in": STATUS_OCUPAM_HORARIO}') == 3     # horários livres + conflito no app + no link
    # a lista antiga, escrita à mão, só sobrevive num lugar: recriar o índice ANTIGO se o novo falhar
    assert fonte.count('["autorizado", "cancelando", "capturado_total", "capturado_taxa"]') == 1


# ------------------------------------------------------------------ lista de agendamentos
def test_lista_traz_os_agendamentos_mais_recentes_em_ordem_de_horario(loja, monkeypatch):
    db, _, _ = loja
    prof = db.users.docs[0]

    async def eu(auth):
        return prof
    monkeypatch.setattr(server, "_current_user", eu)
    base = loc(21, 9) - timedelta(days=300)
    db.agendamentos.docs += [reserva(f"agd_{i:03d}", base + timedelta(days=i), hold="capturado_total") for i in range(205)]
    db.agendamentos.docs.append(reserva("agd_novo", loc(22, 10)))
    r = TestClient(server.app).get("/api/agendamentos")
    assert r.status_code == 200, r.text
    ids = [a["agendamento_id"] for a in r.json()]
    assert len(ids) == server.LIMITE_LISTA_AGENDAMENTOS
    assert ids[-1] == "agd_novo"                                    # o novo aparece (antes: só os 200 mais antigos)
    assert "agd_000" not in ids                                     # os mais antigos é que ficam de fora
    inicios = [a["horario_inicio"] for a in r.json()]
    assert inicios == sorted(inicios)


def test_lista_busca_os_nomes_de_uma_vez_e_acerta_cada_um(loja, monkeypatch):
    db, _, _ = loja
    db.users.docs.append(usuario("cli2", "João Lima", papel="cliente"))
    db.servicos.docs.append({**db.servicos.docs[0], "servico_id": "svc_2", "nome": "Musculação"})
    db.agendamentos.docs += [reserva(f"agd_{i}", loc(22, 9) + timedelta(hours=i)) for i in range(30)]
    db.agendamentos.docs[-1].update(cliente_id="cli2", servico_id="svc_2")
    db.agendamentos.docs[-2].update(cliente_id="sumiu")
    consultas = {"find_one": 0}
    for col in (db.users, db.servicos):
        original = col.find_one

        async def contando(q, proj=None, _o=original):
            consultas["find_one"] += 1
            return await _o(q, proj)
        col.find_one = contando
    itens = asyncio.run(server._hydrate_varios(list(db.agendamentos.docs)))
    assert consultas["find_one"] == 0                               # antes: 3 por agendamento (90 aqui)
    assert (itens[0].cliente_nome, itens[0].servico_nome, itens[0].profissional_nome) == ("Maria Souza", "Corrida", "Eduardo Cerqueira")
    assert (itens[-1].cliente_nome, itens[-1].servico_nome) == ("João Lima", "Musculação")
    assert itens[-2].cliente_nome == "—"                            # cliente apagado não derruba a lista
    assert asyncio.run(server._hydrate_varios([])) == []


# ------------------------------------------------------------------ busca de profissionais
@pytest.fixture
def busca(loja):
    db, _, _ = loja
    db.users.docs += [usuario("u2", "Ana (Pilates)", categorias=["pilates"]), usuario("u3", "Sem Serviço")]
    db.servicos.docs.append({**db.servicos.docs[0], "servico_id": "svc_ana", "profissional_id": "u2"})
    client = TestClient(server.app)
    return lambda **p: client.get("/api/profissionais", params=p)


def test_busca_trata_o_texto_digitado_como_texto(busca):
    assert [p["name"] for p in busca(q="edu").json()] == ["Eduardo Cerqueira"]
    assert [p["name"] for p in busca(q="(Pilates)").json()] == ["Ana (Pilates)"]   # parênteses de verdade, não grupo
    for padrao in (".*", "a|e", "^", "(a+)+$", "[", "\\"):
        r = busca(q=padrao)
        assert r.status_code == 200 and r.json() == [], padrao           # antes: ".*" listava todo mundo e "[" dava erro


def test_busca_mostra_so_quem_tem_servico_ativo_em_ordem_alfabetica(busca):
    nomes = [p["name"] for p in busca().json()]
    assert nomes == ["Ana (Pilates)", "Eduardo Cerqueira"]
    assert busca().json()[1]["servicos_count"] == 1


# ------------------------------------------------------------------ IP real atrás do proxy (limite de tentativas)
def pedido(xff=None, direto="10.0.0.5"):
    return SimpleNamespace(headers={"x-forwarded-for": xff} if xff else {}, client=SimpleNamespace(host=direto))


def test_limite_por_ip_usa_o_ip_que_o_proxy_anotou(monkeypatch):
    monkeypatch.setattr(server, "PROXIES_NA_FRENTE", 1)
    assert server.ip_do_cliente(pedido("189.1.2.3")) == "189.1.2.3"            # antes: 10.0.0.5 para todo mundo
    # quem tenta se passar por outro IP escreve à ESQUERDA; o proxy anota o verdadeiro no fim
    assert server.ip_do_cliente(pedido("6.6.6.6, 189.1.2.3")) == "189.1.2.3"
    assert server.ip_do_cliente(pedido()) == "10.0.0.5"                        # sem proxy: o IP da conexão
    monkeypatch.setattr(server, "PROXIES_NA_FRENTE", 2)
    assert server.ip_do_cliente(pedido("6.6.6.6, 189.1.2.3, 172.64.0.1")) == "189.1.2.3"
    assert server.ip_do_cliente(pedido("189.1.2.3")) == "10.0.0.5"            # cadeia curta demais: não confia
    monkeypatch.setattr(server, "PROXIES_NA_FRENTE", 0)
    assert server.ip_do_cliente(pedido("189.1.2.3")) == "10.0.0.5"
    assert server.limiter._key_func is server.ip_do_cliente


# ------------------------------------------------------------------ índice único do banco
class ColIndices:
    def __init__(self, falhas=()):
        self.falhas, self.criados, self.apagados = list(falhas), [], []

    async def create_index(self, chave, **kw):
        if self.falhas:
            raise self.falhas.pop(0)
        self.criados.append((kw["name"], set(kw["partialFilterExpression"]["hold_status"]["$in"])))

    async def drop_index(self, nome):
        self.apagados.append(nome)


def indice(monkeypatch, falhas=()):
    col = ColIndices(falhas)
    monkeypatch.setattr(server, "db", SimpleNamespace(agendamentos=col))
    asyncio.run(server._garantir_indice_vaga_unica())
    return col


def test_indice_unico_cobre_o_pix_e_troca_o_antigo_sem_ficar_desprotegido(monkeypatch):
    col = indice(monkeypatch)
    assert col.criados == [("uniq_vaga_ativa", set(server.STATUS_OCUPAM_HORARIO))]
    assert {"pago_integral", "aguardando_pix"} <= col.criados[0][1]
    assert col.apagados == ["uniq_slot_ativo"]                       # o antigo só sai DEPOIS de o novo existir


def test_indice_se_o_mongo_recusa_dois_na_mesma_chave_troca_um_pelo_outro(monkeypatch):
    col = indice(monkeypatch, [OperationFailure("IndexKeySpecsConflict", 86)])
    assert col.apagados == ["uniq_slot_ativo"] and col.criados[0][0] == "uniq_vaga_ativa"


def test_indice_novo_falhando_recria_o_antigo(monkeypatch):
    col = indice(monkeypatch, [OperationFailure("conflito", 86), DuplicateKeyError("duplicadas")])
    assert col.apagados == ["uniq_slot_ativo"] and [n for n, _ in col.criados] == ["uniq_slot_ativo"]


def test_indice_com_reservas_duplicadas_mantem_o_antigo(monkeypatch):
    col = indice(monkeypatch, [DuplicateKeyError("duplicadas")])
    assert col.apagados == [] and col.criados == []
