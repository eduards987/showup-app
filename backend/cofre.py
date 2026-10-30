"""Cifra os tokens do Mercado Pago dos profissionais antes de gravar no banco.

O access_token do profissional permite cobrar e estornar EM NOME DELE. Se o banco vazar, um token em texto puro vira
dinheiro na mão de outra pessoa. Por isso ele é gravado cifrado (Fernet: AES + HMAC) com a chave MERCADOPAGO_TOKEN_KEY,
que fica só no Render. Gerar a chave: py -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
Trocar a chave invalida os tokens gravados: cada profissional precisa conectar o Mercado Pago de novo.
"""
from __future__ import annotations

import os
from typing import Optional

from cryptography.fernet import Fernet, InvalidToken


class CofreIndisponivel(RuntimeError):
    pass


def _fernet(chave: Optional[str] = None) -> Fernet:
    chave = chave if chave is not None else os.environ.get("MERCADOPAGO_TOKEN_KEY", "")
    if not chave:
        raise CofreIndisponivel("MERCADOPAGO_TOKEN_KEY não configurada")
    try:
        return Fernet(chave.encode() if isinstance(chave, str) else chave)
    except (ValueError, TypeError) as e:
        raise CofreIndisponivel("MERCADOPAGO_TOKEN_KEY inválida (gere com Fernet.generate_key())") from e


def cofre_configurado(chave: Optional[str] = None) -> bool:
    try:
        _fernet(chave)
        return True
    except CofreIndisponivel:
        return False


def cifrar(texto: str, chave: Optional[str] = None) -> str:
    return _fernet(chave).encrypt(texto.encode()).decode()


def decifrar(cifrado: str, chave: Optional[str] = None) -> str:
    try:
        return _fernet(chave).decrypt(cifrado.encode()).decode()
    except InvalidToken as e:
        raise CofreIndisponivel("token gravado com outra chave: o profissional precisa conectar o Mercado Pago de novo") from e
