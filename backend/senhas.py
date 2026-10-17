"""Senhas: hash com scrypt (biblioteca padrão — sem dependência nova) e regras mínimas.

Formato guardado: scrypt$<log2 N>$<r>$<p>$<salt base64>$<hash base64>. Os parâmetros ficam no
próprio texto, então dá pra endurecer o custo no futuro sem invalidar as senhas já guardadas.
Custo: N=2^15, r=8, p=3 (≈32 MB e ~100–200 ms por conferência), na faixa que o OWASP recomenda
para scrypt quando não se usa 128 MB. Rode `hash_senha`/`verificar_senha` fora do loop de
eventos (asyncio.to_thread): são lentas DE PROPÓSITO.
"""
import base64
import hashlib
import hmac
import os

_LOG2_N, _R, _P = 15, 8, 3
_MAXMEM = 128 * 1024 * 1024
_TAM_HASH = 32

SENHA_MIN, SENHA_MAX = 8, 128

# Lista curta das senhas mais óbvias (em português e inglês). Não substitui um verificador de
# vazamentos; só barra o que qualquer pessoa tentaria primeiro.
SENHAS_COMUNS = frozenset({
    "12345678", "123456789", "1234567890", "87654321", "11111111", "00000000", "12341234",
    "password", "password1", "passw0rd", "qwertyui", "qwerty123", "abc12345", "iloveyou",
    "senha123", "senha1234", "senhasenha", "mudar123", "brasil123", "brasileiro", "futebol1",
    "corinthians", "flamengo1", "showup123", "showup1234",
})


def validar_senha(senha: str, email: str = "") -> str | None:
    """Mensagem de erro (para mostrar ao usuário) ou None se a senha serve."""
    if not isinstance(senha, str) or len(senha) < SENHA_MIN:
        return f"A senha precisa ter pelo menos {SENHA_MIN} caracteres."
    if len(senha) > SENHA_MAX:
        return f"A senha pode ter no máximo {SENHA_MAX} caracteres."
    baixa = senha.lower()
    if baixa in SENHAS_COMUNS or len(set(baixa)) == 1:
        return "Essa senha é muito fácil de adivinhar. Escolha outra."
    email_baixo = (email or "").strip().lower()
    parte_local = email_baixo.split("@")[0]
    if email_baixo and baixa == email_baixo or (len(parte_local) >= 4 and baixa == parte_local):
        return "A senha não pode ser igual ao seu e-mail."
    return None


def _derivar(senha: str, salt: bytes, log2_n: int, r: int, p: int) -> bytes:
    return hashlib.scrypt(senha.encode("utf-8"), salt=salt, n=2 ** log2_n, r=r, p=p,
                          maxmem=_MAXMEM, dklen=_TAM_HASH)


def hash_senha(senha: str) -> str:
    salt = os.urandom(16)
    derivado = _derivar(senha, salt, _LOG2_N, _R, _P)
    b64 = lambda b: base64.b64encode(b).decode("ascii")  # noqa: E731
    return f"scrypt${_LOG2_N}${_R}${_P}${b64(salt)}${b64(derivado)}"


def verificar_senha(senha: str, armazenado: str) -> bool:
    """True só se a senha confere. Formato inválido ou qualquer erro → False (nunca levanta)."""
    try:
        esquema, log2_n, r, p, salt_b64, hash_b64 = armazenado.split("$")
        if esquema != "scrypt":
            return False
        esperado = base64.b64decode(hash_b64)
        derivado = _derivar(senha, base64.b64decode(salt_b64), int(log2_n), int(r), int(p))
        return hmac.compare_digest(derivado, esperado)
    except Exception:
        return False


_HASH_FALSO: str | None = None


def hash_falso() -> str:
    """Hash descartável pra gastar o mesmo tempo quando o e-mail não existe — assim o login não
    revela, pelo tempo de resposta, quais e-mails têm conta."""
    global _HASH_FALSO
    if _HASH_FALSO is None:
        _HASH_FALSO = hash_senha("senha-descartavel-que-ninguem-usa")
    return _HASH_FALSO
