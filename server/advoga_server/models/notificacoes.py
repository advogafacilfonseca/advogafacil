from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, Integer, String, Text, func, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base


class DestinatarioNotificacao(Base):
    """Quem recebe cada categoria de aviso (escolhido pela Master)."""

    __tablename__ = "destinatarios_notificacao"

    categoria: Mapped[str] = mapped_column(String(40), primary_key=True)
    usuario_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("usuarios.id"), primary_key=True)


class Notificacao(Base):
    """Aviso gerado pelo serviço do servidor para um usuário, com o resultado do envio por e-mail.

    A chave impede avisos duplicados: o mesmo aviso, para o mesmo usuário, só existe uma vez.
    """

    __tablename__ = "notificacoes"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    chave: Mapped[str] = mapped_column(String(200), nullable=False, unique=True)
    categoria: Mapped[str] = mapped_column(String(40), nullable=False)
    usuario_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("usuarios.id"), nullable=False)
    titulo: Mapped[str] = mapped_column(String(200), nullable=False)
    mensagem: Mapped[str] = mapped_column(Text, nullable=False)
    entidade: Mapped[str | None] = mapped_column(String(40))
    entidade_id: Mapped[str | None] = mapped_column(String(64))
    criada_em: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    lida_em: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    email_situacao: Mapped[str] = mapped_column(String(20), nullable=False, server_default=text("'pendente'"))
    email_tentativas: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    email_erro: Mapped[str | None] = mapped_column(String(500))
    email_enviado_em: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    proxima_tentativa_em: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    email_destino: Mapped[str | None] = mapped_column(String(254))

    __table_args__ = (
        CheckConstraint("email_situacao IN ('pendente', 'enviado', 'falhou', 'rejeitado', 'nao_configurado', "
                        "'desativado', 'sem_email', 'cancelado')", name="situacao_email_valida"),
        Index("ix_notificacoes_usuario", "usuario_id", "criada_em"),
        Index("ix_notificacoes_pendentes", "proxima_tentativa_em", postgresql_where=text("email_situacao = 'pendente'")),
    )
