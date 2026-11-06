from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import BigInteger, CheckConstraint, DateTime, ForeignKey, Index, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base


class ExecucaoBackup(Base):
    """Cada backup (ou teste de restauração) com data, resultado e detalhes. Não é apagado."""

    __tablename__ = "backups_execucoes"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tipo: Mapped[str] = mapped_column(String(20), nullable=False)
    origem: Mapped[str] = mapped_column(String(15), nullable=False)  # automatico | manual
    situacao: Mapped[str] = mapped_column(String(15), nullable=False)
    iniciado_em: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    concluido_em: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    versao: Mapped[str | None] = mapped_column(String(80))
    destino: Mapped[str | None] = mapped_column(String(400))
    tamanho_bytes: Mapped[int | None] = mapped_column(BigInteger)
    arquivos_novos: Mapped[int | None] = mapped_column(Integer)
    arquivos_total: Mapped[int | None] = mapped_column(Integer)
    copia_secundaria: Mapped[str | None] = mapped_column(String(500))
    mensagem: Mapped[str | None] = mapped_column(Text)
    detalhes: Mapped[Any | None] = mapped_column(JSONB)
    iniciado_por: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("usuarios.id"))

    __table_args__ = (
        CheckConstraint("tipo IN ('rapido', 'completo', 'teste_restauracao')", name="tipo_valido"),
        CheckConstraint("situacao IN ('em_andamento', 'sucesso', 'falhou')", name="situacao_valida"),
        Index("ix_backups_execucoes_inicio", "iniciado_em"),
    )
