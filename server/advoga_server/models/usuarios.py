from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Integer, String, func, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base, ComDatas


class Usuario(ComDatas, Base):
    __tablename__ = "usuarios"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    nome_completo: Mapped[str] = mapped_column(String(150), nullable=False)
    # Nome e cargo exibidos são apenas texto: não concedem permissão alguma.
    nome_exibicao: Mapped[str] = mapped_column(String(80), nullable=False)
    cargo: Mapped[str | None] = mapped_column(String(80))
    nome_usuario: Mapped[str] = mapped_column(String(40), nullable=False, unique=True)
    email: Mapped[str] = mapped_column(String(254), nullable=False)
    senha_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    is_master: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    ativo: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))
    deve_trocar_senha: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    tentativas_falhas: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    bloqueado_ate: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    ultimo_login_em: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    desativado_em: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    permissoes: Mapped[list[PermissaoUsuario]] = relationship(
        back_populates="usuario",
        cascade="all, delete-orphan",
        lazy="selectin",
        foreign_keys="PermissaoUsuario.usuario_id",
    )

    __table_args__ = (
        # Garante no próprio banco que existe no máximo UMA conta Master.
        Index(
            "uq_usuarios_unica_master",
            "is_master",
            unique=True,
            postgresql_where=text("is_master"),
        ),
    )


class PermissaoUsuario(Base):
    __tablename__ = "permissoes_usuario"

    usuario_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("usuarios.id", ondelete="CASCADE"), primary_key=True
    )
    permissao: Mapped[str] = mapped_column(String(40), primary_key=True)
    concedida_em: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    concedida_por: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("usuarios.id")
    )

    usuario: Mapped[Usuario] = relationship(back_populates="permissoes", foreign_keys=[usuario_id])


class Sessao(Base):
    __tablename__ = "sessoes"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    usuario_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("usuarios.id"), nullable=False, index=True
    )
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    criada_em: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    ultimo_uso_em: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    expira_em: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    encerrada_em: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    motivo_encerramento: Mapped[str | None] = mapped_column(String(40))
    ip: Mapped[str | None] = mapped_column(String(64))
    dispositivo: Mapped[str | None] = mapped_column(String(120))

    usuario: Mapped[Usuario] = relationship()
