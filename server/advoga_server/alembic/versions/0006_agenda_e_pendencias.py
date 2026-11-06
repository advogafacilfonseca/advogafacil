"""agenda e pendencias

Revisão: 0006
Anterior: 0005
Criada em: 2026-11-06 02:38:40.663217
"""

from alembic import op
import sqlalchemy as sa


revision = '0006'
down_revision = '0005'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table('compromissos',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('titulo', sa.String(length=300), nullable=False),
    sa.Column('tipo', sa.String(length=30), nullable=False),
    sa.Column('cliente_id', sa.UUID(), nullable=True),
    sa.Column('processo_id', sa.UUID(), nullable=True),
    sa.Column('responsavel_id', sa.UUID(), nullable=True),
    sa.Column('inicio', sa.DateTime(timezone=True), nullable=False),
    sa.Column('dia_inteiro', sa.Boolean(), server_default=sa.text('false'), nullable=False),
    sa.Column('duracao_minutos', sa.Integer(), nullable=True),
    sa.Column('local', sa.String(length=300), nullable=True),
    sa.Column('prioridade', sa.String(length=10), server_default=sa.text("'normal'"), nullable=False),
    sa.Column('observacoes', sa.Text(), nullable=True),
    sa.Column('situacao', sa.String(length=15), server_default=sa.text("'agendado'"), nullable=False),
    sa.Column('do_processo', sa.Boolean(), server_default=sa.text('false'), nullable=False),
    sa.Column('reagendamentos', sa.Integer(), server_default=sa.text('0'), nullable=False),
    sa.Column('concluido_em', sa.DateTime(timezone=True), nullable=True),
    sa.Column('concluido_por', sa.UUID(), nullable=True),
    sa.Column('observacao_conclusao', sa.Text(), nullable=True),
    sa.Column('cancelado_em', sa.DateTime(timezone=True), nullable=True),
    sa.Column('cancelado_por', sa.UUID(), nullable=True),
    sa.Column('motivo_cancelamento', sa.String(length=500), nullable=True),
    sa.Column('criado_por', sa.UUID(), nullable=True),
    sa.Column('versao', sa.Integer(), server_default=sa.text('1'), nullable=False),
    sa.Column('criado_em', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('atualizado_em', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("prioridade IN ('baixa', 'normal', 'alta', 'urgente')", name=op.f('ck_compromissos_prioridade_valida')),
    sa.CheckConstraint("situacao IN ('agendado', 'concluido', 'cancelado')", name=op.f('ck_compromissos_situacao_valida')),
    sa.CheckConstraint("tipo IN ('audiencia', 'reuniao', 'ligacao', 'retorno', 'consulta', 'diligencia', 'entrega_documentos', 'prazo', 'tarefa', 'outro')", name=op.f('ck_compromissos_tipo_valido')),
    sa.ForeignKeyConstraint(['cancelado_por'], ['usuarios.id'], name=op.f('fk_compromissos_cancelado_por_usuarios')),
    sa.ForeignKeyConstraint(['cliente_id'], ['clientes.id'], name=op.f('fk_compromissos_cliente_id_clientes')),
    sa.ForeignKeyConstraint(['concluido_por'], ['usuarios.id'], name=op.f('fk_compromissos_concluido_por_usuarios')),
    sa.ForeignKeyConstraint(['criado_por'], ['usuarios.id'], name=op.f('fk_compromissos_criado_por_usuarios')),
    sa.ForeignKeyConstraint(['processo_id'], ['processos.id'], name=op.f('fk_compromissos_processo_id_processos')),
    sa.ForeignKeyConstraint(['responsavel_id'], ['usuarios.id'], name=op.f('fk_compromissos_responsavel_id_usuarios')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_compromissos'))
    )
    op.create_index('ix_compromissos_cliente', 'compromissos', ['cliente_id'], unique=False)
    op.create_index('ix_compromissos_inicio', 'compromissos', ['inicio'], unique=False)
    op.create_index('ix_compromissos_responsavel', 'compromissos', ['responsavel_id'], unique=False)
    op.create_index('uq_compromissos_do_processo', 'compromissos', ['processo_id'], unique=True, postgresql_where=sa.text("do_processo AND situacao = 'agendado'"))
    # Compromissos nunca são apagados: são concluídos ou cancelados, com histórico.
    op.execute("CREATE TRIGGER trg_compromissos_sem_exclusao BEFORE DELETE ON compromissos "
               "FOR EACH ROW EXECUTE FUNCTION impedir_exclusao()")


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS trg_compromissos_sem_exclusao ON compromissos")
    op.drop_index('uq_compromissos_do_processo', table_name='compromissos', postgresql_where=sa.text("do_processo AND situacao = 'agendado'"))
    op.drop_index('ix_compromissos_responsavel', table_name='compromissos')
    op.drop_index('ix_compromissos_inicio', table_name='compromissos')
    op.drop_index('ix_compromissos_cliente', table_name='compromissos')
    op.drop_table('compromissos')
