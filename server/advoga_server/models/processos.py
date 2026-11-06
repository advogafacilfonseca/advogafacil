from __future__ import annotations

import uuid
from datetime import date, datetime

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, ComDatas


class Processo(ComDatas, Base):
    """Processo judicial vinculado a um cliente (pelo id). Nunca é apagado: é arquivado/encerrado."""

    __tablename__ = "processos"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    numero_cnj: Mapped[str | None] = mapped_column(String(20))
    cliente_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("clientes.id"), nullable=False)
    tipo_acao: Mapped[str | None] = mapped_column(String(150))
    area_juridica: Mapped[str | None] = mapped_column(String(80))
    tribunal: Mapped[str | None] = mapped_column(String(120))
    comarca: Mapped[str | None] = mapped_column(String(120))
    vara: Mapped[str | None] = mapped_column(String(150))
    parte_contraria: Mapped[str | None] = mapped_column(String(300))
    advogado_responsavel_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("usuarios.id"))
    data_distribuicao: Mapped[date | None] = mapped_column(Date)
    situacao: Mapped[str] = mapped_column(String(20), nullable=False, server_default=text("'em_andamento'"))
    fase_processual: Mapped[str | None] = mapped_column(String(120))
    proximo_evento_tipo: Mapped[str | None] = mapped_column(String(20))
    proximo_evento_em: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    proximo_evento_descricao: Mapped[str | None] = mapped_column(String(300))
    descricao: Mapped[str | None] = mapped_column(Text)
    observacoes: Mapped[str | None] = mapped_column(Text)
    criado_por: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("usuarios.id"))
    versao: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("1"))

    __mapper_args__ = {"version_id_col": versao}
    __table_args__ = (
        CheckConstraint("situacao IN ('em_andamento', 'suspenso', 'arquivado', 'encerrado')",
                        name="situacao_valida"),
        CheckConstraint("proximo_evento_tipo IS NULL OR proximo_evento_tipo IN ('audiencia', 'prazo')",
                        name="evento_valido"),
        Index("uq_processos_numero_cnj", "numero_cnj", unique=True, postgresql_where=text("numero_cnj IS NOT NULL")),
        Index("ix_processos_cliente_id", "cliente_id"),
        Index("ix_processos_proximo_evento_em", "proximo_evento_em"),
    )


class MovimentacaoProcesso(Base):
    """Histórico de movimentações. Registros não são alterados nem apagados (correção = novo registro)."""

    __tablename__ = "movimentacoes_processo"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    processo_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("processos.id"), nullable=False)
    data_movimentacao: Mapped[date] = mapped_column(Date, nullable=False)
    descricao: Mapped[str] = mapped_column(Text, nullable=False)
    registrado_por: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("usuarios.id"))
    registrado_em: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())

    __table_args__ = (Index("ix_movimentacoes_processo", "processo_id", "data_movimentacao"),)


class Documento(ComDatas, Base):
    """Arquivo anexado. O conteúdo fica na pasta de documentos do servidor (fora do banco),
    organizado por cliente e processo; o banco guarda os dados e a impressão SHA-256."""

    __tablename__ = "documentos"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    cliente_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("clientes.id"), nullable=False)
    processo_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("processos.id"))
    nome_arquivo: Mapped[str] = mapped_column(String(255), nullable=False)
    descricao: Mapped[str | None] = mapped_column(String(500))
    tipo_conteudo: Mapped[str | None] = mapped_column(String(150))
    tamanho: Mapped[int] = mapped_column(BigInteger, nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    caminho: Mapped[str] = mapped_column(String(400), nullable=False)
    enviado_por: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("usuarios.id"))
    removido_em: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    removido_por: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("usuarios.id"))
    motivo_remocao: Mapped[str | None] = mapped_column(String(500))
    versao: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("1"))

    __mapper_args__ = {"version_id_col": versao}
    __table_args__ = (
        Index("ix_documentos_cliente_id", "cliente_id"),
        Index("ix_documentos_processo_id", "processo_id"),
    )
