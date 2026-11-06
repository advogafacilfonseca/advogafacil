"""valor já pago antes do sistema

Revisão: 0010
Anterior: 0009
Criada em: 2026-11-06
"""

from alembic import op


revision = '0010'
down_revision = '0009'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_constraint('tipo_valido', 'parcelas', type_='check')
    op.create_check_constraint('tipo_valido', 'parcelas', "tipo IN ('entrada', 'parcela', 'anterior')")


def downgrade() -> None:
    op.drop_constraint('tipo_valido', 'parcelas', type_='check')
    op.create_check_constraint('tipo_valido', 'parcelas', "tipo IN ('entrada', 'parcela')")
