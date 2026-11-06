"""Clientes e pesquisa global. Acesso exige a permissão "clientes", verificada no servidor."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import JSONResponse
from sqlalchemy import select
from sqlalchemy.orm import Session
from sqlalchemy.orm.exc import StaleDataError

from advoga_shared.esquemas import (
    Cliente,
    ClienteAtualizar,
    ClienteCriar,
    ClienteEncerrar,
    ItemAuditoria,
    OpcaoUsuario,
    PaginaClientes,
    PaginaPesquisa,
    ResultadoPesquisa,
)
from advoga_shared.permissoes import Permissao

from ..models import Auditoria, Usuario
from ..services import clientes as svc
from ..services import documentos as svc_documentos
from ..services import processos as svc_processos
from .deps import Contexto, exige_permissao, obter_db, usuario_atual
from .idempotencia import executar_gravacao

rotas = APIRouter(prefix="/api", tags=["clientes"])
_clientes = exige_permissao(Permissao.CLIENTES)


def _gravar(db, ctx, request, acao, status=200) -> JSONResponse:
    try:
        return executar_gravacao(db, ctx, request, acao, status)
    except StaleDataError as exc:
        db.rollback()
        raise HTTPException(409, svc.MSG_CONFLITO) from exc


@rotas.get("/clientes", response_model=PaginaClientes)
def listar(
    q: str | None = Query(default=None, max_length=100),
    situacao: str | None = Query(default=None, pattern="^(ativo|encerrado)$"),
    pagina: int = Query(default=1, ge=1),
    por_pagina: int = Query(default=50, ge=1, le=200),
    ctx: Contexto = Depends(_clientes),
    db: Session = Depends(obter_db),
) -> PaginaClientes:
    itens, total = svc.buscar(db, q, situacao, pagina, por_pagina)
    return PaginaClientes(itens=itens, total=total, pagina=pagina, por_pagina=por_pagina)


@rotas.get("/clientes/{cliente_id}", response_model=Cliente)
def obter(cliente_id: uuid.UUID, ctx: Contexto = Depends(_clientes), db: Session = Depends(obter_db)) -> Cliente:
    return svc.saida(db, svc.obter(db, cliente_id))


@rotas.post("/clientes", response_model=Cliente, status_code=201)
def criar(dados: ClienteCriar, request: Request, ctx: Contexto = Depends(_clientes),
          db: Session = Depends(obter_db)) -> JSONResponse:
    return _gravar(db, ctx, request, lambda: svc.saida(db, svc.criar(db, ctx.usuario, dados, ctx.ip)), 201)


@rotas.patch("/clientes/{cliente_id}", response_model=Cliente)
def atualizar(cliente_id: uuid.UUID, dados: ClienteAtualizar, request: Request,
              ctx: Contexto = Depends(_clientes), db: Session = Depends(obter_db)) -> JSONResponse:
    return _gravar(db, ctx, request, lambda: svc.saida(
        db, svc.atualizar(db, ctx.usuario, svc.obter(db, cliente_id), dados, ctx.ip)))


@rotas.post("/clientes/{cliente_id}/encerrar", response_model=Cliente)
def encerrar(cliente_id: uuid.UUID, dados: ClienteEncerrar, request: Request,
             ctx: Contexto = Depends(_clientes), db: Session = Depends(obter_db)) -> JSONResponse:
    return _gravar(db, ctx, request, lambda: svc.saida(
        db, svc.encerrar(db, ctx.usuario, svc.obter(db, cliente_id), dados.motivo, dados.versao, ctx.ip)))


@rotas.post("/clientes/{cliente_id}/reativar", response_model=Cliente)
def reativar(cliente_id: uuid.UUID, request: Request, versao: int = Query(...),
             ctx: Contexto = Depends(_clientes), db: Session = Depends(obter_db)) -> JSONResponse:
    return _gravar(db, ctx, request, lambda: svc.saida(
        db, svc.reativar(db, ctx.usuario, svc.obter(db, cliente_id), versao, ctx.ip)))


@rotas.get("/clientes/{cliente_id}/historico", response_model=list[ItemAuditoria])
def historico(cliente_id: uuid.UUID, ctx: Contexto = Depends(_clientes),
              db: Session = Depends(obter_db)) -> list[ItemAuditoria]:
    svc.obter(db, cliente_id)
    linhas = db.execute(
        select(Auditoria, Usuario.nome_completo)
        .outerjoin(Usuario, Usuario.id == Auditoria.usuario_id)
        .where(Auditoria.entidade == "cliente", Auditoria.entidade_id == str(cliente_id))
        .order_by(Auditoria.ocorrido_em.desc(), Auditoria.id.desc()).limit(500)
    ).all()
    return [ItemAuditoria(id=a.id, ocorrido_em=a.ocorrido_em, usuario_id=a.usuario_id, usuario_nome=nome,
                          acao=a.acao, entidade=a.entidade, entidade_id=a.entidade_id, detalhes=a.detalhes,
                          ip=None) for a, nome in linhas]


@rotas.get("/pesquisa", response_model=PaginaPesquisa)
def pesquisa_global(
    q: str = Query(..., max_length=100),
    pagina: int = Query(default=1, ge=1),
    por_pagina: int = Query(default=20, ge=1, le=100),
    ctx: Contexto = Depends(usuario_atual),
    db: Session = Depends(obter_db),
) -> PaginaPesquisa:
    termo = " ".join(q.split())
    if len(termo) < 3:
        raise HTTPException(422, "Digite pelo menos 3 caracteres para pesquisar.")
    # Cada tipo de registro só entra no resultado se o usuário tiver a permissão correspondente.
    # A paginação percorre os tipos em sequência: clientes, processos, documentos.
    fontes = []
    if ctx.pode(Permissao.CLIENTES):
        fontes.append(lambda off, lim: _res_clientes(db, termo, off, lim))
    if ctx.pode(Permissao.PROCESSOS):
        fontes.append(lambda off, lim: _res_processos(db, termo, off, lim))
    if ctx.pode(Permissao.DOCUMENTOS):
        fontes.append(lambda off, lim: _res_documentos(db, termo, off, lim))
    itens: list[ResultadoPesquisa] = []
    total = 0
    inicio = (pagina - 1) * por_pagina
    for fonte in fontes:
        _, qtd = fonte(0, 0)
        if len(itens) < por_pagina and inicio < total + qtd:
            deslocamento = max(0, inicio - total)
            encontrados, _ = fonte(deslocamento, por_pagina - len(itens))
            itens.extend(encontrados)
        total += qtd
    return PaginaPesquisa(termo=termo, itens=itens, total=total, pagina=pagina, por_pagina=por_pagina)


def _res_clientes(db, termo, offset, limite):
    clientes, total = svc.buscar(db, termo, None, 1, limite, offset=offset)
    return [ResultadoPesquisa(tipo="cliente", id=c.id, titulo=c.nome_completo, resumo=svc.descricao_curta(c))
            for c in clientes], total


def _res_processos(db, termo, offset, limite):
    processos, total = svc_processos.buscar(db, termo=termo, offset=offset, limite=limite)
    return [ResultadoPesquisa(tipo="processo", id=p.id, titulo=svc_processos.rotulo(p),
                              resumo=svc_processos.descricao_curta(p)) for p in processos], total


def _res_documentos(db, termo, offset, limite):
    docs, total = svc_documentos.buscar(db, termo=termo, offset=offset, limite=limite)
    return [ResultadoPesquisa(tipo="documento", id=d.id, titulo=d.nome_arquivo,
                              resumo=svc_documentos.descricao_curta(d)) for d in docs], total


@rotas.get("/usuarios-ativos", response_model=list[OpcaoUsuario])
def usuarios_ativos(ctx: Contexto = Depends(usuario_atual), db: Session = Depends(obter_db)) -> list[OpcaoUsuario]:
    """Lista mínima (nome) para escolher responsáveis. Não expõe permissões nem dados de acesso."""
    return [OpcaoUsuario(id=u.id, nome=u.nome_completo)
            for u in db.scalars(select(Usuario).where(Usuario.ativo).order_by(Usuario.nome_completo))]
