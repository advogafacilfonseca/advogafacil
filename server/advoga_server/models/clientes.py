from __future__ import annotations

import uuid
from datetime import date, datetime

from sqlalchemy import CheckConstraint, Date, DateTime, ForeignKey, Index, Integer, String, Text, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, ComDatas


class Cliente(ComDatas, Base):
    """Cliente do escritório. Todos os registros se ligam a ele pelo `id`, nunca pelo nome."""

    __tablename__ = "clientes"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    nome_completo: Mapped[str] = mapped_column(String(150), nullable=False)
    cpf: Mapped[str | None] = mapped_column(String(11))
    rg: Mapped[str | None] = mapped_column(String(30))
    data_nascimento: Mapped[date | None] = mapped_column(Date)
    telefone_principal: Mapped[str | None] = mapped_column(String(11))
    telefone_secundario: Mapped[str | None] = mapped_column(String(11))
    email: Mapped[str | None] = mapped_column(String(254))
    cep: Mapped[str | None] = mapped_column(String(8))
    logradouro: Mapped[str | None] = mapped_column(String(200))
    numero: Mapped[str | None] = mapped_column(String(20))
    complemento: Mapped[str | None] = mapped_column(String(100))
    bairro: Mapped[str | None] = mapped_column(String(100))
    cidade: Mapped[str | None] = mapped_column(String(100))
    uf: Mapped[str | None] = mapped_column(String(2))
    observacoes: Mapped[str | None] = mapped_column(Text)
    data_inicio_atendimento: Mapped[date | None] = mapped_column(Date)
    advogado_responsavel_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("usuarios.id"))
    situacao: Mapped[str] = mapped_column(String(20), nullable=False, server_default=text("'ativo'"))
    encerrado_em: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    motivo_encerramento: Mapped[str | None] = mapped_column(String(500))
    criado_por: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("usuarios.id"))
    # Controle de edição simultânea: cada alteração incrementa a versão.
    versao: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("1"))

    __mapper_args__ = {"version_id_col": versao}
    __table_args__ = (
        CheckConstraint("situacao IN ('ativo', 'encerrado')", name="situacao_valida"),
        Index("uq_clientes_cpf", "cpf", unique=True, postgresql_where=text("cpf IS NOT NULL")),
        Index("ix_clientes_telefone_principal", "telefone_principal"),
        Index("ix_clientes_telefone_secundario", "telefone_secundario"),
    )
