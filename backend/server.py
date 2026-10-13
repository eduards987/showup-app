"""ShowUp backend — auth + serviços + agendamentos + Stripe (real).

Changes vs. previous iteration:
  * StripeGateway instead of MockGateway (real PaymentIntents in test mode).
  * Profissional Connect Express onboarding (graceful fallback if Connect
    isn't enabled on the platform account yet).
  * Categorias por profissional (lista fixa) + filtro `categoria` no discovery.
  * Disponibilidade semanal por profissional; slots derivam dela.
  * Endpoint /reminders/janela: retorna agendamentos com janela terminando em
    menos de 6h (para banner do profissional).

Nota: sem `from __future__ import annotations` de propósito. O decorator
`@limiter.limit(...)` (slowapi) envolve a função com um wrapper cujo
`__globals__` não é o deste módulo; com anotações adiadas (PEP 563), o
FastAPI tenta resolver `SessionRequest`/`Request` como ForwardRef contra esse
wrapper e quebra a geração do schema OpenAPI. Como o projeto já roda em
Python 3.12, `list[str]`, `dict[str, Any]` e `X | None` funcionam nativamente
sem o future-import — não há motivo para mantê-lo.
"""

import logging
import os
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, time, timedelta, timezone
from pathlib import Path
from typing import Literal, Optional
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from dotenv import load_dotenv
from fastapi import APIRouter, Depends, FastAPI, Header, HTTPException, Query, Request
from fastapi.responses import RedirectResponse
from google.auth.exceptions import GoogleAuthError
from google.auth.transport import requests as google_requests
from google.oauth2 import id_token as google_id_token
import httpx
from motor.motor_asyncio import AsyncIOMotorClient
from pydantic import BaseModel, EmailStr, Field, field_validator
from pymongo.errors import DuplicateKeyError
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware
from slowapi.util import get_remote_address
from starlette.middleware.cors import CORSMiddleware

ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / ".env")

# Importados só depois do load_dotenv(): ambos leem variáveis de ambiente no
# momento do import (security.py falha o boot de propósito se o token não
# estiver setado), então precisam vir depois que o .env já foi carregado.
from security import require_service_token
from payment_errors import CardDeclinedError, GatewayUnavailableError, InvalidPaymentRequestError, PaymentError
from webhooks import router as webhooks_router
from expo_push import is_device_not_registered, send_push

mongo_url = os.environ["MONGO_URL"]
client = AsyncIOMotorClient(mongo_url)
db = client[os.environ["DB_NAME"]]

app = FastAPI(title="ShowUp API")
api_router = APIRouter(prefix="/api")

# Rate limiting: protege endpoints sensíveis a abuso (força-bruta de sessão,
# spam de agendamento/hold — que gera carga real no gateway de pagamento —
# e "card testing", onde um atacante usa /me/card repetidamente para validar
# cartões roubados). Limite por IP; endpoints autenticados poderiam evoluir
# para limite por user_id, mas IP já cobre o cenário de maior risco (um
# atacante não-autenticado batendo no /auth/session ou no /me/card).
#
# TESTING=1 desliga o rate limit inteiro: a suíte pytest chama os mesmos
# endpoints (setup-intent, auth/session, connect/onboarding) dezenas de
# vezes em segundos, todas do mesmo IP (localhost) — sem isso, os próprios
# testes acabam recebendo 429 em vez do status que estão verificando. Em
# produção essa env var nunca deve existir, então o default é proteção ativa.
_TESTING = os.environ.get("TESTING", "").lower() in ("1", "true", "yes")
limiter = Limiter(key_func=get_remote_address, default_limits=["200/minute"], enabled=not _TESTING)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
app.add_middleware(SlowAPIMiddleware)

# Login com o Google via navegador — GOOGLE_WEB_CLIENT_ID é o Client ID
# tipo "Web application" criado no Google Cloud Console (não o Android nem
# o iOS). É esse tipo especificamente porque é o único que aceita o
# redirect_uri HTTPS que usamos aqui (GOOGLE_OAUTH_REDIRECT_URI) — Client
# IDs tipo Android/iOS existem pra outro propósito (vincular ao
# certificado que assina o app) e não entram nesse fluxo.
GOOGLE_WEB_CLIENT_ID = os.environ.get("GOOGLE_WEB_CLIENT_ID", "")
if not GOOGLE_WEB_CLIENT_ID:
    raise RuntimeError(
        "GOOGLE_WEB_CLIENT_ID não configurado. Crie um OAuth Client ID tipo "
        "'Web application' no Google Cloud Console e coloque o valor no .env."
    )
# Client Secret do MESMO Client ID acima — só existe no backend, nunca no
# app. É o que prova pro Google que é realmente o nosso servidor trocando
# o code por tokens, não alguém que interceptou o code no meio do caminho.
GOOGLE_CLIENT_SECRET = os.environ.get("GOOGLE_CLIENT_SECRET", "")
if not GOOGLE_CLIENT_SECRET:
    raise RuntimeError(
        "GOOGLE_CLIENT_SECRET não configurado. Está na mesma tela do Google "
        "Cloud Console onde pegou o GOOGLE_WEB_CLIENT_ID."
    )
# URL completa desse próprio backend + /api/auth/google/callback — tem que
# ser IDÊNTICA (char por char) à cadastrada como "URI de redirecionamento
# autorizado" no Client ID Web do Google Cloud Console.
GOOGLE_OAUTH_REDIRECT_URI = os.environ.get("GOOGLE_OAUTH_REDIRECT_URI", "")
if not GOOGLE_OAUTH_REDIRECT_URI:
    raise RuntimeError(
        "GOOGLE_OAUTH_REDIRECT_URI não configurado. Ex: "
        "https://showup-backend-s9y1.onrender.com/api/auth/google/callback"
    )
Role = Literal["cliente", "profissional"]

CATEGORIAS = ["fitness", "terapia", "consultoria", "estetica", "coaching", "nutricao"]
Categoria = Literal["fitness", "terapia", "consultoria", "estetica", "coaching", "nutricao"]

# Fusos horários do Brasil (o app é BRL-only por enquanto — ver moeda fixa em
# "BRL" nos agendamentos). Lista fechada em vez de aceitar qualquer IANA tz:
# evita profissional digitar algo exótico por engano e reduz a superfície de
# escolha na UI pra 4 opções reais.
TIMEZONES_BR = [
    "America/Sao_Paulo",   # UTC-3, a grande maioria do país
    "America/Manaus",      # UTC-4 (AM, RR, parte de MT/RO)
    "America/Rio_Branco",  # UTC-5 (AC, oeste do AM)
    "America/Noronha",     # UTC-2 (Fernando de Noronha)
]
DEFAULT_TIMEZONE = "America/Sao_Paulo"

# Moedas suportadas — lista fechada (não qualquer código ISO 4217) pelo mesmo
# motivo dos fusos: evita erro de digitação e mantém a validação simples.
# O Stripe em si suporta 135+ moedas; esta lista cobre os mercados mais
# prováveis pra expansão e pode crescer sem tocar em nenhuma outra parte do
# código — tudo abaixo lê `moeda` do profissional/serviço, nunca assume BRL.
MOEDAS_SUPORTADAS = [
    "BRL", "USD", "EUR", "GBP", "MXN", "ARS", "COP", "CLP", "CAD", "AUD",
]
DEFAULT_MOEDA = "BRL"

# Usado só pra abrir a conta Connect do profissional no país certo (Stripe
# exige um país por conta Express) — heurística razoável a partir da moeda
# que ele escolheu, não uma seleção de país explícita e independente. EUR é
# a exceção real (vale pra ~20 países); DE como default é só um chute
# defensável, não uma verdade fiscal — se isso importar de verdade um dia,
# a coisa certa é um campo de país explícito, não inferir da moeda.
MOEDA_PAIS_CONNECT = {
    "BRL": "BR", "USD": "US", "EUR": "DE", "GBP": "GB", "MXN": "MX",
    "ARS": "AR", "COP": "CO", "CLP": "CL", "CAD": "CA", "AUD": "AU",
}

# Planos de assinatura do PROFISSIONAL — decrescem a taxa por agendamento
# conforme a mensalidade sobe. fee_bps em pontos-base (1000 = 10%).
# price_env: nome da env var com o Price ID do Stripe pra esse plano (None
# pro Free, que não tem cobrança). Ver STRIPE_PRICE_ID_* no .env.
PLANOS = {
    "free":         {"nome": "Free",         "fee_bps": 1000, "preco_centavos": 0,    "price_env": None},
    "profissional": {"nome": "Profissional", "fee_bps": 500,  "preco_centavos": 1990, "price_env": "STRIPE_PRICE_ID_PROFISSIONAL"},
    "ultra":        {"nome": "Ultra",        "fee_bps": 200,  "preco_centavos": 5990, "price_env": "STRIPE_PRICE_ID_ULTRA"},
}
DEFAULT_PLANO = "free"
TRIAL_DIAS = 14  # teste grátis do plano pago — uma vez por profissional
RESUMO_JANELA_DIAS = 30  # janela da conta "quanto você pagaria em cada plano"
PIX_RESERVA_MINUTOS = 20  # tempo que um agendamento via Pix fica reservado esperando pagamento antes de liberar o horário sozinho


def _fee_bps_for(profissional_doc: Optional[dict]) -> int:
    """Mesma filosofia de _tz_for/_moeda: nunca deixa um plano desconhecido
    ou ausente quebrar o cálculo — cai pro Free (a taxa mais alta, o que é
    o comportamento seguro do ponto de vista da plataforma)."""
    plano = (profissional_doc or {}).get("plano") or DEFAULT_PLANO
    return PLANOS.get(plano, PLANOS[DEFAULT_PLANO])["fee_bps"]


def _plano_disponivel(p: dict) -> bool:
    """Só é "comprável" de verdade se o Price ID real já foi configurado no
    .env — evita o app oferecer um plano que quebraria no clique."""
    return p["price_env"] is None or bool(os.environ.get(p["price_env"]))


def _teto_div(a: int, b: int) -> int:
    return -(-a // b)


def _equilibrios() -> dict[str, dict[str, int]]:
    """Volume (em centavos de serviços cobrados por mês) a partir do qual cada
    plano pago sai mais barato que o Free e que o plano imediatamente abaixo.
    mensalidade extra / pontos-base economizados * 10_000."""
    ordem = list(PLANOS.items())
    free = ordem[0][1]
    out: dict[str, dict[str, int]] = {}
    for i in range(1, len(ordem)):
        pid, p = ordem[i]
        ant = ordem[i - 1][1]
        out[pid] = {
            "vs_free": _teto_div((p["preco_centavos"] - free["preco_centavos"]) * 10_000, free["fee_bps"] - p["fee_bps"]),
            "vs_anterior": _teto_div((p["preco_centavos"] - ant["preco_centavos"]) * 10_000, ant["fee_bps"] - p["fee_bps"]),
        }
    return out


def calcular_comparacao_planos(valores_centavos: list[int], plano_atual: str) -> list[dict]:
    """Quanto o profissional pagaria em cada plano com o MESMO movimento.
    `valores_centavos` = valor do serviço de cada agendamento cobrado — a taxa
    é calculada por agendamento, com a mesma conta da cobrança real
    (valor * bps // 10_000, arredondando pra baixo cada um)."""
    atual_id = plano_atual if plano_atual in PLANOS else DEFAULT_PLANO
    linhas = []
    for pid, p in PLANOS.items():
        taxa = sum((v * p["fee_bps"]) // 10_000 for v in valores_centavos)
        linhas.append({
            "id": pid, "nome": p["nome"], "fee_percent": p["fee_bps"] / 100,
            "preco_centavos": p["preco_centavos"], "disponivel": _plano_disponivel(p),
            "taxa_estimada_centavos": taxa, "custo_total_centavos": taxa + p["preco_centavos"],
        })
    custo_atual = next(l for l in linhas if l["id"] == atual_id)["custo_total_centavos"]
    eq = _equilibrios()
    for l in linhas:
        l["economia_vs_atual_centavos"] = custo_atual - l["custo_total_centavos"]
        l["equilibrio_vs_free_centavos"] = eq.get(l["id"], {}).get("vs_free")
        l["equilibrio_vs_anterior_centavos"] = eq.get(l["id"], {}).get("vs_anterior")
    return linhas


def _trial_disponivel(doc: dict) -> bool:
    """Teste grátis: só quem está no Free, nunca fez teste e nunca pagou um plano
    (senão daria pra emendar testes sem fim)."""
    return (
        (doc.get("plano") or DEFAULT_PLANO) == DEFAULT_PLANO
        and not doc.get("plano_trial_usado")
        and not doc.get("plano_ja_pago")
    )


def _tz_for(profissional_doc: Optional[dict]) -> ZoneInfo:
    """Nunca deixa uma configuração ruim derrubar o cálculo de slots — cai
    para o fuso default se o profissional não tiver um setado ou se, por
    algum motivo, o valor salvo não for mais um nome IANA válido."""
    tz_name = (profissional_doc or {}).get("timezone") or DEFAULT_TIMEZONE
    try:
        return ZoneInfo(tz_name)
    except ZoneInfoNotFoundError:
        logging.warning("timezone inválida no profissional: %r — usando default", tz_name)
        return ZoneInfo(DEFAULT_TIMEZONE)

# Gateway selection: real Stripe if key is present and valid-looking.
_STRIPE_KEY = os.environ.get("STRIPE_API_KEY", "")
if _STRIPE_KEY.startswith("sk_test_") and len(_STRIPE_KEY) > 20:
    from stripe_gateway import StripeGateway
    gateway = StripeGateway(db)
    GATEWAY_KIND = "stripe"
else:
    from gateway import MockGateway
    gateway = MockGateway(db)
    GATEWAY_KIND = "mock"


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------
class User(BaseModel):
    user_id: str
    email: EmailStr
    name: str
    picture: Optional[str] = None
    role: Optional[Role] = None
    has_card: bool = False
    categorias: list[str] = []
    stripe_account_id: Optional[str] = None
    connect_ready: bool = False
    timezone: str = DEFAULT_TIMEZONE
    moeda: str = DEFAULT_MOEDA
    plano: str = DEFAULT_PLANO
    created_at: datetime


class SessionRequest(BaseModel):
    id_token: str


class SessionResponse(BaseModel):
    session_token: str
    user: User


class RoleRequest(BaseModel):
    role: Role


class MeResponse(BaseModel):
    user: User


class CategoriasRequest(BaseModel):
    categorias: list[Categoria] = Field(min_length=1, max_length=3)


class TimezoneRequest(BaseModel):
    timezone: str

    @field_validator("timezone")
    @classmethod
    def _valida_timezone_suportada(cls, v: str) -> str:
        if v not in TIMEZONES_BR:
            raise ValueError(f"timezone não suportada — use uma de: {', '.join(TIMEZONES_BR)}")
        return v


class MoedaRequest(BaseModel):
    moeda: str

    @field_validator("moeda")
    @classmethod
    def _valida_moeda_suportada(cls, v: str) -> str:
        v = v.upper()
        if v not in MOEDAS_SUPORTADAS:
            raise ValueError(f"moeda não suportada — use uma de: {', '.join(MOEDAS_SUPORTADAS)}")
        return v


class ServicoCreate(BaseModel):
    nome: str = Field(min_length=2, max_length=120)
    descricao: Optional[str] = Field(default=None, max_length=500)
    valor_centavos: int = Field(gt=0)
    taxa_no_show_centavos: int = Field(gt=0)
    duracao_min: int = Field(gt=0, le=480)


class Servico(BaseModel):
    servico_id: str
    profissional_id: str
    nome: str
    descricao: Optional[str] = None
    valor_centavos: int
    taxa_no_show_centavos: int
    duracao_min: int
    moeda: str = "BRL"
    ativo: bool = True
    criado_em: datetime


class ProfissionalPublic(BaseModel):
    user_id: str
    name: str
    picture: Optional[str] = None
    categorias: list[str] = []
    servicos_count: int


class ProfissionalDetail(BaseModel):
    user_id: str
    name: str
    picture: Optional[str] = None
    categorias: list[str] = []
    timezone: str = DEFAULT_TIMEZONE
    servicos: list[Servico]


class AgendamentoCreate(BaseModel):
    servico_id: str
    horario_inicio: datetime


class AgendamentoPublicoCreate(BaseModel):
    """Agendamento criado por um cliente SEM conta no app — fluxo do link
    enviado no WhatsApp. Sem sessão/token nosso; identificamos o cliente
    pelo telefone (criando/reaproveitando uma conta "sintética" pra ele)."""
    profissional_id: str
    servico_id: str
    horario_inicio: datetime
    nome: str = Field(min_length=2, max_length=120)
    telefone: str

    @field_validator("telefone")
    @classmethod
    def _valida_telefone(cls, v: str) -> str:
        digitos = "".join(c for c in v if c.isdigit())
        if len(digitos) not in (10, 11):  # DDD + número, com ou sem o 9
            raise ValueError("Telefone inválido — use DDD + número (ex: 11987654321)")
        return digitos


class AgendamentoPublicoCartaoRequest(AgendamentoPublicoCreate):
    payment_method_id: str  # já coletado/confirmado via Stripe.js Elements na página web


class CartaoSetupPublicoRequest(BaseModel):
    """Primeiro passo do cartão no link público: a página precisa de um
    SetupIntent do cliente (identificado pelo telefone) pra o Stripe.js
    salvar o cartão nele — mesmo papel do /me/card/setup-intent do app,
    só que sem sessão."""
    nome: str = Field(min_length=2, max_length=120)
    telefone: str

    @field_validator("telefone")
    @classmethod
    def _valida_telefone(cls, v: str) -> str:
        digitos = "".join(c for c in v if c.isdigit())
        if len(digitos) not in (10, 11):
            raise ValueError("Telefone inválido — use DDD + número (ex: 11987654321)")
        return digitos


class CartaoSetupPublicoResponse(BaseModel):
    setup_intent_client_secret: str


class AgendamentoPublicoPixResponse(BaseModel):
    agendamento_id: str
    payment_intent_client_secret: str
    qr_code_data: Optional[str] = None
    hosted_instructions_url: Optional[str] = None
    expira_em: datetime


class Agendamento(BaseModel):
    agendamento_id: str
    profissional_id: str
    cliente_id: str
    servico_id: str
    servico_nome: str
    profissional_nome: str
    cliente_nome: str
    horario_inicio: datetime
    horario_fim: datetime
    valor_total_centavos: int
    valor_no_show_centavos: int
    moeda: str
    status_agendamento: str
    status_confirmacao: str
    payment_intent_id: str
    hold_status: str
    hold_expira_em: datetime
    janela_confirmacao_expira_em: datetime
    valor_capturado_centavos: int = 0
    criado_em: datetime
    push_pergunta_enviada_em: Optional[datetime] = None
    push_urgencia_enviada_em: Optional[datetime] = None


class ConfirmacaoRequest(BaseModel):
    resultado: Literal["compareceu", "nao_compareceu"]


class PushTokenRequest(BaseModel):
    expo_push_token: str = Field(min_length=10, max_length=200)
    platform: Optional[Literal["ios", "android", "web"]] = None


class DisponibilidadeSlot(BaseModel):
    weekday: int = Field(ge=0, le=6)  # 0 = Monday
    hora_inicio: str  # "HH:MM"
    hora_fim: str

    @field_validator("hora_inicio", "hora_fim")
    @classmethod
    def _valida_formato_hhmm(cls, v: str) -> str:
        try:
            h, m = v.split(":")
            if not (0 <= int(h) <= 23 and 0 <= int(m) <= 59):
                raise ValueError
        except (ValueError, AttributeError):
            raise ValueError(f"formato inválido: {v!r} (esperado HH:MM, 00:00–23:59)")
        return v

    @field_validator("hora_fim")
    @classmethod
    def _valida_fim_apos_inicio(cls, v: str, info) -> str:
        inicio = info.data.get("hora_inicio")
        if inicio and _parse_hhmm(v) <= _parse_hhmm(inicio):
            raise ValueError("hora_fim deve ser depois de hora_inicio (não oferecemos suporte a horários que cruzam a meia-noite)")
        return v


class DisponibilidadeRequest(BaseModel):
    slots: list[DisponibilidadeSlot] = Field(max_length=42)


class SlotDisponivel(BaseModel):
    iso: str
    day_label: str
    time_label: str


class ConnectStatus(BaseModel):
    account_id: Optional[str] = None
    charges_enabled: bool = False
    payouts_enabled: bool = False
    details_submitted: bool = False


class ConnectLink(BaseModel):
    url: str


class PlanoCheckoutRequest(BaseModel):
    plano: str
    usar_trial: bool = False

    @field_validator("plano")
    @classmethod
    def _valida_plano_pago(cls, v: str) -> str:
        if v not in PLANOS or v == "free":
            raise ValueError(f"plano inválido — use um de: {', '.join(p for p in PLANOS if p != 'free')}")
        return v


class PlanoSubscriptionIntentResponse(BaseModel):
    customer_id: str
    ephemeral_key_secret: str
    # Assinatura paga: payment_intent_client_secret. Teste grátis (nada a
    # cobrar agora): setup_intent_client_secret, pro Payment Sheet só salvar o cartão.
    payment_intent_client_secret: Optional[str] = None
    setup_intent_client_secret: Optional[str] = None
    trial_dias: int = 0
    subscription_id: str


class PlanoComparacao(BaseModel):
    id: str
    nome: str
    fee_percent: float
    preco_centavos: int
    disponivel: bool
    taxa_estimada_centavos: int
    custo_total_centavos: int
    economia_vs_atual_centavos: int
    equilibrio_vs_free_centavos: Optional[int] = None
    equilibrio_vs_anterior_centavos: Optional[int] = None


class PlanoResumoResponse(BaseModel):
    plano_atual: str
    moeda: str
    janela_dias: int
    atendimentos_cobrados: int
    servicos_cobrados_centavos: int
    base_taxa_centavos: int
    faltas_cobradas_qtd: int
    faltas_cobradas_centavos: int
    # Os preços dos planos são em BRL: pra outra moeda não dá pra comparar.
    comparacao_disponivel: bool
    comparacao: list[PlanoComparacao]
    recomendado: Optional[str] = None
    trial_disponivel: bool
    trial_dias: int
    trial_termina_em: Optional[datetime] = None


class ConfirmPlanoRequest(BaseModel):
    subscription_id: str
    plano: str

    @field_validator("plano")
    @classmethod
    def _valida_plano_pago(cls, v: str) -> str:
        if v not in PLANOS or v == "free":
            raise ValueError(f"plano inválido — use um de: {', '.join(p for p in PLANOS if p != 'free')}")
        return v


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _now() -> datetime:
    return datetime.now(timezone.utc)


def _aware(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


async def _serialize_user(doc: dict) -> User:
    has_card = bool(await db.customer_cards.find_one({"user_id": doc["user_id"]}))
    return User(
        user_id=doc["user_id"], email=doc["email"], name=doc["name"],
        picture=doc.get("picture"), role=doc.get("role"), has_card=has_card,
        categorias=doc.get("categorias", []),
        stripe_account_id=doc.get("stripe_account_id"),
        connect_ready=bool(doc.get("connect_ready")),
        timezone=doc.get("timezone") or DEFAULT_TIMEZONE,
        moeda=doc.get("moeda") or DEFAULT_MOEDA,
        plano=doc.get("plano") or DEFAULT_PLANO,
        created_at=_aware(doc["created_at"]),
    )


async def _current_user(authorization: Optional[str]) -> dict:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(401, "Missing bearer token")
    token = authorization.split(" ", 1)[1].strip()
    session = await db.user_sessions.find_one({"session_token": token}, {"_id": 0})
    if not session or _aware(session["expires_at"]) <= _now():
        raise HTTPException(401, "Invalid session")
    doc = await db.users.find_one({"user_id": session["user_id"]}, {"_id": 0})
    if not doc:
        raise HTTPException(401, "User not found")
    return doc


async def _require_role(doc: dict, role: Role):
    if doc.get("role") != role:
        raise HTTPException(403, f"Requires role={role}")


async def _find_or_create_cliente_por_telefone(nome: str, telefone: str) -> dict:
    """Cliente vindo do link público (WhatsApp), sem sessão/conta prévia no
    app. Usamos o telefone como identidade — se ele já agendou antes por
    esse mesmo número, reaproveita a conta em vez de criar duplicata.
    Nosso índice de usuário é por email (único, obrigatório); como esse
    fluxo não coleta email, geramos um sintético e óbvio de reconhecer,
    nunca usado pra login de verdade (login continua sendo só Google)."""
    existing = await db.users.find_one({"telefone": telefone}, {"_id": 0})
    if existing:
        if existing.get("name") != nome:
            await db.users.update_one({"user_id": existing["user_id"]}, {"$set": {"name": nome}})
            existing["name"] = nome
        return existing
    user_id = f"user_{uuid.uuid4().hex[:12]}"
    doc = {
        "user_id": user_id,
        "email": f"tel_{telefone}@showup.cliente",
        "name": nome,
        "telefone": telefone,
        "picture": None,
        "role": "cliente",
        "categorias": [],
        "created_at": _now(),
    }
    await db.users.insert_one(doc)
    return doc


async def _valida_servico_e_conflito(servico_id: str, horario_inicio: datetime) -> tuple[dict, dict, datetime]:
    """Parte compartilhada entre o fluxo normal (app) e o público (link do
    WhatsApp): busca o serviço, calcula horário_fim, e checa sobreposição
    de agenda. Devolve (servico, profissional_doc, horario_fim)."""
    svc = await db.servicos.find_one({"servico_id": servico_id, "ativo": True}, {"_id": 0})
    if not svc:
        raise HTTPException(404, "Serviço não encontrado")
    horario = _aware(horario_inicio)
    if horario <= _now():
        raise HTTPException(422, "Horário deve ser futuro")
    horario_fim = horario + timedelta(minutes=svc["duracao_min"])
    conflito = await db.agendamentos.find_one({
        "profissional_id": svc["profissional_id"],
        "hold_status": {"$in": ["autorizado", "cancelando", "capturado_total", "capturado_taxa", "pago_integral", "aguardando_pix"]},
        "horario_inicio": {"$lt": horario_fim},
        "horario_fim": {"$gt": horario},
    })
    if conflito:
        raise HTTPException(409, "Esse horário acabou de ser reservado por outro cliente. Escolha outro.")
    prof = await db.users.find_one({"user_id": svc["profissional_id"]}, {"_id": 0})
    return svc, prof, horario_fim


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------
@api_router.get("/")
async def root():
    return {"service": "ShowUp API", "status": "ok", "gateway": GATEWAY_KIND}


async def _login_or_create_session_from_google_claims(claims: dict) -> SessionResponse:
    """Lógica compartilhada entre os dois jeitos de chegar num id_token do
    Google validado: o endpoint antigo (/auth/session, recebe direto do
    app) e o novo (/auth/google/callback, troca um `code` pelo token no
    fluxo via navegador)."""
    email = claims.get("email")
    if not email:
        raise HTTPException(401, "Token do Google sem e-mail")
    if not claims.get("email_verified", False):
        raise HTTPException(401, "E-mail do Google não verificado")
    name = claims.get("name") or email.split("@")[0]
    picture = claims.get("picture")

    existing = await db.users.find_one({"email": email}, {"_id": 0})
    if existing:
        user_id = existing["user_id"]
        await db.users.update_one({"user_id": user_id}, {"$set": {"name": name, "picture": picture}})
    else:
        user_id = f"user_{uuid.uuid4().hex[:12]}"
        await db.users.insert_one({
            "user_id": user_id, "email": email, "name": name, "picture": picture,
            "role": None, "categorias": [], "created_at": _now(),
        })

    # session_token é NOSSO, gerado aqui — nunca mais dependemos de um
    # token emitido por um servidor de terceiros pra manter a sessão.
    session_token = uuid.uuid4().hex + uuid.uuid4().hex

    # upsert por segurança (colisão de UUID é praticamente impossível, mas o
    # índice único em session_token é uma garantia barata de manter).
    await db.user_sessions.replace_one(
        {"session_token": session_token},
        {"session_token": session_token, "user_id": user_id,
         "created_at": _now(), "expires_at": _now() + timedelta(days=7)},
        upsert=True,
    )
    doc = await db.users.find_one({"user_id": user_id}, {"_id": 0})
    return SessionResponse(session_token=session_token, user=await _serialize_user(doc))


@api_router.post("/auth/session", response_model=SessionResponse)
@limiter.limit("10/minute")
async def auth_session(request: Request, payload: SessionRequest):
    """Mantido por compatibilidade, mas o app não usa mais esse caminho —
    ele foi trocado pelo fluxo via navegador (/auth/google/callback) pra
    não depender do SDK nativo do Google nem de SHA-1 de certificado.
    Recebe um id_token e valida ele DIRETO com o Google — sem nenhum
    servidor de terceiros no meio. `verify_oauth2_token` confere a
    assinatura, a expiração, e que o "audience" bate com o nosso
    GOOGLE_WEB_CLIENT_ID (prova de que o token foi emitido pra este app,
    não copiado de outro)."""
    try:
        claims = google_id_token.verify_oauth2_token(
            payload.id_token, google_requests.Request(), audience=GOOGLE_WEB_CLIENT_ID,
        )
    except ValueError as e:
        raise HTTPException(401, f"Token do Google inválido: {e}")
    except GoogleAuthError as e:
        # Falha de rede/transporte buscando as chaves públicas do Google —
        # transitório, diferente de um token genuinamente inválido.
        logging.exception("Falha ao verificar token do Google")
        raise HTTPException(503, "Não foi possível verificar o login com o Google agora. Tente de novo.")
    return await _login_or_create_session_from_google_claims(claims)


@api_router.get("/auth/google/callback")
async def auth_google_callback(code: Optional[str] = None, error: Optional[str] = None):
    """O app abre o navegador direto na URL de autorização do Google, com
    redirect_uri apontando pra CÁ (tem que ser HTTPS — Client ID tipo
    "Web" não aceita esquema customizado tipo showup:// como redirect,
    é bloqueado pelo próprio Google). O Google manda o usuário de volta
    pra cá com um `code`; a gente troca esse code por tokens (usando o
    Client Secret, que só o backend tem — nunca vai pro app), monta a
    sessão normalmente, e só então redireciona de volta pro app via
    showup://auth-callback, já com o nosso session_token pronto."""
    if error or not code:
        return RedirectResponse(f"showup://auth-callback?error={error or 'sem_code'}")

    async with httpx.AsyncClient(timeout=15) as client:
        token_resp = await client.post(
            "https://oauth2.googleapis.com/token",
            data={
                "code": code,
                "client_id": GOOGLE_WEB_CLIENT_ID,
                "client_secret": GOOGLE_CLIENT_SECRET,
                "redirect_uri": GOOGLE_OAUTH_REDIRECT_URI,
                "grant_type": "authorization_code",
            },
        )
    if token_resp.status_code != 200:
        logging.error("Falha trocando code por token no Google: %s", token_resp.text)
        return RedirectResponse("showup://auth-callback?error=token_exchange_failed")

    id_token_str = token_resp.json().get("id_token")
    if not id_token_str:
        return RedirectResponse("showup://auth-callback?error=sem_id_token")

    try:
        claims = google_id_token.verify_oauth2_token(
            id_token_str, google_requests.Request(), audience=GOOGLE_WEB_CLIENT_ID,
        )
    except (ValueError, GoogleAuthError) as e:
        logging.exception("id_token inválido no callback do Google")
        return RedirectResponse("showup://auth-callback?error=token_invalido")

    try:
        session = await _login_or_create_session_from_google_claims(claims)
    except HTTPException as e:
        return RedirectResponse(f"showup://auth-callback?error={e.detail}")

    return RedirectResponse(f"showup://auth-callback?token={session.session_token}")


@api_router.get("/auth/me", response_model=MeResponse)
async def auth_me(authorization: Optional[str] = Header(default=None)):
    return MeResponse(user=await _serialize_user(await _current_user(authorization)))


@api_router.post("/auth/role", response_model=MeResponse)
async def auth_set_role(payload: RoleRequest, authorization: Optional[str] = Header(default=None)):
    doc = await _current_user(authorization)
    await db.users.update_one({"user_id": doc["user_id"]}, {"$set": {"role": payload.role}})
    doc = await db.users.find_one({"user_id": doc["user_id"]}, {"_id": 0})
    return MeResponse(user=await _serialize_user(doc))


@api_router.post("/auth/logout")
async def auth_logout(authorization: Optional[str] = Header(default=None)):
    if authorization and authorization.lower().startswith("bearer "):
        token = authorization.split(" ", 1)[1].strip()
        await db.user_sessions.delete_one({"session_token": token})
    return {"ok": True}


@api_router.delete("/me")
@limiter.limit("5/minute")
async def excluir_conta(request: Request, authorization: Optional[str] = Header(default=None)):
    """Exigido pela política da Play Store: qualquer app que permite criar
    conta precisa oferecer um jeito de excluí-la de dentro do próprio app.

    Não apaga o documento do usuário de verdade — anonimiza os campos
    pessoais (nome, e-mail, foto, telefone) e marca deleted_at, mas
    preserva agendamentos/transações já ocorridos (obrigação fiscal/legal
    de manter registro financeiro), agora desvinculados de qualquer dado
    pessoal identificável. Ver Política de Privacidade, seção "Por quanto
    tempo guardamos seus dados"."""
    doc = await _current_user(authorization)
    user_id = doc["user_id"]

    compromisso_pendente = await db.agendamentos.find_one({
        "$and": [
            {"$or": [{"cliente_id": user_id}, {"profissional_id": user_id}]},
            {"$or": [
                {"hold_status": {"$in": ["autorizado", "cancelando", "aguardando_pix"]}},
                {"status_agendamento": "agendado", "horario_inicio": {"$gt": _now()}},
            ]},
        ],
    })
    if compromisso_pendente:
        raise HTTPException(
            409,
            "Você tem agendamentos pendentes ou futuros. Cancele ou aguarde eles "
            "terminarem antes de excluir sua conta.",
        )

    await db.users.update_one(
        {"user_id": user_id},
        {"$set": {
            "name": "Usuário excluído",
            "email": f"deleted_{user_id}@showup.excluido",
            "picture": None,
            "telefone": None,
            "deleted_at": _now(),
        }, "$unset": {"stripe_customer_id": "", "stripe_billing_customer_id": "", "stripe_account_id": ""}},
    )
    await db.user_sessions.delete_many({"user_id": user_id})
    return {"ok": True}


# ---------------------------------------------------------------------------
# Cliente: card (real Stripe when possible)
# ---------------------------------------------------------------------------
class CardInfo(BaseModel):
    brand: str
    last4: str
    exp_month: int
    exp_year: int


# ---------------------------------------------------------------------------
# Cliente: card (coleta real via Stripe Payment Sheet — nunca via backend)
# ---------------------------------------------------------------------------
class CardInfo(BaseModel):
    brand: str
    last4: str
    exp_month: int
    exp_year: int


class SetupIntentResponse(BaseModel):
    customer_id: str
    ephemeral_key_secret: str
    setup_intent_client_secret: str


class ConfirmCardRequest(BaseModel):
    setup_intent_id: str


@api_router.post("/me/card/setup-intent", response_model=SetupIntentResponse)
@limiter.limit("10/minute")
async def card_setup_intent(request: Request, authorization: Optional[str] = Header(default=None)):
    """Primeiro passo da coleta de cartão: prepara tudo que o Payment Sheet
    do app precisa pra coletar o cartão DIRETO com o Stripe — o número do
    cartão nunca passa pelo nosso backend, então nunca escapa do escopo de
    conformidade PCI que o Payment Sheet já resolve sozinho."""
    doc = await _current_user(authorization)
    await _require_role(doc, "cliente")
    customer_id = await gateway.ensure_customer(doc["user_id"], doc["email"], doc["name"])
    ephemeral_key = await gateway.create_ephemeral_key(customer_id)
    setup_intent = await gateway.create_setup_intent(customer_id)
    return SetupIntentResponse(
        customer_id=customer_id,
        ephemeral_key_secret=ephemeral_key,
        setup_intent_client_secret=setup_intent["client_secret"],
    )


@api_router.post("/me/card/confirm", response_model=CardInfo)
@limiter.limit("10/minute")
async def card_confirm(
    request: Request, payload: ConfirmCardRequest, authorization: Optional[str] = Header(default=None)
):
    """Segundo passo: chamado pelo app DEPOIS que o Payment Sheet já
    confirmou a coleta do cartão com o Stripe. Não confiamos cegamente no
    que o app relata — confirm_setup_intent_card() busca a verdade de volta
    no Stripe antes de salvar qualquer coisa como cartão válido."""
    doc = await _current_user(authorization)
    await _require_role(doc, "cliente")
    customer_id = await gateway.ensure_customer(doc["user_id"], doc["email"], doc["name"])
    try:
        info = await gateway.confirm_setup_intent_card(payload.setup_intent_id, customer_id)
    except (InvalidPaymentRequestError, ValueError) as e:
        raise HTTPException(400, str(e))
    except PaymentError:
        logging.exception("confirm_setup_intent_card falhou")
        raise HTTPException(502, "Falha ao confirmar cartão junto ao gateway")

    card = {
        "user_id": doc["user_id"], "customer_id": customer_id,
        "payment_method_id": info["payment_method_id"],
        "brand": info["brand"], "last4": info["last4"],
        "exp_month": info["exp_month"], "exp_year": info["exp_year"],
        "criado_em": _now(),
    }
    await db.customer_cards.replace_one({"user_id": doc["user_id"]}, card, upsert=True)
    return CardInfo(brand=card["brand"], last4=card["last4"],
                    exp_month=card["exp_month"], exp_year=card["exp_year"])



@api_router.get("/me/card")
async def get_card(authorization: Optional[str] = Header(default=None)):
    doc = await _current_user(authorization)
    card = await db.customer_cards.find_one({"user_id": doc["user_id"]}, {"_id": 0})
    if not card:
        return {"has_card": False}
    return {"has_card": True, "brand": card["brand"], "last4": card["last4"],
            "exp_month": card["exp_month"], "exp_year": card["exp_year"]}


# ---------------------------------------------------------------------------
# Push notifications (device token registration)
# ---------------------------------------------------------------------------
@api_router.put("/me/push-token")
async def registrar_push_token(payload: PushTokenRequest, authorization: Optional[str] = Header(default=None)):
    """Um token por usuário (última chamada vence) — igual ao padrão de
    /me/card. Um usuário logado em dois aparelhos perde o push no mais
    antigo; aceitável para o MVP, e evita a complexidade de gerenciar lista
    de tokens + limpeza de duplicados por enquanto."""
    doc = await _current_user(authorization)
    await db.device_tokens.replace_one(
        {"user_id": doc["user_id"]},
        {"user_id": doc["user_id"], "expo_push_token": payload.expo_push_token,
         "platform": payload.platform, "atualizado_em": _now()},
        upsert=True,
    )
    return {"ok": True}


@api_router.delete("/me/push-token")
async def remover_push_token(authorization: Optional[str] = Header(default=None)):
    doc = await _current_user(authorization)
    await db.device_tokens.delete_one({"user_id": doc["user_id"]})
    return {"ok": True}


# ---------------------------------------------------------------------------
# Categorias (profissional)
# ---------------------------------------------------------------------------
@api_router.get("/categorias")
async def listar_categorias():
    return {"categorias": CATEGORIAS}


@api_router.put("/me/categorias", response_model=MeResponse)
async def set_categorias(payload: CategoriasRequest, authorization: Optional[str] = Header(default=None)):
    doc = await _current_user(authorization)
    await _require_role(doc, "profissional")
    await db.users.update_one({"user_id": doc["user_id"]}, {"$set": {"categorias": payload.categorias}})
    doc = await db.users.find_one({"user_id": doc["user_id"]}, {"_id": 0})
    return MeResponse(user=await _serialize_user(doc))


@api_router.get("/timezones")
async def listar_timezones():
    return {"timezones": TIMEZONES_BR}


@api_router.put("/me/timezone", response_model=MeResponse)
async def set_timezone(payload: TimezoneRequest, authorization: Optional[str] = Header(default=None)):
    doc = await _current_user(authorization)
    await _require_role(doc, "profissional")
    await db.users.update_one({"user_id": doc["user_id"]}, {"$set": {"timezone": payload.timezone}})
    doc = await db.users.find_one({"user_id": doc["user_id"]}, {"_id": 0})
    return MeResponse(user=await _serialize_user(doc))


@api_router.get("/moedas")
async def listar_moedas():
    return {"moedas": MOEDAS_SUPORTADAS}


@api_router.put("/me/moeda", response_model=MeResponse)
async def set_moeda(payload: MoedaRequest, authorization: Optional[str] = Header(default=None)):
    """Moeda é uma propriedade do PROFISSIONAL (ligada à conta Connect dele,
    que só liquida numa moeda), não do serviço individual — por isso vive
    aqui, no perfil, e não em ServicoCreate. Trocar a moeda não afeta
    serviços já criados (eles guardam a moeda que tinham no momento da
    criação — ver criar_servico), só os próximos."""
    doc = await _current_user(authorization)
    await _require_role(doc, "profissional")
    await db.users.update_one({"user_id": doc["user_id"]}, {"$set": {"moeda": payload.moeda}})
    doc = await db.users.find_one({"user_id": doc["user_id"]}, {"_id": 0})
    return MeResponse(user=await _serialize_user(doc))


# ---------------------------------------------------------------------------
# Servicos
# ---------------------------------------------------------------------------
@api_router.post("/servicos", response_model=Servico)
async def criar_servico(payload: ServicoCreate, authorization: Optional[str] = Header(default=None)):
    doc = await _current_user(authorization)
    await _require_role(doc, "profissional")
    if payload.taxa_no_show_centavos > payload.valor_centavos:
        raise HTTPException(422, "taxa_no_show > valor")
    servico = {
        "servico_id": f"srv_{uuid.uuid4().hex[:12]}",
        "profissional_id": doc["user_id"],
        **payload.model_dump(),
        "moeda": doc.get("moeda") or DEFAULT_MOEDA, "ativo": True, "criado_em": _now(),
    }
    await db.servicos.insert_one(dict(servico))
    return Servico(**servico)


@api_router.get("/servicos", response_model=list[Servico])
async def listar_meus_servicos(authorization: Optional[str] = Header(default=None)):
    doc = await _current_user(authorization)
    await _require_role(doc, "profissional")
    items = await db.servicos.find({"profissional_id": doc["user_id"], "ativo": True}, {"_id": 0}).to_list(200)
    return [Servico(**{**it, "criado_em": _aware(it["criado_em"])}) for it in items]


@api_router.delete("/servicos/{servico_id}")
async def deletar_servico(servico_id: str, authorization: Optional[str] = Header(default=None)):
    doc = await _current_user(authorization)
    await _require_role(doc, "profissional")
    res = await db.servicos.update_one(
        {"servico_id": servico_id, "profissional_id": doc["user_id"], "ativo": True},
        {"$set": {"ativo": False}},
    )
    if res.matched_count == 0:
        raise HTTPException(404, "Não encontrado")
    return {"ok": True}


# ---------------------------------------------------------------------------
# Profissionais (discovery)
# ---------------------------------------------------------------------------
@api_router.get("/profissionais", response_model=list[ProfissionalPublic])
async def listar_profissionais(
    q: Optional[str] = Query(default=None),
    categoria: Optional[str] = Query(default=None),
):
    query: dict = {"role": "profissional"}
    if q:
        query["name"] = {"$regex": q, "$options": "i"}
    if categoria and categoria in CATEGORIAS:
        query["categorias"] = categoria
    users = await db.users.find(query, {"_id": 0}).to_list(200)
    result = []
    for u in users:
        count = await db.servicos.count_documents({"profissional_id": u["user_id"], "ativo": True})
        if count == 0:
            continue
        result.append(ProfissionalPublic(
            user_id=u["user_id"], name=u["name"], picture=u.get("picture"),
            categorias=u.get("categorias", []), servicos_count=count,
        ))
    return result


@api_router.get("/profissionais/{user_id}", response_model=ProfissionalDetail)
async def detalhe_profissional(user_id: str):
    u = await db.users.find_one({"user_id": user_id, "role": "profissional"}, {"_id": 0})
    if not u:
        raise HTTPException(404, "Não encontrado")
    servicos = await db.servicos.find({"profissional_id": user_id, "ativo": True}, {"_id": 0}).to_list(200)
    return ProfissionalDetail(
        user_id=u["user_id"], name=u["name"], picture=u.get("picture"),
        categorias=u.get("categorias", []),
        timezone=u.get("timezone") or DEFAULT_TIMEZONE,
        servicos=[Servico(**{**s, "criado_em": _aware(s["criado_em"])}) for s in servicos],
    )


# ---------------------------------------------------------------------------
# Disponibilidade (weekly recurring)
# ---------------------------------------------------------------------------
@api_router.get("/profissionais/{user_id}/disponibilidade")
async def get_disponibilidade(user_id: str):
    slots = await db.disponibilidade.find({"profissional_id": user_id}, {"_id": 0}).to_list(200)
    return {"slots": [DisponibilidadeSlot(**s) for s in slots]}


@api_router.put("/me/disponibilidade")
async def set_disponibilidade(payload: DisponibilidadeRequest, authorization: Optional[str] = Header(default=None)):
    doc = await _current_user(authorization)
    await _require_role(doc, "profissional")
    await db.disponibilidade.delete_many({"profissional_id": doc["user_id"]})
    if payload.slots:
        await db.disponibilidade.insert_many(
            [{"profissional_id": doc["user_id"], **s.model_dump()} for s in payload.slots]
        )
    return {"ok": True, "count": len(payload.slots)}


def _parse_hhmm(hhmm: str) -> time:
    h, m = hhmm.split(":")
    return time(int(h), int(m))


@api_router.get("/profissionais/{user_id}/slots", response_model=list[SlotDisponivel])
async def slots_disponiveis(user_id: str, servico_id: str = Query(...)):
    """Compute concrete slots for the next 14 days from weekly availability
    minus already-booked appointments.

    Tudo é calculado no fuso horário LOCAL do profissional (campo
    `timezone`, default America/Sao_Paulo) — o HH:MM que ele cadastra em
    disponibilidade é hora de parede no fuso dele, não UTC. `datetime.combine`
    com um `ZoneInfo` gera o instante absoluto correto automaticamente,
    inclusive em transições de horário de verão (não aplicável ao Brasil
    hoje, mas o código fica correto para qualquer fuso da lista).
    """
    svc = await db.servicos.find_one({"servico_id": servico_id, "ativo": True}, {"_id": 0})
    if not svc or svc["profissional_id"] != user_id:
        raise HTTPException(404, "Serviço não encontrado")
    prof = await db.users.find_one({"user_id": user_id}, {"_id": 0, "timezone": 1})
    tz = _tz_for(prof)
    weekly = await db.disponibilidade.find({"profissional_id": user_id}, {"_id": 0}).to_list(200)
    if not weekly:
        return []

    busy = await db.agendamentos.find(
        {
            "profissional_id": user_id,
            "status_agendamento": "agendado",
            "hold_status": {"$in": ["autorizado", "cancelando", "capturado_total", "capturado_taxa"]},
            "horario_inicio": {"$gte": _now()},
        },
        {"_id": 0, "horario_inicio": 1, "horario_fim": 1},
    ).to_list(500)

    duracao = timedelta(minutes=svc["duracao_min"])
    # Os slots pulam de tanto em tanto quanto o SERVIÇO dura — um serviço de
    # 60min gera 11:00, 12:00, 13:00…, nunca 11:00 e 11:30 juntos (que
    # deixaria o profissional ocupado até as 12:00 mas ainda oferecendo
    # 11:30 como opção). Antes disso era sempre 30min fixo, pulado disso
    # (= menos que a duração para qualquer serviço >30min) e dependendo só
    # da checagem de overlap pra não sobrepor — o que funciona depois de um
    # agendamento já confirmado, mas gera uma grade de horários errada
    # mesmo sem nenhum conflito real ainda.
    step = duracao
    result: list[SlotDisponivel] = []
    now = _now()
    # "Hoje" no calendário LOCAL do profissional — um profissional em
    # America/Noronha (UTC-2) e outro em America/Rio_Branco (UTC-5) podem
    # estar em dias de calendário diferentes no mesmo instante UTC.
    start_date_local = now.astimezone(tz).date()

    for d in range(0, 14):
        day_date = start_date_local + timedelta(days=d)
        weekday = day_date.weekday()  # Python: Mon=0, consistente com o weekday salvo
        day_slots = [s for s in weekly if s["weekday"] == weekday]
        for s in day_slots:
            slot_start_t = _parse_hhmm(s["hora_inicio"])
            slot_end_t = _parse_hhmm(s["hora_fim"])
            # combine com tzinfo=tz: o próprio ZoneInfo resolve o offset
            # correto pra essa data específica (cobre DST se algum dia
            # aplicável; hoje nenhum fuso brasileiro observa DST).
            cursor = datetime.combine(day_date, slot_start_t, tzinfo=tz)
            slot_end = datetime.combine(day_date, slot_end_t, tzinfo=tz)
            while cursor + duracao <= slot_end:
                if cursor > now + timedelta(minutes=15):
                    overlap = any(
                        cursor < _aware(b["horario_fim"]) and (cursor + duracao) > _aware(b["horario_inicio"])
                        for b in busy
                    )
                    if not overlap:
                        result.append(SlotDisponivel(
                            iso=cursor.isoformat(),
                            day_label=cursor.strftime("%a, %d %b"),
                            time_label=cursor.strftime("%H:%M"),
                        ))
                cursor += step
    return result[:200]


# ---------------------------------------------------------------------------
# Connect (Stripe Express)
# ---------------------------------------------------------------------------
@api_router.get("/me/connect", response_model=ConnectStatus)
async def connect_status(authorization: Optional[str] = Header(default=None)):
    doc = await _current_user(authorization)
    await _require_role(doc, "profissional")
    acct_id = doc.get("stripe_account_id")
    if not acct_id or GATEWAY_KIND != "stripe":
        return ConnectStatus(account_id=acct_id)
    try:
        st = await gateway.account_status(acct_id)
        connect_ready = bool(st.get("charges_enabled") and st.get("payouts_enabled"))
        await db.users.update_one({"user_id": doc["user_id"]}, {"$set": {"connect_ready": connect_ready}})
        return ConnectStatus(account_id=acct_id, **st)
    except Exception:
        return ConnectStatus(account_id=acct_id)


# Página web pública (Firebase Hosting) onde o cliente agenda pelo link do
# profissional — é a mesma base que o app mostra em "Seu link de agendamento".
PUBLIC_WEB_BASE_URL = os.environ.get("PUBLIC_WEB_BASE_URL", "https://showup-509120.web.app").rstrip("/")


def _connect_prefill(doc: dict) -> dict:
    """O que a gente já sabe do profissional e pode entregar pro Stripe
    pré-preenchido, pra ele não precisar digitar site nem ramo de atividade
    no onboarding. O "site" é a própria página de agendamento dele no
    ShowUp (é o que a doc do Stripe orienta pra autônomo sem site)."""
    categorias = [c for c in (doc.get("categorias") or []) if c]
    descricao = "Profissional autônomo que atende clientes com hora marcada e recebe os pagamentos pelo ShowUp"
    if categorias:
        descricao += f" (categorias: {', '.join(categorias)})"
    return {
        "profile_url": f"{PUBLIC_WEB_BASE_URL}/agendar?prof={doc['user_id']}",
        "product_description": descricao + ".",
    }


@api_router.post("/me/connect/onboarding", response_model=ConnectLink)
@limiter.limit("10/minute")
async def connect_onboarding(
    request: Request,
    return_url: str = Query(...),
    refresh_url: str = Query(...),
    authorization: Optional[str] = Header(default=None),
):
    doc = await _current_user(authorization)
    await _require_role(doc, "profissional")
    if GATEWAY_KIND != "stripe":
        raise HTTPException(400, "Connect requer gateway Stripe real")

    acct_id = doc.get("stripe_account_id")
    try:
        if not acct_id:
            acct_id = await gateway.create_connect_account(
                doc["email"], doc["name"], country=MOEDA_PAIS_CONNECT.get(doc.get("moeda") or DEFAULT_MOEDA, "BR"),
                **_connect_prefill(doc),
            )
            if not acct_id:
                raise HTTPException(400, "Connect não habilitado na conta Stripe da plataforma. Ative em https://dashboard.stripe.com/connect")
            await db.users.update_one({"user_id": doc["user_id"]}, {"$set": {"stripe_account_id": acct_id}})
        else:
            # Conta criada antes desse pré-preenchimento existir: completa o
            # perfil público se ainda estiver vazio (best-effort, não bloqueia).
            await gateway.prefill_connect_profile(acct_id, **_connect_prefill(doc))

        try:
            url = await gateway.create_onboarding_link(acct_id, return_url=return_url, refresh_url=refresh_url)
        except InvalidPaymentRequestError as e:
            if "No such" not in str(e):
                raise HTTPException(400, str(e))
            # Mesmo cenário do customer_id órfão nos planos: a conta conectada
            # salva é de outro modo/conta do Stripe (ex: foi criada em modo
            # live, depois trocamos pra chave de teste) — recria e tenta de novo.
            logging.warning("stripe_account_id %s não existe na conta/modo atual — recriando", acct_id)
            acct_id = await gateway.create_connect_account(
                doc["email"], doc["name"], country=MOEDA_PAIS_CONNECT.get(doc.get("moeda") or DEFAULT_MOEDA, "BR"),
                **_connect_prefill(doc),
            )
            if not acct_id:
                raise HTTPException(400, "Connect não habilitado na conta Stripe da plataforma. Ative em https://dashboard.stripe.com/connect")
            await db.users.update_one({"user_id": doc["user_id"]}, {"$set": {"stripe_account_id": acct_id}})
            try:
                url = await gateway.create_onboarding_link(acct_id, return_url=return_url, refresh_url=refresh_url)
            except InvalidPaymentRequestError as e2:
                raise HTTPException(400, str(e2))
    except InvalidPaymentRequestError as e:
        # É informação nossa (campo que mandamos errado), não um segredo —
        # mostra a mensagem real em vez de esconder atrás de "gateway falhou".
        logging.exception("connect_onboarding falhou")
        raise HTTPException(400, str(e))
    except PaymentError:
        logging.exception("connect_onboarding falhou")
        raise HTTPException(502, "Falha ao gerar link de onboarding junto ao gateway")
    return ConnectLink(url=url)


# ---------------------------------------------------------------------------
# Planos de assinatura (taxa por agendamento decresce conforme o plano sobe)
# ---------------------------------------------------------------------------
@api_router.get("/planos")
async def listar_planos():
    return {
        "planos": [
            {
                "id": pid,
                "nome": p["nome"],
                "fee_percent": p["fee_bps"] / 100,
                "preco_centavos": p["preco_centavos"],
                "disponivel": _plano_disponivel(p),
            }
            for pid, p in PLANOS.items()
        ],
        "trial_dias": TRIAL_DIAS,
    }


@api_router.get("/me/plano/resumo", response_model=PlanoResumoResponse)
async def plano_resumo(authorization: Optional[str] = Header(default=None)):
    """A conta que o profissional quer ver antes de assinar: o que ele
    movimentou pelo app nos últimos 30 dias e quanto pagaria em cada plano com
    esse mesmo movimento — mais o que o app recuperou em faltas.

    Base de cálculo = agendamentos já COBRADOS (compareceu → capturado_total,
    falta → capturado_taxa). A taxa de cada um incide sobre o valor do
    serviço (`valor_total_centavos`), que é como ela é calculada na cobrança
    (ver authorize em stripe_gateway.py)."""
    doc = await _current_user(authorization)
    await _require_role(doc, "profissional")
    moeda = doc.get("moeda") or DEFAULT_MOEDA
    plano_atual = doc.get("plano") or DEFAULT_PLANO
    if plano_atual not in PLANOS:
        plano_atual = DEFAULT_PLANO

    desde = _now() - timedelta(days=RESUMO_JANELA_DIAS)
    itens = await db.agendamentos.find(
        {
            "profissional_id": doc["user_id"],
            "hold_status": {"$in": ["capturado_total", "capturado_taxa"]},
            "horario_inicio": {"$gte": desde},
            "moeda": moeda,
        },
        {"_id": 0, "valor_total_centavos": 1, "valor_capturado_centavos": 1, "hold_status": 1},
    ).to_list(5000)

    atendimentos = [i for i in itens if i.get("hold_status") == "capturado_total"]
    faltas = [i for i in itens if i.get("hold_status") == "capturado_taxa"]
    valores = [int(i.get("valor_total_centavos") or 0) for i in itens]

    comparacao_ok = moeda == "BRL"
    linhas = calcular_comparacao_planos(valores, plano_atual) if comparacao_ok else []
    melhores = [l for l in linhas if l["disponivel"] and l["economia_vs_atual_centavos"] > 0]
    recomendado = (
        max(melhores, key=lambda l: l["economia_vs_atual_centavos"])["id"] if melhores and valores else None
    )

    termina_em = doc.get("plano_trial_termina_em")
    return PlanoResumoResponse(
        plano_atual=plano_atual,
        moeda=moeda,
        janela_dias=RESUMO_JANELA_DIAS,
        atendimentos_cobrados=len(atendimentos),
        servicos_cobrados_centavos=sum(int(i.get("valor_capturado_centavos") or 0) for i in atendimentos),
        base_taxa_centavos=sum(valores),
        faltas_cobradas_qtd=len(faltas),
        faltas_cobradas_centavos=sum(int(i.get("valor_capturado_centavos") or 0) for i in faltas),
        comparacao_disponivel=comparacao_ok,
        comparacao=[PlanoComparacao(**l) for l in linhas],
        recomendado=recomendado,
        trial_disponivel=_trial_disponivel(doc) and comparacao_ok,
        trial_dias=TRIAL_DIAS,
        trial_termina_em=_aware(termina_em) if (termina_em and plano_atual != DEFAULT_PLANO) else None,
    )


@api_router.post("/me/plano/subscription-intent", response_model=PlanoSubscriptionIntentResponse)
@limiter.limit("10/minute")
async def plano_subscription_intent(request: Request, payload: PlanoCheckoutRequest, authorization: Optional[str] = Header(default=None)):
    """Primeiro passo pra assinar um plano pago — mesma lógica do
    /me/card/setup-intent: prepara tudo que o Payment Sheet nativo do app
    precisa, sem abrir nenhum navegador/página hospedada. A assinatura já
    é criada aqui (com payment_behavior='default_incomplete'), mas só fica
    de fato ativa depois que /me/plano/confirm verificar que o pagamento
    passou."""
    doc = await _current_user(authorization)
    await _require_role(doc, "profissional")
    if GATEWAY_KIND != "stripe":
        raise HTTPException(400, "Assinatura de plano requer gateway Stripe real")

    plano_cfg = PLANOS[payload.plano]
    price_id = os.environ.get(plano_cfg["price_env"] or "")
    if not price_id:
        raise HTTPException(400, f"Plano {payload.plano} ainda não tem Price ID configurado no servidor")

    if payload.usar_trial and not _trial_disponivel(doc):
        raise HTTPException(400, "Teste grátis indisponível: ele só vale uma vez, pra quem ainda não assinou nenhum plano")
    trial_dias = TRIAL_DIAS if payload.usar_trial else 0

    billing_customer_id = doc.get("stripe_billing_customer_id")

    async def _prepare_payment_sheet(customer_id: str):
        ephemeral_key = await gateway.create_ephemeral_key(customer_id)
        sub = await gateway.create_plano_subscription(
            customer_id, price_id, user_id=doc["user_id"], trial_days=trial_dias,
        )
        return ephemeral_key, sub

    if not billing_customer_id:
        billing_customer_id = await gateway.ensure_billing_customer(doc["user_id"], doc["email"], doc["name"])
        await db.users.update_one({"user_id": doc["user_id"]}, {"$set": {"stripe_billing_customer_id": billing_customer_id}})

    try:
        ephemeral_key, sub = await _prepare_payment_sheet(billing_customer_id)
    except InvalidPaymentRequestError as e:
        if "No such" not in str(e):
            raise HTTPException(400, str(e))
        # O customer_id salvo é de outra conta/modo do Stripe (ex: trocamos
        # de chave live pra teste durante o desenvolvimento) — clientes não
        # são compartilhados entre contas/modos. Em vez de travar o usuário
        # pra sempre, criamos um customer novo e tentamos de novo uma vez.
        logging.warning("stripe_billing_customer_id %s não existe na conta/modo atual — recriando", billing_customer_id)
        billing_customer_id = await gateway.ensure_billing_customer(doc["user_id"], doc["email"], doc["name"])
        await db.users.update_one({"user_id": doc["user_id"]}, {"$set": {"stripe_billing_customer_id": billing_customer_id}})
        try:
            ephemeral_key, sub = await _prepare_payment_sheet(billing_customer_id)
        except InvalidPaymentRequestError as e2:
            raise HTTPException(400, str(e2))
    except PaymentError:
        logging.exception("plano_subscription_intent falhou")
        raise HTTPException(502, "Falha ao criar assinatura junto ao gateway")
    if trial_dias and not (sub.get("setup_intent_client_secret") and sub.get("setup_intent_id")):
        # O Stripe não devolveu o SetupIntent do teste: sem ele não tem como
        # salvar o cartão, e deixar a assinatura criada daria teste sem cartão.
        logging.error("teste grátis sem pending_setup_intent (sub=%s)", sub.get("subscription_id"))
        await gateway.cancel_subscription(sub["subscription_id"])
        raise HTTPException(502, "Não foi possível preparar o teste grátis agora. Tente de novo.")

    # Quem abriu o Payment Sheet, fechou sem salvar o cartão e tentou de novo
    # deixaria a assinatura anterior órfã no Stripe (no teste grátis ela
    # nasce `trialing`). Cancela a anterior agora que a nova já existe.
    anterior = (doc.get("plano_pendente") or {}).get("subscription_id")
    if anterior and anterior != sub["subscription_id"]:
        try:
            await gateway.cancel_subscription(anterior)
        except PaymentError:
            logging.warning("não consegui cancelar a assinatura pendente anterior %s", anterior)

    # O servidor guarda O QUE foi criado pra esse profissional. É isso — não o
    # que o app disser depois — que decide o plano em /me/plano/confirm.
    await db.users.update_one(
        {"user_id": doc["user_id"]},
        {"$set": {"plano_pendente": {
            "subscription_id": sub["subscription_id"],
            "plano": payload.plano,
            "trial": bool(trial_dias),
            "setup_intent_id": sub.get("setup_intent_id"),
        }}},
    )
    return PlanoSubscriptionIntentResponse(
        customer_id=billing_customer_id,
        ephemeral_key_secret=ephemeral_key,
        payment_intent_client_secret=sub.get("payment_intent_client_secret"),
        setup_intent_client_secret=sub.get("setup_intent_client_secret"),
        trial_dias=trial_dias,
        subscription_id=sub["subscription_id"],
    )


@api_router.post("/me/plano/confirm", response_model=MeResponse)
@limiter.limit("10/minute")
async def plano_confirm(request: Request, payload: ConfirmPlanoRequest, authorization: Optional[str] = Header(default=None)):
    """Segundo passo: depois que o Payment Sheet fecha com sucesso, confirma
    DE VERDADE com o Stripe antes de liberar a taxa reduzida — nunca confia
    no "sucesso" que o SDK do app reporta, nem no plano que o app manda.

    - O plano vem do registro `plano_pendente` que o servidor gravou em
      /subscription-intent; o que o app envia só é conferido contra ele.
    - Assinatura paga: precisa estar `active`.
    - Teste grátis: a assinatura já nasce `trialing` ANTES do cartão ser salvo
      (por isso status sozinho não vale) — exige o SetupIntent `succeeded`."""
    doc = await _current_user(authorization)
    await _require_role(doc, "profissional")

    # Idempotente: duplo toque / retry de rede depois de já confirmado.
    if doc.get("stripe_subscription_id") == payload.subscription_id and doc.get("plano") == payload.plano:
        return MeResponse(user=await _serialize_user(doc))

    pend = doc.get("plano_pendente")
    if not pend or pend.get("subscription_id") != payload.subscription_id:
        raise HTTPException(400, "Nenhuma assinatura pendente pra confirmar")
    if pend.get("plano") != payload.plano:
        raise HTTPException(400, "Plano diferente do que foi preparado")

    info = await gateway.get_subscription_details(payload.subscription_id)
    if info.get("user_id") not in (None, doc["user_id"]):
        raise HTTPException(403, "Assinatura de outro usuário")

    update: dict = {"plano": pend["plano"], "stripe_subscription_id": payload.subscription_id}
    if pend.get("trial"):
        if info["status"] != "trialing":
            raise HTTPException(402, f"Teste grátis não confirmado (status da assinatura: {info['status']})")
        si_id = pend.get("setup_intent_id")
        si_status = await gateway.get_setup_intent_status(si_id) if si_id else None
        if si_status != "succeeded":
            raise HTTPException(402, f"Cartão do teste grátis não confirmado (status: {si_status})")
        update["plano_trial_usado"] = True
        if info.get("trial_end"):
            update["plano_trial_termina_em"] = datetime.fromtimestamp(info["trial_end"], tz=timezone.utc)
    else:
        if info["status"] != "active":
            raise HTTPException(402, f"Pagamento não confirmado (status da assinatura: {info['status']})")
        update["plano_ja_pago"] = True

    await db.users.update_one(
        {"user_id": doc["user_id"]},
        {"$set": update, "$unset": {"plano_pendente": ""}},
    )
    doc = await db.users.find_one({"user_id": doc["user_id"]}, {"_id": 0})
    return MeResponse(user=await _serialize_user(doc))


@api_router.post("/me/plano/cancelar")
async def plano_cancelar(authorization: Optional[str] = Header(default=None)):
    """Cancela imediatamente (não espera fim do período já pago) e volta pro
    Free na hora — mais simples e previsível pro MVP que lidar com o estado
    intermediário de "cancelamento agendado para o fim do período"."""
    doc = await _current_user(authorization)
    await _require_role(doc, "profissional")
    sub_id = doc.get("stripe_subscription_id")
    if sub_id and GATEWAY_KIND == "stripe":
        await gateway.cancel_subscription(sub_id)
    await db.users.update_one(
        {"user_id": doc["user_id"]},
        # plano_trial_usado/plano_ja_pago ficam de propósito: cancelar não
        # devolve o direito a um novo teste grátis.
        {"$set": {"plano": DEFAULT_PLANO},
         "$unset": {"stripe_subscription_id": "", "plano_pendente": "", "plano_trial_termina_em": ""}},
    )
    doc = await db.users.find_one({"user_id": doc["user_id"]}, {"_id": 0})
    return MeResponse(user=await _serialize_user(doc))


# ---------------------------------------------------------------------------
# Agendamentos
# ---------------------------------------------------------------------------
async def _hydrate(doc: dict) -> Agendamento:
    prof = await db.users.find_one({"user_id": doc["profissional_id"]}, {"_id": 0, "name": 1})
    cli = await db.users.find_one({"user_id": doc["cliente_id"]}, {"_id": 0, "name": 1})
    svc = await db.servicos.find_one({"servico_id": doc["servico_id"]}, {"_id": 0, "nome": 1})
    # Esses 7 campos são sobrescritos explicitamente abaixo (precisam
    # passar por _aware() antes de virar JSON — ver o comentário logo
    # adiante) — por isso ficam de fora do spread: passar a MESMA chave
    # duas vezes pro construtor (uma crua via spread, outra convertida via
    # argumento nomeado) é um TypeError em Python, não uma sobrescrita.
    _campos_convertidos = {
        "horario_inicio", "horario_fim", "hold_expira_em",
        "janela_confirmacao_expira_em", "criado_em",
        "push_pergunta_enviada_em", "push_urgencia_enviada_em",
    }
    return Agendamento(
        **{k: v for k, v in doc.items() if k != "_id" and k not in _campos_convertidos},
        # O Mongo devolve datetime "naive" (sem tzinfo), mas o valor salvo é
        # sempre UTC — sem marcar isso explicitamente, o JSON final sai sem
        # o sufixo "Z"/offset (ex: "2026-10-01T14:00:00" em vez de
        # "...+00:00"), e o celular do cliente interpreta isso como se
        # fosse HORA LOCAL DELE, não UTC — um agendamento às 11:00 (BRT,
        # salvo como 14:00 UTC) reaparecia como "14:00" no app, 3h adiantado.
        horario_inicio=_aware(doc["horario_inicio"]),
        horario_fim=_aware(doc["horario_fim"]),
        hold_expira_em=_aware(doc["hold_expira_em"]),
        janela_confirmacao_expira_em=_aware(doc["janela_confirmacao_expira_em"]),
        criado_em=_aware(doc["criado_em"]),
        push_pergunta_enviada_em=_aware(doc["push_pergunta_enviada_em"]) if doc.get("push_pergunta_enviada_em") else None,
        push_urgencia_enviada_em=_aware(doc["push_urgencia_enviada_em"]) if doc.get("push_urgencia_enviada_em") else None,
        profissional_nome=prof["name"] if prof else "—",
        cliente_nome=cli["name"] if cli else "—",
        servico_nome=svc["nome"] if svc else "—",
    )


@api_router.post("/agendamentos", response_model=Agendamento)
@limiter.limit("20/minute")
async def criar_agendamento(request: Request, payload: AgendamentoCreate, authorization: Optional[str] = Header(default=None)):
    cliente = await _current_user(authorization)
    await _require_role(cliente, "cliente")
    card = await db.customer_cards.find_one({"user_id": cliente["user_id"]}, {"_id": 0})
    if not card:
        raise HTTPException(422, "Cartão não cadastrado")
    svc = await db.servicos.find_one({"servico_id": payload.servico_id, "ativo": True}, {"_id": 0})
    if not svc:
        raise HTTPException(404, "Serviço não encontrado")
    horario = _aware(payload.horario_inicio)
    if horario <= _now():
        raise HTTPException(422, "Horário deve ser futuro")
    horario_fim = horario + timedelta(minutes=svc["duracao_min"])

    # --- Checagem de conflito (double-booking) ---
    # /profissionais/{id}/slots calcula os horários livres, mas nada aqui
    # impedia a criação direta de um agendamento sobreposto — dois clientes
    # via o mesmo slot exibido (ou requisições simultâneas do mesmo cliente)
    # podiam ambos reservar o mesmo horário. Verificação por sobreposição de
    # intervalo, não só igualdade de horário_inicio, para cobrir serviços de
    # duração diferente.
    conflito = await db.agendamentos.find_one({
        "profissional_id": svc["profissional_id"],
        "hold_status": {"$in": ["autorizado", "cancelando", "capturado_total", "capturado_taxa"]},
        "horario_inicio": {"$lt": horario_fim},
        "horario_fim": {"$gt": horario},
    })
    if conflito:
        raise HTTPException(409, "Esse horário acabou de ser reservado por outro cliente. Escolha outro.")

    # Optional Connect destination for split.
    prof = await db.users.find_one({"user_id": svc["profissional_id"]}, {"_id": 0})
    destination = None
    if prof and prof.get("connect_ready") and prof.get("stripe_account_id"):
        destination = prof["stripe_account_id"]

    try:
        agendamento_id = f"agd_{uuid.uuid4().hex[:12]}"
        hold_kwargs = dict(
            customer_id=card["customer_id"],
            payment_method_id=card["payment_method_id"],
            amount_centavos=svc["valor_centavos"],
            moeda=svc["moeda"],
            fee_bps=_fee_bps_for(prof),
            # Chave determinística a partir do agendamento_id: um retry desta
            # mesma requisição (timeout no cliente, nova tentativa do app)
            # nunca resulta em um segundo hold no cartão.
            idempotency_key=f"hold_{agendamento_id}",
            metadata={"servico_id": svc["servico_id"], "cliente_id": cliente["user_id"]},
        )
        if GATEWAY_KIND == "stripe":
            hold_kwargs["destination_account_id"] = destination
        hold = await gateway.authorize(**hold_kwargs)
    except CardDeclinedError:
        raise HTTPException(402, "Cartão recusado pela operadora. Tente outro cartão.")
    except GatewayUnavailableError:
        raise HTTPException(503, "Gateway de pagamento indisponível no momento. Tente novamente em instantes.")
    except (InvalidPaymentRequestError, PaymentError) as e:
        logging.exception("hold falhou")
        raise HTTPException(402, "Falha ao autorizar cartão")

    doc = {
        "agendamento_id": agendamento_id,
        "profissional_id": svc["profissional_id"],
        "cliente_id": cliente["user_id"],
        "servico_id": svc["servico_id"],
        "horario_inicio": horario, "horario_fim": horario_fim,
        "valor_total_centavos": svc["valor_centavos"],
        "valor_no_show_centavos": svc["taxa_no_show_centavos"],
        "moeda": svc["moeda"],
        "status_agendamento": "agendado", "status_confirmacao": "pendente",
        "payment_intent_id": hold["payment_intent_id"],
        "hold_status": "autorizado",
        "hold_expira_em": hold["hold_expira_em"],
        "janela_confirmacao_expira_em": horario_fim + timedelta(hours=24),
        "valor_capturado_centavos": 0,
        "connect_destination": destination,
        "criado_em": _now(),
        "push_pergunta_enviada_em": None,
        "push_urgencia_enviada_em": None,
    }
    try:
        await db.agendamentos.insert_one(dict(doc))
    except DuplicateKeyError:
        # Perdemos a corrida contra outra requisição para o mesmo
        # profissional_id + horario_inicio entre a checagem de sobreposição
        # acima e este insert. O hold já foi autorizado no cartão do
        # perdedor — precisa ser desfeito, ou o cliente fica com limite
        # travado por um agendamento que nunca existiu.
        try:
            await gateway.void(hold["payment_intent_id"], idempotency_key=f"void_race_{agendamento_id}")
        except PaymentError:
            logging.exception("Falha ao desfazer hold órfão de corrida p/ %s", agendamento_id)
        raise HTTPException(409, "Esse horário acabou de ser reservado por outro cliente. Escolha outro.")
    await db.transacoes.insert_one({
        "transacao_id": f"tx_{uuid.uuid4().hex[:12]}",
        "agendamento_id": doc["agendamento_id"], "tipo": "authorization",
        "valor_centavos": doc["valor_total_centavos"], "moeda": doc["moeda"],
        "gateway_object_id": doc["payment_intent_id"], "status": "requires_capture",
        "criado_em": _now(),
    })
    return await _hydrate(doc)


@api_router.post("/public/cartao/setup-intent", response_model=CartaoSetupPublicoResponse)
@limiter.limit("10/minute")
async def cartao_setup_intent_publico(request: Request, payload: CartaoSetupPublicoRequest):
    """Passo 1 do cartão no link público. Acha/cria o cliente pelo telefone,
    garante o customer no Stripe e devolve o client_secret de um SetupIntent
    (usage=off_session, o mesmo tipo que o authorize() exige depois). O
    número do cartão vai direto da página pro Stripe (Stripe.js) — nunca
    passa por aqui. Passo 2 é o /public/agendamentos/cartao, já com o
    payment_method_id que o Stripe.js devolve."""
    cliente = await _find_or_create_cliente_por_telefone(payload.nome, payload.telefone)
    customer_id = await gateway.ensure_customer(cliente["user_id"], cliente["email"], cliente["name"])
    try:
        setup_intent = await gateway.create_setup_intent(customer_id)
    except PaymentError:
        logging.exception("create_setup_intent falhou (link público)")
        raise HTTPException(503, "Não foi possível preparar o pagamento com cartão agora. Tente de novo.")
    return CartaoSetupPublicoResponse(setup_intent_client_secret=setup_intent["client_secret"])


@api_router.post("/public/agendamentos/cartao", response_model=Agendamento)
@limiter.limit("10/minute")
async def criar_agendamento_publico_cartao(request: Request, payload: AgendamentoPublicoCartaoRequest):
    """Mesmo fluxo de hold do endpoint autenticado, mas pro cliente que vem
    do link do WhatsApp (sem conta/sessão no app) — o cartão foi coletado
    na página web via Stripe.js Elements, não no Payment Sheet nativo."""
    cliente = await _find_or_create_cliente_por_telefone(payload.nome, payload.telefone)
    svc, prof, horario_fim = await _valida_servico_e_conflito(payload.servico_id, payload.horario_inicio)
    if svc["profissional_id"] != payload.profissional_id:
        raise HTTPException(400, "servico_id não pertence ao profissional_id informado")
    horario = _aware(payload.horario_inicio)

    destination = None
    if prof and prof.get("connect_ready") and prof.get("stripe_account_id"):
        destination = prof["stripe_account_id"]

    customer_id = await gateway.ensure_customer(cliente["user_id"], cliente["email"], cliente["name"])

    try:
        agendamento_id = f"agd_{uuid.uuid4().hex[:12]}"
        hold_kwargs = dict(
            customer_id=customer_id,
            payment_method_id=payload.payment_method_id,
            amount_centavos=svc["valor_centavos"],
            moeda=svc["moeda"],
            fee_bps=_fee_bps_for(prof),
            idempotency_key=f"hold_{agendamento_id}",
            metadata={"servico_id": svc["servico_id"], "cliente_id": cliente["user_id"], "origem": "link_publico"},
        )
        if GATEWAY_KIND == "stripe":
            hold_kwargs["destination_account_id"] = destination
        hold = await gateway.authorize(**hold_kwargs)
    except CardDeclinedError:
        raise HTTPException(402, "Cartão recusado pela operadora. Tente outro cartão.")
    except GatewayUnavailableError:
        raise HTTPException(503, "Gateway de pagamento indisponível no momento. Tente novamente em instantes.")
    except (InvalidPaymentRequestError, PaymentError):
        logging.exception("hold falhou (link público)")
        raise HTTPException(402, "Falha ao autorizar cartão")

    doc = {
        "agendamento_id": agendamento_id,
        "profissional_id": svc["profissional_id"],
        "cliente_id": cliente["user_id"],
        "servico_id": svc["servico_id"],
        "horario_inicio": horario, "horario_fim": horario_fim,
        "valor_total_centavos": svc["valor_centavos"],
        "valor_no_show_centavos": svc["taxa_no_show_centavos"],
        "moeda": svc["moeda"],
        "status_agendamento": "agendado", "status_confirmacao": "pendente",
        "payment_intent_id": hold["payment_intent_id"],
        "hold_status": "autorizado",
        "hold_expira_em": hold["hold_expira_em"],
        "janela_confirmacao_expira_em": horario_fim + timedelta(hours=24),
        "valor_capturado_centavos": 0,
        "connect_destination": destination,
        "origem": "link_publico",
        "criado_em": _now(),
        "push_pergunta_enviada_em": None,
        "push_urgencia_enviada_em": None,
    }
    try:
        await db.agendamentos.insert_one(dict(doc))
    except DuplicateKeyError:
        try:
            await gateway.void(hold["payment_intent_id"], idempotency_key=f"void_race_{agendamento_id}")
        except PaymentError:
            logging.exception("Falha ao desfazer hold órfão de corrida p/ %s", agendamento_id)
        raise HTTPException(409, "Esse horário acabou de ser reservado por outro cliente. Escolha outro.")
    await db.transacoes.insert_one({
        "transacao_id": f"tx_{uuid.uuid4().hex[:12]}",
        "agendamento_id": doc["agendamento_id"], "tipo": "authorization",
        "valor_centavos": doc["valor_total_centavos"], "moeda": doc["moeda"],
        "gateway_object_id": doc["payment_intent_id"], "status": "requires_capture",
        "criado_em": _now(),
    })
    return await _hydrate(doc)


@api_router.post("/public/agendamentos/pix", response_model=AgendamentoPublicoPixResponse)
@limiter.limit("10/minute")
async def criar_agendamento_publico_pix(request: Request, payload: AgendamentoPublicoCreate):
    """Pix não suporta hold (ver create_pix_payment_intent) — cobra o valor
    TOTAL do serviço de uma vez, sem proteção de no-show. O agendamento
    fica reservado por tempo LIMITADO (PIX_RESERVA_MINUTOS) esperando o
    pagamento confirmar via webhook; se expirar sem pagar, libera o
    horário sozinho (job _expirar_pix_pendentes)."""
    if GATEWAY_KIND != "stripe":
        raise HTTPException(400, "Pix requer gateway Stripe real")
    cliente = await _find_or_create_cliente_por_telefone(payload.nome, payload.telefone)
    svc, prof, horario_fim = await _valida_servico_e_conflito(payload.servico_id, payload.horario_inicio)
    if svc["profissional_id"] != payload.profissional_id:
        raise HTTPException(400, "servico_id não pertence ao profissional_id informado")
    horario = _aware(payload.horario_inicio)

    destination = None
    if prof and prof.get("connect_ready") and prof.get("stripe_account_id"):
        destination = prof["stripe_account_id"]

    agendamento_id = f"agd_{uuid.uuid4().hex[:12]}"
    try:
        pix = await gateway.create_pix_payment_intent(
            amount_centavos=svc["valor_centavos"],
            moeda=svc["moeda"],
            fee_bps=_fee_bps_for(prof),
            idempotency_key=f"pix_{agendamento_id}",
            metadata={"agendamento_id": agendamento_id, "servico_id": svc["servico_id"], "cliente_id": cliente["user_id"]},
            destination_account_id=destination,
        )
    except InvalidPaymentRequestError as e:
        logging.exception("criação de PaymentIntent Pix falhou")
        # Pix é liberado por convite pro Stripe Brasil (conta com 60+ dias
        # processando). Se o Stripe recusa o tipo "pix", o problema não é
        # transitório nem do cliente — é a conta ainda não ter Pix. Mensagem
        # própria em vez de "falha no gateway", pra pagina poder orientar.
        if "pix" in str(e).lower() and "invalid" in str(e).lower():
            raise HTTPException(503, "Pix indisponível no momento. Pague com cartão.")
        raise HTTPException(502, "Falha ao gerar cobrança Pix junto ao gateway")
    except PaymentError:
        logging.exception("criação de PaymentIntent Pix falhou")
        raise HTTPException(502, "Falha ao gerar cobrança Pix junto ao gateway")

    expira_em = _now() + timedelta(minutes=PIX_RESERVA_MINUTOS)
    doc = {
        "agendamento_id": agendamento_id,
        "profissional_id": svc["profissional_id"],
        "cliente_id": cliente["user_id"],
        "servico_id": svc["servico_id"],
        "horario_inicio": horario, "horario_fim": horario_fim,
        "valor_total_centavos": svc["valor_centavos"],
        "valor_no_show_centavos": 0,  # Pix já cobrou o total — não há taxa de no-show separada
        "moeda": svc["moeda"],
        "status_agendamento": "agendado", "status_confirmacao": "pendente",
        "payment_intent_id": pix["payment_intent_id"],
        "hold_status": "aguardando_pix",
        "hold_expira_em": expira_em,
        "janela_confirmacao_expira_em": horario_fim + timedelta(hours=24),
        "valor_capturado_centavos": 0,
        "connect_destination": destination,
        "metodo_pagamento": "pix",
        "origem": "link_publico",
        "criado_em": _now(),
        "push_pergunta_enviada_em": None,
        "push_urgencia_enviada_em": None,
    }
    try:
        await db.agendamentos.insert_one(dict(doc))
    except DuplicateKeyError:
        raise HTTPException(409, "Esse horário acabou de ser reservado por outro cliente. Escolha outro.")
    return AgendamentoPublicoPixResponse(
        agendamento_id=agendamento_id,
        payment_intent_client_secret=pix["client_secret"],
        qr_code_data=pix.get("qr_code_data"),
        hosted_instructions_url=pix.get("hosted_instructions_url"),
        expira_em=expira_em,
    )


@api_router.get("/public/agendamentos/{agendamento_id}/status")
@limiter.limit("60/minute")
async def status_agendamento_publico(request: Request, agendamento_id: str):
    """Endpoint público (sem auth) pra página web do link do WhatsApp fazer
    polling e saber quando o Pix confirmou — o pagamento acontece fora do
    nosso controle (app do banco do cliente), então não temos como saber
    na hora, só via webhook + o cliente checando de volta."""
    doc = await db.agendamentos.find_one({"agendamento_id": agendamento_id}, {"_id": 0, "hold_status": 1, "status_agendamento": 1})
    if not doc:
        raise HTTPException(404, "Agendamento não encontrado")
    return {"hold_status": doc["hold_status"], "status_agendamento": doc["status_agendamento"]}


@api_router.get("/agendamentos", response_model=list[Agendamento])
async def listar_agendamentos(authorization: Optional[str] = Header(default=None)):
    doc = await _current_user(authorization)
    role = doc.get("role")
    if role == "cliente":
        query = {"cliente_id": doc["user_id"]}
    elif role == "profissional":
        query = {"profissional_id": doc["user_id"]}
    else:
        raise HTTPException(400, "Papel não definido")
    items = await db.agendamentos.find(query, {"_id": 0}).sort("horario_inicio", 1).to_list(200)
    return [await _hydrate(it) for it in items]


@api_router.get("/agendamentos/{agendamento_id}", response_model=Agendamento)
async def detalhe_agendamento(agendamento_id: str, authorization: Optional[str] = Header(default=None)):
    doc = await _current_user(authorization)
    ag = await db.agendamentos.find_one({"agendamento_id": agendamento_id}, {"_id": 0})
    if not ag:
        raise HTTPException(404, "Não encontrado")
    if doc["user_id"] not in (ag["cliente_id"], ag["profissional_id"]):
        raise HTTPException(403, "Acesso negado")
    return await _hydrate(ag)


@api_router.post("/agendamentos/{agendamento_id}/confirmar", response_model=Agendamento)
@limiter.limit("30/minute")
async def confirmar(
    request: Request,
    agendamento_id: str,
    payload: ConfirmacaoRequest,
    authorization: Optional[str] = Header(default=None),
):
    doc = await _current_user(authorization)
    await _require_role(doc, "profissional")
    ag = await db.agendamentos.find_one({"agendamento_id": agendamento_id}, {"_id": 0})
    if not ag:
        raise HTTPException(404, "Não encontrado")
    if ag["profissional_id"] != doc["user_id"]:
        raise HTTPException(403, "Acesso negado")
    if ag["status_confirmacao"] not in ("pendente",):
        raise HTTPException(409, f"Já confirmado ou em processamento: {ag['status_confirmacao']}")
    if ag["hold_status"] != "autorizado":
        raise HTTPException(409, f"Hold não autorizado: {ag['hold_status']}")
    if _now() > _aware(ag["janela_confirmacao_expira_em"]):
        raise HTTPException(410, "Janela expirada")

    # --- Guarda atômica contra corrida ---
    # Duas requisições concorrentes (duplo-toque no app, retry de rede) podem
    # ambas passar pelas validações acima antes de qualquer uma gravar no
    # banco. Para evitar capturar o pagamento duas vezes, "reivindicamos" o
    # agendamento numa única operação atômica no Mongo: só quem conseguir
    # transicionar pendente -> processando segue para chamar o Stripe: a
    # ausência de resultado aqui significa que outra requisição já venceu a
    # corrida entre o nosso find_one acima e este update.
    claimed = await db.agendamentos.find_one_and_update(
        {"agendamento_id": agendamento_id, "status_confirmacao": "pendente", "hold_status": "autorizado"},
        {"$set": {"status_confirmacao": "processando"}},
    )
    if claimed is None:
        raise HTTPException(409, "Confirmação já em processamento por outra requisição")

    try:
        if payload.resultado == "compareceu":
            cap = await gateway.capture(
                ag["payment_intent_id"], amount_to_capture=None,
                idempotency_key=f"capture_{agendamento_id}_total",
            )
            update = {"status_confirmacao": "compareceu", "hold_status": "capturado_total",
                      "valor_capturado_centavos": cap["amount_received"]}
            tipo = "capture"
        else:
            cap = await gateway.capture(
                ag["payment_intent_id"], amount_to_capture=ag["valor_no_show_centavos"],
                idempotency_key=f"capture_{agendamento_id}_noshow",
            )
            update = {"status_confirmacao": "nao_compareceu", "hold_status": "capturado_taxa",
                      "valor_capturado_centavos": cap["amount_received"]}
            tipo = "partial_capture"
    except CardDeclinedError:
        # Hold já estava autorizado — recusa na captura é raríssima, mas
        # pode acontecer (cartão cancelado entre o agendamento e a captura).
        await db.agendamentos.update_one(
            {"agendamento_id": agendamento_id, "status_confirmacao": "processando"},
            {"$set": {"status_confirmacao": "pendente"}},
        )
        raise HTTPException(402, "Cartão recusado na captura. Contate o cliente.")
    except GatewayUnavailableError:
        await db.agendamentos.update_one(
            {"agendamento_id": agendamento_id, "status_confirmacao": "processando"},
            {"$set": {"status_confirmacao": "pendente"}},
        )
        raise HTTPException(503, "Gateway de pagamento indisponível. Tente confirmar novamente.")
    except PaymentError:
        # Gateway falhou depois que já reivindicamos o registro: devolvemos
        # ao estado "pendente" para que o profissional possa tentar de novo,
        # em vez de deixar o agendamento travado em "processando" para sempre.
        logging.exception("captura falhou p/ %s", agendamento_id)
        await db.agendamentos.update_one(
            {"agendamento_id": agendamento_id, "status_confirmacao": "processando"},
            {"$set": {"status_confirmacao": "pendente"}},
        )
        raise HTTPException(502, "Falha ao processar pagamento junto ao gateway")

    await db.agendamentos.update_one(
        {"agendamento_id": agendamento_id, "status_confirmacao": "processando"}, {"$set": update}
    )
    await db.transacoes.insert_one({
        "transacao_id": f"tx_{uuid.uuid4().hex[:12]}",
        "agendamento_id": agendamento_id, "tipo": tipo,
        "valor_centavos": cap["amount_received"], "moeda": ag["moeda"],
        "gateway_object_id": ag["payment_intent_id"], "status": "succeeded",
        "criado_em": _now(),
    })
    ag = await db.agendamentos.find_one({"agendamento_id": agendamento_id}, {"_id": 0})
    return await _hydrate(ag)


@api_router.post("/agendamentos/{agendamento_id}/cancelar")
@limiter.limit("30/minute")
async def cancelar(request: Request, agendamento_id: str, authorization: Optional[str] = Header(default=None)):
    doc = await _current_user(authorization)
    ag = await db.agendamentos.find_one({"agendamento_id": agendamento_id}, {"_id": 0})
    if not ag:
        raise HTTPException(404, "Não encontrado")
    if doc["user_id"] not in (ag["cliente_id"], ag["profissional_id"]):
        raise HTTPException(403, "Acesso negado")

    # --- Guarda atômica contra corrida com /confirmar e o job de expiração ---
    # Sem isso, um cancelamento do cliente podia entrar exatamente entre o
    # profissional confirmar "compareceu" e a captura terminar: os dois
    # liam hold_status="autorizado" ao mesmo tempo, e cancelar() chamava
    # gateway.void() num payment_intent que confirmar() estava capturando.
    # Reivindicamos a transição hold_status autorizado -> cancelando, e só
    # seguimos se também não houver uma confirmação em andamento.
    claimed = await db.agendamentos.find_one_and_update(
        {"agendamento_id": agendamento_id, "hold_status": "autorizado", "status_confirmacao": "pendente"},
        {"$set": {"hold_status": "cancelando"}},
    )
    if claimed is None:
        raise HTTPException(409, "Hold já processado ou confirmação em andamento — não é mais possível cancelar")

    try:
        await gateway.void(ag["payment_intent_id"], idempotency_key=f"void_{agendamento_id}")
    except PaymentError:
        logging.exception("void falhou p/ %s", agendamento_id)
        # Devolve ao estado anterior para permitir nova tentativa, em vez de
        # deixar o agendamento travado em "cancelando" para sempre.
        await db.agendamentos.update_one(
            {"agendamento_id": agendamento_id, "hold_status": "cancelando"},
            {"$set": {"hold_status": "autorizado"}},
        )
        raise HTTPException(502, "Falha ao cancelar hold junto ao gateway")

    status_label = "cancelado_cliente" if doc["user_id"] == ag["cliente_id"] else "cancelado_profissional"
    await db.agendamentos.update_one(
        {"agendamento_id": agendamento_id},
        {"$set": {"hold_status": "cancelado", "status_agendamento": status_label}},
    )
    return {"ok": True}


# ---------------------------------------------------------------------------
# Reminders (in-app)
# ---------------------------------------------------------------------------
@api_router.get("/reminders/janela")
async def reminders_janela(
    horas: int = Query(default=6, ge=1, le=48),
    authorization: Optional[str] = Header(default=None),
):
    """Agendamentos onde o profissional ainda não confirmou e a janela termina em <= `horas` horas."""
    doc = await _current_user(authorization)
    await _require_role(doc, "profissional")
    limite = _now() + timedelta(hours=horas)
    items = await db.agendamentos.find({
        "profissional_id": doc["user_id"],
        "status_confirmacao": "pendente",
        "hold_status": "autorizado",
        "horario_fim": {"$lte": _now()},
        "janela_confirmacao_expira_em": {"$lte": limite},
    }, {"_id": 0}).sort("janela_confirmacao_expira_em", 1).to_list(50)
    return {"count": len(items), "items": [await _hydrate(it) for it in items]}


async def _expirar_pix_pendentes() -> int:
    """Reservas via Pix (link público) que passaram do prazo sem confirmar
    pagamento — libera o horário pra outro cliente poder agendar. Diferente
    do fluxo de cartão, não precisa desfazer hold nenhum no gateway: Pix
    nunca trava nada no lado do cliente antes de pagar de verdade."""
    now = _now()
    result = await db.agendamentos.update_many(
        {"hold_status": "aguardando_pix", "hold_expira_em": {"$lt": now}},
        {"$set": {"hold_status": "expirado", "status_agendamento": "cancelado", "status_confirmacao": "sem_resposta"}},
    )
    return result.modified_count


async def _expirar_janela() -> int:
    """Lógica de negócio isolada da rota HTTP para que o scheduler em processo
    possa chamá-la diretamente, sem dar uma volta desnecessária por HTTP (e
    sem precisar conhecer o token de serviço internamente)."""
    now = _now()
    cursor = db.agendamentos.find({
        "status_confirmacao": "pendente",
        "hold_status": "autorizado",
        "janela_confirmacao_expira_em": {"$lt": now},
    }, {"_id": 0})
    n = 0
    async for ag in cursor:
        # Guarda atômica: mesma técnica usada em /confirmar e /cancelar. Se o
        # profissional confirmar (ou o cliente cancelar) bem na hora em que
        # o job dispara, essa transição autorizado -> processando garante
        # que só um dos caminhos capture/expire/cancele o payment_intent.
        claimed = await db.agendamentos.find_one_and_update(
            {"agendamento_id": ag["agendamento_id"], "status_confirmacao": "pendente", "hold_status": "autorizado"},
            {"$set": {"status_confirmacao": "processando"}},
        )
        if claimed is None:
            continue
        try:
            await gateway.expire(ag["payment_intent_id"], idempotency_key=f"expire_{ag['agendamento_id']}")
        except PaymentError:
            logging.exception("expire falhou p/ %s", ag["payment_intent_id"])
        await db.agendamentos.update_one(
            {"agendamento_id": ag["agendamento_id"]},
            {"$set": {"status_confirmacao": "sem_resposta", "hold_status": "expirado"}},
        )
        n += 1
    return n


@api_router.post("/internal/jobs/expirar-janela", dependencies=[Depends(require_service_token)])
async def job_expirar_janela():
    """Protegido por X-Internal-Token (ver security.py). O scheduler em
    processo chama `_expirar_janela()` diretamente (sem HTTP); esta rota
    existe como gatilho manual para operação/depuração — nunca deve ser
    alcançável sem o token de serviço."""
    n = await _expirar_janela()
    return {"expirados": n}


# Limiar de urgência: quando falta menos que isso para o hold expirar, o
# profissional recebe um segundo push de aviso ("última chance"), decidido
# na conversa de produto para reduzir "sem_resposta" sem cobrar errado.
_URGENCIA_ANTES_DE_EXPIRAR = timedelta(hours=2)


async def _push_para_usuario(user_id: str, title: str, body: str, data: dict) -> None:
    token_doc = await db.device_tokens.find_one({"user_id": user_id}, {"_id": 0})
    if not token_doc:
        return  # profissional não tem device registrado — nada a fazer
    try:
        ticket = await send_push(token_doc["expo_push_token"], title, body, data)
    except Exception:
        logging.exception("Falha de rede ao enviar push p/ %s", user_id)
        return
    if is_device_not_registered(ticket):
        # Token morto (app desinstalado, permissão revogada) — limpa para não
        # continuar gastando chamadas à Expo com ele.
        await db.device_tokens.delete_one({"user_id": user_id})


async def _enviar_pushes_confirmacao() -> dict:
    """Duas notificações distintas, cada uma disparada uma única vez por
    agendamento (controlado pelos campos push_*_enviada_em):

    1. Assim que o horário termina e ainda está pendente: pergunta direta
       "fulano compareceu?".
    2. Perto do hold expirar sem resposta: aviso de urgência, para reduzir
       quantos agendamentos terminam em "sem_resposta" por esquecimento.
    """
    now = _now()
    enviados_pergunta = 0
    enviados_urgencia = 0

    cursor_pergunta = db.agendamentos.find({
        "status_confirmacao": "pendente",
        "hold_status": "autorizado",
        "horario_fim": {"$lte": now},
        "push_pergunta_enviada_em": None,
    }, {"_id": 0})
    async for ag in cursor_pergunta:
        claimed = await db.agendamentos.find_one_and_update(
            {"agendamento_id": ag["agendamento_id"], "push_pergunta_enviada_em": None},
            {"$set": {"push_pergunta_enviada_em": now}},
        )
        if claimed is None:
            continue  # outro tick do job já pegou este (não deveria acontecer com max_instances=1, mas é barato garantir)
        await _push_para_usuario(
            ag["profissional_id"],
            title="Confirme o atendimento",
            body=f"{ag['cliente_nome']} tinha horário de {ag['servico_nome']}. Compareceu?",
            data={"type": "confirmacao_pendente", "agendamento_id": ag["agendamento_id"]},
        )
        enviados_pergunta += 1

    limite_urgencia = now + _URGENCIA_ANTES_DE_EXPIRAR
    cursor_urgencia = db.agendamentos.find({
        "status_confirmacao": "pendente",
        "hold_status": "autorizado",
        "janela_confirmacao_expira_em": {"$lte": limite_urgencia, "$gt": now},
        "push_urgencia_enviada_em": None,
    }, {"_id": 0})
    async for ag in cursor_urgencia:
        claimed = await db.agendamentos.find_one_and_update(
            {"agendamento_id": ag["agendamento_id"], "push_urgencia_enviada_em": None},
            {"$set": {"push_urgencia_enviada_em": now}},
        )
        if claimed is None:
            continue
        await _push_para_usuario(
            ag["profissional_id"],
            title="Última chance para confirmar",
            body=f"O horário de {ag['cliente_nome']} vai liberar sem cobrança em breve. Confirme agora.",
            data={"type": "confirmacao_urgente", "agendamento_id": ag["agendamento_id"]},
        )
        enviados_urgencia += 1

    return {"pergunta": enviados_pergunta, "urgencia": enviados_urgencia}


@api_router.post("/internal/jobs/enviar-pushes", dependencies=[Depends(require_service_token)])
async def job_enviar_pushes():
    """Mesmo padrão de proteção/uso do job de expiração — ver comentário lá."""
    return await _enviar_pushes_confirmacao()


logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

# CORS: allow_credentials=True nunca pode conviver com allow_origins=["*"] —
# além de ser rejeitado pelo próprio navegador nesse combo, é uma prática
# insegura por si só. A allowlist vem de env var (uma origem por linha,
# separada por vírgula) para que staging/produção configurem sem tocar código.
_ALLOWED_ORIGINS = [o.strip() for o in os.environ.get("ALLOWED_ORIGINS", "").split(",") if o.strip()]

_scheduler = AsyncIOScheduler(timezone="UTC")


@asynccontextmanager
async def lifespan(_: FastAPI):
    await db.users.create_index("email", unique=True)
    # esparso: só usuários criados via link público (WhatsApp) têm telefone;
    # evita duplicar o mesmo cliente se ele volta a agendar pelo mesmo número.
    await db.users.create_index("telefone", unique=True, sparse=True)
    await db.users.create_index("user_id", unique=True)
    await db.user_sessions.create_index("session_token", unique=True)
    await db.user_sessions.create_index("expires_at", expireAfterSeconds=0)
    await db.servicos.create_index([("profissional_id", 1), ("ativo", 1)])
    await db.servicos.create_index("servico_id", unique=True)
    await db.agendamentos.create_index("agendamento_id", unique=True)
    await db.agendamentos.create_index([("profissional_id", 1), ("horario_inicio", 1)])
    # Defesa em profundidade contra double-booking: além da checagem de
    # sobreposição em criar_agendamento (que cobre serviços de duração
    # diferente), este índice único parcial garante — a nível de banco — que
    # duas requisições simultâneas para o EXATO mesmo horário de início nunca
    # resultam em dois agendamentos ativos. "Ativo" = hold ainda não
    # cancelado/expirado, por isso o partialFilterExpression: um horário
    # pode ser reocupado depois que o agendamento anterior nele é cancelado.
    await db.agendamentos.create_index(
        [("profissional_id", 1), ("horario_inicio", 1)],
        unique=True,
        partialFilterExpression={"hold_status": {"$in": ["autorizado", "cancelando", "capturado_total", "capturado_taxa"]}},
        name="uniq_slot_ativo",
    )
    await db.agendamentos.create_index([("cliente_id", 1), ("horario_inicio", 1)])
    await db.customer_cards.create_index("user_id", unique=True)
    await db.disponibilidade.create_index([("profissional_id", 1), ("weekday", 1)])
    await db.webhook_events.create_index("event_id", unique=True)
    await db.device_tokens.create_index("user_id", unique=True)
    logger.info("Startup complete (gateway=%s)", GATEWAY_KIND)

    # Job crítico do produto: sem isso, holds nunca expiram sozinhos e o
    # cliente fica com o limite do cartão travado indefinidamente até o
    # próprio emissor do cartão liberar. Roda a cada 5 min — barato o
    # suficiente para não gerar carga, frequente o bastante para a UX de
    # "liberado automaticamente" fazer sentido.
    _scheduler.add_job(_expirar_janela, "interval", minutes=5, id="expirar_janela", max_instances=1)
    # Reservas via Pix do link público expiram bem mais rápido (minutos, não
    # horas) — o cliente decide na hora se paga ou não, não faz sentido
    # segurar o horário por muito tempo esperando. Roda a cada 2 min.
    _scheduler.add_job(_expirar_pix_pendentes, "interval", minutes=2, id="expirar_pix_pendentes", max_instances=1)
    # Mesma cadência para as notificações de confirmação — pergunta assim
    # que o horário termina, e aviso de urgência perto do hold expirar.
    _scheduler.add_job(_enviar_pushes_confirmacao, "interval", minutes=5, id="enviar_pushes", max_instances=1)
    _scheduler.start()
    logger.info("Scheduler iniciado: expirar-janela e enviar-pushes a cada 5min")

    yield

    _scheduler.shutdown(wait=False)
    client.close()


app.router.lifespan_context = lifespan
app.include_router(api_router)
app.include_router(webhooks_router)
app.add_middleware(
    CORSMiddleware, allow_credentials=True, allow_origins=_ALLOWED_ORIGINS,
    allow_methods=["*"], allow_headers=["*"],
)
