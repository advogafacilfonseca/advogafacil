from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, Index, Integer, String, Text, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, ComDatas


class Compromisso(ComDatas, Base):
    """Compromisso da agenda (audiência, reunião, ligação, prazo, tarefa...). Nunca é apagado:
    é concluído ou cancelado, com histórico na auditoria."""

    __tablename__ = "compromissos"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    titulo: Mapped[str] = mapped_column(String(300), nullable=False)
    tipo: Mapped[str] = mapped_column(String(30), nullable=False)
    cliente_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("clientes.id"))
    processo_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("processos.id"))
    responsavel_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("usuarios.id"))
    inicio: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    dia_inteiro: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    duracao_minutos: Mapped[int | None] = mapped_column(Integer)
    local: Mapped[str | None] = mapped_column(String(300))
    prioridade: Mapped[str] = mapped_column(String(10), nullable=False, server_default=text("'normal'"))
    observacoes: Mapped[str | None] = mapped_column(Text)
    situacao: Mapped[str] = mapped_column(String(15), nullable=False, server_default=text("'agendado'"))
    do_processo: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    reagendamentos: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    concluido_em: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    concluido_por: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("usuarios.id"))
    observacao_conclusao: Mapped[str | None] = mapped_column(Text)
    cancelado_em: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cancelado_por: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("usuarios.id"))
    motivo_cancelamento: Mapped[str | None] = mapped_column(String(500))
    criado_por: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("usuarios.id"))
    versao: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("1"))

    __mapper_args__ = {"version_id_col": versao}
    __table_args__ = (
        CheckConstraint("situacao IN ('agendado', 'concluido', 'cancelado')", name="situacao_valida"),
        CheckConstraint("prioridade IN ('baixa', 'normal', 'alta', 'urgente')", name="prioridade_valida"),
        CheckConstraint("tipo IN ('audiencia', 'reuniao', 'ligacao', 'retorno', 'consulta', 'diligencia', "
                        "'entrega_documentos', 'prazo', 'tarefa', 'outro')", name="tipo_valido"),
        Index("ix_compromissos_inicio", "inicio"),
        Index("ix_compromissos_responsavel", "responsavel_id"),
        Index("ix_compromissos_cliente", "cliente_id"),
        # Cada processo tem no máximo um compromisso ativo espelhando sua "próxima audiência ou prazo".
        Index("uq_compromissos_do_processo", "processo_id", unique=True,
              postgresql_where=text("do_processo AND situacao = 'agendado'")),
    )
