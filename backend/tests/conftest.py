"""Carregado automaticamente pelo pytest antes de qualquer teste (convenção
padrão do pytest para conftest.py — não precisa importar isso em lugar
nenhum).

Sem isso, os arquivos de teste liam MONGO_URL/DB_NAME/etc via os.environ
puro, mas nada aqui carregava o .env pra dentro do processo do pytest — só
o server.py fazia isso por conta própria (e como o servidor roda num
processo separado do uvicorn, o pytest nunca via essas variáveis). Isso
fazia os testes caírem silenciosamente no default `mongodb://localhost:27017
/test_database` em vez do Atlas real configurado no .env, mesmo com o
servidor já rodando corretamente contra o Atlas.
"""
import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

# EXPO_PUBLIC_BACKEND_URL é obrigatória em test_auth_endpoints.py (sem
# default) — se quem estiver rodando não passou na linha de comando nem
# tem no .env, cai num default sensato em vez de um KeyError confuso.
os.environ.setdefault("EXPO_PUBLIC_BACKEND_URL", "http://127.0.0.1:8001")


def attach_test_card(base_url: str, headers: dict):
    """Substitui o antigo `POST /api/me/card` (removido no Módulo 9). O
    fluxo real agora exige um Payment Sheet no app, então aqui simulamos
    exatamente o que ele faria: pega o SetupIntent, confirma com o cartão
    de teste oficial do Stripe (pm_card_visa) e finaliza no backend.
    Retorna um objeto com .status_code/.json()/.text como um requests.Response
    normal, pra ser um substituto direto dos antigos call sites."""
    import requests

    r = requests.post(f"{base_url}/api/me/card/setup-intent", headers=headers)
    if r.status_code != 200:
        return r  # deixa o teste original decidir o que fazer com o erro (ex: 403 esperado)

    setup = r.json()
    setup_intent_id = setup["setup_intent_client_secret"].split("_secret_")[0]

    if not setup_intent_id.startswith("seti_mock_"):
        # Gateway Stripe real: o SetupIntent só fica "succeeded" depois de
        # confirmado com um payment_method de verdade -- pm_card_visa é o
        # cartão de teste oficial do Stripe pra isso, exatamente o que o
        # antigo attach_test_card() usava internamente.
        import stripe

        stripe.api_key = os.environ.get("STRIPE_API_KEY", "")
        stripe.SetupIntent.confirm(setup_intent_id, payment_method="pm_card_visa")
    # MockGateway já marca o SetupIntent como succeeded na criação -- nada a
    # confirmar nesse caso.

    return requests.post(
        f"{base_url}/api/me/card/confirm",
        headers=headers,
        json={"setup_intent_id": setup_intent_id},
    )
