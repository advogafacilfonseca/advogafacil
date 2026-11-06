"""Dependências comuns das rotas: sessão do banco, usuário logado e permissões."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from advoga_shared.permissoes import Permissao

from ..core.config import Configuracoes, obter_configuracoes
from ..core.db import obter_sessao as obter_db
from ..models import Sessao, Usuario
from ..services import auditoria
from ..services.autenticacao import ErroAutenticacao, permissoes_efetivas, validar_sessao


def obter_cfg() -> Configuracoes:
    return obter_configuracoes()


ROTAS_LIVRES_SENHA_PROVISORIA = {"/api/auth/eu", "/api/auth/trocar-senha", "/api/auth/logout"}


def ip_cliente(request: Request) -> str | None:
    return request.client.host if request.client else None


@dataclass
class Contexto:
    usuario: Usuario
    sessao: Sessao
    permissoes: set[Permissao]
    ip: str | None

    def pode(self, permissao: Permissao) -> bool:
        return permissao in self.permissoes


def usuario_atual(
    request: Request,
    db: Session = Depends(obter_db),
    cfg: Configuracoes = Depends(obter_cfg),
) -> Contexto:
    cabecalho = request.headers.get("Authorization", "")
    if not cabecalho.lower().startswith("bearer "):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Faça login para continuar.")
    token = cabecalho[7:].strip()
    try:
        sessao, usuario = validar_sessao(db, token, cfg)
    except ErroAutenticacao as exc:
        raise HTTPException(exc.status, exc.mensagem) from exc
    if usuario.deve_trocar_senha and request.url.path not in ROTAS_LIVRES_SENHA_PROVISORIA:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            "Você está usando uma senha provisória. Troque a senha para continuar.",
        )
    return Contexto(usuario, sessao, permissoes_efetivas(usuario), ip_cliente(request))


def exige_permissao(permissao: Permissao) -> Callable[..., Contexto]:
    """Bloqueia a rota no servidor quando o usuário não tem a permissão."""

    def _verificar(
        ctx: Contexto = Depends(usuario_atual), db: Session = Depends(obter_db)
    ) -> Contexto:
        if not ctx.pode(permissao):
            auditoria.registrar(
                db, "acesso.negado", usuario_id=ctx.usuario.id,
                detalhes={"permissao": permissao.value}, ip=ctx.ip,
            )
            db.commit()
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Você não tem permissão para acessar esta área.")
        return ctx

    return _verificar


def exige_master(ctx: Contexto = Depends(usuario_atual), db: Session = Depends(obter_db)) -> Contexto:
    if not ctx.usuario.is_master:
        auditoria.registrar(db, "acesso.negado", usuario_id=ctx.usuario.id,
                            detalhes={"exigido": "master"}, ip=ctx.ip)
        db.commit()
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Somente a Advogada Master pode fazer isso.")
    return ctx


def exige_alguma_permissao(*permissoes: Permissao) -> Callable[..., Contexto]:
    """Libera a rota para quem tiver pelo menos uma das permissões (ex.: escolher o cliente
    ao cadastrar um processo ou anexar um documento)."""

    def _verificar(
        ctx: Contexto = Depends(usuario_atual), db: Session = Depends(obter_db)
    ) -> Contexto:
        if not any(ctx.pode(p) for p in permissoes):
            auditoria.registrar(
                db, "acesso.negado", usuario_id=ctx.usuario.id,
                detalhes={"permissao": [p.value for p in permissoes]}, ip=ctx.ip,
            )
            db.commit()
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Você não tem permissão para acessar esta área.")
        return ctx

    return _verificar
