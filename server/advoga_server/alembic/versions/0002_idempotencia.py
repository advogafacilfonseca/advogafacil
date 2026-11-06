"""idempotencia

Revisão: 0002
Anterior: 0001
Criada em: 2026-11-06
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = '0002'
down_revision = '0001'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table('chaves_idempotencia',
    sa.Column('usuario_id', sa.UUID(), nullable=False),
    sa.Column('chave', sa.String(length=64), nullable=False),
    sa.Column('rota', sa.String(length=120), nullable=False),
    sa.Column('status', sa.Integer(), nullable=False),
    sa.Column('corpo', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('criado_em', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['usuario_id'], ['usuarios.id'], name=op.f('fk_chaves_idempotencia_usuario_id_usuarios')),
    sa.PrimaryKeyConstraint('usuario_id', 'chave', name=op.f('pk_chaves_idempotencia'))
    )
    op.create_index(op.f('ix_chaves_idempotencia_criado_em'), 'chaves_idempotencia', ['criado_em'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_chaves_idempotencia_criado_em'), table_name='chaves_idempotencia')
    op.drop_table('chaves_idempotencia')
