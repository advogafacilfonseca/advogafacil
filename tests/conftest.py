"""Testes do servidor com um PostgreSQL REAL (nunca SQLite).

Defina ADVOGA_TESTE_PG_ADMIN com a URL de um usuário que possa criar bancos, ex.:
postgresql+psycopg://postgres@127.0.0.1:5433/postgres
Cada execução cria um banco temporário e o apaga ao final.
"""

from __future__ import annotations

import os
import uuid
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

from advoga_server.app import criar_app
from advoga_server.api.deps import obter_cfg
from advoga_server.core.config import Configuracoes
from advoga_server.core.db import obter_sessao
from advoga_server.core.migracoes import atualizar_banco
from advoga_server.services.servidor import obter_identidade, preparar_codigo_instalacao

ADMIN = os.environ.get(
    "ADVOGA_TESTE_PG_ADMIN", "postgresql+psycopg://postgres@127.0.0.1:5433/postgres"
)
SENHA_MASTER = "SenhaForte2026"


@pytest.fixture(scope="session")
def url_banco() -> Iterator[str]:
    nome = f"advoga_teste_{uuid.uuid4().hex[:10]}"
    admin = create_engine(ADMIN, isolation_level="AUTOCOMMIT")
    with admin.connect() as c:
        c.execute(text(f'CREATE DATABASE "{nome}"'))
    url = make_url(ADMIN).set(database=nome).render_as_string(hide_password=False)
    atualizar_banco(url)
    yield url
    with admin.connect() as c:
        c.execute(text(f'DROP DATABASE IF EXISTS "{nome}" WITH (FORCE)'))
    admin.dispose()


@pytest.fixture
def cfg(tmp_path, url_banco) -> Configuracoes:
    c = Configuracoes(pasta_dados=tmp_path / "dados", database_url=url_banco,
                      login_max_tentativas=3, login_bloqueio_minutos=15)
    c.garantir_pastas()
    return c


@pytest.fixture
def banco_limpo(url_banco) -> None:
    """Esvazia as tabelas entre testes (os gatilhos de proteção são desligados só aqui)."""
    eng = create_engine(url_banco)
    with eng.begin() as c:
        c.execute(text("SET session_replication_role = replica"))
        c.execute(text(
            "TRUNCATE pagamentos, parcelas, despesas, contratos, comprovantes, movimentacoes_processo, documentos, processos, clientes, chaves_idempotencia, auditoria, sessoes, permissoes_usuario, configuracoes, usuarios, "
            "identidade_servidor CASCADE"
        ))
    eng.dispose()


@pytest.fixture
def app(cfg, banco_limpo):
    aplicacao = criar_app(cfg)
    aplicacao.dependency_overrides[obter_cfg] = lambda: cfg
    return aplicacao


@pytest.fixture
def cliente(app) -> Iterator[TestClient]:
    with TestClient(app) as c:
        yield c


@pytest.fixture
def db(app):
    gen = obter_sessao()
    sessao = next(gen)
    yield sessao
    sessao.close()


@pytest.fixture
def codigo(db, cfg) -> str:
    obter_identidade(db)
    c = preparar_codigo_instalacao(db, cfg)
    assert c
    return c


def dados_master(codigo: str, **extra) -> dict:
    base = {
        "codigo_instalacao": codigo,
        "nome_completo": "Maria Advogada Teste",
        "nome_usuario": "master",
        "email": "master@exemplo.com",
        "senha": SENHA_MASTER,
        "senha_confirmacao": SENHA_MASTER,
    }
    base.update(extra)
    return base


@pytest.fixture
def master(cliente, codigo) -> dict:
    r = cliente.post("/api/setup/master", json=dados_master(codigo))
    assert r.status_code == 201, r.text
    return r.json()


@pytest.fixture
def token_master(cliente, master) -> str:
    r = cliente.post("/api/auth/login", json={"nome_usuario": "master", "senha": SENHA_MASTER})
    assert r.status_code == 200, r.text
    return r.json()["token"]


def auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def login(cliente, nome: str, senha: str) -> str:
    r = cliente.post("/api/auth/login", json={"nome_usuario": nome, "senha": senha})
    assert r.status_code == 200, r.text
    return r.json()["token"]


def criar_usuario(cliente, token: str, nome_usuario: str, permissoes=(), senha="Provisoria2026",
                  trocar=True, **extra) -> dict:
    """Cria um usuário pela API (como a Master) e, se pedido, já troca a senha provisória."""
    corpo = {"nome_completo": f"Usuário {nome_usuario}", "nome_usuario": nome_usuario,
             "email": f"{nome_usuario}@exemplo.com", "senha_provisoria": senha,
             "permissoes": list(permissoes)}
    corpo.update(extra)
    r = cliente.post("/api/usuarios", json=corpo, headers=auth(token))
    assert r.status_code == 201, r.text
    if trocar:
        t = login(cliente, nome_usuario, senha)
        r2 = cliente.post("/api/auth/trocar-senha", headers=auth(t), json={
            "senha_atual": senha, "nova_senha": "Definitiva2026", "nova_senha_confirmacao": "Definitiva2026"})
        assert r2.status_code == 200, r2.text
    return r.json()
