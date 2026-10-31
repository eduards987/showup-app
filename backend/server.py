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

import asyncio
import base64
import hashlib
import hmac
import json
import logging
import os
import re
import secrets
import unicodedata
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, time, timedelta, timezone
from pathlib import Path
from typing import Literal, Optional
from urllib.parse import urlencode
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from dotenv import load_dotenv
from fastapi import APIRouter, BackgroundTasks, Depends, FastAPI, Header, HTTPException, Query, Request
from fastapi.responses import JSONResponse, RedirectResponse
from starlette.exceptions import HTTPException as StarletteHTTPException
from google.auth.exceptions import GoogleAuthError
from google.auth.transport import requests as google_requests
from google.oauth2 import id_token as google_id_token
import httpx
from motor.motor_asyncio import AsyncIOMotorClient
from pydantic import BaseModel, EmailStr, Field, field_validator
from pymongo.errors import DuplicateKeyError, OperationFailure
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware
from starlette.middleware.cors import CORSMiddleware

ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / ".env")

# Importados só depois do load_dotenv(): ambos leem variáveis de ambiente no
# momento do import (security.py falha o boot de propósito se o token não
# estiver setado), então precisam vir depois que o .env já foi carregado.
from security import require_service_token
from payment_errors import CardDeclinedError, GatewayUnavailableError, InvalidPaymentRequestError, PaymentError
from webhooks import router as webhooks_router
from expo_push import buscar_recibo, is_device_not_registered, push_para_usuario, send_push
from i18n_servidor import idioma_da_requisicao, traduzir
from agenda import HOLD_DIAS_MERCADOPAGO, HOLD_MAX_DIAS, MENSAGENS as MENSAGENS_AGENDA, inicios_possiveis, janela_de_confirmacao, montar_janela
from notificacoes import avisar_novo_agendamento, avisar_proximo_atendimento, dados_do_agendamento, explicar_erro_push
from avisos_cliente import avisar_cliente_confirmado, enviar_lembretes as enviar_lembretes_cliente
from emailer import email_configurado, enviar_email
from senhas import hash_falso, hash_senha, validar_senha, verificar_senha
import cofre
from mercadopago_gateway import MARCAS_CAPTURA_PARCIAL, PIX_MINUTOS as PIX_MINUTOS_MERCADOPAGO, MercadoPagoGateway, assinatura_valida, taxa_centavos

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
# IP de quem fez o pedido. No Render o servidor fica atrás de um proxy: sem isto, request.client é o IP do PROXY e o
# limite ("5 por minuto") vale para TODOS os usuários juntos. O X-Forwarded-For é lido DA DIREITA: os itens da
# esquerda podem ter sido escritos pelo próprio usuário (falsos); o último é o que o proxy de confiança anotou.
# PROXIES_NA_FRENTE = quantos proxies de confiança há na frente (1 no Render; 0 = sem proxy, usa o IP da conexão).
PROXIES_NA_FRENTE = max(0, int(os.environ.get("PROXIES_NA_FRENTE", "1") or 0))
_ip_registrado = False


def ip_do_cliente(request: Request) -> str:
    global _ip_registrado
    cadeia = [p.strip() for p in (request.headers.get("x-forwarded-for") or "").split(",") if p.strip()]
    direto = request.client.host if request.client else "desconhecido"
    if not _ip_registrado and cadeia:
        _ip_registrado = True       # uma vez por processo: para conferir PROXIES_NA_FRENTE no log do Render
        logging.info("limite por IP: conexão de %s, X-Forwarded-For com %d IP(s); PROXIES_NA_FRENTE=%d",
                     direto, len(cadeia), PROXIES_NA_FRENTE)
    if PROXIES_NA_FRENTE and len(cadeia) >= PROXIES_NA_FRENTE:
        return cadeia[-PROXIES_NA_FRENTE]
    return direto


limiter = Limiter(key_func=ip_do_cliente, default_limits=["200/minute"], enabled=not _TESTING)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)


@app.exception_handler(StarletteHTTPException)
async def _http_exception_traduzida(request: Request, exc: StarletteHTTPException):
    """Mesmo formato de sempre ({"detail": ...}), mas a mensagem sai no idioma do cabeçalho Accept-Language (en/es) quando há tradução."""
    detalhe = traduzir(exc.detail, idioma_da_requisicao(request.headers.get("accept-language")))
    return JSONResponse({"detail": detalhe}, status_code=exc.status_code, headers=getattr(exc, "headers", None))
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

# --- Login com Microsoft (contas PESSOAIS: Outlook, Hotmail, Live) ---------
# Opcional: sem as três variáveis o botão some do app (ver GET /auth/metodos).
# Só aceitamos o locatário de contas pessoais: nele o e-mail é verificado pela
# Microsoft. Em contas corporativas o claim `email` pode ser definido por quem
# administra o diretório (falha "nOAuth"), então vincular conta por e-mail ali
# permitiria tomar a conta de outra pessoa.
MICROSOFT_CLIENT_ID = os.environ.get("MICROSOFT_CLIENT_ID", "")
MICROSOFT_CLIENT_SECRET = os.environ.get("MICROSOFT_CLIENT_SECRET", "")
# URL completa deste backend + /api/auth/microsoft/callback (idêntica à cadastrada no Azure).
MICROSOFT_OAUTH_REDIRECT_URI = os.environ.get("MICROSOFT_OAUTH_REDIRECT_URI", "")
MS_TENANT_PESSOAL = "9188040d-6c67-4c5b-b112-36a304b66dad"
MS_AUTORIZAR_URL = "https://login.microsoftonline.com/consumers/oauth2/v2.0/authorize"
MS_TOKEN_URL = "https://login.microsoftonline.com/consumers/oauth2/v2.0/token"

# --- Cadastro e login por e-mail + senha ------------------------------------
# "1" imprime os códigos de verificação no LOG em vez de enviá-los: só para
# desenvolvimento sem SMTP. NUNCA em produção (quem lê o log toma contas).
EMAIL_CODIGOS_NO_LOG = os.environ.get("EMAIL_CODIGOS_NO_LOG", "0") == "1"
CODIGO_EMAIL_VALIDADE_MIN = 10
CODIGO_EMAIL_MAX_TENTATIVAS = 5
CODIGO_EMAIL_REENVIO_SEG = 60
LOGIN_MAX_FALHAS = 5
LOGIN_BLOQUEIO_MIN = 15
_EMAIL_RE = re.compile(r"^[^@\s]{1,64}@[^@\s]+\.[^@\s]{2,}$")
# "pimenta" do HMAC dos códigos: sem ela, quem vazasse o banco poderia testar os 10^6
# códigos possíveis offline. Reaproveita o token interno se não houver uma própria.
_AUTH_PEPPER = (os.environ.get("AUTH_CODE_PEPPER") or os.environ.get("INTERNAL_SERVICE_TOKEN") or "").encode()

Role = Literal["cliente", "profissional"]

# Quem usa o ShowUp: qualquer profissional que atenda com hora marcada e sofra com falta de cliente. A ordem é a da tela. O CÓDIGO é o que fica gravado no
# perfil (por isso os 6 originais — fitness, terapia, consultoria, estetica, coaching, nutricao — NUNCA mudam de código); o nome aparece traduzido no app
# (frontend/src/lib/categorias.ts). Para acrescentar uma categoria: código aqui + nome em categorias.ts + tradução em en.ts/es.ts (test_categorias.py confere).
CATEGORIAS_POR_GRUPO: dict[str, list[str]] = {
    "saude": ["medicina", "odontologia", "psicologia", "terapia", "fisioterapia", "fonoaudiologia", "nutricao", "acupuntura"],
    "beleza": ["estetica", "cabeleireiro", "barbearia", "unhas", "maquiagem", "depilacao", "tatuagem"],
    "bem_estar": ["fitness", "yoga_pilates", "massagem", "danca", "artes_marciais", "esportes"],
    "educacao": ["aulas_particulares", "idiomas", "musica"],
    "profissionais": ["consultoria", "coaching", "advocacia", "contabilidade", "fotografia", "imobiliario"],
    "pets": ["veterinaria", "banho_tosa", "adestramento"],
    "casa_auto": ["automotivo", "reparos"],
    "outros": ["outros"],
}
CATEGORIAS = [c for grupo in CATEGORIAS_POR_GRUPO.values() for c in grupo]
MAX_CATEGORIAS_POR_PROFISSIONAL = 3

# Fusos horários que o profissional pode escolher (a mesma tabela do app: frontend/src/lib/fusos.ts, com as regras de horário de verão). O servidor aceita qualquer
# fuso da base oficial (ZoneInfo), mas só estes aparecem na lista, para ninguém digitar algo exótico por engano. Para acrescentar um: aqui + fusos.ts + nome nas
# traduções; test_fusos.py confere o horário de verão contra a base oficial e que o app conhece todos.
TIMEZONES_POR_GRUPO: dict[str, list[str]] = {
    "brasil": [
        "America/Sao_Paulo",
        "America/Manaus",
        "America/Rio_Branco",
        "America/Noronha",
    ],
    "america_sul": [
        "America/Argentina/Buenos_Aires",
        "America/Santiago",
        "America/Montevideo",
        "America/Asuncion",
        "America/La_Paz",
        "America/Bogota",
        "America/Lima",
        "America/Guayaquil",
        "America/Caracas",
    ],
    "america_norte": [
        "America/Mexico_City",
        "America/Cancun",
        "America/Tijuana",
        "America/Guatemala",
        "America/El_Salvador",
        "America/Tegucigalpa",
        "America/Managua",
        "America/Costa_Rica",
        "America/Panama",
        "America/Jamaica",
        "America/Santo_Domingo",
        "America/Puerto_Rico",
        "America/New_York",
        "America/Chicago",
        "America/Denver",
        "America/Phoenix",
        "America/Los_Angeles",
        "America/Anchorage",
        "Pacific/Honolulu",
        "America/Toronto",
        "America/Vancouver",
        "America/Edmonton",
        "America/Winnipeg",
        "America/Regina",
        "America/Halifax",
        "America/St_Johns",
    ],
    "europa": [
        "Europe/London",
        "Europe/Dublin",
        "Europe/Lisbon",
        "Atlantic/Azores",
        "Europe/Madrid",
        "Europe/Paris",
        "Europe/Berlin",
        "Europe/Rome",
        "Europe/Amsterdam",
        "Europe/Brussels",
        "Europe/Vienna",
        "Europe/Zurich",
        "Europe/Stockholm",
        "Europe/Oslo",
        "Europe/Copenhagen",
        "Europe/Warsaw",
        "Europe/Prague",
        "Europe/Budapest",
        "Europe/Athens",
        "Europe/Helsinki",
        "Europe/Bucharest",
        "Europe/Kyiv",
        "Europe/Istanbul",
        "Europe/Moscow",
    ],
    "africa": [
        "Africa/Johannesburg",
        "Africa/Lagos",
        "Africa/Nairobi",
        "Africa/Accra",
        "Africa/Luanda",
        "Africa/Maputo",
        "Africa/Algiers",
        "Africa/Addis_Ababa",
    ],
    "asia": [
        "Asia/Dubai",
        "Asia/Riyadh",
        "Asia/Tehran",
        "Asia/Karachi",
        "Asia/Kolkata",
        "Asia/Colombo",
        "Asia/Kathmandu",
        "Asia/Dhaka",
        "Asia/Bangkok",
        "Asia/Jakarta",
        "Asia/Ho_Chi_Minh",
        "Asia/Shanghai",
        "Asia/Hong_Kong",
        "Asia/Singapore",
        "Asia/Kuala_Lumpur",
        "Asia/Manila",
        "Asia/Taipei",
        "Asia/Seoul",
        "Asia/Tokyo",
    ],
    "oceania": [
        "Australia/Perth",
        "Australia/Darwin",
        "Australia/Brisbane",
        "Australia/Adelaide",
        "Australia/Sydney",
        "Australia/Melbourne",
        "Australia/Hobart",
        "Pacific/Auckland",
        "Pacific/Guam",
    ],
}
TIMEZONES = [z for zs in TIMEZONES_POR_GRUPO.values() for z in zs]
DEFAULT_TIMEZONE = "America/Sao_Paulo"

# Moedas suportadas — lista fechada (não qualquer código ISO 4217) pelo mesmo
# motivo dos fusos: evita erro de digitação e mantém a validação simples.
# O Stripe em si suporta 135+ moedas; esta lista cobre os mercados mais
# prováveis pra expansão e pode crescer sem tocar em nenhuma outra parte do
# código — tudo abaixo lê `moeda` do profissional/serviço, nunca assume BRL.
# SEM moedas "sem centavos" do Stripe (CLP, JPY, KRW, VND, PYG...): o app guarda todo valor em centavos (x100) e o Stripe espera o
# valor inteiro nessas moedas, então cobraria 100 vezes o valor digitado. O teste test_moedas.py impede que alguma volte à lista.
MOEDAS_SUPORTADAS = [
    "BRL", "USD", "EUR", "GBP", "MXN", "ARS", "COP", "CAD", "AUD",
]
DEFAULT_MOEDA = "BRL"
# Moedas em que o Stripe DEPOSITA na conta do profissional, sem converter. Conta brasileira: só BRL (o repasse exige conta bancária em reais).
# Cobrar em qualquer outra moeda funciona, mas o Stripe converte para reais e cobra taxa de conversão: o app AVISA o profissional.
# Só acrescente outra moeda aqui depois que o Stripe liberar "liquidação em várias moedas" para a sua conta (veja lancamento/TAXAS-E-MOEDAS.md).
MOEDAS_RECEBIMENTO = [m.strip().upper() for m in os.environ.get("MOEDAS_RECEBIMENTO", "BRL").split(",") if m.strip()]

# País da conta Stripe (Connect) do profissional. É SEMPRE o país da PLATAFORMA (Brasil): o Stripe só permite transferir entre contas
# na mesma região (as exceções são entre EUA, Canadá, Reino Unido, Europa e Suíça), então uma plataforma brasileira não consegue
# pagar uma conta conectada nos EUA ou na Alemanha. A MOEDA do preço é outra coisa (o cliente pode pagar em dólar, por exemplo; o
# Stripe converte para real). Antes o país era inferido da moeda (USD -> EUA), o que quebraria o cadastro de quem escolhesse outra moeda.
CONNECT_PAIS = os.environ.get("CONNECT_PAIS", "BR").upper()

# Planos de assinatura do PROFISSIONAL — decrescem a taxa por agendamento
# conforme a mensalidade sobe. fee_bps em pontos-base (1000 = 10%).
# Valores de 29/10/2026: nenhum plano pode ficar abaixo do custo do Stripe (3,99% + R$ 0,39 por cobrança, mais o Connect).
# Conta e motivo em lancamento/PRECOS-DOS-PLANOS.md e lancamento/calcular-precos.py. Mudou aqui? Crie o Price novo no Stripe
# e troque o STRIPE_PRICE_ID_* no Render: o servidor RECUSA assinar se o Price não tiver este valor (_price_confere).
# price_env: nome da env var com o Price ID do Stripe pra esse plano (None
# pro Free, que não tem cobrança). Ver STRIPE_PRICE_ID_* no .env.
PLANOS = {
    "free":         {"nome": "Free",         "fee_bps": 1000, "preco_centavos": 0,    "price_env": None},
    "profissional": {"nome": "Profissional", "fee_bps": 700,  "preco_centavos": 2990, "price_env": "STRIPE_PRICE_ID_PROFISSIONAL"},
    "ultra":        {"nome": "Ultra",        "fee_bps": 550,  "preco_centavos": 6990, "price_env": "STRIPE_PRICE_ID_ULTRA"},
}
PLANOS_MOEDA = "brl"  # os Prices dos planos no Stripe são em reais
# Adicional na taxa do ShowUp quando o serviço é cobrado numa moeda que o Stripe converte para real (fora de MOEDAS_RECEBIMENTO):
# cobre a conversão (a partir de 2%) e o cartão internacional (+2%). O app mostra o valor ao profissional (GET /api/moedas).
ADICIONAL_CONVERSAO_BPS = 400
DEFAULT_PLANO = "free"
TRIAL_DIAS = 14  # teste grátis do plano pago — uma vez por profissional
RESUMO_JANELA_DIAS = 30  # janela da conta "quanto você pagaria em cada plano"
# Trava de segurança do dinheiro: com "1", só dá pra agendar com profissional que
# já tem a conta conectada do Stripe LIBERADA (repasse automático). Sem ela, o
# valor cobrado fica na conta da plataforma e o repasse vira acerto manual
# ("ledger interno"). Ligar em PRODUÇÃO; em teste pode ficar desligado.
EXIGIR_RECEBIMENTO_ATIVO = os.environ.get("EXIGIR_RECEBIMENTO_ATIVO", "0") == "1"
# Interruptor da COMPRA de planos pagos (e do teste grátis) dentro do app. O Google
# Play costuma exigir o sistema de cobrança dele pra vender acesso a funções do
# app, e aqui a assinatura é paga pelo Stripe. Com "0": os planos pagos aparecem
# como "em breve", a assinatura é recusada e quem já assina continua assinando
# (e pode cancelar). Tudo continua no código — é só religar com "1". Ver
# lancamento/LANCAMENTO.md antes de decidir.
PLANOS_COMPRA_HABILITADA = os.environ.get("PLANOS_COMPRA_HABILITADA", "1") == "1"
# Quantos minutos ANTES do atendimento o profissional recebe o aviso "próximo atendimento". 0 desliga.
try:
    LEMBRETE_PROFISSIONAL_MIN = int(os.environ.get("LEMBRETE_PROFISSIONAL_MIN", "60"))
except ValueError:
    LEMBRETE_PROFISSIONAL_MIN = 60
# Segundos que o teste de notificação espera pelo recibo da Expo (é ele que revela erro de credencial do Firebase).
RECIBO_ESPERA_SEG = 4
PIX_RESERVA_MINUTOS = 20  # tempo que um agendamento via Pix fica reservado esperando pagamento antes de liberar o horário sozinho
# Pix pelo Stripe: só por convite no Brasil (hoje a conta não tem). Com "1" a página de agendamento oferece Pix para quem recebe
# pelo Stripe. Quem recebe pelo Mercado Pago tem Pix sempre (o Mercado Pago não exige convite).
PIX_STRIPE_HABILITADO = os.environ.get("PIX_STRIPE_HABILITADO", "0") == "1"

# ---- Mercado Pago: segunda forma de o profissional receber (só Brasil, só reais). Guia: lancamento/MERCADO-PAGO.md
# Sem as 4 variáveis (e a MERCADOPAGO_TOKEN_KEY do cofre.py) a opção nem aparece no app: tudo continua só com o Stripe.
MERCADOPAGO_CLIENT_ID = os.environ.get("MERCADOPAGO_CLIENT_ID", "").strip()
MERCADOPAGO_CLIENT_SECRET = os.environ.get("MERCADOPAGO_CLIENT_SECRET", "").strip()
# Endereço deste servidor + /api/mercadopago/callback, IDÊNTICO ao cadastrado na aplicação do Mercado Pago.
MERCADOPAGO_REDIRECT_URI = os.environ.get("MERCADOPAGO_REDIRECT_URI", "").strip()
# Chave secreta dos webhooks (Suas integrações > Webhooks). Sem ela, avisos do Mercado Pago são recusados.
MERCADOPAGO_WEBHOOK_SECRET = os.environ.get("MERCADOPAGO_WEBHOOK_SECRET", "").strip()
MERCADOPAGO_SANDBOX = os.environ.get("MERCADOPAGO_SANDBOX", "0") == "1"
# No Mercado Pago a tarifa do cartão/Pix sai do valor do PROFISSIONAL (no Stripe sai do ShowUp). Para ele não pagar duas vezes,
# a taxa do ShowUp é 3 pontos menor: Free 7%, Profissional 4%, Ultra 2,5%. Decidido em 30/10/2026.
DESCONTO_MERCADOPAGO_BPS = 300


def _notificacao_mercadopago(redirect_uri: str) -> Optional[str]:
    """O aviso de pagamento vai para /api/webhooks/mercadopago no mesmo servidor do callback do OAuth."""
    if "/api/" not in redirect_uri:
        return None
    return redirect_uri.split("/api/", 1)[0] + "/api/webhooks/mercadopago"


MERCADOPAGO_ATIVO = bool(MERCADOPAGO_CLIENT_ID and MERCADOPAGO_CLIENT_SECRET and MERCADOPAGO_REDIRECT_URI) and cofre.cofre_configurado()
mp_gateway: Optional[MercadoPagoGateway] = (
    MercadoPagoGateway(MERCADOPAGO_CLIENT_ID, MERCADOPAGO_CLIENT_SECRET, MERCADOPAGO_REDIRECT_URI,
                       _notificacao_mercadopago(MERCADOPAGO_REDIRECT_URI), sandbox=MERCADOPAGO_SANDBOX)
    if MERCADOPAGO_ATIVO else None
)


def _recebe_pelo_mp(prof: Optional[dict]) -> bool:
    """O profissional escolheu receber pelo Mercado Pago e a conta dele está conectada."""
    return bool(prof and prof.get("recebimento") == "mercadopago" and prof.get("mp_user_id"))


def _hold_dias(prof: Optional[dict]) -> int:
    """Validade da reserva no cartão de quem recebe: Mercado Pago 5 dias, Stripe 7 (decide até onde a agenda abre)."""
    return HOLD_DIAS_MERCADOPAGO if _recebe_pelo_mp(prof) else HOLD_MAX_DIAS


def _fee_bps_for(profissional_doc: Optional[dict], moeda: Optional[str] = None) -> int:
    """Mesma filosofia de _tz_for/_moeda: nunca deixa um plano desconhecido
    ou ausente quebrar o cálculo — cai pro Free (a taxa mais alta, o que é
    o comportamento seguro do ponto de vista da plataforma).
    `moeda` = moeda da cobrança: se o Stripe precisa converter para real, soma ADICIONAL_CONVERSAO_BPS.
    Quem recebe pelo Mercado Pago paga a tarifa do cartão do próprio bolso: tira DESCONTO_MERCADOPAGO_BPS (só reais, sem adicional)."""
    plano = (profissional_doc or {}).get("plano") or DEFAULT_PLANO
    bps = PLANOS.get(plano, PLANOS[DEFAULT_PLANO])["fee_bps"]
    if _recebe_pelo_mp(profissional_doc):
        return max(bps - DESCONTO_MERCADOPAGO_BPS, 0)
    if moeda and moeda.upper() not in MOEDAS_RECEBIMENTO:
        bps += ADICIONAL_CONVERSAO_BPS
    return bps


def _price_confere(plano_cfg: dict, price: dict) -> bool:
    """O Price do Stripe cobra exatamente o que o app mostra? (valor, moeda, mensal e ativo).
    Protege contra trocar o valor em PLANOS e esquecer o STRIPE_PRICE_ID_* no Render (ou o contrário)."""
    return (
        price.get("unit_amount") == plano_cfg["preco_centavos"]
        and (price.get("currency") or "").lower() == PLANOS_MOEDA
        and price.get("interval") == "month"
        and bool(price.get("active"))
    )


def _plano_disponivel(p: dict) -> bool:
    """Só é "comprável" de verdade se o Price ID real já foi configurado no
    .env — evita o app oferecer um plano que quebraria no clique."""
    if p["price_env"] is None:
        return True   # o Free sempre existe
    return PLANOS_COMPRA_HABILITADA and bool(os.environ.get(p["price_env"]))


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


def calcular_comparacao_planos(valores_centavos: list[int], plano_atual: str, desconto_bps: int = 0) -> list[dict]:
    """Quanto o profissional pagaria em cada plano com o MESMO movimento.
    `valores_centavos` = valor do serviço de cada agendamento cobrado — a taxa
    é calculada por agendamento, com a mesma conta da cobrança real
    (valor * bps // 10_000, arredondando pra baixo cada um).
    `desconto_bps`: quem recebe pelo Mercado Pago tem a taxa menor em todos os planos (os equilíbrios não mudam)."""
    atual_id = plano_atual if plano_atual in PLANOS else DEFAULT_PLANO
    linhas = []
    for pid, p in PLANOS.items():
        bps = max(p["fee_bps"] - desconto_bps, 0)
        taxa = sum((v * bps) // 10_000 for v in valores_centavos)
        linhas.append({
            "id": pid, "nome": p["nome"], "fee_percent": bps / 100,
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

def _gateway_para_chave(chave: str) -> str:
    """Qual gateway usar, a partir da STRIPE_API_KEY.

    - vazia → "mock" (desenvolvimento/testes: pagamentos SIMULADOS);
    - chave secreta ou restrita do Stripe, de TESTE ou de PRODUÇÃO → "stripe";
    - qualquer outra coisa → erro e o servidor NÃO sobe.

    Antes só `sk_test_` era reconhecida: ao trocar pela chave de produção (`sk_live_`)
    o backend caía em silêncio no modo simulado, que "aprova" reservas sem cobrar nada.
    Chave preenchida porém irreconhecível é erro de configuração, não motivo para simular.
    """
    chave = (chave or "").strip()
    if not chave:
        return "mock"
    if chave.startswith(("sk_test_", "sk_live_", "rk_test_", "rk_live_")) and len(chave) > 20:
        return "stripe"
    raise RuntimeError(
        "STRIPE_API_KEY está preenchida, mas não parece uma chave secreta do Stripe "
        "(esperado sk_test_..., sk_live_... ou rk_..., completa). Corrija a variável — ou deixe-a "
        "vazia para usar o modo simulado (só em desenvolvimento)."
    )


# Gateway selection: real Stripe if the key is valid (test OR live); mock only if no key at all.
GATEWAY_KIND = _gateway_para_chave(os.environ.get("STRIPE_API_KEY", ""))
if GATEWAY_KIND == "stripe":
    from stripe_gateway import StripeGateway
    gateway = StripeGateway(db)
else:
    from gateway import MockGateway
    gateway = MockGateway(db)


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
    recebimento: Literal["stripe", "mercadopago"] = "stripe"
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
    categorias: list[str] = Field(min_length=1, max_length=MAX_CATEGORIAS_POR_PROFISSIONAL)

    @field_validator("categorias")
    @classmethod
    def _so_categorias_conhecidas_e_sem_repeticao(cls, valores: list[str]) -> list[str]:
        desconhecidas = [c for c in valores if c not in CATEGORIAS]
        if desconhecidas:
            raise ValueError(f"Categoria inválida: {', '.join(desconhecidas)}")
        if len(set(valores)) != len(valores):
            raise ValueError("Categorias repetidas")
        return valores


class TimezoneRequest(BaseModel):
    timezone: str

    @field_validator("timezone")
    @classmethod
    def _valida_timezone_suportada(cls, v: str) -> str:
        if v not in TIMEZONES:
            raise ValueError("timezone não suportada — escolha uma da lista (GET /api/timezones)")
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
    # False quando EXIGIR_RECEBIMENTO_ATIVO está ligado e o profissional ainda
    # não habilitou o recebimento — a página pública avisa em vez de deixar o
    # cliente ir até o pagamento pra só então recusar.
    aceita_agendamentos: bool = True
    # Por onde o dinheiro do cliente passa. "mercadopago": a página usa o formulário do Mercado Pago (chave pública do
    # PROFISSIONAL, como manda o modelo marketplace), a reserva vale 5 dias e o app manda o cliente para o link.
    recebimento: Literal["stripe", "mercadopago"] = "stripe"
    mp_public_key: Optional[str] = None
    pix_disponivel: bool = False
    link_agendamento: Optional[str] = None


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
    # Só o Mercado Pago pede: o comprovante do Pix e do cartão vai para este e-mail (o Stripe não precisa).
    email: Optional[EmailStr] = None

    @field_validator("telefone")
    @classmethod
    def _valida_telefone(cls, v: str) -> str:
        digitos = "".join(c for c in v if c.isdigit())
        if len(digitos) not in (10, 11):  # DDD + número, com ou sem o 9
            raise ValueError("Telefone inválido — use DDD + número (ex: 11987654321)")
        return digitos


class AgendamentoPublicoCartaoRequest(AgendamentoPublicoCreate):
    payment_method_id: str  # já coletado/confirmado via Stripe.js Elements na página web


class AgendamentoPublicoMPCartaoRequest(AgendamentoPublicoCreate):
    """Cartão pelo Mercado Pago: o formulário do Mercado Pago (Card Payment Brick) tokeniza o cartão no navegador com a
    chave pública do profissional; o número nunca passa por aqui."""
    token: str = Field(min_length=8, max_length=200)
    payment_method_id: str = Field(min_length=2, max_length=40)       # bandeira: visa, master, amex, elo...
    issuer_id: Optional[str] = Field(default=None, max_length=40)
    email: EmailStr
    identificacao_tipo: Optional[str] = Field(default=None, max_length=10)
    identificacao_numero: Optional[str] = Field(default=None, max_length=20)


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
    payment_intent_client_secret: Optional[str] = None   # só no Stripe
    qr_code_data: Optional[str] = None
    qr_code_base64: Optional[str] = None                 # só no Mercado Pago (imagem pronta do QR)
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
    # nao_conectada | pendente_informacoes | em_analise | restrita | recusada | ativa
    # | indisponivel (tem conta, mas não deu pra consultar o Stripe agora)
    estado: str = "nao_conectada"
    pendencias: list[str] = []
    motivo_bloqueio: Optional[str] = None


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
    # True quando o Stripe não conseguiu cobrar a mensalidade (past_due).
    cobranca_pendente: bool = False
    # False quando a compra de planos pagos está desligada (PLANOS_COMPRA_HABILITADA):
    # o app esconde a comparação e o teste grátis e mostra só o que o app já recuperou.
    compra_habilitada: bool = True


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
        recebimento="mercadopago" if _recebe_pelo_mp(doc) else "stripe",
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


async def _avisar_reserva_confirmada(db_, agendamento_id: str) -> None:
    """Reserva valendo (cartão reservado ou Pix pago): avisa o profissional e o cliente. Cada um sai uma vez só e
    nenhum dos dois levanta exceção (aviso nunca derruba uma reserva paga)."""
    await avisar_novo_agendamento(db_, agendamento_id)
    await avisar_cliente_confirmado(db_, agendamento_id)


def _contato_do_aviso(request: Request, email: Optional[str] = None) -> dict:
    """O que a reserva guarda para avisar o cliente: o e-mail que ele informou (link) e o idioma da página/app."""
    return {"email_cliente": (str(email).strip().lower() if email else None),
            "idioma": idioma_da_requisicao(request.headers.get("accept-language"))}


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


async def _exigir_horario_na_agenda(prof_id: str, horario: datetime, horario_fim: datetime, reserva_no_cartao: bool = True) -> None:
    """Recusa (422) horário fora da janela da agenda: o cliente só agenda nos próximos N dias em que o profissional atende
    (N = dias da semana que ele cadastrou) e nunca num horário em que a reserva no cartão venceria antes da cobrança.
    A mesma regra filtra a lista de horários (/slots), mas é AQUI que vale: um pedido montado à mão não pode furá-la."""
    prof = await db.users.find_one({"user_id": prof_id}, {"_id": 0, "timezone": 1, "recebimento": 1, "mp_user_id": 1})
    weekly = await db.disponibilidade.find({"profissional_id": prof_id}, {"_id": 0}).to_list(200)
    tz, agora = _tz_for(prof), _now()
    motivo = montar_janela(weekly, agora, tz, _hold_dias(prof)).motivo_recusa(horario, horario_fim, reserva_no_cartao)
    if motivo:
        raise HTTPException(422, MENSAGENS_AGENDA[motivo])
    # Dentro da janela de dias, mas é um horário que o expediente realmente oferece? (um pedido montado à mão poderia
    # reservar às 03:00, num dia de folga ou fora da grade do serviço). Mesma função que gera a lista de horários.
    if horario not in set(inicios_possiveis(weekly, horario_fim - horario, agora, tz)):
        raise HTTPException(422, MENSAGENS_AGENDA["fora_do_expediente"])


async def _mp_access_token(prof: dict) -> str:
    """Token do Mercado Pago do profissional, decifrado. Renova sozinho quando faltam menos de 7 dias para vencer
    (vale 180 dias). Falha vira GatewayUnavailableError: quem chama já trata erro de pagamento sem travar o agendamento."""
    if not MERCADOPAGO_ATIVO or mp_gateway is None:
        raise GatewayUnavailableError("Mercado Pago não configurado neste servidor")
    try:
        token = cofre.decifrar(prof["mp_access_token_cifrado"])
        expira = prof.get("mp_token_expira_em")
        if expira and _aware(expira) - _now() < timedelta(days=7) and prof.get("mp_refresh_token_cifrado"):
            novo = await mp_gateway.renovar(cofre.decifrar(prof["mp_refresh_token_cifrado"]))
            await _gravar_tokens_mp(prof["user_id"], novo)
            token = novo["access_token"]
    except (KeyError, cofre.CofreIndisponivel) as e:
        raise GatewayUnavailableError(f"token do Mercado Pago indisponível: {e}") from e
    return token


async def _gravar_tokens_mp(user_id: str, tokens: dict) -> None:
    campos = {
        "mp_access_token_cifrado": cofre.cifrar(tokens["access_token"]),
        "mp_token_expira_em": tokens["expira_em"],
    }
    if tokens.get("refresh_token"):
        campos["mp_refresh_token_cifrado"] = cofre.cifrar(tokens["refresh_token"])
    if tokens.get("public_key"):
        campos["mp_public_key"] = tokens["public_key"]
    if tokens.get("user_id"):
        campos["mp_user_id"] = tokens["user_id"]
    await db.users.update_one({"user_id": user_id}, {"$set": campos})


async def _desfazer_reserva(gateway_nome: Optional[str], profissional_id: str, payment_id: str, idempotency_key: str) -> None:
    """Solta a reserva no cartão no gateway em que ela foi feita (cada agendamento grava o seu em `gateway`)."""
    if gateway_nome == "mercadopago":
        prof = await db.users.find_one({"user_id": profissional_id}, {"_id": 0})
        if not prof:
            raise GatewayUnavailableError("profissional não encontrado para desfazer a reserva")
        token = await _mp_access_token(prof)
        await mp_gateway.cancelar(token, payment_id, idempotency_key=idempotency_key)
        return
    await gateway.void(payment_id, idempotency_key=idempotency_key)


async def _janela_de_confirmacao_ou_desfazer(hold: dict, horario_fim: datetime, agendamento_id: str,
                                             gateway_nome: Optional[str] = None, profissional_id: str = "") -> datetime:
    """Prazo para o profissional confirmar o atendimento: normalmente fim + 24 h, mas nunca depois de o Stripe soltar a
    reserva (alguns cartões vencem antes de 7 dias). Se a reserva venceria antes de o atendimento acabar, desfaz a
    autorização (o cliente não fica com o limite preso) e recusa."""
    janela = janela_de_confirmacao(horario_fim, _aware(hold["hold_expira_em"]))
    if janela is not None:
        return janela
    try:
        await _desfazer_reserva(gateway_nome, profissional_id, hold["payment_intent_id"], f"void_curto_{agendamento_id}")
    except PaymentError:
        logging.exception("Falha ao desfazer hold de validade curta p/ %s", agendamento_id)
    raise HTTPException(422, "O seu cartão só permite reservar por poucos dias. Escolha um horário mais próximo.")


# Reserva nestes estados OCUPA o horário. A lista de horários livres, as duas checagens de conflito (app e link) e o
# índice único do banco usam esta MESMA lista: antes cada um tinha a sua, e o Pix ficava de fora de três delas.
STATUS_OCUPAM_HORARIO = ["autorizado", "cancelando", "capturado_total", "capturado_taxa", "pago_integral", "aguardando_pix"]


async def _valida_servico_e_conflito(servico_id: str, horario_inicio: datetime, reserva_no_cartao: bool = True) -> tuple[dict, dict, datetime]:
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
    await _exigir_horario_na_agenda(svc["profissional_id"], horario, horario_fim, reserva_no_cartao)
    conflito = await db.agendamentos.find_one({
        "profissional_id": svc["profissional_id"],
        "hold_status": {"$in": STATUS_OCUPAM_HORARIO},
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


async def _emitir_sessao(user_id: str) -> SessionResponse:
    """Cria a sessão NOSSA (7 dias) e devolve o usuário. Usado por todos os jeitos de entrar
    (Google, Microsoft, e-mail e senha): depois do login, ninguém depende de token de terceiros."""
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

    return await _emitir_sessao(user_id)


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


# ---------------------------------------------------------------------------
# Auth: métodos disponíveis, e-mail + senha e Microsoft
# ---------------------------------------------------------------------------
class MetodosLogin(BaseModel):
    google: bool = True
    microsoft: bool = False
    email: bool = False


class EmailCadastroRequest(BaseModel):
    name: str
    email: str
    password: str


class EmailVerificarRequest(BaseModel):
    email: str
    code: str


class EmailLoginRequest(BaseModel):
    email: str
    password: str


class EmailEsqueciRequest(BaseModel):
    email: str


class EmailRedefinirRequest(BaseModel):
    email: str
    code: str
    new_password: str


def _microsoft_ativo() -> bool:
    return bool(MICROSOFT_CLIENT_ID and MICROSOFT_CLIENT_SECRET and MICROSOFT_OAUTH_REDIRECT_URI)


def _email_ativo() -> bool:
    return email_configurado() or EMAIL_CODIGOS_NO_LOG


@api_router.get("/auth/metodos", response_model=MetodosLogin)
async def auth_metodos():
    """O app só mostra os botões que o servidor realmente consegue atender."""
    return MetodosLogin(google=True, microsoft=_microsoft_ativo(), email=_email_ativo())


def _norm_email(valor: str) -> str:
    email = (valor or "").strip().lower()
    if len(email) > 254 or not _EMAIL_RE.match(email):
        raise HTTPException(422, "Informe um e-mail válido.")
    return email


def _exigir_email_ativo() -> None:
    if not _email_ativo():
        raise HTTPException(503, "O cadastro por e-mail ainda não está disponível. Use o login com Google ou Microsoft.")


def _hash_codigo(email: str, finalidade: str, codigo: str) -> str:
    return hmac.new(_AUTH_PEPPER, f"{email}|{finalidade}|{codigo}".encode(), hashlib.sha256).hexdigest()


async def _entregar_codigo(email: str, finalidade: str, codigo: str) -> None:
    if finalidade == "verify":
        assunto = "Seu código de verificação do ShowUp"
        abertura = "Use este código para confirmar o seu e-mail e concluir o cadastro no ShowUp:"
    else:
        assunto = "Redefinir a sua senha do ShowUp"
        abertura = "Use este código para criar uma nova senha no ShowUp:"
    texto = (f"{abertura}\n\n    {codigo}\n\nEle vale por {CODIGO_EMAIL_VALIDADE_MIN} minutos e só pode ser usado uma vez.\n"
             "Se não foi você que pediu, ignore esta mensagem: nada será alterado.\n\n— Equipe ShowUp")
    if email_configurado():
        await enviar_email(email, assunto, texto)
    elif EMAIL_CODIGOS_NO_LOG:
        logging.warning("[DEV] código %s para %s: %s", finalidade, email, codigo)
    else:
        raise RuntimeError("e-mail não configurado")


async def _entregar_aviso_conta_existente(email: str) -> None:
    texto = ("Alguém tentou criar uma conta no ShowUp com este e-mail, mas ele já tem cadastro.\n\n"
             "Se foi você, entre normalmente com o seu e-mail e senha (ou use \"Esqueci minha senha\" no app).\n"
             "Se não foi você, ignore esta mensagem: nada foi alterado.\n\n— Equipe ShowUp")
    if email_configurado():
        await enviar_email(email, "Você já tem uma conta no ShowUp", texto)
    elif EMAIL_CODIGOS_NO_LOG:
        logging.warning("[DEV] aviso de conta existente para %s", email)
    else:
        raise RuntimeError("e-mail não configurado")


async def _emitir_codigo(email: str, finalidade: str, modo: str = "codigo", extra: Optional[dict] = None) -> None:
    """Guarda (só o HASH do) código e envia o e-mail.

    modo "codigo": envia o código · "aviso": envia o aviso de conta já existente (sem código) ·
    "silencio": não envia nada. Os três gravam o registro de espera de 60 s, então quem pede
    não consegue descobrir, pela resposta, se um e-mail tem conta: o comportamento é igual."""
    agora = _now()
    filtro = {"email": email, "finalidade": finalidade}
    atual = await db.email_codes.find_one(filtro, {"_id": 0, "enviado_em": 1})
    if atual and (agora - _aware(atual["enviado_em"])).total_seconds() < CODIGO_EMAIL_REENVIO_SEG:
        raise HTTPException(429, "Aguarde um minuto antes de pedir outro código.")
    codigo = f"{secrets.randbelow(10 ** 6):06d}"
    await db.email_codes.replace_one(filtro, {
        **filtro, "enviado_em": agora, "tentativas": 0,
        "expira_em": agora + timedelta(minutes=CODIGO_EMAIL_VALIDADE_MIN),
        "codigo_hash": _hash_codigo(email, finalidade, codigo) if modo == "codigo" else None,
        **(extra or {}),
    }, upsert=True)
    if modo == "silencio":
        return
    try:
        if modo == "codigo":
            await _entregar_codigo(email, finalidade, codigo)
        else:
            await _entregar_aviso_conta_existente(email)
    except Exception:
        logging.exception("falha ao enviar e-mail de %s", finalidade)
        await db.email_codes.delete_one(filtro)
        raise HTTPException(503, "Não conseguimos enviar o e-mail agora. Tente de novo em instantes.")


async def _validar_codigo(email: str, finalidade: str, codigo: str) -> dict:
    """Confere o código e devolve o registro. A tentativa é contada de forma ATÔMICA antes da
    comparação (5 no máximo), então chamadas em paralelo não furam o limite."""
    erro = HTTPException(400, "Código inválido ou expirado.")
    agora = _now()
    doc = await db.email_codes.find_one_and_update(
        {"email": email, "finalidade": finalidade, "codigo_hash": {"$ne": None},
         "tentativas": {"$lt": CODIGO_EMAIL_MAX_TENTATIVAS}, "expira_em": {"$gt": agora}},
        {"$inc": {"tentativas": 1}},
    )
    if not doc:
        raise erro
    recebido = _hash_codigo(email, finalidade, (codigo or "").strip())
    if not hmac.compare_digest(doc["codigo_hash"], recebido):
        raise erro
    return doc


async def _checar_bloqueio_login(email: str) -> None:
    doc = await db.login_attempts.find_one({"email": email}, {"_id": 0})
    if doc and doc.get("bloqueado_ate") and _aware(doc["bloqueado_ate"]) > _now():
        raise HTTPException(429, "Muitas tentativas. Tente de novo em alguns minutos ou use \"Esqueci minha senha\".")


async def _registrar_falha_login(email: str) -> None:
    agora = _now()
    doc = await db.login_attempts.find_one({"email": email}, {"_id": 0})
    falhas = (doc["falhas"] if doc and _aware(doc["expira_em"]) > agora else 0) + 1
    novo = {"email": email, "falhas": falhas, "expira_em": agora + timedelta(minutes=LOGIN_BLOQUEIO_MIN)}
    if falhas >= LOGIN_MAX_FALHAS:
        novo["bloqueado_ate"] = agora + timedelta(minutes=LOGIN_BLOQUEIO_MIN)
    await db.login_attempts.replace_one({"email": email}, novo, upsert=True)


@api_router.post("/auth/email/cadastro")
@limiter.limit("5/minute")
async def auth_email_cadastro(request: Request, payload: EmailCadastroRequest):
    """Passo 1 do cadastro: manda um código de 6 dígitos pro e-mail. A conta SÓ é criada no passo 2
    (depois de provar que o e-mail é da pessoa), então ninguém reserva o e-mail dos outros e a
    senha só vale depois da prova."""
    _exigir_email_ativo()
    email = _norm_email(payload.email)
    nome = (payload.name or "").strip()
    if not 2 <= len(nome) <= 80:
        raise HTTPException(422, "Informe seu nome (de 2 a 80 caracteres).")
    erro_senha = validar_senha(payload.password, email)
    if erro_senha:
        raise HTTPException(422, erro_senha)

    existente = await db.users.find_one({"email": email}, {"_id": 0, "password_hash": 1})
    if existente and existente.get("password_hash"):
        await _emitir_codigo(email, "verify", modo="aviso")
    else:
        # conta que já existe por Google/Microsoft, sem senha: o mesmo caminho adiciona a senha
        pendente = {"nome": nome, "password_hash": await asyncio.to_thread(hash_senha, payload.password)}
        await _emitir_codigo(email, "verify", extra=pendente)
    return {"ok": True, "mensagem": f"Se o e-mail for válido, enviamos um código de 6 dígitos. Ele vale {CODIGO_EMAIL_VALIDADE_MIN} minutos."}


@api_router.post("/auth/email/verificar", response_model=SessionResponse)
@limiter.limit("10/minute")
async def auth_email_verificar(request: Request, payload: EmailVerificarRequest):
    """Passo 2: o código confere → cria a conta (ou adiciona a senha a uma conta Google/Microsoft
    do mesmo e-mail, já que o código prova que o e-mail é dele) e já entra."""
    email = _norm_email(payload.email)
    doc = await _validar_codigo(email, "verify", payload.code)
    if not doc.get("password_hash"):
        raise HTTPException(400, "Código inválido ou expirado.")
    existente = await db.users.find_one({"email": email}, {"_id": 0, "user_id": 1})
    if existente:
        user_id = existente["user_id"]
        await db.users.update_one({"user_id": user_id}, {"$set": {"password_hash": doc["password_hash"], "email_verified": True}})
    else:
        user_id = f"user_{uuid.uuid4().hex[:12]}"
        await db.users.insert_one({
            "user_id": user_id, "email": email, "name": doc.get("nome") or email.split("@")[0], "picture": None,
            "role": None, "categorias": [], "created_at": _now(),
            "password_hash": doc["password_hash"], "email_verified": True,
        })
    await db.email_codes.delete_one({"email": email, "finalidade": "verify"})
    return await _emitir_sessao(user_id)


@api_router.post("/auth/email/login", response_model=SessionResponse)
@limiter.limit("10/minute")
async def auth_email_login(request: Request, payload: EmailLoginRequest):
    erro = HTTPException(401, "E-mail ou senha incorretos.")
    try:
        email = _norm_email(payload.email)
    except HTTPException:
        raise erro
    await _checar_bloqueio_login(email)
    user = await db.users.find_one({"email": email}, {"_id": 0, "user_id": 1, "password_hash": 1})
    armazenado = (user or {}).get("password_hash")
    # sempre gasta o tempo de uma conferência, exista a conta ou não
    confere = await asyncio.to_thread(verificar_senha, payload.password or "", armazenado or hash_falso())
    if not (user and armazenado and confere):
        await _registrar_falha_login(email)
        raise erro
    await db.login_attempts.delete_one({"email": email})
    return await _emitir_sessao(user["user_id"])


@api_router.post("/auth/email/esqueci")
@limiter.limit("5/minute")
async def auth_email_esqueci(request: Request, payload: EmailEsqueciRequest):
    """Sempre responde igual, exista a conta ou não (não revela quem tem cadastro)."""
    _exigir_email_ativo()
    email = _norm_email(payload.email)
    user = await db.users.find_one({"email": email}, {"_id": 0, "user_id": 1})
    await _emitir_codigo(email, "reset", modo="codigo" if user else "silencio")
    return {"ok": True, "mensagem": "Se existir uma conta com esse e-mail, enviamos um código de 6 dígitos."}


@api_router.post("/auth/email/redefinir")
@limiter.limit("10/minute")
async def auth_email_redefinir(request: Request, payload: EmailRedefinirRequest):
    email = _norm_email(payload.email)
    erro_senha = validar_senha(payload.new_password, email)
    if erro_senha:
        raise HTTPException(422, erro_senha)
    await _validar_codigo(email, "reset", payload.code)
    user = await db.users.find_one({"email": email}, {"_id": 0, "user_id": 1})
    if not user:
        raise HTTPException(400, "Código inválido ou expirado.")
    novo_hash = await asyncio.to_thread(hash_senha, payload.new_password)
    await db.users.update_one({"user_id": user["user_id"]}, {"$set": {"password_hash": novo_hash, "email_verified": True}})
    # quem tinha a senha antiga (ou a sessão roubada) é desconectado em todos os aparelhos
    await db.user_sessions.delete_many({"user_id": user["user_id"]})
    await db.email_codes.delete_one({"email": email, "finalidade": "reset"})
    await db.login_attempts.delete_one({"email": email})
    return {"ok": True}


def _claims_do_jwt(token: str) -> dict:
    """Lê o payload de um JWT SEM verificar a assinatura. Só é seguro aqui porque o token veio
    direto do endpoint de token da Microsoft, por TLS, na resposta a um pedido autenticado com o
    nosso segredo (OIDC Core §3.1.3.7 dispensa a checagem de assinatura nesse caso). Nunca use
    isto com um token que veio do app ou de qualquer outro lugar."""
    try:
        payload = token.split(".")[1]
        return json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))
    except Exception:
        raise ValueError("id_token ilegível")


@api_router.get("/auth/microsoft/start")
async def auth_microsoft_start():
    """O app abre ESTE endereço no navegador; daqui mandamos pra Microsoft com `state` e `nonce`
    nossos (guardados por 10 minutos), que o callback confere. O client id fica só no servidor."""
    if not _microsoft_ativo():
        return RedirectResponse("showup://auth-callback?error=microsoft_indisponivel")
    state, nonce = secrets.token_urlsafe(24), secrets.token_urlsafe(24)
    await db.oauth_states.insert_one({"state": state, "nonce": nonce, "expira_em": _now() + timedelta(minutes=10)})
    return RedirectResponse(MS_AUTORIZAR_URL + "?" + urlencode({
        "client_id": MICROSOFT_CLIENT_ID, "response_type": "code", "redirect_uri": MICROSOFT_OAUTH_REDIRECT_URI,
        "response_mode": "query", "scope": "openid profile email", "state": state, "nonce": nonce,
        "prompt": "select_account",
    }))


async def _login_ou_cria_sessao_microsoft(claims: dict) -> SessionResponse:
    oid = claims.get("oid") or claims.get("sub")
    if not oid:
        raise HTTPException(401, "Resposta da Microsoft sem identificador")
    ms_id = f"{MS_TENANT_PESSOAL}:{oid}"
    email = (claims.get("email") or claims.get("preferred_username") or "").strip().lower()
    nome = claims.get("name") or (email.split("@")[0] if email else "Usuário")

    user = await db.users.find_one({"microsoft_id": ms_id}, {"_id": 0, "user_id": 1})
    if user:
        return await _emitir_sessao(user["user_id"])
    if not _EMAIL_RE.match(email):
        raise HTTPException(401, "A conta Microsoft não informou um e-mail")
    existente = await db.users.find_one({"email": email}, {"_id": 0, "user_id": 1})
    if existente:
        # conta pessoal Microsoft = e-mail verificado pela Microsoft → vincular é seguro
        await db.users.update_one({"user_id": existente["user_id"]}, {"$set": {"microsoft_id": ms_id, "email_verified": True}})
        return await _emitir_sessao(existente["user_id"])
    user_id = f"user_{uuid.uuid4().hex[:12]}"
    await db.users.insert_one({
        "user_id": user_id, "email": email, "name": nome, "picture": None, "role": None, "categorias": [],
        "created_at": _now(), "microsoft_id": ms_id, "email_verified": True,
    })
    return await _emitir_sessao(user_id)


@api_router.get("/auth/microsoft/callback")
async def auth_microsoft_callback(code: Optional[str] = None, state: Optional[str] = None, error: Optional[str] = None):
    def volta(erro: str) -> RedirectResponse:
        return RedirectResponse(f"showup://auth-callback?error={erro}")

    if error or not code or not state or not _microsoft_ativo():
        return volta(error or "sem_code")
    # `state` é de uso único: apaga ao ler (impede reuso e login forjado por link de terceiros)
    guardado = await db.oauth_states.find_one_and_delete({"state": state})
    if not guardado or _aware(guardado["expira_em"]) <= _now():
        return volta("estado_invalido")

    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.post(MS_TOKEN_URL, data={
            "client_id": MICROSOFT_CLIENT_ID, "client_secret": MICROSOFT_CLIENT_SECRET, "code": code,
            "redirect_uri": MICROSOFT_OAUTH_REDIRECT_URI, "grant_type": "authorization_code",
            "scope": "openid profile email",
        })
    if resp.status_code != 200:
        logging.error("Falha trocando code por token na Microsoft: %s", resp.text[:300])
        return volta("token_exchange_failed")
    id_token_str = resp.json().get("id_token")
    if not id_token_str:
        return volta("sem_id_token")
    try:
        claims = _claims_do_jwt(id_token_str)
    except ValueError:
        return volta("token_invalido")

    # confere para quem e de quem é o token (a assinatura não precisa: ver _claims_do_jwt)
    valido = (
        claims.get("aud") == MICROSOFT_CLIENT_ID
        and claims.get("iss") == f"https://login.microsoftonline.com/{MS_TENANT_PESSOAL}/v2.0"
        and claims.get("tid") == MS_TENANT_PESSOAL
        and claims.get("nonce") == guardado["nonce"]
        and isinstance(claims.get("exp"), (int, float)) and claims["exp"] > _now().timestamp()
    )
    if not valido:
        logging.warning("id_token da Microsoft recusado (aud/iss/tid/nonce/exp não conferem)")
        return volta("token_invalido")
    try:
        sessao = await _login_ou_cria_sessao_microsoft(claims)
    except HTTPException as e:
        return volta(e.detail)
    return RedirectResponse(f"showup://auth-callback?token={sessao.session_token}")


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

    # Cobrança que seguiria rolando sem dono: o código abaixo desvincula o
    # cliente do Stripe, então quem excluísse a conta com plano pago (ou teste
    # grátis) continuaria sendo cobrado sem ter como cancelar. Cancela ANTES e,
    # se não conseguir, NÃO exclui — melhor pedir pra tentar de novo.
    if GATEWAY_KIND == "stripe":
        assinaturas = {doc.get("stripe_subscription_id"), (doc.get("plano_pendente") or {}).get("subscription_id")}
        for sub_id in assinaturas - {None, ""}:
            try:
                await gateway.cancel_subscription(sub_id)
            except Exception:
                logging.exception("exclusão de conta: falha ao cancelar a assinatura %s", sub_id)
                raise HTTPException(
                    503,
                    "Não conseguimos cancelar a cobrança do seu plano agora. "
                    "Tente de novo em instantes — sua conta não foi excluída.",
                )

    await db.users.update_one(
        {"user_id": user_id},
        {"$set": {
            "name": "Usuário excluído",
            "email": f"deleted_{user_id}@showup.excluido",
            "picture": None,
            "telefone": None,
            "plano": DEFAULT_PLANO,
            "deleted_at": _now(),
        }, "$unset": {
            "stripe_customer_id": "", "stripe_billing_customer_id": "", "stripe_account_id": "",
            "stripe_subscription_id": "", "plano_pendente": "", "plano_trial_termina_em": "",
            "plano_cobranca_pendente": "", "password_hash": "", "microsoft_id": "", "email_verified": "",
            "mp_access_token_cifrado": "", "mp_refresh_token_cifrado": "", "mp_token_expira_em": "",
            "mp_public_key": "", "mp_user_id": "", "recebimento": "",
        }},
    )
    await db.user_sessions.delete_many({"user_id": user_id})
    # Dados pessoais que não ficam no documento do usuário: token de push (senão o
    # aparelho continuaria recebendo avisos de uma conta excluída) e o cartão salvo.
    await db.device_tokens.delete_many({"user_id": user_id})
    await db.customer_cards.delete_many({"user_id": user_id})
    await db.agendamentos.update_many({"cliente_id": user_id}, {"$unset": {"email_cliente": ""}})
    await db.email_codes.delete_many({"email": doc["email"]})
    await db.login_attempts.delete_many({"email": doc["email"]})
    # No Stripe, apaga os Customers (melhor esforço — não trava a exclusão). Os
    # registros de transação ficam lá por obrigação legal; a conta conectada do
    # profissional (verificação de identidade) segue a política do próprio Stripe.
    if GATEWAY_KIND == "stripe":
        for customer_id in (doc.get("stripe_customer_id"), doc.get("stripe_billing_customer_id")):
            if customer_id:
                try:
                    await gateway.delete_customer(customer_id)
                except Exception:
                    logging.warning("exclusão de conta: não consegui apagar o customer %s no Stripe", customer_id)
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


@api_router.post("/me/notificacoes/teste")
@limiter.limit("6/minute")
async def testar_notificacoes(request: Request, authorization: Optional[str] = Header(default=None)):
    """Manda uma notificação de teste para o aparelho do profissional e diz, em português, por que NÃO chegou.
    O "ticket" da Expo só prova que ela recebeu o pedido; erro de credencial do Firebase aparece no RECIBO, por isso
    esperamos alguns segundos por ele."""
    doc = await _current_user(authorization)
    await _require_role(doc, "profissional")
    tok = await db.device_tokens.find_one({"user_id": doc["user_id"]}, {"_id": 0})
    if not tok:
        raise HTTPException(409, "Este aparelho ainda não está registrado para receber notificações. "
                                 "Abra o app no celular (não no emulador), permita as notificações e tente de novo.")
    try:
        ticket = await send_push(tok["expo_push_token"], "Teste do ShowUp",
                                 "Se você está vendo isto, as notificações estão funcionando.", {"type": "teste"})
    except Exception:
        logging.exception("teste de notificação: falha falando com a Expo")
        raise HTTPException(503, "Não consegui falar com o serviço de notificações agora. Tente de novo em instantes.")

    def resposta(enviado: bool, recibo: str, mensagem: str, etapa: Optional[str] = None) -> dict:
        # etapa: onde falhou — "ticket" (a Expo recusou o pedido) ou "recibo" (a Expo aceitou, mas o Firebase não entregou)
        return {"enviado": enviado, "recibo": recibo, "mensagem": mensagem, "etapa": etapa}

    if ticket.get("status") == "error":
        codigo = (ticket.get("details") or {}).get("error")
        if is_device_not_registered(ticket):
            await db.device_tokens.delete_one({"user_id": doc["user_id"]})
        return resposta(False, "erro", explicar_erro_push(codigo, ticket.get("message", "")), etapa="ticket")

    recibo = None
    if ticket.get("id"):
        await asyncio.sleep(RECIBO_ESPERA_SEG)
        try:
            recibo = await buscar_recibo(ticket["id"])
        except Exception:
            logging.warning("teste de notificação: não consegui buscar o recibo", exc_info=True)
    if recibo and recibo.get("status") == "error":
        codigo = (recibo.get("details") or {}).get("error")
        if codigo == "DeviceNotRegistered":
            await db.device_tokens.delete_one({"user_id": doc["user_id"]})
        return resposta(False, "erro", explicar_erro_push(codigo, recibo.get("message", "")), etapa="recibo")
    if recibo and recibo.get("status") == "ok":
        return resposta(True, "ok", "Notificação enviada. Ela deve aparecer no celular em instantes.")
    return resposta(True, "pendente", "Enviamos o teste, mas a Expo ainda não confirmou a entrega. "
                                      "Se não aparecer em 1 ou 2 minutos, siga lancamento/NOTIFICACOES.md.")


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
    """`categorias` (lista plana, como sempre) + `grupos` (para a lista suspensa por grupo) + o máximo que cada profissional pode escolher."""
    return {
        "categorias": CATEGORIAS,
        "grupos": [{"grupo": g, "categorias": cs} for g, cs in CATEGORIAS_POR_GRUPO.items()],
        "maximo": MAX_CATEGORIAS_POR_PROFISSIONAL,
    }


@api_router.put("/me/categorias", response_model=MeResponse)
async def set_categorias(payload: CategoriasRequest, authorization: Optional[str] = Header(default=None)):
    doc = await _current_user(authorization)
    await _require_role(doc, "profissional")
    await db.users.update_one({"user_id": doc["user_id"]}, {"$set": {"categorias": payload.categorias}})
    doc = await db.users.find_one({"user_id": doc["user_id"]}, {"_id": 0})
    return MeResponse(user=await _serialize_user(doc))


@api_router.get("/timezones")
async def listar_timezones():
    return {"timezones": TIMEZONES, "grupos": [{"grupo": g, "timezones": zs} for g, zs in TIMEZONES_POR_GRUPO.items()]}


@api_router.put("/me/timezone", response_model=MeResponse)
async def set_timezone(payload: TimezoneRequest, authorization: Optional[str] = Header(default=None)):
    doc = await _current_user(authorization)
    await _require_role(doc, "profissional")
    await db.users.update_one({"user_id": doc["user_id"]}, {"$set": {"timezone": payload.timezone}})
    doc = await db.users.find_one({"user_id": doc["user_id"]}, {"_id": 0})
    return MeResponse(user=await _serialize_user(doc))


@api_router.get("/moedas")
async def listar_moedas():
    return {"moedas": MOEDAS_SUPORTADAS, "moedas_de_recebimento": [m for m in MOEDAS_RECEBIMENTO if m in MOEDAS_SUPORTADAS] or [DEFAULT_MOEDA],
            "adicional_conversao_bps": ADICIONAL_CONVERSAO_BPS}


@api_router.put("/me/moeda", response_model=MeResponse)
async def set_moeda(payload: MoedaRequest, authorization: Optional[str] = Header(default=None)):
    """Moeda é uma propriedade do PROFISSIONAL (ligada à conta Connect dele,
    que só liquida numa moeda), não do serviço individual — por isso vive
    aqui, no perfil, e não em ServicoCreate. Trocar a moeda não afeta
    serviços já criados (eles guardam a moeda que tinham no momento da
    criação — ver criar_servico), só os próximos."""
    doc = await _current_user(authorization)
    await _require_role(doc, "profissional")
    if _recebe_pelo_mp(doc) and payload.moeda != "BRL":
        raise HTTPException(409, "O Mercado Pago só recebe em reais. Para usar outra moeda, passe a receber pelo Stripe.")
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
    # Só quem tem serviço ativo aparece: começa pelos serviços (1 consulta), não por profissional (antes, 1 por pessoa).
    contagem: dict[str, int] = {}
    async for s_ in db.servicos.find({"ativo": True}, {"_id": 0, "profissional_id": 1}):
        contagem[s_["profissional_id"]] = contagem.get(s_["profissional_id"], 0) + 1
    query: dict = {"role": "profissional", "user_id": {"$in": list(contagem)}}
    termo = (q or "").strip()[:60]
    if termo:
        # O texto digitado é TEXTO: re.escape impede que ".*", "(a+)+" etc. virem um padrão (busca errada ou travada).
        query["name"] = {"$regex": re.escape(termo), "$options": "i"}
    if categoria and categoria in CATEGORIAS:
        query["categorias"] = categoria
    users = await db.users.find(query, {"_id": 0}).sort("name", 1).to_list(200)
    result = []
    for u in users:
        count = contagem.get(u["user_id"], 0)
        result.append(ProfissionalPublic(
            user_id=u["user_id"], name=u["name"], picture=u.get("picture"),
            categorias=u.get("categorias", []), servicos_count=count,
        ))
    return result


@api_router.get("/profissionais/{user_id}", response_model=ProfissionalDetail)
async def detalhe_profissional(user_id: str):
    """Aceita o id interno (links antigos: /agendar?prof=user_xxx) OU o endereço legível (/p/eduardo-cerqueira)."""
    u = await db.users.find_one({"user_id": user_id, "role": "profissional"}, {"_id": 0})
    if not u:
        u = await db.users.find_one({"slug": user_id.lower(), "role": "profissional"}, {"_id": 0})
    if not u:
        raise HTTPException(404, "Não encontrado")
    user_id = u["user_id"]
    servicos = await db.servicos.find({"profissional_id": user_id, "ativo": True}, {"_id": 0}).to_list(200)
    pelo_mp = _recebe_pelo_mp(u)
    if pelo_mp:
        # Escolheu o Mercado Pago: só aceita se o servidor ainda tem o Mercado Pago configurado (senão a reserva falharia no fim).
        aceita = MERCADOPAGO_ATIVO
    else:
        aceita = not EXIGIR_RECEBIMENTO_ATIVO or bool(u.get("connect_ready") and u.get("stripe_account_id"))
    return ProfissionalDetail(
        user_id=u["user_id"], name=u["name"], picture=u.get("picture"),
        categorias=u.get("categorias", []),
        timezone=u.get("timezone") or DEFAULT_TIMEZONE,
        servicos=[Servico(**{**s, "criado_em": _aware(s["criado_em"])}) for s in servicos],
        aceita_agendamentos=aceita,
        recebimento="mercadopago" if pelo_mp else "stripe",
        mp_public_key=u.get("mp_public_key") if pelo_mp else None,
        pix_disponivel=(pelo_mp and MERCADOPAGO_ATIVO) or (not pelo_mp and PIX_STRIPE_HABILITADO and GATEWAY_KIND == "stripe"),
        link_agendamento=f"{PUBLIC_WEB_BASE_URL}/p/{await _garantir_slug(u)}" if pelo_mp else None,
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
    """Horários livres para o cliente escolher: a disponibilidade semanal menos o que já está reservado, limitado à
    JANELA DA AGENDA (agenda.py): os próximos N dias em que o profissional atende (N = dias da semana que ele cadastrou;
    seg a sex = 5, seg a dom = 7) e nunca depois do prazo em que a reserva no cartão ainda pode ser cobrada.
    O servidor aplica a mesma regra ao reservar (_exigir_horario_na_agenda), então a lista e a reserva não divergem.

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
    prof = await db.users.find_one({"user_id": user_id}, {"_id": 0, "timezone": 1, "recebimento": 1, "mp_user_id": 1})
    tz = _tz_for(prof)
    weekly = await db.disponibilidade.find({"profissional_id": user_id}, {"_id": 0}).to_list(200)
    if not weekly:
        return []

    busy = await db.agendamentos.find(
        {
            "profissional_id": user_id,
            "hold_status": {"$in": STATUS_OCUPAM_HORARIO},
            "horario_fim": {"$gt": _now()},
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
    janela = montar_janela(weekly, now, tz, _hold_dias(prof))
    # "Hoje" no calendário LOCAL do profissional — um profissional em
    # America/Noronha (UTC-2) e outro em America/Rio_Branco (UTC-5) podem
    # estar em dias de calendário diferentes no mesmo instante UTC.
    start_date_local = now.astimezone(tz).date()

    # A grade de horários vem de agenda.inicios_possiveis — a MESMA função que o servidor usa para conferir o expediente
    # na hora de reservar. Aqui só se tira o que já está ocupado e o que cai fora da janela de dias.
    for cursor in sorted(inicios_possiveis(weekly, step, now, tz)):
        overlap = any(
            cursor < _aware(b["horario_fim"]) and (cursor + duracao) > _aware(b["horario_inicio"])
            for b in busy
        )
        if not overlap and janela.motivo_recusa(cursor, cursor + duracao) is None:
            result.append(SlotDisponivel(
                iso=cursor.isoformat(),
                day_label=cursor.strftime("%a, %d %b"),
                time_label=cursor.strftime("%H:%M"),
            ))
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
    except Exception:
        return ConnectStatus(account_id=acct_id, estado="indisponivel")
    connect_ready = bool(st.get("charges_enabled") and st.get("payouts_enabled"))
    await db.users.update_one({"user_id": doc["user_id"]}, {"$set": {"connect_ready": connect_ready}})
    return ConnectStatus(
        account_id=acct_id,
        charges_enabled=bool(st.get("charges_enabled")),
        payouts_enabled=bool(st.get("payouts_enabled")),
        details_submitted=bool(st.get("details_submitted")),
        estado=_estado_connect(st),
        pendencias=list(st.get("pendencias") or []) + list(st.get("vencidas") or []),
        motivo_bloqueio=st.get("motivo_bloqueio"),
    )


def _estado_connect(st: dict) -> str:
    """Traduz o que o Stripe devolve num estado que o app sabe explicar. A ordem
    importa: o que o PROFISSIONAL pode resolver (pendências) vem antes de "em
    análise" (só esperar)."""
    if st.get("charges_enabled") and st.get("payouts_enabled"):
        return "ativa"
    motivo = st.get("motivo_bloqueio") or ""
    if motivo.startswith("rejected"):
        return "recusada"
    if st.get("pendencias") or st.get("vencidas") or not st.get("details_submitted"):
        return "pendente_informacoes"
    if motivo in ("under_review", "requirements.pending_verification") or st.get("em_verificacao"):
        return "em_analise"
    return "restrita"


@api_router.post("/me/connect/painel", response_model=ConnectLink)
async def connect_painel(authorization: Optional[str] = Header(default=None)):
    """Abre o painel Express do Stripe do profissional. É lá que aparecem as
    "Tasks" que o Stripe cria depois do cadastro (informações adicionais do
    negócio, revisão de risco) — o link de onboarding não cobre isso."""
    doc = await _current_user(authorization)
    await _require_role(doc, "profissional")
    if GATEWAY_KIND != "stripe":
        raise HTTPException(400, "Connect requer gateway Stripe real")
    acct_id = doc.get("stripe_account_id")
    if not acct_id:
        raise HTTPException(409, "Conecte sua conta do Stripe primeiro.")
    try:
        url = await gateway.create_login_link(acct_id)
    except InvalidPaymentRequestError:
        raise HTTPException(409, "Conclua o cadastro no Stripe antes de abrir o painel.")
    except PaymentError:
        logging.exception("connect_painel falhou")
        raise HTTPException(502, "Não foi possível abrir o painel do Stripe agora. Tente de novo.")
    return ConnectLink(url=url)


async def _recebimento_ativo(prof: Optional[dict]) -> bool:
    """O profissional consegue receber (conta conectada liberada)? Usa o cache
    `connect_ready`; se ele diz "não" mas existe conta, confere no Stripe (o
    cache só atualiza quando o profissional abre a tela, e a conta pode ter sido
    liberada nesse meio-tempo).
    Mercado Pago: a conta conectada por OAuth já recebe (quem libera é o próprio Mercado Pago)."""
    if _recebe_pelo_mp(prof):
        return MERCADOPAGO_ATIVO and bool(prof.get("mp_access_token_cifrado"))
    if not prof or not prof.get("stripe_account_id"):
        return False
    if prof.get("connect_ready"):
        return True
    if GATEWAY_KIND != "stripe":
        return False
    try:
        st = await gateway.account_status(prof["stripe_account_id"])
    except Exception:
        return False
    pronto = bool(st.get("charges_enabled") and st.get("payouts_enabled"))
    if pronto:
        await db.users.update_one({"user_id": prof["user_id"]}, {"$set": {"connect_ready": True}})
    return pronto


async def _exigir_recebimento_ativo(prof: Optional[dict]) -> None:
    if EXIGIR_RECEBIMENTO_ATIVO and not await _recebimento_ativo(prof):
        raise HTTPException(
            409, "Este profissional ainda não habilitou os recebimentos pelo ShowUp. Tente de novo mais tarde."
        )


async def _atualizar_connect_pendentes() -> int:
    """Job (10 min): contas conectadas que ainda não estão liberadas são
    reconsultadas no Stripe, pra liberarem as reservas assim que o Stripe
    aprovar — sem depender do profissional abrir o app."""
    if GATEWAY_KIND != "stripe":
        return 0
    pendentes = await db.users.find(
        {"role": "profissional", "stripe_account_id": {"$nin": [None, ""]}, "connect_ready": {"$ne": True}},
        {"_id": 0, "user_id": 1, "stripe_account_id": 1},
    ).to_list(500)
    liberados = 0
    for u in pendentes:
        try:
            st = await gateway.account_status(u["stripe_account_id"])
        except Exception:
            continue
        if st.get("charges_enabled") and st.get("payouts_enabled"):
            await db.users.update_one({"user_id": u["user_id"]}, {"$set": {"connect_ready": True}})
            liberados += 1
    return liberados


# Página web pública (Firebase Hosting) onde o cliente agenda pelo link do
# profissional — é a mesma base que o app mostra em "Seu link de agendamento".
PUBLIC_WEB_BASE_URL = os.environ.get("PUBLIC_WEB_BASE_URL", "https://showup-509120.web.app").rstrip("/")


def _slugify(nome: str) -> str:
    """"José da Conceição" -> "jose-da-conceicao": letras e números sem acento, separados por hífen (até 40 caracteres)."""
    ascii_ = unicodedata.normalize("NFKD", nome or "").encode("ascii", "ignore").decode()
    slug = re.sub(r"[^a-z0-9]+", "-", ascii_.lower()).strip("-")[:40].strip("-")
    return slug or "profissional"


async def _garantir_slug(u: dict) -> str:
    """Endereço legível do profissional (/p/eduardo-cerqueira). Criado na primeira vez que é pedido e NUNCA muda depois
    (os links já enviados pelo WhatsApp continuam valendo, mesmo se ele trocar de nome). Dois profissionais com o mesmo
    nome ficam "maria-silva" e "maria-silva-2"; o índice único do banco evita duplicata mesmo em pedidos simultâneos."""
    if u.get("slug"):
        return u["slug"]
    base = _slugify(u.get("name") or "")
    for tentativa in range(30):
        candidato = base if tentativa == 0 else f"{base}-{tentativa + 1}"
        if await db.users.find_one({"slug": candidato}, {"_id": 1}):
            continue
        try:
            res = await db.users.update_one({"user_id": u["user_id"], "slug": {"$exists": False}}, {"$set": {"slug": candidato}})
        except DuplicateKeyError:
            continue                      # outro profissional pegou o mesmo nome no mesmo instante
        if res.modified_count:
            return candidato
        atual = await db.users.find_one({"user_id": u["user_id"]}, {"_id": 0, "slug": 1})
        if atual and atual.get("slug"):
            return atual["slug"]          # outra requisição do mesmo profissional já gravou
    candidato = f"{base}-{uuid.uuid4().hex[:6]}"
    await db.users.update_one({"user_id": u["user_id"]}, {"$set": {"slug": candidato}})
    return candidato


@api_router.get("/me/link-publico")
async def link_publico(authorization: Optional[str] = Header(default=None)):
    """O link de agendamento que o profissional compartilha. Vem do servidor (e não fixo no app) para que trocar o
    domínio do site não exija recompilar o aplicativo."""
    u = await _current_user(authorization)
    await _require_role(u, "profissional")
    slug = await _garantir_slug(u)
    return {"slug": slug, "url": f"{PUBLIC_WEB_BASE_URL}/p/{slug}"}


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
                doc["email"], doc["name"], country=CONNECT_PAIS,
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
                doc["email"], doc["name"], country=CONNECT_PAIS,
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
    falta → capturado_taxa). A taxa de cada um incide sobre o valor
    EFETIVAMENTE cobrado (`valor_capturado_centavos`): o serviço inteiro no
    atendimento, só a taxa de falta na falta — ver
    StripeGateway._taxa_na_captura."""
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
    # A taxa incide sobre o valor REALMENTE cobrado: o serviço inteiro no
    # atendimento, só a taxa de falta na falta (ver StripeGateway._taxa_na_captura).
    valores = [int(i.get("valor_capturado_centavos") or i.get("valor_total_centavos") or 0) for i in atendimentos]
    valores += [int(i.get("valor_capturado_centavos") or 0) for i in faltas]

    comparacao_ok = moeda == "BRL"
    linhas = calcular_comparacao_planos(valores, plano_atual, DESCONTO_MERCADOPAGO_BPS if _recebe_pelo_mp(doc) else 0) if comparacao_ok else []
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
        trial_disponivel=_trial_disponivel(doc) and comparacao_ok and PLANOS_COMPRA_HABILITADA,
        trial_dias=TRIAL_DIAS,
        trial_termina_em=_aware(termina_em) if (termina_em and plano_atual != DEFAULT_PLANO) else None,
        cobranca_pendente=bool(doc.get("plano_cobranca_pendente")) and plano_atual != DEFAULT_PLANO,
        compra_habilitada=PLANOS_COMPRA_HABILITADA,
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

    if not PLANOS_COMPRA_HABILITADA:
        raise HTTPException(403, "A assinatura de planos pagos ainda não está disponível.")
    plano_cfg = PLANOS[payload.plano]
    price_id = os.environ.get(plano_cfg["price_env"] or "")
    if not price_id:
        raise HTTPException(400, f"Plano {payload.plano} ainda não tem Price ID configurado no servidor")
    try:
        price = await gateway.get_price(price_id)
    except PaymentError:
        logging.exception("não consegui ler o Price %s do plano %s", price_id, payload.plano)
        raise HTTPException(502, "Falha ao criar assinatura junto ao gateway")
    if not _price_confere(plano_cfg, price):
        logging.error("Price %s do plano %s não confere com PLANOS: %s", price_id, payload.plano, price)
        raise HTTPException(503, "O preço deste plano está sendo atualizado. Tente de novo mais tarde.")

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
    return (await _hydrate_varios([doc]))[0]


async def _hydrate_varios(docs: list[dict]) -> list[Agendamento]:
    """Monta a lista com os nomes de profissional, cliente e serviço em DUAS consultas para a lista inteira
    (antes eram 3 por agendamento: 600 consultas para abrir a tela com 200)."""
    if not docs:
        return []
    ids_users = list({d["profissional_id"] for d in docs} | {d["cliente_id"] for d in docs})
    ids_svc = list({d["servico_id"] for d in docs})
    nomes = {u["user_id"]: u.get("name") async for u in db.users.find({"user_id": {"$in": ids_users}}, {"_id": 0, "user_id": 1, "name": 1})}
    servicos = {x["servico_id"]: x.get("nome") async for x in db.servicos.find({"servico_id": {"$in": ids_svc}}, {"_id": 0, "servico_id": 1, "nome": 1})}
    return [_montar_agendamento(d, nomes, servicos) for d in docs]


def _montar_agendamento(doc: dict, nomes: dict, servicos: dict) -> Agendamento:
    prof = {"name": nomes[doc["profissional_id"]]} if nomes.get(doc["profissional_id"]) else None
    cli = {"name": nomes[doc["cliente_id"]]} if nomes.get(doc["cliente_id"]) else None
    svc = {"nome": servicos[doc["servico_id"]]} if servicos.get(doc["servico_id"]) else None
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
async def criar_agendamento(request: Request, background_tasks: BackgroundTasks, payload: AgendamentoCreate, authorization: Optional[str] = Header(default=None)):
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
    await _exigir_horario_na_agenda(svc["profissional_id"], horario, horario_fim)

    # --- Checagem de conflito (double-booking) ---
    # /profissionais/{id}/slots calcula os horários livres, mas nada aqui
    # impedia a criação direta de um agendamento sobreposto — dois clientes
    # via o mesmo slot exibido (ou requisições simultâneas do mesmo cliente)
    # podiam ambos reservar o mesmo horário. Verificação por sobreposição de
    # intervalo, não só igualdade de horário_inicio, para cobrir serviços de
    # duração diferente.
    conflito = await db.agendamentos.find_one({
        "profissional_id": svc["profissional_id"],
        "hold_status": {"$in": STATUS_OCUPAM_HORARIO},
        "horario_inicio": {"$lt": horario_fim},
        "horario_fim": {"$gt": horario},
    })
    if conflito:
        raise HTTPException(409, "Esse horário acabou de ser reservado por outro cliente. Escolha outro.")

    # Optional Connect destination for split.
    prof = await db.users.find_one({"user_id": svc["profissional_id"]}, {"_id": 0})
    if _recebe_pelo_mp(prof):
        # O cartão salvo no app é do Stripe e não serve para o Mercado Pago: o app manda o cliente para o link (cartão ou Pix).
        raise HTTPException(409, "Este profissional recebe pelo Mercado Pago. Agende pelo link de agendamento dele, com cartão ou Pix.")
    await _exigir_recebimento_ativo(prof)
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
            fee_bps=_fee_bps_for(prof, svc["moeda"]),
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

    janela_conf = await _janela_de_confirmacao_ou_desfazer(hold, horario_fim, agendamento_id)
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
        "janela_confirmacao_expira_em": janela_conf,
        "valor_capturado_centavos": 0,
        "connect_destination": destination,
        # Percentual de taxa vigente NA ÉPOCA da reserva (plano de então). A
        # captura da falta usa este valor — mudar de plano depois não altera
        # reservas já feitas.
        "fee_bps": _fee_bps_for(prof, svc["moeda"]),
        "idioma": idioma_da_requisicao(request.headers.get("accept-language")),
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
    # Depois da resposta (não atrasa a reserva): o profissional recebe "Novo agendamento".
    background_tasks.add_task(_avisar_reserva_confirmada, db, agendamento_id)
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
async def criar_agendamento_publico_cartao(request: Request, background_tasks: BackgroundTasks, payload: AgendamentoPublicoCartaoRequest):
    contato = _contato_do_aviso(request, payload.email)
    """Mesmo fluxo de hold do endpoint autenticado, mas pro cliente que vem
    do link do WhatsApp (sem conta/sessão no app) — o cartão foi coletado
    na página web via Stripe.js Elements, não no Payment Sheet nativo."""
    cliente = await _find_or_create_cliente_por_telefone(payload.nome, payload.telefone)
    svc, prof, horario_fim = await _valida_servico_e_conflito(payload.servico_id, payload.horario_inicio)
    if svc["profissional_id"] != payload.profissional_id:
        raise HTTPException(400, "servico_id não pertence ao profissional_id informado")
    horario = _aware(payload.horario_inicio)
    if _recebe_pelo_mp(prof):
        raise HTTPException(409, "Este profissional recebe pelo Mercado Pago. Agende pelo link de agendamento dele, com cartão ou Pix.")

    await _exigir_recebimento_ativo(prof)
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
            fee_bps=_fee_bps_for(prof, svc["moeda"]),
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

    janela_conf = await _janela_de_confirmacao_ou_desfazer(hold, horario_fim, agendamento_id)
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
        "janela_confirmacao_expira_em": janela_conf,
        "valor_capturado_centavos": 0,
        "connect_destination": destination,
        # Percentual de taxa vigente NA ÉPOCA da reserva (plano de então). A
        # captura da falta usa este valor — mudar de plano depois não altera
        # reservas já feitas.
        "fee_bps": _fee_bps_for(prof, svc["moeda"]),
        "origem": "link_publico",
        **contato,
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
    background_tasks.add_task(_avisar_reserva_confirmada, db, agendamento_id)
    return await _hydrate(doc)


@api_router.post("/public/agendamentos/pix", response_model=AgendamentoPublicoPixResponse)
@limiter.limit("10/minute")
async def criar_agendamento_publico_pix(request: Request, payload: AgendamentoPublicoCreate):
    contato = _contato_do_aviso(request, payload.email)
    """Pix não suporta hold (ver create_pix_payment_intent) — cobra o valor
    TOTAL do serviço de uma vez, sem proteção de no-show. O agendamento
    fica reservado por tempo LIMITADO (PIX_RESERVA_MINUTOS) esperando o
    pagamento confirmar via webhook; se expirar sem pagar, libera o
    horário sozinho (job _expirar_pix_pendentes).
    Quem recebe pelo Mercado Pago gera o Pix lá (sem convite, com a taxa do ShowUp já separada)."""
    prof_rapido = await db.users.find_one({"user_id": payload.profissional_id}, {"_id": 0, "recebimento": 1, "mp_user_id": 1})
    pelo_mp = _recebe_pelo_mp(prof_rapido)
    if not pelo_mp and GATEWAY_KIND != "stripe":
        raise HTTPException(400, "Pix requer gateway Stripe real")
    if pelo_mp and not payload.email:
        raise HTTPException(422, "Informe seu e-mail para pagar com Pix.")
    cliente = await _find_or_create_cliente_por_telefone(payload.nome, payload.telefone)
    svc, prof, horario_fim = await _valida_servico_e_conflito(payload.servico_id, payload.horario_inicio, reserva_no_cartao=False)
    if svc["profissional_id"] != payload.profissional_id:
        raise HTTPException(400, "servico_id não pertence ao profissional_id informado")
    horario = _aware(payload.horario_inicio)
    if pelo_mp:
        return await _pix_mercadopago(payload, cliente, svc, prof, horario, horario_fim, contato)

    await _exigir_recebimento_ativo(prof)
    destination = None
    if prof and prof.get("connect_ready") and prof.get("stripe_account_id"):
        destination = prof["stripe_account_id"]

    agendamento_id = f"agd_{uuid.uuid4().hex[:12]}"
    try:
        pix = await gateway.create_pix_payment_intent(
            amount_centavos=svc["valor_centavos"],
            moeda=svc["moeda"],
            fee_bps=_fee_bps_for(prof, svc["moeda"]),
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
        # Percentual de taxa vigente NA ÉPOCA da reserva (plano de então). A
        # captura da falta usa este valor — mudar de plano depois não altera
        # reservas já feitas.
        "fee_bps": _fee_bps_for(prof, svc["moeda"]),
        "metodo_pagamento": "pix",
        "origem": "link_publico",
        **contato,
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
    doc = await db.agendamentos.find_one({"agendamento_id": agendamento_id}, {"_id": 0})
    if not doc:
        raise HTTPException(404, "Agendamento não encontrado")
    if doc.get("gateway") == "mercadopago" and doc.get("hold_status") == "aguardando_pix":
        # Não depende só do webhook: se ele atrasar (ou falhar), a página do cliente confirma consultando o Mercado Pago.
        doc = await _sincronizar_pagamento_mp(doc) or doc
    return {"hold_status": doc["hold_status"], "status_agendamento": doc["status_agendamento"]}


LIMITE_LISTA_AGENDAMENTOS = 200


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
    # Os MAIS RECENTES (antes: os 200 mais antigos, e com o tempo os novos sumiam da tela), devolvidos em ordem de horário.
    items = await db.agendamentos.find(query, {"_id": 0}).sort("horario_inicio", -1).to_list(LIMITE_LISTA_AGENDAMENTOS)
    items.reverse()
    return await _hydrate_varios(items)


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
        if ag.get("gateway") == "mercadopago":
            cap, update, tipo = await _capturar_mercadopago(ag, payload.resultado)
        elif payload.resultado == "compareceu":
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
                # Taxa proporcional ao que foi de fato cobrado (ver
                # StripeGateway._taxa_na_captura), não ao valor total do serviço.
                fee_bps=ag.get("fee_bps"),
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
    # Termos: o cliente cancela ANTES do atendimento. Depois do início, só o profissional decide (compareceu, falta
    # ou cancelar). Sem isto, quem faltava cancelava depois e o profissional perdia a taxa de falta.
    if doc["user_id"] == ag["cliente_id"] and doc["user_id"] != ag["profissional_id"] and _aware(ag["horario_inicio"]) <= _now():
        raise HTTPException(409, "O horário já começou: não dá mais para cancelar. Fale com o profissional.")

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
        await _desfazer_reserva(ag.get("gateway"), ag["profissional_id"], ag["payment_intent_id"], f"void_{agendamento_id}")
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
    return {"count": len(items), "items": await _hydrate_varios(items)}


async def _expirar_pix_pendentes() -> int:
    """Reservas via Pix (link público) que passaram do prazo sem confirmar
    pagamento — libera o horário pra outro cliente poder agendar. Diferente
    do fluxo de cartão, não precisa desfazer hold nenhum no gateway: Pix
    nunca trava nada no lado do cliente antes de pagar de verdade.
    Mercado Pago: antes de expirar, pergunta a ele se o Pix foi pago (o aviso de pagamento pode ter atrasado)."""
    now = _now()
    async for ag in db.agendamentos.find({"hold_status": "aguardando_pix", "gateway": "mercadopago", "hold_expira_em": {"$lt": now}}, {"_id": 0}):
        await _sincronizar_pagamento_mp(ag)
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
            if ag.get("gateway") == "mercadopago":
                await _desfazer_reserva("mercadopago", ag["profissional_id"], ag["payment_intent_id"], f"expire_{ag['agendamento_id']}")
            else:
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


# ---------------------------------------------------------------------------
# Mercado Pago: conectar a conta, escolher onde receber, cartão, Pix e avisos de pagamento
# ---------------------------------------------------------------------------
class RecebimentoRequest(BaseModel):
    metodo: Literal["stripe", "mercadopago"]


async def _servicos_fora_do_real(user_id: str) -> int:
    return len([s for s in await db.servicos.find({"profissional_id": user_id, "ativo": True}, {"_id": 0, "moeda": 1}).to_list(500)
                if (s.get("moeda") or DEFAULT_MOEDA).upper() != "BRL"])


def _estado_recebimento(doc: dict) -> dict:
    conectado = bool(doc.get("mp_user_id") and doc.get("mp_access_token_cifrado"))
    pelo_mp = _recebe_pelo_mp(doc)
    return {
        "metodo": "mercadopago" if pelo_mp else "stripe",
        "mercadopago_disponivel": MERCADOPAGO_ATIVO,
        "mercadopago_conectado": conectado,
        "desconto_mercadopago_bps": DESCONTO_MERCADOPAGO_BPS,
        "reserva_dias": _hold_dias(doc),
        "reserva_dias_stripe": HOLD_MAX_DIAS,
        "reserva_dias_mercadopago": HOLD_DIAS_MERCADOPAGO,
    }


@api_router.get("/me/recebimento")
async def recebimento_status(authorization: Optional[str] = Header(default=None)):
    doc = await _current_user(authorization)
    await _require_role(doc, "profissional")
    return _estado_recebimento(doc)


@api_router.put("/me/recebimento")
async def escolher_recebimento(payload: RecebimentoRequest, authorization: Optional[str] = Header(default=None)):
    """Troca por onde o profissional recebe. Vale para os agendamentos NOVOS: cada agendamento grava o seu gateway,
    então reservas já feitas terminam no gateway em que foram feitas."""
    doc = await _current_user(authorization)
    await _require_role(doc, "profissional")
    if payload.metodo == "mercadopago":
        if not MERCADOPAGO_ATIVO:
            raise HTTPException(503, "O Mercado Pago ainda não está disponível no ShowUp.")
        if not (doc.get("mp_user_id") and doc.get("mp_access_token_cifrado")):
            raise HTTPException(409, "Conecte sua conta do Mercado Pago primeiro.")
        if (doc.get("moeda") or DEFAULT_MOEDA).upper() != "BRL" or await _servicos_fora_do_real(doc["user_id"]):
            raise HTTPException(409, "O Mercado Pago só recebe em reais. Mude a moeda e os serviços para real (BRL) antes.")
    await db.users.update_one({"user_id": doc["user_id"]}, {"$set": {"recebimento": payload.metodo}})
    doc["recebimento"] = payload.metodo
    return _estado_recebimento(doc)


@api_router.post("/me/mercadopago/conectar", response_model=ConnectLink)
@limiter.limit("10/minute")
async def mercadopago_conectar(request: Request, authorization: Optional[str] = Header(default=None)):
    """Link da tela de autorização do Mercado Pago. O `state` é aleatório, guardado por 15 minutos e usado UMA vez:
    é ele que diz, no retorno, de qual profissional é a conta (e impede alguém de ligar a conta dele no perfil de outro)."""
    doc = await _current_user(authorization)
    await _require_role(doc, "profissional")
    if not MERCADOPAGO_ATIVO or mp_gateway is None:
        raise HTTPException(503, "O Mercado Pago ainda não está disponível no ShowUp.")
    state = secrets.token_urlsafe(32)
    await db.mp_oauth_states.insert_one({"state": state, "user_id": doc["user_id"], "expira_em": _now() + timedelta(minutes=15)})
    return ConnectLink(url=mp_gateway.url_autorizacao(state))


# Volta para o app depois da autorização (o app revalida o estado quando volta ao primeiro plano).
_MP_VOLTA_APP = "showup://configuracoes"


@api_router.get("/mercadopago/callback")
async def mercadopago_callback(code: Optional[str] = None, state: Optional[str] = None, error: Optional[str] = None):
    if not MERCADOPAGO_ATIVO or mp_gateway is None:
        return RedirectResponse(f"{_MP_VOLTA_APP}?mercadopago=indisponivel")
    guardado = await db.mp_oauth_states.find_one_and_delete({"state": state}) if state else None
    if not guardado or _aware(guardado["expira_em"]) <= _now():
        return RedirectResponse(f"{_MP_VOLTA_APP}?mercadopago=expirado")
    if error or not code:
        return RedirectResponse(f"{_MP_VOLTA_APP}?mercadopago=cancelado")
    try:
        tokens = await mp_gateway.trocar_codigo(code)
    except PaymentError:
        logging.exception("Mercado Pago: troca do código falhou")
        return RedirectResponse(f"{_MP_VOLTA_APP}?mercadopago=erro")
    if not tokens.get("user_id"):
        return RedirectResponse(f"{_MP_VOLTA_APP}?mercadopago=erro")
    # A mesma conta do Mercado Pago não pode receber por dois profissionais diferentes.
    outro = await db.users.find_one({"mp_user_id": tokens["user_id"], "user_id": {"$ne": guardado["user_id"]}}, {"_id": 0, "user_id": 1})
    if outro:
        return RedirectResponse(f"{_MP_VOLTA_APP}?mercadopago=conta_em_uso")
    await _gravar_tokens_mp(guardado["user_id"], tokens)
    prof = await db.users.find_one({"user_id": guardado["user_id"]}, {"_id": 0})
    # Conectou para usar: já passa a receber pelo Mercado Pago se tudo estiver em reais.
    if prof and (prof.get("moeda") or DEFAULT_MOEDA).upper() == "BRL" and not await _servicos_fora_do_real(prof["user_id"]):
        await db.users.update_one({"user_id": prof["user_id"]}, {"$set": {"recebimento": "mercadopago"}})
    return RedirectResponse(f"{_MP_VOLTA_APP}?mercadopago=ok")


@api_router.delete("/me/mercadopago")
async def mercadopago_desconectar(authorization: Optional[str] = Header(default=None)):
    """Apaga os tokens e volta a receber pelo Stripe. Recusa se ainda há reserva aberta no Mercado Pago (sem o token
    não daria para cobrar nem soltar a reserva)."""
    doc = await _current_user(authorization)
    await _require_role(doc, "profissional")
    aberta = await db.agendamentos.find_one({
        "profissional_id": doc["user_id"], "gateway": "mercadopago",
        "hold_status": {"$in": ["autorizado", "cancelando", "aguardando_pix"]},
    })
    if aberta:
        raise HTTPException(409, "Você ainda tem reservas abertas no Mercado Pago. Confirme ou cancele antes de desconectar.")
    await db.users.update_one({"user_id": doc["user_id"]}, {
        "$set": {"recebimento": "stripe"},
        "$unset": {"mp_access_token_cifrado": "", "mp_refresh_token_cifrado": "", "mp_token_expira_em": "", "mp_public_key": "", "mp_user_id": ""},
    })
    return {"ok": True}


def _identificacao(payload: AgendamentoPublicoMPCartaoRequest) -> Optional[dict]:
    numero = "".join(c for c in (payload.identificacao_numero or "") if c.isdigit())
    return {"type": (payload.identificacao_tipo or "CPF").upper(), "number": numero} if numero else None


@api_router.post("/public/agendamentos/mercadopago/cartao", response_model=Agendamento)
@limiter.limit("10/minute")
async def criar_agendamento_publico_mp_cartao(request: Request, background_tasks: BackgroundTasks, payload: AgendamentoPublicoMPCartaoRequest):
    contato = _contato_do_aviso(request, payload.email)
    """Reserva no cartão pelo Mercado Pago (link público). Mesmas regras do Stripe — agenda, conflito, prazo de
    confirmação —, mas a reserva vale 5 dias e só aceita bandeiras em que dá para cobrar só a taxa de falta."""
    if not MERCADOPAGO_ATIVO or mp_gateway is None:
        raise HTTPException(503, "O Mercado Pago ainda não está disponível no ShowUp.")
    if payload.payment_method_id.lower() not in MARCAS_CAPTURA_PARCIAL:
        # Com Elo, Hipercard etc. o Mercado Pago não deixa cobrar só a taxa de falta: recusa ANTES de travar o limite do cliente.
        raise HTTPException(422, "Para reservar com cartão use Visa, Mastercard, American Express ou Cabal. Ou pague com Pix.")
    cliente = await _find_or_create_cliente_por_telefone(payload.nome, payload.telefone)
    svc, prof, horario_fim = await _valida_servico_e_conflito(payload.servico_id, payload.horario_inicio)
    if svc["profissional_id"] != payload.profissional_id:
        raise HTTPException(400, "servico_id não pertence ao profissional_id informado")
    if not _recebe_pelo_mp(prof):
        raise HTTPException(409, "Este profissional não recebe pelo Mercado Pago. Recarregue a página e tente de novo.")
    horario = _aware(payload.horario_inicio)
    fee_bps = _fee_bps_for(prof, svc["moeda"])
    agendamento_id = f"agd_{uuid.uuid4().hex[:12]}"
    try:
        token = await _mp_access_token(prof)
        hold = await mp_gateway.reservar_cartao(
            token, valor_centavos=svc["valor_centavos"], taxa_centavos_=taxa_centavos(svc["valor_centavos"], fee_bps),
            token_cartao=payload.token, payment_method_id=payload.payment_method_id.lower(), issuer_id=payload.issuer_id,
            email=payload.email, identificacao=_identificacao(payload), descricao=f"ShowUp: {svc['nome']}",
            referencia=agendamento_id, idempotency_key=f"hold_{agendamento_id}",
        )
    except CardDeclinedError:
        raise HTTPException(402, "Cartão recusado pela operadora. Tente outro cartão.")
    except GatewayUnavailableError:
        raise HTTPException(503, "Gateway de pagamento indisponível no momento. Tente novamente em instantes.")
    except PaymentError:
        logging.exception("reserva no Mercado Pago falhou")
        raise HTTPException(402, "Falha ao autorizar cartão")

    janela_conf = await _janela_de_confirmacao_ou_desfazer(hold, horario_fim, agendamento_id, "mercadopago", prof["user_id"])
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
        "janela_confirmacao_expira_em": janela_conf,
        "valor_capturado_centavos": 0,
        "gateway": "mercadopago",
        "fee_bps": fee_bps,
        "origem": "link_publico",
        **contato,
        "criado_em": _now(),
        "push_pergunta_enviada_em": None,
        "push_urgencia_enviada_em": None,
    }
    try:
        await db.agendamentos.insert_one(dict(doc))
    except DuplicateKeyError:
        try:
            await _desfazer_reserva("mercadopago", prof["user_id"], hold["payment_intent_id"], f"void_race_{agendamento_id}")
        except PaymentError:
            logging.exception("Falha ao desfazer reserva órfã de corrida p/ %s", agendamento_id)
        raise HTTPException(409, "Esse horário acabou de ser reservado por outro cliente. Escolha outro.")
    await db.transacoes.insert_one({
        "transacao_id": f"tx_{uuid.uuid4().hex[:12]}",
        "agendamento_id": agendamento_id, "tipo": "authorization",
        "valor_centavos": doc["valor_total_centavos"], "moeda": doc["moeda"],
        "gateway_object_id": doc["payment_intent_id"], "status": "requires_capture", "gateway": "mercadopago",
        "criado_em": _now(),
    })
    background_tasks.add_task(_avisar_reserva_confirmada, db, agendamento_id)
    return await _hydrate(doc)


async def _pix_mercadopago(payload: AgendamentoPublicoCreate, cliente: dict, svc: dict, prof: dict,
                           horario: datetime, horario_fim: datetime, contato: dict) -> AgendamentoPublicoPixResponse:
    if not MERCADOPAGO_ATIVO or mp_gateway is None:
        raise HTTPException(503, "O Mercado Pago ainda não está disponível no ShowUp.")
    fee_bps = _fee_bps_for(prof, svc["moeda"])
    agendamento_id = f"agd_{uuid.uuid4().hex[:12]}"
    expira_pix = _now() + timedelta(minutes=PIX_MINUTOS_MERCADOPAGO)
    try:
        token = await _mp_access_token(prof)
        pix = await mp_gateway.criar_pix(
            token, valor_centavos=svc["valor_centavos"], taxa_centavos_=taxa_centavos(svc["valor_centavos"], fee_bps),
            email=payload.email, descricao=f"ShowUp: {svc['nome']}", expira_em=expira_pix,
            referencia=agendamento_id, idempotency_key=f"pix_{agendamento_id}",
        )
    except PaymentError:
        logging.exception("Pix no Mercado Pago falhou")
        raise HTTPException(502, "Falha ao gerar cobrança Pix junto ao gateway")
    doc = {
        "agendamento_id": agendamento_id,
        "profissional_id": svc["profissional_id"],
        "cliente_id": cliente["user_id"],
        "servico_id": svc["servico_id"],
        "horario_inicio": horario, "horario_fim": horario_fim,
        "valor_total_centavos": svc["valor_centavos"],
        "valor_no_show_centavos": 0,
        "moeda": svc["moeda"],
        "status_agendamento": "agendado", "status_confirmacao": "pendente",
        "payment_intent_id": pix["payment_intent_id"],
        "hold_status": "aguardando_pix",
        # O horário fica preso um pouco além do prazo do Pix: antes de soltar, o job consulta o Mercado Pago.
        "hold_expira_em": expira_pix + timedelta(minutes=5),
        "janela_confirmacao_expira_em": horario_fim + timedelta(hours=24),
        "valor_capturado_centavos": 0,
        "gateway": "mercadopago",
        "fee_bps": fee_bps,
        "metodo_pagamento": "pix",
        "origem": "link_publico",
        **contato,
        "criado_em": _now(),
        "push_pergunta_enviada_em": None,
        "push_urgencia_enviada_em": None,
    }
    try:
        await db.agendamentos.insert_one(dict(doc))
    except DuplicateKeyError:
        try:
            await _desfazer_reserva("mercadopago", prof["user_id"], pix["payment_intent_id"], f"void_race_{agendamento_id}")
        except PaymentError:
            logging.exception("Falha ao cancelar Pix órfão de corrida p/ %s", agendamento_id)
        raise HTTPException(409, "Esse horário acabou de ser reservado por outro cliente. Escolha outro.")
    return AgendamentoPublicoPixResponse(
        agendamento_id=agendamento_id,
        qr_code_data=pix["qr_code_data"],
        qr_code_base64=pix.get("qr_code_base64"),
        hosted_instructions_url=pix.get("hosted_instructions_url"),
        expira_em=expira_pix,
    )


async def _sincronizar_pagamento_mp(ag: dict) -> Optional[dict]:
    """Pergunta ao Mercado Pago como está o pagamento do agendamento e aplica no banco. Fonte da verdade é a consulta
    (com o token do profissional), nunca o corpo do aviso: um aviso forjado não consegue marcar nada como pago."""
    prof = await db.users.find_one({"user_id": ag["profissional_id"]}, {"_id": 0})
    if not prof:
        return None
    try:
        token = await _mp_access_token(prof)
        p = await mp_gateway.consultar(token, ag["payment_intent_id"])
    except PaymentError:
        logging.warning("Mercado Pago: não consegui consultar o pagamento %s", ag["payment_intent_id"])
        return None
    if p.get("referencia") and p["referencia"] != ag["agendamento_id"]:
        logging.error("Mercado Pago: pagamento %s é de outro agendamento (%s)", ag["payment_intent_id"], p["referencia"])
        return None
    status = p.get("status")
    filtro = {"agendamento_id": ag["agendamento_id"]}
    if status == "approved" and ag.get("hold_status") == "aguardando_pix":
        res = await db.agendamentos.update_one({**filtro, "hold_status": "aguardando_pix"},
                                               {"$set": {"hold_status": "pago_integral", "valor_capturado_centavos": p["valor_centavos"]}})
        if res.modified_count:
            await _avisar_reserva_confirmada(db, ag["agendamento_id"])
    elif status == "approved" and ag.get("hold_status") == "expirado" and ag.get("metodo_pagamento") == "pix":
        # Pago depois de o horário ser solto (aviso muito atrasado): não some com o dinheiro do cliente — marca para revisão.
        await db.agendamentos.update_one(filtro, {"$set": {"pago_apos_expirar": True}})
        logging.error("Pix %s pago depois de expirar: devolver ao cliente pelo painel do Mercado Pago", ag["payment_intent_id"])
    elif status in ("cancelled", "rejected", "expired") and ag.get("hold_status") == "aguardando_pix":
        await db.agendamentos.update_one({**filtro, "hold_status": "aguardando_pix"},
                                         {"$set": {"hold_status": "expirado", "status_agendamento": "cancelado", "status_confirmacao": "sem_resposta"}})
    elif status in ("cancelled", "rejected") and ag.get("hold_status") == "autorizado":
        await db.agendamentos.update_one({**filtro, "hold_status": "autorizado", "status_confirmacao": "pendente"},
                                         {"$set": {"hold_status": "expirado", "status_confirmacao": "sem_resposta"}})
    elif status == "charged_back":
        await db.agendamentos.update_one(filtro, {"$set": {"em_disputa": True}})
    return await db.agendamentos.find_one(filtro, {"_id": 0})


async def _capturar_mercadopago(ag: dict, resultado: str) -> tuple[dict, dict, str]:
    prof = await db.users.find_one({"user_id": ag["profissional_id"]}, {"_id": 0})
    if not prof:
        raise GatewayUnavailableError("profissional não encontrado")
    token = await _mp_access_token(prof)
    aid = ag["agendamento_id"]
    if resultado == "compareceu":
        cap = await mp_gateway.capturar(token, ag["payment_intent_id"], None, None, idempotency_key=f"capture_{aid}_total")
        return cap, {"status_confirmacao": "compareceu", "hold_status": "capturado_total",
                     "valor_capturado_centavos": cap["amount_received"]}, "capture"
    falta = ag["valor_no_show_centavos"]
    taxa = taxa_centavos(falta, ag.get("fee_bps") or _fee_bps_for(prof))
    cap = await mp_gateway.capturar(token, ag["payment_intent_id"], falta, taxa, idempotency_key=f"capture_{aid}_noshow")
    update = {"status_confirmacao": "nao_compareceu", "hold_status": "capturado_taxa", "valor_capturado_centavos": cap["amount_received"]}
    if cap.get("taxa_gravada_centavos") is not None and cap["taxa_gravada_centavos"] > taxa:
        # O Mercado Pago manteve a taxa do valor total: o profissional ficou com menos do que deveria. Marca para acerto.
        update["taxa_a_devolver_centavos"] = cap["taxa_gravada_centavos"] - taxa
        logging.error("Mercado Pago gravou taxa %s em vez de %s no agendamento %s", cap["taxa_gravada_centavos"], taxa, aid)
    return cap, update, "partial_capture"


async def _renovar_tokens_mp() -> int:
    """Job: renova o token de quem não usa o Mercado Pago há tempo (vale 180 dias) antes de vencer."""
    if not MERCADOPAGO_ATIVO or mp_gateway is None:
        return 0
    limite = _now() + timedelta(days=30)
    n = 0
    async for u in db.users.find({"mp_token_expira_em": {"$lt": limite}, "mp_refresh_token_cifrado": {"$nin": [None, ""]}}, {"_id": 0}):
        try:
            novo = await mp_gateway.renovar(cofre.decifrar(u["mp_refresh_token_cifrado"]))
            await _gravar_tokens_mp(u["user_id"], novo)
            n += 1
        except Exception:
            logging.exception("não consegui renovar o token do Mercado Pago de %s", u["user_id"])
    return n


@api_router.post("/webhooks/mercadopago")
async def webhook_mercadopago(request: Request):
    """Aviso de pagamento do Mercado Pago. Confere a assinatura (x-signature) e, se bater, CONSULTA o pagamento no
    Mercado Pago antes de mudar qualquer coisa. Sem a chave secreta configurada, recusa tudo."""
    if not MERCADOPAGO_WEBHOOK_SECRET:
        logging.error("MERCADOPAGO_WEBHOOK_SECRET ausente — recusando aviso por segurança")
        return JSONResponse({"ok": False}, status_code=500)
    data_id = request.query_params.get("data.id") or request.query_params.get("id")
    try:
        corpo = await request.json()
    except Exception:
        corpo = {}
    if not data_id:
        data_id = str(((corpo or {}).get("data") or {}).get("id") or "")
    if not assinatura_valida(request.headers.get("x-signature", ""), request.headers.get("x-request-id"), data_id,
                             MERCADOPAGO_WEBHOOK_SECRET, agora_s=_now().timestamp()):
        logging.warning("Aviso do Mercado Pago com assinatura inválida — ignorado")
        return JSONResponse({"ok": False}, status_code=400)
    tipo = (corpo or {}).get("type") or request.query_params.get("type") or request.query_params.get("topic")
    if tipo != "payment" or not data_id:
        return {"ok": True}
    ag = await db.agendamentos.find_one({"payment_intent_id": str(data_id), "gateway": "mercadopago"}, {"_id": 0})
    if ag:
        await _sincronizar_pagamento_mp(ag)
    return {"ok": True}


# Limiar de urgência: quando falta menos que isso para o hold expirar, o
# profissional recebe um segundo push de aviso ("última chance"), decidido
# na conversa de produto para reduzir "sem_resposta" sem cobrar errado.
_URGENCIA_ANTES_DE_EXPIRAR = timedelta(hours=2)


async def _push_para_usuario(user_id: str, title: str, body: str, data: dict) -> None:
    await push_para_usuario(db, user_id, title, body, data)


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
        nomes = await dados_do_agendamento(db, ag)   # o registro só tem ids; os nomes vêm das outras coleções
        await _push_para_usuario(
            ag["profissional_id"],
            title="Confirme o atendimento",
            body=f"{nomes['cliente_nome']} tinha horário de {nomes['servico_nome']}. Compareceu?",
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
        nomes = await dados_do_agendamento(db, ag)
        await _push_para_usuario(
            ag["profissional_id"],
            title="Última chance para confirmar",
            body=f"O horário de {nomes['cliente_nome']} vai liberar sem cobrança em breve. Confirme agora.",
            data={"type": "confirmacao_urgente", "agendamento_id": ag["agendamento_id"]},
        )
        enviados_urgencia += 1

    return {"pergunta": enviados_pergunta, "urgencia": enviados_urgencia}


async def _enviar_lembretes_cliente() -> dict:
    """Lembretes ao CLIENTE (24 h e 2 h antes, LEMBRETE_CLIENTE_HORAS): push no app ou e-mail. Ver avisos_cliente.py."""
    return await enviar_lembretes_cliente(db, _now())


async def _enviar_lembretes_proximo() -> dict:
    """Avisa o profissional que o PRÓXIMO atendimento está chegando (LEMBRETE_PROFISSIONAL_MIN antes).

    Cada agendamento é avisado uma única vez (campo push_lembrete_enviado_em, reivindicado de forma atômica).
    Só entram reservas confirmadas e ainda por acontecer: cartão autorizado ou Pix pago, não canceladas.
    Reserva feita DENTRO da janela é só marcada: o aviso de "novo agendamento" acabou de dizer o horário."""
    if LEMBRETE_PROFISSIONAL_MIN <= 0:
        return {"lembretes": 0, "ignorados": 0}
    now = _now()
    antecedencia = timedelta(minutes=LEMBRETE_PROFISSIONAL_MIN)
    cursor = db.agendamentos.find({
        "status_agendamento": "agendado",
        "hold_status": {"$in": ["autorizado", "pago_integral"]},
        "horario_inicio": {"$gt": now, "$lte": now + antecedencia},
        "push_lembrete_enviado_em": None,
    }, {"_id": 0})
    enviados = ignorados = 0
    async for ag in cursor:
        claimed = await db.agendamentos.find_one_and_update(
            {"agendamento_id": ag["agendamento_id"], "push_lembrete_enviado_em": None},
            {"$set": {"push_lembrete_enviado_em": now}},
        )
        if claimed is None:
            continue
        if _aware(ag["criado_em"]) >= _aware(ag["horario_inicio"]) - antecedencia:
            ignorados += 1
            continue
        if await avisar_proximo_atendimento(db, ag, now):
            enviados += 1
    return {"lembretes": enviados, "ignorados": ignorados}


@api_router.post("/internal/jobs/enviar-lembretes", dependencies=[Depends(require_service_token)])
async def job_enviar_lembretes():
    return await _enviar_lembretes_proximo()


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

INDICE_VAGA_UNICA = "uniq_vaga_ativa"
_INDICE_VAGA_ANTIGO = "uniq_slot_ativo"


async def _garantir_indice_vaga_unica() -> None:
    """Índice único parcial: duas reservas ATIVAS nunca no mesmo início de horário do mesmo profissional, nem com
    pedidos simultâneos. A lista vem de STATUS_OCUPAM_HORARIO. O índice antigo (sem o Pix) tinha outro nome: cria o
    novo e só então apaga o antigo, então o banco nunca fica sem proteção. Se o Mongo recusar dois índices na mesma
    chave, apaga o antigo, cria o novo e, se o novo falhar (reservas duplicadas antigas), recria o antigo."""
    chave = [("profissional_id", 1), ("horario_inicio", 1)]

    def criar(nome, status):
        return db.agendamentos.create_index(chave, unique=True, name=nome, partialFilterExpression={"hold_status": {"$in": status}})

    async def apagar_antigo():
        try:
            await db.agendamentos.drop_index(_INDICE_VAGA_ANTIGO)
        except OperationFailure:
            pass        # já não existe

    try:
        await criar(INDICE_VAGA_UNICA, STATUS_OCUPAM_HORARIO)
    except DuplicateKeyError:
        logging.error("índice %s não criado: há reservas ativas duplicadas no mesmo horário. Mantido o antigo; "
                      "resolva as duplicadas e reinicie.", INDICE_VAGA_UNICA)
        return
    except OperationFailure:
        await apagar_antigo()
        try:
            await criar(INDICE_VAGA_UNICA, STATUS_OCUPAM_HORARIO)
        except (DuplicateKeyError, OperationFailure):
            logging.exception("índice %s não criado; recriando o antigo", INDICE_VAGA_UNICA)
            await criar(_INDICE_VAGA_ANTIGO, ["autorizado", "cancelando", "capturado_total", "capturado_taxa"])
        return
    await apagar_antigo()


@asynccontextmanager
async def lifespan(_: FastAPI):
    await db.users.create_index("email", unique=True)
    # esparso: só usuários criados via link público (WhatsApp) têm telefone;
    # evita duplicar o mesmo cliente se ele volta a agendar pelo mesmo número.
    await db.users.create_index("telefone", unique=True, sparse=True)
    await db.users.create_index("user_id", unique=True)
    await db.users.create_index("microsoft_id", unique=True, sparse=True)
    await db.users.create_index("slug", unique=True, sparse=True)
    # expira_em: o Mongo apaga sozinho os códigos, os "state" do OAuth e os bloqueios de login
    await db.email_codes.create_index([("email", 1), ("finalidade", 1)], unique=True)
    await db.email_codes.create_index("expira_em", expireAfterSeconds=0)
    await db.oauth_states.create_index("state", unique=True)
    await db.oauth_states.create_index("expira_em", expireAfterSeconds=0)
    await db.login_attempts.create_index("email", unique=True)
    await db.login_attempts.create_index("expira_em", expireAfterSeconds=0)
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
    await _garantir_indice_vaga_unica()
    await db.agendamentos.create_index([("cliente_id", 1), ("horario_inicio", 1)])
    await db.customer_cards.create_index("user_id", unique=True)
    await db.disponibilidade.create_index([("profissional_id", 1), ("weekday", 1)])
    await db.webhook_events.create_index("event_id", unique=True)
    await db.device_tokens.create_index("user_id", unique=True)
    await db.mp_oauth_states.create_index("state", unique=True)
    await db.mp_oauth_states.create_index("expira_em", expireAfterSeconds=0)
    logger.info("Startup complete (gateway=%s, mercadopago=%s)", GATEWAY_KIND, MERCADOPAGO_ATIVO)

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
    _scheduler.add_job(_atualizar_connect_pendentes, "interval", minutes=10, id="connect_pendentes", max_instances=1)
    _scheduler.add_job(_enviar_lembretes_proximo, "interval", minutes=5, id="lembretes_proximo", max_instances=1)
    _scheduler.add_job(_enviar_lembretes_cliente, "interval", minutes=5, id="lembretes_cliente", max_instances=1)
    if MERCADOPAGO_ATIVO:
        _scheduler.add_job(_renovar_tokens_mp, "interval", hours=12, id="renovar_tokens_mp", max_instances=1)
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
