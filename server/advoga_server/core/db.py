"""Conexão com o PostgreSQL."""

from __future__ import annotations

from collections.abc import Iterator

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

_engine: Engine | None = None
_fabrica: sessionmaker[Session] | None = None


def configurar_banco(url: str) -> Engine:
    global _engine, _fabrica
    if _engine is not None:
        _engine.dispose()
    _engine = create_engine(url, pool_pre_ping=True, pool_size=10, max_overflow=10, future=True)
    _fabrica = sessionmaker(bind=_engine, expire_on_commit=False)
    return _engine


def obter_engine() -> Engine:
    if _engine is None:
        raise RuntimeError("Banco de dados ainda não configurado.")
    return _engine


def obter_sessao() -> Iterator[Session]:
    if _fabrica is None:
        raise RuntimeError("Banco de dados ainda não configurado.")
    sessao = _fabrica()
    try:
        yield sessao
    finally:
        sessao.close()
