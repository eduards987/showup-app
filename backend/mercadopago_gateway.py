"""Mercado Pago (Brasil) como segunda forma de o PROFISSIONAL receber, ao lado do Stripe Connect.

Modelo "marketplace" do Mercado Pago: o profissional conecta a conta dele por OAuth e o ShowUp cria cada cobrança com o
access_token DELE. O dinheiro cai direto na conta do profissional e o Mercado Pago repassa ao ShowUp a `application_fee`
(valor em reais, não percentual). A tarifa do Mercado Pago sai do valor do profissional, e não da plataforma como no Stripe:
por isso a taxa do ShowUp é menor para quem recebe aqui (DESCONTO_MERCADOPAGO_BPS em server.py).

Diferenças que o resto do código precisa respeitar (guia: lancamento/MERCADO-PAGO.md):
- a reserva no cartão vale 5 dias (Stripe: 7), então a agenda abre menos dias à frente (HOLD_DIAS);
- a cobrança parcial (taxa de falta) só existe para Visa, Mastercard, Amex e Cabal (MARCAS_CAPTURA_PARCIAL);
- o Pix precisa de pelo menos 30 minutos de validade (PIX_MINUTOS);
- só reais (conta brasileira).

Dinheiro: o resto do sistema usa centavos inteiros. O Mercado Pago recebe e devolve valores DECIMAIS em reais. A conversão
fica só aqui: `c / 100` é a divisão de inteiros corretamente arredondada pelo IEEE e o `repr` do Python devolve o decimal curto
("12.34"), então o JSON sai exato (test_mercadopago.py confere). Na volta, Decimal(str(v)) * 100, nunca float * 100.
"""
from __future__ import annotations

import hashlib
import hmac
import logging
from datetime import datetime, timedelta, timezone
from decimal import ROUND_HALF_UP, Decimal
from typing import Any, Callable, Optional
from urllib.parse import urlencode

import httpx

from payment_errors import CardDeclinedError, GatewayUnavailableError, InvalidPaymentRequestError

log = logging.getLogger("mercadopago_gateway")

API = "https://api.mercadopago.com"
AUTORIZACAO = "https://auth.mercadopago.com/authorization"
HOLD_DIAS = 5                  # o Mercado Pago cancela a reserva não capturada em 5 dias (Brasil)
PIX_MINUTOS = 30               # validade mínima aceita pelo Mercado Pago para um Pix
# Bandeiras em que o Mercado Pago aceita capturar MENOS do que foi reservado (a taxa de falta). Com outra bandeira (Elo,
# Hipercard...) a falta não poderia ser cobrada: a reserva é recusada antes de travar o limite do cliente.
MARCAS_CAPTURA_PARCIAL = frozenset({"visa", "master", "amex", "cabal"})
TIMEOUT_S = 20


def reais(centavos: int) -> float:
    """Centavos inteiros -> número que o Mercado Pago espera (12345 -> 123.45). Só para o JSON enviado."""
    if not isinstance(centavos, int) or isinstance(centavos, bool):
        raise TypeError("valor em centavos precisa ser inteiro")
    return centavos / 100


def centavos(valor: Any) -> int:
    """Número em reais devolvido pelo Mercado Pago -> centavos inteiros, sem passar por conta com float."""
    return int((Decimal(str(valor)) * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def taxa_centavos(valor_centavos: int, fee_bps: int) -> int:
    """Mesma conta do Stripe (server.py / stripe_gateway.py): arredonda para baixo, a favor do profissional."""
    return (valor_centavos * fee_bps) // 10_000


def assinatura_valida(x_signature: str, x_request_id: Optional[str], data_id: Optional[str], segredo: str,
                      agora_s: Optional[float] = None, tolerancia_s: int = 600) -> bool:
    """Confere o cabeçalho x-signature ("ts=...,v1=...") de um aviso do Mercado Pago.

    Manifesto da documentação: "id:{data.id};request-id:{x-request-id};ts:{ts};" (data.id em minúsculas; cada pedaço
    ausente sai do manifesto), HMAC-SHA256 em hexadecimal com a chave secreta dos webhooks. Recusa aviso antigo
    (mais de `tolerancia_s`) para que um aviso capturado não possa ser reenviado depois."""
    if not segredo or not x_signature:
        return False
    partes = {}
    for pedaco in x_signature.split(","):
        chave, _, valor = pedaco.strip().partition("=")
        partes[chave.strip()] = valor.strip()
    ts, v1 = partes.get("ts"), partes.get("v1")
    if not ts or not v1:
        return False
    if agora_s is not None:
        try:
            ts_s = int(ts)
        except ValueError:
            return False
        if ts_s > 10_000_000_000:          # a documentação fala em milissegundos; o exemplo dela está em segundos
            ts_s //= 1000
        if abs(agora_s - ts_s) > tolerancia_s:
            return False
    manifesto = ""
    if data_id:
        manifesto += f"id:{str(data_id).lower()};"
    if x_request_id:
        manifesto += f"request-id:{x_request_id};"
    manifesto += f"ts:{ts};"
    esperado = hmac.new(segredo.encode(), manifesto.encode(), hashlib.sha256).hexdigest()
    return hmac.compare_digest(esperado, v1)


def _agora() -> datetime:
    return datetime.now(timezone.utc)


def _data_mp(dt: datetime) -> str:
    """Formato que o Mercado Pago aceita em date_of_expiration: 2026-10-30T15:20:00.000-03:00 (aqui em UTC, +00:00)."""
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000+00:00")


class MercadoPagoGateway:
    """Chamadas HTTP ao Mercado Pago. `http` permite trocar o cliente nos testes (httpx.MockTransport)."""

    def __init__(self, client_id: str, client_secret: str, redirect_uri: str, notification_url: Optional[str] = None,
                 http: Optional[Callable[[], httpx.AsyncClient]] = None, sandbox: bool = False):
        self.client_id = client_id
        self.client_secret = client_secret
        self.redirect_uri = redirect_uri
        self.notification_url = notification_url
        self.sandbox = sandbox
        self._http = http or (lambda: httpx.AsyncClient(base_url=API, timeout=TIMEOUT_S))

    # ------------------------------------------------------------------ OAuth (o profissional conecta a conta dele)
    def url_autorizacao(self, state: str) -> str:
        return AUTORIZACAO + "?" + urlencode({
            "client_id": self.client_id, "response_type": "code", "platform_id": "mp",
            "state": state, "redirect_uri": self.redirect_uri,
        })

    async def _token(self, corpo: dict) -> dict:
        dados = await self._chamar("POST", "/oauth/token", json={
            "client_id": self.client_id, "client_secret": self.client_secret, **corpo,
        })
        if not dados.get("access_token"):
            raise InvalidPaymentRequestError("o Mercado Pago não devolveu o access_token")
        expira = int(dados.get("expires_in") or 15_552_000)          # 180 dias, segundo a documentação
        return {
            "access_token": dados["access_token"],
            "refresh_token": dados.get("refresh_token"),
            "public_key": dados.get("public_key"),
            "user_id": str(dados.get("user_id") or ""),
            "expira_em": _agora() + timedelta(seconds=expira),
        }

    async def trocar_codigo(self, code: str) -> dict:
        return await self._token({
            "grant_type": "authorization_code", "code": code, "redirect_uri": self.redirect_uri,
            "test_token": "true" if self.sandbox else "false",
        })

    async def renovar(self, refresh_token: str) -> dict:
        return await self._token({"grant_type": "refresh_token", "refresh_token": refresh_token})

    # ------------------------------------------------------------------ cartão: reserva -> captura (total ou taxa de falta) / cancelamento
    async def reservar_cartao(self, access_token: str, *, valor_centavos: int, taxa_centavos_: int, token_cartao: str,
                              payment_method_id: str, issuer_id: Optional[str], email: str,
                              identificacao: Optional[dict], descricao: str, referencia: str,
                              idempotency_key: str) -> dict:
        corpo: dict[str, Any] = {
            "transaction_amount": reais(valor_centavos),
            "application_fee": reais(taxa_centavos_),
            "token": token_cartao,
            "description": descricao[:200],
            "installments": 1,
            "payment_method_id": payment_method_id,
            "capture": False,
            "binary_mode": True,              # aprovado ou recusado: nunca "em análise" com o horário preso
            "external_reference": referencia,
            "statement_descriptor": "SHOWUP",
            "payer": {"email": email},
        }
        if issuer_id:
            corpo["issuer_id"] = str(issuer_id)
        if identificacao and identificacao.get("number"):
            corpo["payer"]["identification"] = {"type": identificacao.get("type") or "CPF", "number": str(identificacao["number"])}
        if self.notification_url:
            corpo["notification_url"] = self.notification_url
        p = await self._chamar("POST", "/v1/payments", token=access_token, json=corpo, idempotency_key=idempotency_key)
        status, detalhe = p.get("status"), p.get("status_detail")
        if status == "rejected":
            raise CardDeclinedError(decline_code=detalhe)
        if status != "authorized":
            # Aprovado direto (capturou sem querer) ou outro estado: nada de deixar dinheiro cobrado sem agendamento.
            log.error("reserva no Mercado Pago voltou em %s/%s (pagamento %s): desfazendo", status, detalhe, p.get("id"))
            if p.get("id"):
                try:
                    await self.cancelar(access_token, str(p["id"]), idempotency_key=f"{idempotency_key}_desfaz",
                                        estornar=status == "approved")
                except Exception:
                    log.exception("não consegui desfazer o pagamento %s", p.get("id"))
            raise InvalidPaymentRequestError(f"reserva não autorizada (status={status}, detalhe={detalhe})")
        return {"payment_intent_id": str(p["id"]), "status": "requires_capture",
                "hold_expira_em": _agora() + timedelta(days=HOLD_DIAS)}

    async def capturar(self, access_token: str, payment_id: str, valor_centavos: Optional[int],
                       taxa_centavos_: Optional[int], idempotency_key: str) -> dict:
        """Captura total (valor None) ou parcial (taxa de falta). Na parcial manda também a taxa do ShowUp proporcional ao
        que foi de fato cobrado e depois CONFERE o que o Mercado Pago gravou: a documentação não diz se ele recalcula."""
        corpo: dict[str, Any] = {"capture": True}
        if valor_centavos is not None:
            corpo["transaction_amount"] = reais(valor_centavos)
            if taxa_centavos_ is not None:
                corpo["application_fee"] = reais(taxa_centavos_)
        p = await self._chamar("PUT", f"/v1/payments/{payment_id}", token=access_token, json=corpo, idempotency_key=idempotency_key)
        if p.get("status") != "approved":
            raise InvalidPaymentRequestError(f"captura não aprovada (status={p.get('status')}, detalhe={p.get('status_detail')})")
        recebido = centavos(p.get("transaction_amount") or 0)
        taxa_gravada = None
        for f in p.get("fee_details") or []:
            if f.get("type") == "application_fee":
                taxa_gravada = centavos(f.get("amount") or 0)
        return {"payment_intent_id": str(p.get("id") or payment_id), "status": "succeeded",
                "amount_received": recebido, "taxa_gravada_centavos": taxa_gravada}

    async def cancelar(self, access_token: str, payment_id: str, idempotency_key: str, estornar: bool = False) -> dict:
        if estornar:
            await self._chamar("POST", f"/v1/payments/{payment_id}/refunds", token=access_token, json={}, idempotency_key=idempotency_key)
            return {"payment_intent_id": payment_id, "status": "refunded"}
        try:
            p = await self._chamar("PUT", f"/v1/payments/{payment_id}", token=access_token, json={"status": "cancelled"},
                                   idempotency_key=idempotency_key)
        except InvalidPaymentRequestError as e:
            # Já cancelado / já expirado no Mercado Pago: estado final legítimo, igual ao void do Stripe.
            log.warning("cancelar %s: o Mercado Pago recusou (%s)", payment_id, e)
            return {"payment_intent_id": payment_id, "status": "unknown"}
        return {"payment_intent_id": payment_id, "status": p.get("status")}

    # ------------------------------------------------------------------ Pix
    async def criar_pix(self, access_token: str, *, valor_centavos: int, taxa_centavos_: int, email: str, descricao: str,
                        expira_em: datetime, referencia: str, idempotency_key: str) -> dict:
        corpo: dict[str, Any] = {
            "transaction_amount": reais(valor_centavos),
            "application_fee": reais(taxa_centavos_),
            "description": descricao[:200],
            "payment_method_id": "pix",
            "date_of_expiration": _data_mp(expira_em),
            "external_reference": referencia,
            "payer": {"email": email},
        }
        if self.notification_url:
            corpo["notification_url"] = self.notification_url
        p = await self._chamar("POST", "/v1/payments", token=access_token, json=corpo, idempotency_key=idempotency_key)
        dados = ((p.get("point_of_interaction") or {}).get("transaction_data")) or {}
        if not dados.get("qr_code"):
            raise InvalidPaymentRequestError(f"o Mercado Pago não devolveu o código Pix (status={p.get('status')})")
        return {"payment_intent_id": str(p["id"]), "qr_code_data": dados["qr_code"],
                "qr_code_base64": dados.get("qr_code_base64"), "hosted_instructions_url": dados.get("ticket_url")}

    async def consultar(self, access_token: str, payment_id: str) -> dict:
        p = await self._chamar("GET", f"/v1/payments/{payment_id}", token=access_token)
        return {"status": p.get("status"), "status_detail": p.get("status_detail"),
                "valor_centavos": centavos(p.get("transaction_amount") or 0),
                "referencia": p.get("external_reference"), "metodo": p.get("payment_method_id")}

    # ------------------------------------------------------------------ HTTP
    async def _chamar(self, metodo: str, caminho: str, token: Optional[str] = None, json: Optional[dict] = None,
                      idempotency_key: Optional[str] = None) -> dict:
        cab = {"Content-Type": "application/json"}
        if token:
            cab["Authorization"] = f"Bearer {token}"
        if idempotency_key:
            cab["X-Idempotency-Key"] = idempotency_key        # obrigatório no POST de pagamento; mesmo valor = mesmo pagamento
        try:
            async with self._http() as cliente:
                r = await cliente.request(metodo, caminho, headers=cab, json=json)
        except httpx.HTTPError as e:
            raise GatewayUnavailableError(f"Mercado Pago fora do ar: {e}") from e
        if r.status_code in (429,) or r.status_code >= 500:
            raise GatewayUnavailableError(f"Mercado Pago respondeu {r.status_code}")
        try:
            dados = r.json()
        except ValueError:
            dados = {}
        if r.status_code >= 400:
            # A mensagem do Mercado Pago vai para o log (diagnóstico), nunca o token.
            log.warning("Mercado Pago %s %s -> %s: %s", metodo, caminho.split("?")[0], r.status_code,
                        (dados or {}).get("message") or r.text[:300])
            raise InvalidPaymentRequestError(f"Mercado Pago recusou ({r.status_code}): {(dados or {}).get('message') or ''}")
        return dados if isinstance(dados, dict) else {}
