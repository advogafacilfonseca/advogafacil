"""migração de servidor

Revisão: 0009
Anterior: 0008
Criada em: 2026-11-06
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = '0009'
down_revision = '0008'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_constraint('status_valido', 'identidade_servidor', type_='check')
    op.create_check_constraint('status_valido', 'identidade_servidor',
                               "status IN ('ativo', 'em_migracao', 'desativado')")
    op.add_column('identidade_servidor', sa.Column('migrado_de', sa.UUID(), nullable=True))
    op.add_column('identidade_servidor', sa.Column('migrado_em', sa.DateTime(timezone=True), nullable=True))
    op.create_table('migracoes',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('tipo', sa.String(length=15), nullable=False),
    sa.Column('situacao', sa.String(length=15), nullable=False),
    sa.Column('iniciado_em', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('concluido_em', sa.DateTime(timezone=True), nullable=True),
    sa.Column('iniciado_por', sa.UUID(), nullable=True),
    sa.Column('servidor_origem', sa.UUID(), nullable=True),
    sa.Column('servidor_destino', sa.UUID(), nullable=True),
    sa.Column('arquivo', sa.String(length=500), nullable=True),
    sa.Column('etapa', sa.String(length=200), nullable=True),
    sa.Column('mensagem', sa.Text(), nullable=True),
    sa.Column('codigo_hash', sa.String(length=64), nullable=True),
    sa.Column('relatorio', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.CheckConstraint("tipo IN ('exportacao', 'importacao')", name=op.f('ck_migracoes_tipo_valido')),
    sa.CheckConstraint("situacao IN ('em_andamento', 'exportada', 'concluida', 'cancelada', 'falhou', 'importada')",
                       name=op.f('ck_migracoes_situacao_valida')),
    sa.ForeignKeyConstraint(['iniciado_por'], ['usuarios.id'], name=op.f('fk_migracoes_iniciado_por_usuarios')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_migracoes'))
    )
    op.create_index('ix_migracoes_inicio', 'migracoes', ['iniciado_em'], unique=False)
    op.execute("CREATE TRIGGER trg_migracoes_sem_exclusao BEFORE DELETE ON migracoes "
               "FOR EACH ROW EXECUTE FUNCTION impedir_exclusao()")


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS trg_migracoes_sem_exclusao ON migracoes")
    op.drop_index('ix_migracoes_inicio', table_name='migracoes')
    op.drop_table('migracoes')
    op.drop_column('identidade_servidor', 'migrado_em')
    op.drop_column('identidade_servidor', 'migrado_de')
    op.drop_constraint('status_valido', 'identidade_servidor', type_='check')
    op.create_check_constraint('status_valido', 'identidade_servidor', "status IN ('ativo', 'desativado')")
