"""Registro de atividades (auditoria)."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy.orm import Session

from ..models import Auditoria


def registrar(
    db: Session,
    acao: str,
    *,
    usuario_id: uuid.UUID | None = None,
    entidade: str | None = None,
    entidade_id: str | uuid.UUID | None = None,
    detalhes: dict[str, Any] | None = None,
    ip: str | None = None,
) -> None:
    """Adiciona um registro à transação corrente (gravado junto com a operação)."""
    db.add(
        Auditoria(
            acao=acao,
            usuario_id=usuario_id,
            entidade=entidade,
            entidade_id=str(entidade_id) if entidade_id is not None else None,
            detalhes=detalhes,
            ip=ip,
        )
    )
