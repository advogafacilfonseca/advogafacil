"""contratos e financeiro

Revisão: 0005
Anterior: 0004
Criada em: 2026-11-06 02:00:49.931460
"""

from alembic import op
import sqlalchemy as sa


revision = '0005'
down_revision = '0004'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table('comprovantes',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('nome_arquivo', sa.String(length=255), nullable=False),
    sa.Column('tipo_conteudo', sa.String(length=150), nullable=True),
    sa.Column('tamanho', sa.BigInteger(), nullable=False),
    sa.Column('sha256', sa.String(length=64), nullable=False),
    sa.Column('caminho', sa.String(length=400), nullable=False),
    sa.Column('enviado_por', sa.UUID(), nullable=True),
    sa.Column('criado_em', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['enviado_por'], ['usuarios.id'], name=op.f('fk_comprovantes_enviado_por_usuarios')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_comprovantes'))
    )
    op.create_table('contratos',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('cliente_id', sa.UUID(), nullable=False),
    sa.Column('processo_id', sa.UUID(), nullable=True),
    sa.Column('servico_contratado', sa.String(length=300), nullable=False),
    sa.Column('advogado_responsavel_id', sa.UUID(), nullable=True),
    sa.Column('data_inicio', sa.Date(), nullable=False),
    sa.Column('valor_total', sa.Numeric(precision=14, scale=2), nullable=False),
    sa.Column('valor_original', sa.Numeric(precision=14, scale=2), nullable=False),
    sa.Column('observacoes', sa.Text(), nullable=True),
    sa.Column('situacao', sa.String(length=20), server_default=sa.text("'ativo'"), nullable=False),
    sa.Column('cancelado_em', sa.DateTime(timezone=True), nullable=True),
    sa.Column('motivo_cancelamento', sa.String(length=500), nullable=True),
    sa.Column('criado_por', sa.UUID(), nullable=True),
    sa.Column('versao', sa.Integer(), server_default=sa.text('1'), nullable=False),
    sa.Column('criado_em', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('atualizado_em', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("situacao IN ('ativo', 'quitado', 'cancelado')", name=op.f('ck_contratos_situacao_valida')),
    sa.CheckConstraint('valor_total >= 0 AND valor_original > 0', name=op.f('ck_contratos_valores_validos')),
    sa.ForeignKeyConstraint(['advogado_responsavel_id'], ['usuarios.id'], name=op.f('fk_contratos_advogado_responsavel_id_usuarios')),
    sa.ForeignKeyConstraint(['cliente_id'], ['clientes.id'], name=op.f('fk_contratos_cliente_id_clientes')),
    sa.ForeignKeyConstraint(['criado_por'], ['usuarios.id'], name=op.f('fk_contratos_criado_por_usuarios')),
    sa.ForeignKeyConstraint(['processo_id'], ['processos.id'], name=op.f('fk_contratos_processo_id_processos')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_contratos'))
    )
    op.create_index('ix_contratos_cliente_id', 'contratos', ['cliente_id'], unique=False)
    op.create_table('despesas',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('descricao', sa.String(length=300), nullable=False),
    sa.Column('categoria', sa.String(length=30), nullable=False),
    sa.Column('valor', sa.Numeric(precision=14, scale=2), nullable=False),
    sa.Column('data', sa.Date(), nullable=False),
    sa.Column('responsavel_id', sa.UUID(), nullable=True),
    sa.Column('cliente_id', sa.UUID(), nullable=True),
    sa.Column('processo_id', sa.UUID(), nullable=True),
    sa.Column('comprovante_id', sa.UUID(), nullable=True),
    sa.Column('observacoes', sa.Text(), nullable=True),
    sa.Column('registrado_por', sa.UUID(), nullable=True),
    sa.Column('cancelada_em', sa.DateTime(timezone=True), nullable=True),
    sa.Column('cancelada_por', sa.UUID(), nullable=True),
    sa.Column('motivo_cancelamento', sa.String(length=500), nullable=True),
    sa.Column('versao', sa.Integer(), server_default=sa.text('1'), nullable=False),
    sa.Column('criado_em', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('atualizado_em', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint('valor > 0', name=op.f('ck_despesas_valor_positivo')),
    sa.ForeignKeyConstraint(['cancelada_por'], ['usuarios.id'], name=op.f('fk_despesas_cancelada_por_usuarios')),
    sa.ForeignKeyConstraint(['cliente_id'], ['clientes.id'], name=op.f('fk_despesas_cliente_id_clientes')),
    sa.ForeignKeyConstraint(['comprovante_id'], ['comprovantes.id'], name=op.f('fk_despesas_comprovante_id_comprovantes')),
    sa.ForeignKeyConstraint(['processo_id'], ['processos.id'], name=op.f('fk_despesas_processo_id_processos')),
    sa.ForeignKeyConstraint(['registrado_por'], ['usuarios.id'], name=op.f('fk_despesas_registrado_por_usuarios')),
    sa.ForeignKeyConstraint(['responsavel_id'], ['usuarios.id'], name=op.f('fk_despesas_responsavel_id_usuarios')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_despesas'))
    )
    op.create_index('ix_despesas_data', 'despesas', ['data'], unique=False)
    op.create_table('parcelas',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('contrato_id', sa.UUID(), nullable=False),
    sa.Column('numero', sa.Integer(), nullable=False),
    sa.Column('tipo', sa.String(length=10), nullable=False),
    sa.Column('valor', sa.Numeric(precision=14, scale=2), nullable=False),
    sa.Column('vencimento', sa.Date(), nullable=False),
    sa.Column('situacao', sa.String(length=20), server_default=sa.text("'aberta'"), nullable=False),
    sa.Column('valor_baixado', sa.Numeric(precision=14, scale=2), server_default=sa.text('0'), nullable=False),
    sa.Column('motivo_baixa', sa.String(length=500), nullable=True),
    sa.Column('criado_em', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('versao', sa.Integer(), server_default=sa.text('1'), nullable=False),
    sa.CheckConstraint("situacao IN ('aberta', 'paga', 'cancelada', 'renegociada')", name=op.f('ck_parcelas_situacao_valida')),
    sa.CheckConstraint("tipo IN ('entrada', 'parcela')", name=op.f('ck_parcelas_tipo_valido')),
    sa.CheckConstraint('valor > 0 AND valor_baixado >= 0 AND valor_baixado <= valor', name=op.f('ck_parcelas_valores_validos')),
    sa.ForeignKeyConstraint(['contrato_id'], ['contratos.id'], name=op.f('fk_parcelas_contrato_id_contratos')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_parcelas')),
    sa.UniqueConstraint('contrato_id', 'numero', name='numero_unico_no_contrato')
    )
    op.create_index('ix_parcelas_vencimento_abertas', 'parcelas', ['vencimento'], unique=False, postgresql_where=sa.text("situacao = 'aberta'"))
    op.create_table('pagamentos',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('parcela_id', sa.UUID(), nullable=False),
    sa.Column('contrato_id', sa.UUID(), nullable=False),
    sa.Column('cliente_id', sa.UUID(), nullable=False),
    sa.Column('valor', sa.Numeric(precision=14, scale=2), nullable=False),
    sa.Column('data_recebimento', sa.Date(), nullable=False),
    sa.Column('forma_pagamento', sa.String(length=20), nullable=False),
    sa.Column('observacoes', sa.Text(), nullable=True),
    sa.Column('comprovante_id', sa.UUID(), nullable=True),
    sa.Column('registrado_por', sa.UUID(), nullable=True),
    sa.Column('registrado_em', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('estornado_em', sa.DateTime(timezone=True), nullable=True),
    sa.Column('estornado_por', sa.UUID(), nullable=True),
    sa.Column('motivo_estorno', sa.String(length=500), nullable=True),
    sa.CheckConstraint('valor > 0', name=op.f('ck_pagamentos_valor_positivo')),
    sa.ForeignKeyConstraint(['cliente_id'], ['clientes.id'], name=op.f('fk_pagamentos_cliente_id_clientes')),
    sa.ForeignKeyConstraint(['comprovante_id'], ['comprovantes.id'], name=op.f('fk_pagamentos_comprovante_id_comprovantes')),
    sa.ForeignKeyConstraint(['contrato_id'], ['contratos.id'], name=op.f('fk_pagamentos_contrato_id_contratos')),
    sa.ForeignKeyConstraint(['estornado_por'], ['usuarios.id'], name=op.f('fk_pagamentos_estornado_por_usuarios')),
    sa.ForeignKeyConstraint(['parcela_id'], ['parcelas.id'], name=op.f('fk_pagamentos_parcela_id_parcelas')),
    sa.ForeignKeyConstraint(['registrado_por'], ['usuarios.id'], name=op.f('fk_pagamentos_registrado_por_usuarios')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_pagamentos'))
    )
    op.create_index('ix_pagamentos_data', 'pagamentos', ['data_recebimento'], unique=False)
    op.create_index('ix_pagamentos_parcela_id', 'pagamentos', ['parcela_id'], unique=False)

    tabelas = ("contratos", "parcelas", "pagamentos", "despesas", "comprovantes")
    for t in tabelas:  # registros financeiros nunca são apagados (cancelamento/estorno controlados)
        op.execute(f"CREATE TRIGGER trg_{t}_sem_exclusao BEFORE DELETE ON {t} "
                   "FOR EACH ROW EXECUTE FUNCTION impedir_exclusao()")
    # Recebimento registrado não muda: somente o estorno (uma única vez) pode ser anotado.
    op.execute("""
        CREATE FUNCTION pagamento_imutavel() RETURNS trigger AS $$
        BEGIN
            IF OLD.estornado_em IS NOT NULL
               OR NEW.valor <> OLD.valor OR NEW.parcela_id <> OLD.parcela_id
               OR NEW.contrato_id <> OLD.contrato_id OR NEW.cliente_id <> OLD.cliente_id
               OR NEW.data_recebimento <> OLD.data_recebimento
               OR NEW.forma_pagamento <> OLD.forma_pagamento
               OR NEW.registrado_por IS DISTINCT FROM OLD.registrado_por
               OR NEW.registrado_em <> OLD.registrado_em THEN
                RAISE EXCEPTION 'Recebimentos registrados não podem ser alterados; utilize o estorno.'
                    USING ERRCODE = 'insufficient_privilege';
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql
    """)
    op.execute("CREATE TRIGGER trg_pagamentos_imutaveis BEFORE UPDATE ON pagamentos "
               "FOR EACH ROW EXECUTE FUNCTION pagamento_imutavel()")


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS trg_pagamentos_imutaveis ON pagamentos")
    op.execute("DROP FUNCTION IF EXISTS pagamento_imutavel()")
    op.drop_index('ix_pagamentos_parcela_id', table_name='pagamentos')
    op.drop_index('ix_pagamentos_data', table_name='pagamentos')
    op.drop_table('pagamentos')
    op.drop_index('ix_parcelas_vencimento_abertas', table_name='parcelas', postgresql_where=sa.text("situacao = 'aberta'"))
    op.drop_table('parcelas')
    op.drop_index('ix_despesas_data', table_name='despesas')
    op.drop_table('despesas')
    op.drop_index('ix_contratos_cliente_id', table_name='contratos')
    op.drop_table('contratos')
    op.drop_table('comprovantes')
