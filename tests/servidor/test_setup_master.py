"""Criação da conta Master: protegida, única e auditada."""

from __future__ import annotations

import threading

import pytest
from sqlalchemy import create_engine, func, select, text
from sqlalchemy.exc import DBAPIError

from advoga_server.models import Auditoria, Configuracao, Usuario
from advoga_server.services.servidor import CHAVE_CODIGO

from .conftest import SENHA_MASTER, dados_master


def test_saude_informa_nao_configurado(cliente, codigo):
    r = cliente.get("/api/saude")
    assert r.status_code == 200
    corpo = r.json()
    assert corpo["banco"] == "ok"
    assert corpo["configurado"] is False
    assert corpo["servidor_status"] == "ativo"


def test_criar_master_com_codigo_valido(cliente, codigo, cfg, db):
    assert cfg.arquivo_codigo_instalacao.exists()
    r = cliente.post("/api/setup/master", json=dados_master(codigo))
    assert r.status_code == 201, r.text
    corpo = r.json()
    assert corpo["is_master"] is True
    assert corpo["nome_usuario"] == "master"
    assert len(corpo["permissoes"]) == 10  # Master tem todas as permissões
    # Código de uso único: some do banco e do disco
    assert db.get(Configuracao, CHAVE_CODIGO) is None
    assert not cfg.arquivo_codigo_instalacao.exists()
    assert cliente.get("/api/setup/status").json() == {"configurado": True}
    acoes = db.scalars(select(Auditoria.acao)).all()
    assert "setup.master_criada" in acoes


def test_senha_guardada_com_hash_argon2(cliente, master, db):
    u = db.scalar(select(Usuario).where(Usuario.nome_usuario == "master"))
    assert u.senha_hash.startswith("$argon2id$")
    assert SENHA_MASTER not in u.senha_hash


def test_codigo_invalido_e_recusado(cliente, codigo, db):
    r = cliente.post("/api/setup/master", json=dados_master("AAAA-BBBB-CCCC"))
    assert r.status_code == 403
    assert db.scalar(select(func.count()).select_from(Usuario)) == 0
    assert "setup.codigo_invalido" in db.scalars(select(Auditoria.acao)).all()


def test_segunda_master_e_impossivel_pela_api(cliente, master, codigo):
    r = cliente.post("/api/setup/master", json=dados_master(codigo, nome_usuario="outra"))
    assert r.status_code == 409


def test_validacoes_em_portugues(cliente, codigo):
    r = cliente.post("/api/setup/master", json=dados_master(codigo, senha="curta", senha_confirmacao="curta"))
    assert r.status_code == 422
    assert "pelo menos 10 caracteres" in r.json()["detail"]
    r = cliente.post("/api/setup/master", json=dados_master(codigo, senha_confirmacao="OutraSenha2026"))
    assert r.status_code == 422
    assert "confirmação de senha não confere" in r.json()["detail"]
    r = cliente.post("/api/setup/master", json=dados_master(codigo, email="invalido"))
    assert "e-mail válido" in r.json()["detail"]
    r = cliente.post("/api/setup/master", json=dados_master(codigo, nome_usuario="Nome Com Espaço"))
    assert "nome de usuário" in r.json()["detail"].lower()


def test_criacao_simultanea_gera_uma_unica_master(app, codigo, db):
    from fastapi.testclient import TestClient

    resultados: list[int] = []

    def tentar(i: int) -> None:
        with TestClient(app) as c:
            r = c.post("/api/setup/master", json=dados_master(codigo, nome_usuario=f"master{i}"))
            resultados.append(r.status_code)

    threads = [threading.Thread(target=tentar, args=(i,)) for i in range(5)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert sorted(resultados).count(201) == 1
    assert db.scalar(select(func.count()).select_from(Usuario).where(Usuario.is_master)) == 1


# ---- Proteções diretamente no banco de dados (defesa mesmo fora da API) ----


def _executar(url: str, sql: str, **params) -> None:
    eng = create_engine(url)
    try:
        with eng.begin() as c:
            c.execute(text(sql), params)
    finally:
        eng.dispose()


def test_banco_recusa_inserir_master_fora_do_assistente(url_banco, banco_limpo):
    with pytest.raises(DBAPIError, match="assistente de configuração"):
        _executar(url_banco, "INSERT INTO usuarios (id, nome_completo, nome_exibicao, nome_usuario, "
                  "email, senha_hash, is_master) VALUES (gen_random_uuid(), 'X', 'X', 'x', 'x@x.test', 'h', true)")


def test_banco_recusa_promover_usuario_a_master(url_banco, master):
    _executar(url_banco, "INSERT INTO usuarios (id, nome_completo, nome_exibicao, nome_usuario, email, "
              "senha_hash) VALUES (gen_random_uuid(), 'Comum', 'Comum', 'comum', 'c@x.test', 'h')")
    with pytest.raises(DBAPIError, match="não pode ser concedida"):
        _executar(url_banco, "UPDATE usuarios SET is_master = true WHERE nome_usuario = 'comum'")


def test_banco_recusa_desativar_ou_apagar_master(url_banco, master):
    with pytest.raises(DBAPIError, match="não pode ser desativada"):
        _executar(url_banco, "UPDATE usuarios SET ativo = false WHERE is_master")
    with pytest.raises(DBAPIError, match="não podem ser apagados"):
        _executar(url_banco, "DELETE FROM usuarios WHERE is_master")


def test_banco_garante_master_unica_mesmo_autorizado(url_banco, master):
    with pytest.raises(DBAPIError):
        _executar(url_banco, "SET LOCAL advoga.criacao_master = 'autorizada'; "
                  "INSERT INTO usuarios (id, nome_completo, nome_exibicao, nome_usuario, email, senha_hash, "
                  "is_master) VALUES (gen_random_uuid(), 'X', 'X', 'x2', 'x@x.test', 'h', true)")


def test_auditoria_nao_pode_ser_alterada_nem_apagada(url_banco, master):
    with pytest.raises(DBAPIError, match="auditoria"):
        _executar(url_banco, "UPDATE auditoria SET acao = 'adulterado'")
    with pytest.raises(DBAPIError, match="auditoria"):
        _executar(url_banco, "DELETE FROM auditoria")
