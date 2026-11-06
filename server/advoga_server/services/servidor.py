"""Identidade do servidor e código de instalação."""

from __future__ import annotations

import threading
import time

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..core.config import Configuracoes
from ..core.seguranca import gerar_codigo_instalacao, hash_token
from ..models import Configuracao, IdentidadeServidor, Usuario

CHAVE_CODIGO = "setup.codigo_instalacao_hash"


def obter_identidade(db: Session) -> IdentidadeServidor:
    ident = db.get(IdentidadeServidor, 1)
    if ident is None:
        ident = IdentidadeServidor(id=1, status="ativo")
        db.add(ident)
        db.commit()
        db.refresh(ident)
    return ident


def sistema_configurado(db: Session) -> bool:
    return db.scalar(select(Usuario.id).where(Usuario.is_master).limit(1)) is not None


def preparar_codigo_instalacao(db: Session, cfg: Configuracoes) -> str | None:
    """Gera o código de uso único exigido para criar a conta Master.

    O código é gravado apenas em um arquivo local do computador servidor e, no banco,
    somente o seu hash. Depois que a Master é criada, o código deixa de existir.
    Retorna o código gerado, ou None se o sistema já estiver configurado.
    """
    if sistema_configurado(db):
        remover_codigo_instalacao(db, cfg)
        return None
    existente = db.get(Configuracao, CHAVE_CODIGO)
    if existente is not None and cfg.arquivo_codigo_instalacao.exists():
        return cfg.arquivo_codigo_instalacao.read_text(encoding="utf-8").strip().splitlines()[-1]
    codigo = gerar_codigo_instalacao()
    if existente is None:
        db.add(Configuracao(chave=CHAVE_CODIGO, valor=hash_token(codigo)))
    else:
        existente.valor = hash_token(codigo)
    db.commit()
    cfg.pasta_config.mkdir(parents=True, exist_ok=True)
    cfg.arquivo_codigo_instalacao.write_text(
        "Código de instalação do Advoga Fácil (uso único, necessário para criar a conta Master):\n"
        f"{codigo}\n",
        encoding="utf-8",
    )
    return codigo


def remover_codigo_instalacao(db: Session, cfg: Configuracoes) -> None:
    existente = db.get(Configuracao, CHAVE_CODIGO)
    if existente is not None:
        db.delete(existente)
        db.commit()
    if cfg.arquivo_codigo_instalacao.exists():
        cfg.arquivo_codigo_instalacao.unlink()


# ------------------------------------------------- situação do servidor (ativo / em migração / desativado)
_cache = {"status": None, "momento": 0.0}
_cache_trava = threading.Lock()
VALIDADE_CACHE = 3.0


def definir_status_cache(status: str | None) -> None:
    with _cache_trava:
        _cache["status"] = status
        _cache["momento"] = time.monotonic() if status else 0.0


def limpar_cache_status() -> None:
    definir_status_cache(None)


def status_atual() -> str:
    """Situação deste servidor, consultada no banco a cada poucos segundos (usada em toda requisição
    e pelos serviços em segundo plano)."""
    from ..core.db import obter_sessao

    with _cache_trava:
        if _cache["status"] and time.monotonic() - _cache["momento"] < VALIDADE_CACHE:
            return _cache["status"]
        anterior = _cache["status"]
    gerador = obter_sessao()
    try:
        db = next(gerador)
        st = db.scalar(select(IdentidadeServidor.status).where(IdentidadeServidor.id == 1)) or "ativo"
    except Exception:  # noqa: BLE001 - banco indisponível (ou em importação): mantém o último valor
        return anterior or "ativo"
    finally:
        gerador.close()
    definir_status_cache(st)
    return st
