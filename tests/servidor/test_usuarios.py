"""Gerenciamento de Usuários e Permissões."""

from __future__ import annotations

import uuid

from sqlalchemy import func, select

from advoga_server.models import Auditoria, Usuario
from tests.conftest import SENHA_MASTER, auth, criar_usuario, login

SENHA = "Definitiva2026"


def test_master_cria_usuario_com_senha_provisoria(cliente, token_master, db):
    u = criar_usuario(cliente, token_master, "adv2", permissoes=["clientes", "agenda"], trocar=False,
                      cargo="Advogado associado")
    assert u["deve_trocar_senha"] is True
    assert u["permissoes"] == ["agenda", "clientes"]
    assert u["cargo"] == "Advogado associado" and u["is_master"] is False
    # Com senha provisória, só consegue trocar a senha
    t = login(cliente, "adv2", "Provisoria2026")
    r = cliente.get("/api/usuarios", headers=auth(t))
    assert r.status_code == 403 and "senha provisória" in r.json()["detail"]
    assert cliente.get("/api/auth/eu", headers=auth(t)).json()["deve_trocar_senha"] is True
    assert "usuario.criado" in db.scalars(select(Auditoria.acao)).all()


def test_nome_de_usuario_duplicado(cliente, token_master):
    criar_usuario(cliente, token_master, "adv2", trocar=False)
    r = cliente.post("/api/usuarios", headers=auth(token_master), json={
        "nome_completo": "Outro", "nome_usuario": "ADV2", "email": "o@exemplo.com",
        "senha_provisoria": "Provisoria2026"})
    assert r.status_code == 409


def test_sem_permissao_admin_nao_lista_nem_cria(cliente, token_master):
    criar_usuario(cliente, token_master, "comum", permissoes=["clientes"])
    t = login(cliente, "comum", SENHA)
    assert cliente.get("/api/usuarios", headers=auth(t)).status_code == 403
    r = cliente.post("/api/usuarios", headers=auth(t), json={
        "nome_completo": "Invasor", "nome_usuario": "invasor", "email": "i@exemplo.com",
        "senha_provisoria": "Provisoria2026"})
    assert r.status_code == 403


def test_somente_master_concede_permissoes(cliente, token_master):
    admin = criar_usuario(cliente, token_master, "admin", permissoes=["admin_usuarios"])
    alvo = criar_usuario(cliente, token_master, "alvo", permissoes=["clientes"])
    t = login(cliente, "admin", SENHA)
    # Admin comum não concede permissões, nem na criação
    r = cliente.put(f"/api/usuarios/{alvo['id']}/permissoes", headers=auth(t), json={"permissoes": ["financeiro"]})
    assert r.status_code == 403
    r = cliente.post("/api/usuarios", headers=auth(t), json={
        "nome_completo": "Novo", "nome_usuario": "novo", "email": "n@exemplo.com",
        "senha_provisoria": "Provisoria2026", "permissoes": ["financeiro"]})
    assert r.status_code == 403
    # Nem a si mesmo
    r = cliente.put(f"/api/usuarios/{admin['id']}/permissoes", headers=auth(t),
                    json={"permissoes": ["admin_usuarios", "financeiro"]})
    assert r.status_code == 403
    # A Master concede
    r = cliente.put(f"/api/usuarios/{alvo['id']}/permissoes", headers=auth(token_master),
                    json={"permissoes": ["clientes", "financeiro"]})
    assert r.status_code == 200 and r.json()["permissoes"] == ["clientes", "financeiro"]


def test_permissoes_da_master_nao_mudam(cliente, token_master, master):
    r = cliente.put(f"/api/usuarios/{master['id']}/permissoes", headers=auth(token_master), json={"permissoes": []})
    assert r.status_code == 400


def test_admin_comum_nao_altera_master_nem_outro_admin(cliente, token_master, master):
    criar_usuario(cliente, token_master, "admin", permissoes=["admin_usuarios"])
    outro = criar_usuario(cliente, token_master, "admin2", permissoes=["admin_usuarios"])
    t = login(cliente, "admin", SENHA)
    assert cliente.patch(f"/api/usuarios/{master['id']}", headers=auth(t), json={"cargo": "Estagiária"}).status_code == 403
    assert cliente.post(f"/api/usuarios/{outro['id']}/desativar", headers=auth(t)).status_code == 403
    assert cliente.post(f"/api/usuarios/{master['id']}/redefinir-senha", headers=auth(t),
                        json={"senha_provisoria": "Provisoria2026"}).status_code == 400


def test_alterar_cargo_para_master_nao_da_poder(cliente, token_master, db):
    u = criar_usuario(cliente, token_master, "adv3")
    r = cliente.patch(f"/api/usuarios/{u['id']}", headers=auth(token_master),
                      json={"cargo": "Advogada Master", "nome_exibicao": "Master"})
    assert r.status_code == 200
    corpo = r.json()
    assert corpo["cargo"] == "Advogada Master" and corpo["is_master"] is False and corpo["permissoes"] == []
    assert db.scalar(select(func.count()).select_from(Usuario).where(Usuario.is_master)) == 1


def test_desativar_preserva_historico_e_encerra_sessao(cliente, token_master, db):
    u = criar_usuario(cliente, token_master, "adv2", permissoes=["clientes"])
    t = login(cliente, "adv2", SENHA)
    r = cliente.post(f"/api/usuarios/{u['id']}/desativar", headers=auth(token_master))
    assert r.status_code == 200 and r.json()["ativo"] is False and r.json()["sessoes_ativas"] == 0
    assert cliente.get("/api/auth/eu", headers=auth(t)).status_code in (401, 403)
    assert cliente.post("/api/auth/login", json={"nome_usuario": "adv2", "senha": SENHA}).status_code == 403
    # O histórico continua lá, ligado ao identificador do usuário
    acoes = db.scalars(select(Auditoria.acao).where(Auditoria.usuario_id == uuid.UUID(u["id"]))).all()
    assert "login.sucesso" in acoes
    assert db.get(Usuario, uuid.UUID(u["id"])) is not None
    # Reativar
    r = cliente.post(f"/api/usuarios/{u['id']}/reativar", headers=auth(token_master))
    assert r.json()["ativo"] is True
    assert cliente.post("/api/auth/login", json={"nome_usuario": "adv2", "senha": SENHA}).status_code == 200


def test_master_nao_pode_ser_desativada_nem_se_desativar(cliente, token_master, master):
    r = cliente.post(f"/api/usuarios/{master['id']}/desativar", headers=auth(token_master))
    assert r.status_code == 400


def test_redefinir_senha_exige_troca_e_encerra_sessoes(cliente, token_master):
    u = criar_usuario(cliente, token_master, "adv2")
    t = login(cliente, "adv2", SENHA)
    r = cliente.post(f"/api/usuarios/{u['id']}/redefinir-senha", headers=auth(token_master),
                     json={"senha_provisoria": "NovaProvisoria2026"})
    assert r.status_code == 200 and r.json()["deve_trocar_senha"] is True
    assert cliente.get("/api/auth/eu", headers=auth(t)).status_code == 401
    assert cliente.post("/api/auth/login", json={"nome_usuario": "adv2", "senha": SENHA}).status_code == 401
    assert cliente.post("/api/auth/login", json={"nome_usuario": "adv2", "senha": "NovaProvisoria2026"}).status_code == 200


def test_mesma_chave_de_operacao_nao_duplica_cadastro(cliente, token_master, db):
    h = auth(token_master) | {"Idempotency-Key": "chave-de-teste-123"}
    corpo = {"nome_completo": "Repetido", "nome_usuario": "repetido", "email": "r@exemplo.com",
             "senha_provisoria": "Provisoria2026"}
    r1 = cliente.post("/api/usuarios", headers=h, json=corpo)
    r2 = cliente.post("/api/usuarios", headers=h, json=corpo)
    assert r1.status_code == r2.status_code == 201
    assert r1.json()["id"] == r2.json()["id"]
    assert db.scalar(select(func.count()).select_from(Usuario).where(Usuario.nome_usuario == "repetido")) == 1
    criados = db.scalar(select(func.count()).select_from(Auditoria).where(Auditoria.acao == "usuario.criado"))
    assert criados == 1


def test_auditoria_somente_master(cliente, token_master):
    criar_usuario(cliente, token_master, "admin", permissoes=["admin_usuarios", "configuracoes"])
    t = login(cliente, "admin", SENHA)
    assert cliente.get("/api/auditoria", headers=auth(t)).status_code == 403
    r = cliente.get("/api/auditoria", headers=auth(token_master), params={"acao": "usuario.criado"})
    assert r.status_code == 200
    corpo = r.json()
    assert corpo["total"] >= 1
    assert all(i["acao"] == "usuario.criado" for i in corpo["itens"])
    assert corpo["itens"][0]["usuario_nome"] == "Maria Advogada Teste"


def test_master_troca_senha_normalmente(cliente, token_master):
    r = cliente.post("/api/auth/trocar-senha", headers=auth(token_master), json={
        "senha_atual": SENHA_MASTER, "nova_senha": "OutraSenha2026", "nova_senha_confirmacao": "OutraSenha2026"})
    assert r.status_code == 200
