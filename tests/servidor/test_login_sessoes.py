"""Login, sessões, bloqueio por tentativas e troca de senha."""

from __future__ import annotations

from datetime import timedelta

from sqlalchemy import select, text

from advoga_server.core.seguranca import gerar_hash_senha
from advoga_server.models import Auditoria, Sessao, Usuario
from advoga_server.services.autenticacao import agora

from .conftest import SENHA_MASTER


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def test_login_correto_retorna_token_e_dados(cliente, master):
    r = cliente.post("/api/auth/login", json={"nome_usuario": "MASTER ", "senha": SENHA_MASTER})
    assert r.status_code == 200
    corpo = r.json()
    assert corpo["token"] and corpo["usuario"]["is_master"] is True


def test_token_salvo_somente_como_hash(cliente, token_master, db):
    hashes = db.scalars(select(Sessao.token_hash)).all()
    assert token_master not in hashes and len(hashes) == 1


def test_senha_errada_e_usuario_inexistente_tem_mesma_mensagem(cliente, master):
    a = cliente.post("/api/auth/login", json={"nome_usuario": "master", "senha": "errada"})
    b = cliente.post("/api/auth/login", json={"nome_usuario": "ninguem", "senha": "errada"})
    assert a.status_code == b.status_code == 401
    assert a.json()["detail"] == b.json()["detail"] == "Usuário ou senha incorretos."


def test_bloqueio_apos_tentativas_erradas(cliente, master, db):
    for _ in range(3):
        assert cliente.post("/api/auth/login", json={"nome_usuario": "master", "senha": "x"}).status_code == 401
    r = cliente.post("/api/auth/login", json={"nome_usuario": "master", "senha": SENHA_MASTER})
    assert r.status_code == 423
    assert "bloqueado temporariamente" in r.json()["detail"]
    falhas = db.scalars(select(Auditoria).where(Auditoria.acao == "login.falha")).all()
    assert any((f.detalhes or {}).get("bloqueado") for f in falhas)


def test_rotas_protegidas_exigem_login(cliente, master):
    assert cliente.get("/api/auth/eu").status_code == 401
    assert cliente.get("/api/auth/eu", headers=_auth("token-falso")).status_code == 401


def test_eu_retorna_permissoes_da_master(cliente, token_master):
    r = cliente.get("/api/auth/eu", headers=_auth(token_master))
    assert r.status_code == 200
    assert "financeiro" in r.json()["permissoes"]


def test_logout_invalida_token(cliente, token_master):
    assert cliente.post("/api/auth/logout", headers=_auth(token_master)).status_code == 200
    assert cliente.get("/api/auth/eu", headers=_auth(token_master)).status_code == 401


def test_sessao_expira_por_inatividade(cliente, token_master, db):
    db.execute(text("UPDATE sessoes SET ultimo_uso_em = now() - interval '5 hours'"))
    db.commit()
    r = cliente.get("/api/auth/eu", headers=_auth(token_master))
    assert r.status_code == 401
    assert "expirou" in r.json()["detail"]


def test_sessao_expira_pelo_tempo_maximo(cliente, token_master, db):
    db.execute(text("UPDATE sessoes SET expira_em = now() - interval '1 minute'"))
    db.commit()
    assert cliente.get("/api/auth/eu", headers=_auth(token_master)).status_code == 401


def _criar_comum(db, nome="adv2", ativo=True, permissoes=()) -> Usuario:
    from advoga_server.models import PermissaoUsuario

    u = Usuario(nome_completo="Advogado Dois", nome_exibicao="Advogado", nome_usuario=nome,
                email=f"{nome}@exemplo.com", senha_hash=gerar_hash_senha("SenhaComum2026"), ativo=ativo)
    u.permissoes = [PermissaoUsuario(permissao=p) for p in permissoes]
    db.add(u)
    db.commit()
    return u


def test_usuario_comum_recebe_apenas_suas_permissoes(cliente, master, db):
    _criar_comum(db, permissoes=("clientes", "agenda"))
    r = cliente.post("/api/auth/login", json={"nome_usuario": "adv2", "senha": "SenhaComum2026"})
    assert r.status_code == 200
    assert r.json()["usuario"]["permissoes"] == ["agenda", "clientes"]
    assert r.json()["usuario"]["is_master"] is False


def test_cargo_com_nome_master_nao_concede_poder(cliente, master, db):
    u = _criar_comum(db, nome="impostor")
    u.cargo = "Advogada Master"
    u.nome_exibicao = "Master"
    db.commit()
    r = cliente.post("/api/auth/login", json={"nome_usuario": "impostor", "senha": "SenhaComum2026"})
    assert r.json()["usuario"]["is_master"] is False
    assert r.json()["usuario"]["permissoes"] == []


def test_usuario_desativado_nao_entra_e_perde_sessao(cliente, master, db):
    u = _criar_comum(db)
    token = cliente.post("/api/auth/login", json={"nome_usuario": "adv2", "senha": "SenhaComum2026"}).json()["token"]
    u.ativo = False
    u.desativado_em = agora()
    db.commit()
    assert cliente.get("/api/auth/eu", headers=_auth(token)).status_code == 403
    r = cliente.post("/api/auth/login", json={"nome_usuario": "adv2", "senha": "SenhaComum2026"})
    assert r.status_code == 403


def test_trocar_senha(cliente, token_master):
    h = _auth(token_master)
    r = cliente.post("/api/auth/trocar-senha", headers=h, json={
        "senha_atual": "errada", "nova_senha": "NovaSenha2026", "nova_senha_confirmacao": "NovaSenha2026"})
    assert r.status_code == 400
    r = cliente.post("/api/auth/trocar-senha", headers=h, json={
        "senha_atual": SENHA_MASTER, "nova_senha": "NovaSenha2026", "nova_senha_confirmacao": "NovaSenha2026"})
    assert r.status_code == 200
    assert cliente.post("/api/auth/login", json={"nome_usuario": "master", "senha": SENHA_MASTER}).status_code == 401
    assert cliente.post("/api/auth/login", json={"nome_usuario": "master", "senha": "NovaSenha2026"}).status_code == 200
