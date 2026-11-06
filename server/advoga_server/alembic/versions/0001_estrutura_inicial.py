"""estrutura inicial

Revisão: 0001
Anterior: 
Criada em: 2026-11-06
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = '0001'
down_revision = None
branch_labels = None
depends_on = None


GATILHOS = [
    # Auditoria: somente inserção. Nenhum registro pode ser alterado ou apagado.
    """
    CREATE FUNCTION auditoria_somente_insercao() RETURNS trigger AS $$
    BEGIN
        RAISE EXCEPTION 'Registros de auditoria não podem ser alterados ou apagados.'
            USING ERRCODE = 'insufficient_privilege';
    END;
    $$ LANGUAGE plpgsql
    """,
    """
    CREATE TRIGGER trg_auditoria_imutavel
    BEFORE UPDATE OR DELETE ON auditoria
    FOR EACH ROW EXECUTE FUNCTION auditoria_somente_insercao()
    """,
    # Proteção da autoridade Master no próprio banco de dados.
    """
    CREATE FUNCTION protege_master() RETURNS trigger AS $$
    BEGIN
        IF TG_OP = 'DELETE' THEN
            RAISE EXCEPTION 'Usuários não podem ser apagados; utilize a desativação.'
                USING ERRCODE = 'insufficient_privilege';
        END IF;
        IF TG_OP = 'INSERT' THEN
            IF NEW.is_master AND coalesce(current_setting('advoga.criacao_master', true), '') <> 'autorizada' THEN
                RAISE EXCEPTION 'A conta Master só pode ser criada pelo assistente de configuração inicial.'
                    USING ERRCODE = 'insufficient_privilege';
            END IF;
            RETURN NEW;
        END IF;
        IF NEW.is_master IS DISTINCT FROM OLD.is_master
           AND coalesce(current_setting('advoga.transferencia_master', true), '') <> 'autorizada' THEN
            RAISE EXCEPTION 'A autoridade Master não pode ser concedida ou retirada por alteração direta.'
                USING ERRCODE = 'insufficient_privilege';
        END IF;
        IF NEW.is_master AND NOT NEW.ativo THEN
            RAISE EXCEPTION 'A conta Master não pode ser desativada.'
                USING ERRCODE = 'insufficient_privilege';
        END IF;
        RETURN NEW;
    END;
    $$ LANGUAGE plpgsql
    """,
    """
    CREATE TRIGGER trg_usuarios_protege_master
    BEFORE INSERT OR UPDATE OR DELETE ON usuarios
    FOR EACH ROW EXECUTE FUNCTION protege_master()
    """,
]

REMOVER_GATILHOS = [
    "DROP TRIGGER IF EXISTS trg_usuarios_protege_master ON usuarios",
    "DROP FUNCTION IF EXISTS protege_master()",
    "DROP TRIGGER IF EXISTS trg_auditoria_imutavel ON auditoria",
    "DROP FUNCTION IF EXISTS auditoria_somente_insercao()",
]


def upgrade() -> None:
    # Extensões para pesquisa sem acento e por semelhança (usadas a partir da etapa 3).
    op.execute("CREATE EXTENSION IF NOT EXISTS unaccent")
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")

    op.create_table('identidade_servidor',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('servidor_id', sa.UUID(), nullable=False),
    sa.Column('status', sa.String(length=20), nullable=False),
    sa.Column('criado_em', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('desativado_em', sa.DateTime(timezone=True), nullable=True),
    sa.Column('observacao', sa.String(length=255), nullable=True),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_identidade_servidor')),
    sa.CheckConstraint('id = 1', name='linha_unica'),
    sa.CheckConstraint("status IN ('ativo', 'desativado')", name='status_valido'),
    )
    op.create_table('usuarios',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('nome_completo', sa.String(length=150), nullable=False),
    sa.Column('nome_exibicao', sa.String(length=80), nullable=False),
    sa.Column('cargo', sa.String(length=80), nullable=True),
    sa.Column('nome_usuario', sa.String(length=40), nullable=False),
    sa.Column('email', sa.String(length=254), nullable=False),
    sa.Column('senha_hash', sa.String(length=255), nullable=False),
    sa.Column('is_master', sa.Boolean(), server_default=sa.text('false'), nullable=False),
    sa.Column('ativo', sa.Boolean(), server_default=sa.text('true'), nullable=False),
    sa.Column('deve_trocar_senha', sa.Boolean(), server_default=sa.text('false'), nullable=False),
    sa.Column('tentativas_falhas', sa.Integer(), server_default=sa.text('0'), nullable=False),
    sa.Column('bloqueado_ate', sa.DateTime(timezone=True), nullable=True),
    sa.Column('ultimo_login_em', sa.DateTime(timezone=True), nullable=True),
    sa.Column('desativado_em', sa.DateTime(timezone=True), nullable=True),
    sa.Column('criado_em', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('atualizado_em', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_usuarios')),
    sa.UniqueConstraint('nome_usuario', name=op.f('uq_usuarios_nome_usuario'))
    )
    op.create_index('uq_usuarios_unica_master', 'usuarios', ['is_master'], unique=True, postgresql_where=sa.text('is_master'))
    op.create_table('auditoria',
    sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
    sa.Column('ocorrido_em', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('usuario_id', sa.UUID(), nullable=True),
    sa.Column('acao', sa.String(length=60), nullable=False),
    sa.Column('entidade', sa.String(length=60), nullable=True),
    sa.Column('entidade_id', sa.String(length=64), nullable=True),
    sa.Column('detalhes', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('ip', sa.String(length=64), nullable=True),
    sa.ForeignKeyConstraint(['usuario_id'], ['usuarios.id'], name=op.f('fk_auditoria_usuario_id_usuarios')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_auditoria'))
    )
    op.create_index(op.f('ix_auditoria_acao'), 'auditoria', ['acao'], unique=False)
    op.create_index(op.f('ix_auditoria_ocorrido_em'), 'auditoria', ['ocorrido_em'], unique=False)
    op.create_index(op.f('ix_auditoria_usuario_id'), 'auditoria', ['usuario_id'], unique=False)
    op.create_table('configuracoes',
    sa.Column('chave', sa.String(length=80), nullable=False),
    sa.Column('valor', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('atualizado_em', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('atualizado_por', sa.UUID(), nullable=True),
    sa.ForeignKeyConstraint(['atualizado_por'], ['usuarios.id'], name=op.f('fk_configuracoes_atualizado_por_usuarios')),
    sa.PrimaryKeyConstraint('chave', name=op.f('pk_configuracoes'))
    )
    op.create_table('permissoes_usuario',
    sa.Column('usuario_id', sa.UUID(), nullable=False),
    sa.Column('permissao', sa.String(length=40), nullable=False),
    sa.Column('concedida_em', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('concedida_por', sa.UUID(), nullable=True),
    sa.ForeignKeyConstraint(['concedida_por'], ['usuarios.id'], name=op.f('fk_permissoes_usuario_concedida_por_usuarios')),
    sa.ForeignKeyConstraint(['usuario_id'], ['usuarios.id'], name=op.f('fk_permissoes_usuario_usuario_id_usuarios'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('usuario_id', 'permissao', name=op.f('pk_permissoes_usuario'))
    )
    op.create_table('sessoes',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('usuario_id', sa.UUID(), nullable=False),
    sa.Column('token_hash', sa.String(length=64), nullable=False),
    sa.Column('criada_em', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('ultimo_uso_em', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('expira_em', sa.DateTime(timezone=True), nullable=False),
    sa.Column('encerrada_em', sa.DateTime(timezone=True), nullable=True),
    sa.Column('motivo_encerramento', sa.String(length=40), nullable=True),
    sa.Column('ip', sa.String(length=64), nullable=True),
    sa.Column('dispositivo', sa.String(length=120), nullable=True),
    sa.ForeignKeyConstraint(['usuario_id'], ['usuarios.id'], name=op.f('fk_sessoes_usuario_id_usuarios')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_sessoes')),
    sa.UniqueConstraint('token_hash', name=op.f('uq_sessoes_token_hash'))
    )
    op.create_index(op.f('ix_sessoes_usuario_id'), 'sessoes', ['usuario_id'], unique=False)

    for comando in GATILHOS:
        op.execute(comando)


def downgrade() -> None:
    for comando in REMOVER_GATILHOS:
        op.execute(comando)
    op.drop_index(op.f('ix_sessoes_usuario_id'), table_name='sessoes')
    op.drop_table('sessoes')
    op.drop_table('permissoes_usuario')
    op.drop_table('configuracoes')
    op.drop_index(op.f('ix_auditoria_usuario_id'), table_name='auditoria')
    op.drop_index(op.f('ix_auditoria_ocorrido_em'), table_name='auditoria')
    op.drop_index(op.f('ix_auditoria_acao'), table_name='auditoria')
    op.drop_table('auditoria')
    op.drop_index('uq_usuarios_unica_master', table_name='usuarios', postgresql_where=sa.text('is_master'))
    op.drop_table('usuarios')
    op.drop_table('identidade_servidor')
