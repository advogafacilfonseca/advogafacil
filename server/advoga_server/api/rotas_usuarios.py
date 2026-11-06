"""Gerenciamento de Usuários e Permissões (verificado no servidor)."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from advoga_shared.esquemas import (
    PermissoesDefinir,
    RedefinirSenha,
    UsuarioAtualizar,
    UsuarioCriar,
    UsuarioDetalhe,
)
from advoga_shared.permissoes import Permissao

from ..services import usuarios as svc
from .deps import Contexto, exige_permissao, obter_db
from .idempotencia import executar_gravacao

rotas = APIRouter(prefix="/api/usuarios", tags=["usuários"])
_admin = exige_permissao(Permissao.ADMIN_USUARIOS)


@rotas.get("", response_model=list[UsuarioDetalhe])
def listar(ctx: Contexto = Depends(_admin), db: Session = Depends(obter_db)) -> list[UsuarioDetalhe]:
    return [svc.detalhe(db, u) for u in svc.listar(db)]


@rotas.get("/{usuario_id}", response_model=UsuarioDetalhe)
def obter(usuario_id: uuid.UUID, ctx: Contexto = Depends(_admin), db: Session = Depends(obter_db)) -> UsuarioDetalhe:
    return svc.detalhe(db, svc.obter(db, usuario_id))


@rotas.post("", response_model=UsuarioDetalhe, status_code=201)
def criar(dados: UsuarioCriar, request: Request, ctx: Contexto = Depends(_admin),
          db: Session = Depends(obter_db)) -> JSONResponse:
    return executar_gravacao(db, ctx, request,
                             lambda: svc.detalhe(db, svc.criar(db, ctx.usuario, dados, ctx.ip)), 201)


@rotas.patch("/{usuario_id}", response_model=UsuarioDetalhe)
def atualizar(usuario_id: uuid.UUID, dados: UsuarioAtualizar, request: Request,
              ctx: Contexto = Depends(_admin), db: Session = Depends(obter_db)) -> JSONResponse:
    return executar_gravacao(db, ctx, request, lambda: svc.detalhe(
        db, svc.atualizar(db, ctx.usuario, svc.obter(db, usuario_id), dados, ctx.ip)))


@rotas.put("/{usuario_id}/permissoes", response_model=UsuarioDetalhe)
def definir_permissoes(usuario_id: uuid.UUID, dados: PermissoesDefinir, request: Request,
                       ctx: Contexto = Depends(_admin), db: Session = Depends(obter_db)) -> JSONResponse:
    return executar_gravacao(db, ctx, request, lambda: svc.detalhe(
        db, svc.definir_permissoes(db, ctx.usuario, svc.obter(db, usuario_id), dados.permissoes, ctx.ip)))


@rotas.post("/{usuario_id}/desativar", response_model=UsuarioDetalhe)
def desativar(usuario_id: uuid.UUID, request: Request, ctx: Contexto = Depends(_admin),
              db: Session = Depends(obter_db)) -> JSONResponse:
    return executar_gravacao(db, ctx, request, lambda: svc.detalhe(
        db, svc.alterar_situacao(db, ctx.usuario, svc.obter(db, usuario_id), False, ctx.ip)))


@rotas.post("/{usuario_id}/reativar", response_model=UsuarioDetalhe)
def reativar(usuario_id: uuid.UUID, request: Request, ctx: Contexto = Depends(_admin),
             db: Session = Depends(obter_db)) -> JSONResponse:
    return executar_gravacao(db, ctx, request, lambda: svc.detalhe(
        db, svc.alterar_situacao(db, ctx.usuario, svc.obter(db, usuario_id), True, ctx.ip)))


@rotas.post("/{usuario_id}/redefinir-senha", response_model=UsuarioDetalhe)
def redefinir_senha(usuario_id: uuid.UUID, dados: RedefinirSenha, request: Request,
                    ctx: Contexto = Depends(_admin), db: Session = Depends(obter_db)) -> JSONResponse:
    return executar_gravacao(db, ctx, request, lambda: svc.detalhe(
        db, svc.redefinir_senha(db, ctx.usuario, svc.obter(db, usuario_id), dados.senha_provisoria, ctx.ip)))
