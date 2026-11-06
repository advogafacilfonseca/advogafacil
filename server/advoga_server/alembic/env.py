from __future__ import annotations

from alembic import context
from sqlalchemy import create_engine, pool

from advoga_server.core.config import obter_configuracoes
from advoga_server.models import Base

config = context.config
alvo = Base.metadata


def _url() -> str:
    return config.attributes.get("url") or obter_configuracoes().url_banco()


def executar_offline() -> None:
    context.configure(url=_url(), target_metadata=alvo, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()


def _incluir(objeto, nome, tipo, refletido, comparado) -> bool:
    # Índices de pesquisa (funções/trigramas) são criados à mão nas migrações.
    return not (tipo == "index" and nome and nome.endswith("_busca"))


def executar_online() -> None:
    conexao = config.attributes.get("connection")
    if conexao is not None:
        context.configure(connection=conexao, target_metadata=alvo, compare_type=True, include_object=_incluir)
        with context.begin_transaction():
            context.run_migrations()
        return
    engine = create_engine(_url(), poolclass=pool.NullPool)
    with engine.connect() as conn:
        context.configure(connection=conn, target_metadata=alvo, compare_type=True, include_object=_incluir)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    executar_offline()
else:
    executar_online()
