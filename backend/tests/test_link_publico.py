"""Endereço legível do profissional (/p/eduardo-cerqueira): geração, unicidade, rota pública e link do app."""
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import offline_env  # noqa: E402,F401

import asyncio

import pytest
from fastapi.testclient import TestClient
from pymongo.errors import DuplicateKeyError

import server

AGORA = datetime(2026, 10, 20, 15, 0, tzinfo=timezone.utc)


class Res:
    def __init__(self, n):
        self.modified_count = n


class Col:
    def __init__(self, docs=None):
        self.docs = docs if docs is not None else []
        self.falhar_proxima_gravacao = False          # simula perder a corrida no índice único

    @staticmethod
    def _casa(d, q):
        for k, v in q.items():
            if isinstance(v, dict) and "$exists" in v:
                if (k in d) != v["$exists"]:
                    return False
            elif d.get(k) != v:
                return False
        return True

    async def find_one(self, q, proj=None):
        return next((dict(d) for d in self.docs if self._casa(d, q)), None)

    def find(self, q, proj=None):
        docs = [dict(d) for d in self.docs if self._casa(d, q)]

        class C:
            async def to_list(self, n):
                return docs[:n]

        return C()

    async def update_one(self, q, upd):
        if self.falhar_proxima_gravacao:
            self.falhar_proxima_gravacao = False
            raise DuplicateKeyError("E11000 duplicate key (slug)")
        alvo = next((d for d in self.docs if self._casa(d, q)), None)
        if not alvo:
            return Res(0)
        novo = upd["$set"].get("slug")
        if novo and any(d.get("slug") == novo for d in self.docs if d is not alvo):
            raise DuplicateKeyError("E11000 duplicate key (slug)")
        alvo.update(upd["$set"])
        return Res(1)


class DB:
    def __init__(self):
        self.users = Col()
        self.servicos = Col()


def usuario(uid, nome, papel="profissional", **extra):
    return {"user_id": uid, "name": nome, "role": papel, "email": f"{uid}@x.com", "created_at": AGORA, **extra}


@pytest.fixture
def db(monkeypatch):
    d = DB()
    monkeypatch.setattr(server, "db", d)
    monkeypatch.setattr(server, "PUBLIC_WEB_BASE_URL", "https://showup.exemplo.com.br")
    return d


def rodar(c):
    return asyncio.run(c)


# ------------------------------------------------------------------ _slugify
@pytest.mark.parametrize("nome,esperado", [
    ("Eduardo Cerqueira", "eduardo-cerqueira"),
    ("José da Conceição", "jose-da-conceicao"),
    ("  Ana  --  Lima!! ", "ana-lima"),
    ("Dr. João Pedro  (Fisio)", "dr-joao-pedro-fisio"),
    ("李雷", "profissional"),
    ("", "profissional"),
    ("🙂🙂", "profissional"),
])
def test_slugify(nome, esperado):
    assert server._slugify(nome) == esperado


def test_slugify_corta_em_40_sem_deixar_hifen_no_fim():
    s = server._slugify("Maria das Graças Fernandes de Albuquerque Cavalcanti Neto")
    assert len(s) <= 40 and not s.endswith("-") and not s.startswith("-") and s.startswith("maria-das-gracas")


# ------------------------------------------------------------------ _garantir_slug
def test_primeiro_profissional_fica_com_o_nome_e_o_slug_nao_muda(db):
    db.users.docs.append(usuario("u1", "Eduardo Cerqueira"))
    u = rodar(db.users.find_one({"user_id": "u1"}))
    assert rodar(server._garantir_slug(u)) == "eduardo-cerqueira"
    u["name"] = "Eduardo C. Silva"                                    # mudou de nome depois: o link antigo continua valendo
    u2 = rodar(db.users.find_one({"user_id": "u1"}))
    assert rodar(server._garantir_slug(u2)) == "eduardo-cerqueira"


def test_mesmo_nome_vira_numero_e_nunca_repete(db):
    for i in (1, 2, 3):
        db.users.docs.append(usuario(f"u{i}", "Maria Silva"))
    slugs = [rodar(server._garantir_slug(rodar(db.users.find_one({"user_id": f"u{i}"})))) for i in (1, 2, 3)]
    assert slugs == ["maria-silva", "maria-silva-2", "maria-silva-3"]


def test_perder_a_corrida_no_indice_unico_tenta_o_proximo_nome(db):
    db.users.docs.append(usuario("u1", "Maria Silva"))
    db.users.falhar_proxima_gravacao = True
    assert rodar(server._garantir_slug(rodar(db.users.find_one({"user_id": "u1"})))) == "maria-silva-2"


def test_pedido_repetido_do_mesmo_profissional_devolve_o_mesmo_slug(db):
    db.users.docs.append(usuario("u1", "Ana Lima"))
    velho = rodar(db.users.find_one({"user_id": "u1"}))                       # duas requisições leram o usuário SEM slug
    assert rodar(server._garantir_slug(velho)) == "ana-lima"
    assert rodar(server._garantir_slug(velho)) == "ana-lima"                   # a segunda não cria "ana-lima-2"
    assert [d["slug"] for d in db.users.docs] == ["ana-lima"]


# ------------------------------------------------------------------ rotas
def test_endpoint_do_link_devolve_url_do_servidor_e_so_para_profissional(db, monkeypatch):
    db.users.docs += [usuario("u1", "Eduardo Cerqueira"), usuario("c1", "Cliente", papel="cliente")]
    atual = {"id": "u1"}

    async def current(auth):
        return rodar_sync_find(db, atual["id"])

    monkeypatch.setattr(server, "_current_user", current)
    client = TestClient(server.app)
    r = client.get("/api/me/link-publico")
    assert r.status_code == 200
    assert r.json() == {"slug": "eduardo-cerqueira", "url": "https://showup.exemplo.com.br/p/eduardo-cerqueira"}
    atual["id"] = "c1"
    assert client.get("/api/me/link-publico").status_code == 403


def rodar_sync_find(db, uid):
    return next(dict(d) for d in db.users.docs if d["user_id"] == uid)


def test_perfil_publico_abre_pelo_slug_e_pelo_id_antigo(db):
    db.users.docs.append(usuario("user_abc123", "Eduardo Cerqueira", slug="eduardo-cerqueira", categorias=["Corrida"]))
    db.servicos.docs.append({"servico_id": "s1", "profissional_id": "user_abc123", "nome": "Corrida", "ativo": True, "duracao_min": 60,
                             "valor_centavos": 12000, "taxa_no_show_centavos": 3000, "moeda": "BRL", "criado_em": AGORA})
    client = TestClient(server.app)
    por_slug = client.get("/api/profissionais/eduardo-cerqueira")
    por_slug_maiusculo = client.get("/api/profissionais/Eduardo-Cerqueira")
    por_id = client.get("/api/profissionais/user_abc123")
    for r in (por_slug, por_slug_maiusculo, por_id):
        assert r.status_code == 200, r.text
        assert r.json()["user_id"] == "user_abc123" and r.json()["name"] == "Eduardo Cerqueira"
        assert [s["nome"] for s in r.json()["servicos"]] == ["Corrida"]      # os serviços vêm pelo id real, mesmo abrindo pelo slug


def test_slug_de_cliente_ou_inexistente_da_404(db):
    db.users.docs.append(usuario("c1", "Joana Cliente", papel="cliente", slug="joana-cliente"))
    client = TestClient(server.app)
    assert client.get("/api/profissionais/joana-cliente").status_code == 404
    assert client.get("/api/profissionais/ninguem").status_code == 404


def test_indice_unico_do_slug_e_criado_na_subida():
    fonte = (Path(server.__file__)).read_text(encoding="utf-8")
    assert 'db.users.create_index("slug", unique=True, sparse=True)' in fonte
