"""Recuperação da senha da Master, feita só no próprio servidor (comando de administrador)."""

from __future__ import annotations

from sqlalchemy import select

from advoga_server.models import Auditoria, Notificacao, Usuario
from advoga_server.services.recuperacao_master import recuperar_senha_master, senha_provisoria
from tests.conftest import SENHA_MASTER, auth


def test_senha_provisoria_forte():
    for _ in range(50):
        s = senha_provisoria()
        assert len(s) == 12 and any(c.isdigit() for c in s) and any(c.isalpha() for c in s)
        assert not set(s) & set("0O1lI")


def test_recuperar_senha_da_master(cliente, db, token_master):
    # A Master esqueceu a senha e ficou bloqueada de tanto tentar
    for _ in range(6):
        cliente.post("/api/auth/login", json={"nome_usuario": "master", "senha": "esqueci"})
    master, senha = recuperar_senha_master(db)
    db.commit()
    assert master.nome_usuario == "master"
    # A senha antiga não funciona mais e a sessão aberta foi encerrada
    assert cliente.post("/api/auth/login", json={"nome_usuario": "master", "senha": SENHA_MASTER}).status_code == 401
    assert cliente.get("/api/auth/eu", headers=auth(token_master)).status_code == 401
    # A provisória entra (desbloqueada) e exige a troca da senha
    r = cliente.post("/api/auth/login", json={"nome_usuario": "master", "senha": senha})
    assert r.status_code == 200, r.text
    assert r.json()["usuario"]["deve_trocar_senha"] is True
    db.expire_all()
    assert db.scalar(select(Auditoria).where(Auditoria.acao == "usuario.senha_master_recuperada")) is not None
    aviso = db.scalar(select(Notificacao).where(Notificacao.usuario_id == master.id,
                                                Notificacao.titulo.like("A senha da conta Master%")))
    assert aviso is not None and "Se não foi você" in aviso.mensagem
    assert db.scalar(select(Usuario).where(Usuario.is_master)).tentativas_falhas == 0


def test_sem_master_ainda(db, codigo):
    import pytest

    with pytest.raises(LookupError):
        recuperar_senha_master(db)
