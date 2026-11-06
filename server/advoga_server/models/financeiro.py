"""Contratos, parcelas, recebimentos, despesas e comprovantes (área restrita do financeiro)."""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, ComDatas

Valor = Numeric(14, 2)


class Contrato(ComDatas, Base):
    __tablename__ = "contratos"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    cliente_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("clientes.id"), nullable=False)
    processo_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("processos.id"))
    servico_contratado: Mapped[str] = mapped_column(String(300), nullable=False)
    advogado_responsavel_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("usuarios.id"))
    data_inicio: Mapped[date] = mapped_column(Date, nullable=False)
    # Valor contratado vigente: o original, ajustado por renegociações (sempre registradas).
    valor_total: Mapped[Decimal] = mapped_column(Valor, nullable=False)
    valor_original: Mapped[Decimal] = mapped_column(Valor, nullable=False)
    observacoes: Mapped[str | None] = mapped_column(Text)
    situacao: Mapped[str] = mapped_column(String(20), nullable=False, server_default=text("'ativo'"))
    cancelado_em: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    motivo_cancelamento: Mapped[str | None] = mapped_column(String(500))
    criado_por: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("usuarios.id"))
    versao: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("1"))

    __mapper_args__ = {"version_id_col": versao}
    __table_args__ = (
        CheckConstraint("situacao IN ('ativo', 'quitado', 'cancelado')", name="situacao_valida"),
        CheckConstraint("valor_total >= 0 AND valor_original > 0", name="valores_validos"),
        Index("ix_contratos_cliente_id", "cliente_id"),
    )


class Parcela(Base):
    """Entrada (número 0) ou parcela (1..n). Gerada automaticamente; nunca apagada.
    Pagamento é sempre um registro à parte (contratado ≠ recebido)."""

    __tablename__ = "parcelas"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    contrato_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("contratos.id"), nullable=False)
    numero: Mapped[int] = mapped_column(Integer, nullable=False)
    tipo: Mapped[str] = mapped_column(String(10), nullable=False)
    valor: Mapped[Decimal] = mapped_column(Valor, nullable=False)
    vencimento: Mapped[date] = mapped_column(Date, nullable=False)
    situacao: Mapped[str] = mapped_column(String(20), nullable=False, server_default=text("'aberta'"))
    # Parte não paga que foi cancelada ou transferida para novas parcelas na renegociação.
    valor_baixado: Mapped[Decimal] = mapped_column(Valor, nullable=False, server_default=text("0"))
    motivo_baixa: Mapped[str | None] = mapped_column(String(500))
    criado_em: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    versao: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("1"))

    __mapper_args__ = {"version_id_col": versao}
    __table_args__ = (
        UniqueConstraint("contrato_id", "numero", name="numero_unico_no_contrato"),
        CheckConstraint("tipo IN ('entrada', 'parcela')", name="tipo_valido"),
        CheckConstraint("situacao IN ('aberta', 'paga', 'cancelada', 'renegociada')", name="situacao_valida"),
        CheckConstraint("valor > 0 AND valor_baixado >= 0 AND valor_baixado <= valor", name="valores_validos"),
        Index("ix_parcelas_vencimento_abertas", "vencimento", postgresql_where=text("situacao = 'aberta'")),
    )


class Comprovante(Base):
    """Arquivo de comprovante financeiro. Fica numa pasta separada e só é acessível pelo financeiro."""

    __tablename__ = "comprovantes"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    nome_arquivo: Mapped[str] = mapped_column(String(255), nullable=False)
    tipo_conteudo: Mapped[str | None] = mapped_column(String(150))
    tamanho: Mapped[int] = mapped_column(BigInteger, nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    caminho: Mapped[str] = mapped_column(String(400), nullable=False)
    enviado_por: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("usuarios.id"))
    criado_em: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class Pagamento(Base):
    """Recebimento registrado (baixa). Não é alterado nem apagado; erro se corrige por estorno."""

    __tablename__ = "pagamentos"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    parcela_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("parcelas.id"), nullable=False)
    contrato_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("contratos.id"), nullable=False)
    cliente_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("clientes.id"), nullable=False)
    valor: Mapped[Decimal] = mapped_column(Valor, nullable=False)
    data_recebimento: Mapped[date] = mapped_column(Date, nullable=False)
    forma_pagamento: Mapped[str] = mapped_column(String(20), nullable=False)
    observacoes: Mapped[str | None] = mapped_column(Text)
    comprovante_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("comprovantes.id"))
    registrado_por: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("usuarios.id"))
    registrado_em: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    estornado_em: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    estornado_por: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("usuarios.id"))
    motivo_estorno: Mapped[str | None] = mapped_column(String(500))

    __table_args__ = (
        CheckConstraint("valor > 0", name="valor_positivo"),
        Index("ix_pagamentos_parcela_id", "parcela_id"),
        Index("ix_pagamentos_data", "data_recebimento"),
    )


class Despesa(ComDatas, Base):
    __tablename__ = "despesas"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    descricao: Mapped[str] = mapped_column(String(300), nullable=False)
    categoria: Mapped[str] = mapped_column(String(30), nullable=False)
    valor: Mapped[Decimal] = mapped_column(Valor, nullable=False)
    data: Mapped[date] = mapped_column(Date, nullable=False)
    responsavel_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("usuarios.id"))
    cliente_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("clientes.id"))
    processo_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("processos.id"))
    comprovante_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("comprovantes.id"))
    observacoes: Mapped[str | None] = mapped_column(Text)
    registrado_por: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("usuarios.id"))
    cancelada_em: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cancelada_por: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("usuarios.id"))
    motivo_cancelamento: Mapped[str | None] = mapped_column(String(500))
    versao: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("1"))

    __mapper_args__ = {"version_id_col": versao}
    __table_args__ = (
        CheckConstraint("valor > 0", name="valor_positivo"),
        Index("ix_despesas_data", "data"),
    )
