"""processos e documentos

Revisão: 0004
Anterior: 0003
Criada em: 2026-11-06 01:33:25.537510
"""

from alembic import op
import sqlalchemy as sa


revision = '0004'
down_revision = '0003'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table('processos',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('numero_cnj', sa.String(length=20), nullable=True),
    sa.Column('cliente_id', sa.UUID(), nullable=False),
    sa.Column('tipo_acao', sa.String(length=150), nullable=True),
    sa.Column('area_juridica', sa.String(length=80), nullable=True),
    sa.Column('tribunal', sa.String(length=120), nullable=True),
    sa.Column('comarca', sa.String(length=120), nullable=True),
    sa.Column('vara', sa.String(length=150), nullable=True),
    sa.Column('parte_contraria', sa.String(length=300), nullable=True),
    sa.Column('advogado_responsavel_id', sa.UUID(), nullable=True),
    sa.Column('data_distribuicao', sa.Date(), nullable=True),
    sa.Column('situacao', sa.String(length=20), server_default=sa.text("'em_andamento'"), nullable=False),
    sa.Column('fase_processual', sa.String(length=120), nullable=True),
    sa.Column('proximo_evento_tipo', sa.String(length=20), nullable=True),
    sa.Column('proximo_evento_em', sa.DateTime(timezone=True), nullable=True),
    sa.Column('proximo_evento_descricao', sa.String(length=300), nullable=True),
    sa.Column('descricao', sa.Text(), nullable=True),
    sa.Column('observacoes', sa.Text(), nullable=True),
    sa.Column('criado_por', sa.UUID(), nullable=True),
    sa.Column('versao', sa.Integer(), server_default=sa.text('1'), nullable=False),
    sa.Column('criado_em', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('atualizado_em', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("proximo_evento_tipo IS NULL OR proximo_evento_tipo IN ('audiencia', 'prazo')", name=op.f('ck_processos_evento_valido')),
    sa.CheckConstraint("situacao IN ('em_andamento', 'suspenso', 'arquivado', 'encerrado')", name=op.f('ck_processos_situacao_valida')),
    sa.ForeignKeyConstraint(['advogado_responsavel_id'], ['usuarios.id'], name=op.f('fk_processos_advogado_responsavel_id_usuarios')),
    sa.ForeignKeyConstraint(['cliente_id'], ['clientes.id'], name=op.f('fk_processos_cliente_id_clientes')),
    sa.ForeignKeyConstraint(['criado_por'], ['usuarios.id'], name=op.f('fk_processos_criado_por_usuarios')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_processos'))
    )
    op.create_index('ix_processos_cliente_id', 'processos', ['cliente_id'], unique=False)
    op.create_index('ix_processos_proximo_evento_em', 'processos', ['proximo_evento_em'], unique=False)
    op.create_index('uq_processos_numero_cnj', 'processos', ['numero_cnj'], unique=True, postgresql_where=sa.text('numero_cnj IS NOT NULL'))
    op.create_table('documentos',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('cliente_id', sa.UUID(), nullable=False),
    sa.Column('processo_id', sa.UUID(), nullable=True),
    sa.Column('nome_arquivo', sa.String(length=255), nullable=False),
    sa.Column('descricao', sa.String(length=500), nullable=True),
    sa.Column('tipo_conteudo', sa.String(length=150), nullable=True),
    sa.Column('tamanho', sa.BigInteger(), nullable=False),
    sa.Column('sha256', sa.String(length=64), nullable=False),
    sa.Column('caminho', sa.String(length=400), nullable=False),
    sa.Column('enviado_por', sa.UUID(), nullable=True),
    sa.Column('removido_em', sa.DateTime(timezone=True), nullable=True),
    sa.Column('removido_por', sa.UUID(), nullable=True),
    sa.Column('motivo_remocao', sa.String(length=500), nullable=True),
    sa.Column('versao', sa.Integer(), server_default=sa.text('1'), nullable=False),
    sa.Column('criado_em', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('atualizado_em', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['cliente_id'], ['clientes.id'], name=op.f('fk_documentos_cliente_id_clientes')),
    sa.ForeignKeyConstraint(['enviado_por'], ['usuarios.id'], name=op.f('fk_documentos_enviado_por_usuarios')),
    sa.ForeignKeyConstraint(['processo_id'], ['processos.id'], name=op.f('fk_documentos_processo_id_processos')),
    sa.ForeignKeyConstraint(['removido_por'], ['usuarios.id'], name=op.f('fk_documentos_removido_por_usuarios')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_documentos'))
    )
    op.create_index('ix_documentos_cliente_id', 'documentos', ['cliente_id'], unique=False)
    op.create_index('ix_documentos_processo_id', 'documentos', ['processo_id'], unique=False)
    op.create_table('movimentacoes_processo',
    sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
    sa.Column('processo_id', sa.UUID(), nullable=False),
    sa.Column('data_movimentacao', sa.Date(), nullable=False),
    sa.Column('descricao', sa.Text(), nullable=False),
    sa.Column('registrado_por', sa.UUID(), nullable=True),
    sa.Column('registrado_em', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['processo_id'], ['processos.id'], name=op.f('fk_movimentacoes_processo_processo_id_processos')),
    sa.ForeignKeyConstraint(['registrado_por'], ['usuarios.id'], name=op.f('fk_movimentacoes_processo_registrado_por_usuarios')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_movimentacoes_processo'))
    )
    op.create_index('ix_movimentacoes_processo', 'movimentacoes_processo', ['processo_id', 'data_movimentacao'], unique=False)

    # Pesquisa por número (dígitos), parte contrária, tipo de ação e nome de documento.
    op.execute("CREATE INDEX ix_processos_numero_busca ON processos USING gin (numero_cnj gin_trgm_ops)")
    op.execute("CREATE INDEX ix_processos_texto_busca ON processos USING gin "
               "(f_normalizar(coalesce(parte_contraria, '') || ' ' || coalesce(tipo_acao, '')) gin_trgm_ops)")
    op.execute("CREATE INDEX ix_documentos_nome_busca ON documentos USING gin "
               "(f_normalizar(nome_arquivo || ' ' || coalesce(descricao, '')) gin_trgm_ops)")

    # Processos e documentos nunca são apagados do banco (arquivamento / remoção controlada).
    op.execute("CREATE TRIGGER trg_processos_sem_exclusao BEFORE DELETE ON processos "
               "FOR EACH ROW EXECUTE FUNCTION impedir_exclusao()")
    op.execute("CREATE TRIGGER trg_documentos_sem_exclusao BEFORE DELETE ON documentos "
               "FOR EACH ROW EXECUTE FUNCTION impedir_exclusao()")
    # Movimentações são um histórico: não podem ser alteradas nem apagadas.
    op.execute("""
        CREATE FUNCTION movimentacao_imutavel() RETURNS trigger AS $$
        BEGIN
            RAISE EXCEPTION 'Movimentações registradas não podem ser alteradas nem apagadas; registre uma nova movimentação de correção.'
                USING ERRCODE = 'insufficient_privilege';
        END;
        $$ LANGUAGE plpgsql
    """)
    op.execute("CREATE TRIGGER trg_movimentacoes_imutaveis BEFORE UPDATE OR DELETE ON movimentacoes_processo "
               "FOR EACH ROW EXECUTE FUNCTION movimentacao_imutavel()")


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS trg_movimentacoes_imutaveis ON movimentacoes_processo")
    op.execute("DROP FUNCTION IF EXISTS movimentacao_imutavel()")
    op.drop_index('ix_movimentacoes_processo', table_name='movimentacoes_processo')
    op.drop_table('movimentacoes_processo')
    op.drop_index('ix_documentos_processo_id', table_name='documentos')
    op.drop_index('ix_documentos_cliente_id', table_name='documentos')
    op.drop_table('documentos')
    op.drop_index('uq_processos_numero_cnj', table_name='processos', postgresql_where=sa.text('numero_cnj IS NOT NULL'))
    op.drop_index('ix_processos_proximo_evento_em', table_name='processos')
    op.drop_index('ix_processos_cliente_id', table_name='processos')
    op.drop_table('processos')
