"""clientes

Revisão: 0003
Anterior: 0002
Criada em: 2026-11-06
"""

from alembic import op
import sqlalchemy as sa


revision = '0003'
down_revision = '0002'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table('clientes',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('nome_completo', sa.String(length=150), nullable=False),
    sa.Column('cpf', sa.String(length=11), nullable=True),
    sa.Column('rg', sa.String(length=30), nullable=True),
    sa.Column('data_nascimento', sa.Date(), nullable=True),
    sa.Column('telefone_principal', sa.String(length=11), nullable=True),
    sa.Column('telefone_secundario', sa.String(length=11), nullable=True),
    sa.Column('email', sa.String(length=254), nullable=True),
    sa.Column('cep', sa.String(length=8), nullable=True),
    sa.Column('logradouro', sa.String(length=200), nullable=True),
    sa.Column('numero', sa.String(length=20), nullable=True),
    sa.Column('complemento', sa.String(length=100), nullable=True),
    sa.Column('bairro', sa.String(length=100), nullable=True),
    sa.Column('cidade', sa.String(length=100), nullable=True),
    sa.Column('uf', sa.String(length=2), nullable=True),
    sa.Column('observacoes', sa.Text(), nullable=True),
    sa.Column('data_inicio_atendimento', sa.Date(), nullable=True),
    sa.Column('advogado_responsavel_id', sa.UUID(), nullable=True),
    sa.Column('situacao', sa.String(length=20), server_default=sa.text("'ativo'"), nullable=False),
    sa.Column('encerrado_em', sa.DateTime(timezone=True), nullable=True),
    sa.Column('motivo_encerramento', sa.String(length=500), nullable=True),
    sa.Column('criado_por', sa.UUID(), nullable=True),
    sa.Column('versao', sa.Integer(), server_default=sa.text('1'), nullable=False),
    sa.Column('criado_em', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('atualizado_em', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("situacao IN ('ativo', 'encerrado')", name=op.f('ck_clientes_situacao_valida')),
    sa.ForeignKeyConstraint(['advogado_responsavel_id'], ['usuarios.id'], name=op.f('fk_clientes_advogado_responsavel_id_usuarios')),
    sa.ForeignKeyConstraint(['criado_por'], ['usuarios.id'], name=op.f('fk_clientes_criado_por_usuarios')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_clientes'))
    )
    op.create_index('ix_clientes_telefone_principal', 'clientes', ['telefone_principal'], unique=False)
    op.create_index('ix_clientes_telefone_secundario', 'clientes', ['telefone_secundario'], unique=False)
    op.create_index('uq_clientes_cpf', 'clientes', ['cpf'], unique=True, postgresql_where=sa.text('cpf IS NOT NULL'))

    # Pesquisa sem acento e sem diferenciar maiúsculas: "joao" encontra "João".
    op.execute(
        "CREATE OR REPLACE FUNCTION f_normalizar(texto text) RETURNS text "
        "LANGUAGE sql IMMUTABLE PARALLEL SAFE STRICT "
        "AS $$ SELECT lower(public.unaccent('public.unaccent'::regdictionary, texto)) $$"
    )
    op.execute("CREATE INDEX ix_clientes_nome_busca ON clientes USING gin (f_normalizar(nome_completo) gin_trgm_ops)")
    op.execute("CREATE INDEX ix_clientes_cpf_busca ON clientes USING gin (cpf gin_trgm_ops)")
    # Registros de clientes nunca são apagados: o atendimento é encerrado e o histórico permanece.
    op.execute("""
        CREATE FUNCTION impedir_exclusao() RETURNS trigger AS $$
        BEGIN
            RAISE EXCEPTION 'Este registro não pode ser apagado; utilize o encerramento.'
                USING ERRCODE = 'insufficient_privilege';
        END;
        $$ LANGUAGE plpgsql
    """)
    op.execute("CREATE TRIGGER trg_clientes_sem_exclusao BEFORE DELETE ON clientes "
               "FOR EACH ROW EXECUTE FUNCTION impedir_exclusao()")


def downgrade() -> None:
    op.drop_index('uq_clientes_cpf', table_name='clientes', postgresql_where=sa.text('cpf IS NOT NULL'))
    op.drop_index('ix_clientes_telefone_secundario', table_name='clientes')
    op.drop_index('ix_clientes_telefone_principal', table_name='clientes')
    op.drop_table('clientes')
    op.execute("DROP FUNCTION IF EXISTS f_normalizar(text)")
