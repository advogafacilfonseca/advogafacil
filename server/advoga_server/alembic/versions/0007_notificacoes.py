"""notificacoes

Revisão: 0007
Anterior: 0006
Criada em: 2026-11-06 03:02:42.271064
"""

from alembic import op
import sqlalchemy as sa


revision = '0007'
down_revision = '0006'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table('destinatarios_notificacao',
    sa.Column('categoria', sa.String(length=40), nullable=False),
    sa.Column('usuario_id', sa.UUID(), nullable=False),
    sa.ForeignKeyConstraint(['usuario_id'], ['usuarios.id'], name=op.f('fk_destinatarios_notificacao_usuario_id_usuarios')),
    sa.PrimaryKeyConstraint('categoria', 'usuario_id', name=op.f('pk_destinatarios_notificacao'))
    )
    op.create_table('notificacoes',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('chave', sa.String(length=200), nullable=False),
    sa.Column('categoria', sa.String(length=40), nullable=False),
    sa.Column('usuario_id', sa.UUID(), nullable=False),
    sa.Column('titulo', sa.String(length=200), nullable=False),
    sa.Column('mensagem', sa.Text(), nullable=False),
    sa.Column('entidade', sa.String(length=40), nullable=True),
    sa.Column('entidade_id', sa.String(length=64), nullable=True),
    sa.Column('criada_em', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('lida_em', sa.DateTime(timezone=True), nullable=True),
    sa.Column('email_situacao', sa.String(length=20), server_default=sa.text("'pendente'"), nullable=False),
    sa.Column('email_tentativas', sa.Integer(), server_default=sa.text('0'), nullable=False),
    sa.Column('email_erro', sa.String(length=500), nullable=True),
    sa.Column('email_enviado_em', sa.DateTime(timezone=True), nullable=True),
    sa.Column('proxima_tentativa_em', sa.DateTime(timezone=True), nullable=True),
    sa.Column('email_destino', sa.String(length=254), nullable=True),
    sa.CheckConstraint("email_situacao IN ('pendente', 'enviado', 'falhou', 'rejeitado', 'nao_configurado', 'desativado', 'sem_email', 'cancelado')", name=op.f('ck_notificacoes_situacao_email_valida')),
    sa.ForeignKeyConstraint(['usuario_id'], ['usuarios.id'], name=op.f('fk_notificacoes_usuario_id_usuarios')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_notificacoes')),
    sa.UniqueConstraint('chave', name=op.f('uq_notificacoes_chave'))
    )
    op.create_index('ix_notificacoes_pendentes', 'notificacoes', ['proxima_tentativa_em'], unique=False, postgresql_where=sa.text("email_situacao = 'pendente'"))
    op.create_index('ix_notificacoes_usuario', 'notificacoes', ['usuario_id', 'criada_em'], unique=False)
    # O histórico de avisos e envios não é apagado.
    op.execute("CREATE TRIGGER trg_notificacoes_sem_exclusao BEFORE DELETE ON notificacoes "
               "FOR EACH ROW EXECUTE FUNCTION impedir_exclusao()")


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS trg_notificacoes_sem_exclusao ON notificacoes")
    op.drop_index('ix_notificacoes_usuario', table_name='notificacoes')
    op.drop_index('ix_notificacoes_pendentes', table_name='notificacoes', postgresql_where=sa.text("email_situacao = 'pendente'"))
    op.drop_table('notificacoes')
    op.drop_table('destinatarios_notificacao')
