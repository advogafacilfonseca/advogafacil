"""O servidor bloqueia rotas sem permissão, independentemente da interface."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import select

from advoga_server.api.deps import Contexto, exige_master, exige_permissao
from advoga_server.core.seguranca import gerar_hash_senha
from advoga_server.models import Auditoria, PermissaoUsuario, Usuario
from advoga_shared.permissoes import Permissao


def _app_com_rota_protegida(app):
    r = APIRouter()

    @r.get("/api/teste/financeiro")
    def fin(ctx: Contexto = Depends(exige_permissao(Permissao.FINANCEIRO))):
        return {"ok": True}

    @r.get("/api/teste/master")
    def mst(ctx: Contexto = Depends(exige_master)):
        return {"ok": True}

    app.include_router(r)
    return app


def _login(cliente, nome, senha):
    return {"Authorization": "Bearer " + cliente.post(
        "/api/auth/login", json={"nome_usuario": nome, "senha": senha}).json()["token"]}


def test_financeiro_bloqueado_para_quem_nao_tem_permissao(app, cliente, master, db, token_master):
    _app_com_rota_protegida(app)
    sem = Usuario(nome_completo="Sem Financeiro", nome_exibicao="Sem", nome_usuario="semfin",
                  email="s@exemplo.com", senha_hash=gerar_hash_senha("SenhaComum2026"))
    sem.permissoes = [PermissaoUsuario(permissao="clientes")]
    com = Usuario(nome_completo="Com Financeiro", nome_exibicao="Com", nome_usuario="comfin",
                  email="c@exemplo.com", senha_hash=gerar_hash_senha("SenhaComum2026"))
    com.permissoes = [PermissaoUsuario(permissao="financeiro")]
    db.add_all([sem, com])
    db.commit()

    r = cliente.get("/api/teste/financeiro", headers=_login(cliente, "semfin", "SenhaComum2026"))
    assert r.status_code == 403
    assert cliente.get("/api/teste/financeiro", headers=_login(cliente, "comfin", "SenhaComum2026")).status_code == 200
    assert cliente.get("/api/teste/financeiro", headers={"Authorization": f"Bearer {token_master}"}).status_code == 200
    assert db.scalar(select(Auditoria).where(Auditoria.acao == "acesso.negado")) is not None


def test_rota_de_master_bloqueada_para_comum_mesmo_com_todas_permissoes(app, cliente, master, db):
    _app_com_rota_protegida(app)
    u = Usuario(nome_completo="Quase Master", nome_exibicao="Quase", nome_usuario="quase",
                email="q@exemplo.com", senha_hash=gerar_hash_senha("SenhaComum2026"))
    u.permissoes = [PermissaoUsuario(permissao=p.value) for p in Permissao]
    db.add(u)
    db.commit()
    assert cliente.get("/api/teste/master", headers=_login(cliente, "quase", "SenhaComum2026")).status_code == 403
