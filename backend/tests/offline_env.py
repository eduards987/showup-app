"""Variáveis mínimas pra importar o `server` nos testes OFFLINE.

Valores FALSOS de propósito: `setdefault` só preenche o que ainda não existe, e como
isso roda antes do `import server` (que lê o .env sem sobrescrever o ambiente), os
testes nunca enxergam credenciais reais — nem as do seu .env.
"""
import os

for chave, valor in {
    "TESTING": "1",                                   # desliga o rate limit
    "MONGO_URL": "mongodb://localhost:27017",         # o cliente é criado no import; nunca é usado (db é falso)
    "DB_NAME": "teste_offline",
    "INTERNAL_SERVICE_TOKEN": "token-de-teste",
    "GOOGLE_WEB_CLIENT_ID": "teste.apps.googleusercontent.com",
    "GOOGLE_CLIENT_SECRET": "segredo-de-teste",
    "GOOGLE_OAUTH_REDIRECT_URI": "http://localhost/api/auth/google/callback",
}.items():
    os.environ.setdefault(chave, valor)
