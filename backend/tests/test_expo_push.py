"""expo_push.push_para_usuario: devolve (e registra) o que aconteceu em cada envio."""
import asyncio
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest

import expo_push


class Col:
    def __init__(self, docs):
        self.docs = docs

    async def find_one(self, q, proj=None):
        return next((dict(d) for d in self.docs if all(d.get(k) == v for k, v in q.items())), None)

    async def delete_one(self, q):
        self.docs[:] = [d for d in self.docs if not all(d.get(k) == v for k, v in q.items())]


class DB:
    def __init__(self, com_token=True):
        self.device_tokens = Col([{"user_id": "u1", "expo_push_token": "ExponentPushToken[abc]"}] if com_token else [])


def enviar(db, monkeypatch, ticket=None, erro=None):
    async def falso(token, title, body, data=None):
        if erro:
            raise erro
        return ticket

    monkeypatch.setattr(expo_push, "send_push", falso)
    return asyncio.run(expo_push.push_para_usuario(db, "u1", "Título", "Corpo", {}))


def test_sem_aparelho_registrado_diz_isso_no_resultado_e_no_log(monkeypatch, caplog):
    caplog.set_level(logging.INFO, logger="expo_push")
    assert enviar(DB(com_token=False), monkeypatch, ticket={"status": "ok"}) == "sem_token"
    assert "não tem aparelho registrado" in caplog.text


def test_envio_ok(monkeypatch, caplog):
    caplog.set_level(logging.INFO, logger="expo_push")
    assert enviar(DB(), monkeypatch, ticket={"status": "ok", "id": "tk1"}) == "enviado"
    assert "enviado a u1 (ticket tk1)" in caplog.text


def test_aparelho_morto_apaga_o_token(monkeypatch):
    db = DB()
    resultado = enviar(db, monkeypatch, ticket={"status": "error", "details": {"error": "DeviceNotRegistered"}})
    assert resultado == "erro:DeviceNotRegistered" and db.device_tokens.docs == []


def test_outros_erros_da_expo_mantem_o_token_e_dizem_qual(monkeypatch):
    db = DB()
    assert enviar(db, monkeypatch, ticket={"status": "error", "details": {"error": "MessageRateExceeded"}}) == "erro:MessageRateExceeded"
    assert enviar(db, monkeypatch, ticket={"status": "error"}) == "erro:desconhecido"
    assert len(db.device_tokens.docs) == 1


def test_falha_de_rede_nunca_levanta(monkeypatch):
    assert enviar(DB(), monkeypatch, erro=RuntimeError("sem rede")) == "falha_rede"
