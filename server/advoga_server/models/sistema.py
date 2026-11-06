from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import BigInteger, CheckConstraint, DateTime, ForeignKey, String, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base


class IdentidadeServidor(Base):
    """Identifica a base oficial. Usada para impedir duas bases oficiais após migração."""

    __tablename__ = "identidade_servidor"
    __table_args__ = (
        CheckConstraint("id = 1", name="linha_unica"),
        CheckConstraint("status IN ('ativo', 'desativado')", name="status_valido"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, default=1)
    servidor_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False, default=uuid.uuid4
    )
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="ativo")
    criado_em: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    desativado_em: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    observacao: Mapped[str | None] = mapped_column(String(255))


class Configuracao(Base):
    __tablename__ = "configuracoes"

    chave: Mapped[str] = mapped_column(String(80), primary_key=True)
    valor: Mapped[Any] = mapped_column(JSONB, nullable=False)
    atualizado_em: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
    atualizado_por: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("usuarios.id")
    )


class Auditoria(Base):
    """Registro de atividades. O banco só aceita inserções (gatilho na migração)."""

    __tablename__ = "auditoria"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    ocorrido_em: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False, index=True
    )
    usuario_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("usuarios.id"), index=True
    )
    acao: Mapped[str] = mapped_column(String(60), nullable=False, index=True)
    entidade: Mapped[str | None] = mapped_column(String(60))
    entidade_id: Mapped[str | None] = mapped_column(String(64))
    detalhes: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    ip: Mapped[str | None] = mapped_column(String(64))
