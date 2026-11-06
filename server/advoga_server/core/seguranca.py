"""Senhas (Argon2id) e tokens de sessão."""

from __future__ import annotations

import hashlib
import hmac
import secrets

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

_hasher = PasswordHasher()  # Argon2id com parâmetros recomendados pela biblioteca

# Hash fixo usado para gastar o mesmo tempo quando o usuário não existe,
# evitando revelar quais nomes de usuário são válidos.
_HASH_FICTICIO = _hasher.hash("senha-inexistente-para-tempo-constante-0")


def gerar_hash_senha(senha: str) -> str:
    return _hasher.hash(senha)


def verificar_senha(hash_salvo: str | None, senha: str) -> bool:
    try:
        return _hasher.verify(hash_salvo or _HASH_FICTICIO, senha) and hash_salvo is not None
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False


def precisa_rehash(hash_salvo: str) -> bool:
    return _hasher.check_needs_rehash(hash_salvo)


def gerar_token() -> str:
    return secrets.token_urlsafe(32)


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def gerar_codigo_instalacao() -> str:
    # 12 caracteres em 3 blocos, sem letras ambíguas.
    alfabeto = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
    bruto = "".join(secrets.choice(alfabeto) for _ in range(12))
    return f"{bruto[:4]}-{bruto[4:8]}-{bruto[8:]}"


def comparar_seguro(a: str, b: str) -> bool:
    return hmac.compare_digest(a.encode("utf-8"), b.encode("utf-8"))
