"""Identidade do servidor e código de instalação."""

from __future__ import annotations

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
