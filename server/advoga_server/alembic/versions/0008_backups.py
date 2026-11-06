"""backups

Revisão: 0008
Anterior: 0007
Criada em: 2026-11-06
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = '0008'
down_revision = '0007'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table('backups_execucoes',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('tipo', sa.String(length=20), nullable=False),
    sa.Column('origem', sa.String(length=15), nullable=False),
    sa.Column('situacao', sa.String(length=15), nullable=False),
    sa.Column('iniciado_em', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('concluido_em', sa.DateTime(timezone=True), nullable=True),
    sa.Column('versao', sa.String(length=80), nullable=True),
    sa.Column('destino', sa.String(length=400), nullable=True),
    sa.Column('tamanho_bytes', sa.BigInteger(), nullable=True),
    sa.Column('arquivos_novos', sa.Integer(), nullable=True),
    sa.Column('arquivos_total', sa.Integer(), nullable=True),
    sa.Column('copia_secundaria', sa.String(length=500), nullable=True),
    sa.Column('mensagem', sa.Text(), nullable=True),
    sa.Column('detalhes', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('iniciado_por', sa.UUID(), nullable=True),
    sa.CheckConstraint("situacao IN ('em_andamento', 'sucesso', 'falhou')", name=op.f('ck_backups_execucoes_situacao_valida')),
    sa.CheckConstraint("tipo IN ('rapido', 'completo', 'teste_restauracao')", name=op.f('ck_backups_execucoes_tipo_valido')),
    sa.ForeignKeyConstraint(['iniciado_por'], ['usuarios.id'], name=op.f('fk_backups_execucoes_iniciado_por_usuarios')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_backups_execucoes'))
    )
    op.create_index('ix_backups_execucoes_inicio', 'backups_execucoes', ['iniciado_em'], unique=False)
    # O histórico de backups não é apagado.
    op.execute("CREATE TRIGGER trg_backups_execucoes_sem_exclusao BEFORE DELETE ON backups_execucoes "
               "FOR EACH ROW EXECUTE FUNCTION impedir_exclusao()")


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS trg_backups_execucoes_sem_exclusao ON backups_execucoes")
    op.drop_index('ix_backups_execucoes_inicio', table_name='backups_execucoes')
    op.drop_table('backups_execucoes')
