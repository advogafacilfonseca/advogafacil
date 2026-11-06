"""Cofre de segredos do servidor (tokens da conta de envio de e-mail).

Os segredos ficam no banco CRIPTOGRAFADOS com uma chave que fica só no servidor, na pasta de
configuração (fora do banco). Assim, uma cópia do banco ou uma migração não carrega tokens
utilizáveis: no novo servidor a conta de envio precisa ser conectada de novo.
"""

from __future__ import annotations

import os
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken

from .config import Configuracoes

NOME_ARQUIVO = "segredos.chave"


class SegredoIndisponivel(Exception):
    """A chave deste servidor não abre o segredo (ex.: banco migrado de outro servidor)."""


def _arquivo(cfg: Configuracoes) -> Path:
    return cfg.pasta_config / NOME_ARQUIVO


def _chave(cfg: Configuracoes, criar: bool) -> bytes | None:
    arq = _arquivo(cfg)
    if arq.exists():
        return arq.read_bytes().strip()
    if not criar:
        return None
    cfg.pasta_config.mkdir(parents=True, exist_ok=True)
    chave = Fernet.generate_key()
    fd = os.open(arq, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "wb") as f:
        f.write(chave)
    return chave


def cifrar(cfg: Configuracoes, texto: str) -> str:
    return Fernet(_chave(cfg, criar=True)).encrypt(texto.encode()).decode()


def decifrar(cfg: Configuracoes, cifrado: str) -> str:
    chave = _chave(cfg, criar=False)
    if chave is None:
        raise SegredoIndisponivel("Chave de segredos ausente neste servidor.")
    try:
        return Fernet(chave).decrypt(cifrado.encode()).decode()
    except InvalidToken as exc:
        raise SegredoIndisponivel("O segredo foi gravado por outro servidor.") from exc
