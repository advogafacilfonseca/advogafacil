"""Processos e movimentações. Acesso exige a permissão "processos", verificada no servidor."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import JSONResponse
from sqlalchemy import select
from sqlalchemy.orm import Session
from sqlalchemy.orm.exc import StaleDataError

from advoga_shared.esquemas import (
    ItemAuditoria,
    Movimentacao,
    MovimentacaoCriar,
    OpcaoCliente,
    OpcaoProcesso,
    PaginaProcessos,
    Processo,
    ProcessoAtualizar,
    ProcessoCriar,
)
from advoga_shared.permissoes import Permissao

from ..models import Auditoria, Cliente, Usuario
from ..services import clientes as svc_clientes
from ..services import processos as svc
from .deps import Contexto, exige_alguma_permissao, exige_permissao, obter_db
from .idempotencia import executar_gravacao

rotas = APIRouter(prefix="/api", tags=["processos"])
_processos = exige_permissao(Permissao.PROCESSOS)
_escolher_cliente = exige_alguma_permissao(Permissao.CLIENTES, Permissao.PROCESSOS, Permissao.DOCUMENTOS)
_escolher_processo = exige_alguma_permissao(Permissao.PROCESSOS, Permissao.DOCUMENTOS)


def _gravar(db, ctx, request, acao, status=200) -> JSONResponse:
    try:
        return executar_gravacao(db, ctx, request, acao, status)
    except StaleDataError as exc:
        db.rollback()
        raise HTTPException(409, svc.MSG_CONFLITO) from exc


@rotas.get("/processos", response_model=PaginaProcessos)
def listar(
    q: str | None = Query(default=None, max_length=100),
    cliente_id: uuid.UUID | None = None,
    situacao: str | None = Query(default=None, pattern="^(em_andamento|suspenso|arquivado|encerrado)$"),
    responsavel_id: uuid.UUID | None = None,
    pagina: int = Query(default=1, ge=1),
    por_pagina: int = Query(default=50, ge=1, le=200),
    ctx: Contexto = Depends(_processos),
    db: Session = Depends(obter_db),
) -> PaginaProcessos:
    itens, total = svc.buscar(db, termo=q, cliente_id=cliente_id, situacao=situacao, responsavel_id=responsavel_id,
                              offset=(pagina - 1) * por_pagina, limite=por_pagina)
    return PaginaProcessos(itens=itens, total=total, pagina=pagina, por_pagina=por_pagina)


@rotas.get("/processos/{processo_id}", response_model=Processo)
def obter(processo_id: uuid.UUID, ctx: Contexto = Depends(_processos), db: Session = Depends(obter_db)) -> Processo:
    return svc.saida(db, svc.obter(db, processo_id))


@rotas.post("/processos", response_model=Processo, status_code=201)
def criar(dados: ProcessoCriar, request: Request, ctx: Contexto = Depends(_processos),
          db: Session = Depends(obter_db)) -> JSONResponse:
    return _gravar(db, ctx, request, lambda: svc.saida(db, svc.criar(db, ctx.usuario, dados, ctx.ip)), 201)


@rotas.patch("/processos/{processo_id}", response_model=Processo)
def atualizar(processo_id: uuid.UUID, dados: ProcessoAtualizar, request: Request,
              ctx: Contexto = Depends(_processos), db: Session = Depends(obter_db)) -> JSONResponse:
    return _gravar(db, ctx, request, lambda: svc.saida(
        db, svc.atualizar(db, ctx.usuario, svc.obter(db, processo_id), dados, ctx.ip)))


@rotas.get("/processos/{processo_id}/movimentacoes", response_model=list[Movimentacao])
def movimentacoes(processo_id: uuid.UUID, ctx: Contexto = Depends(_processos),
                  db: Session = Depends(obter_db)) -> list[Movimentacao]:
    svc.obter(db, processo_id)
    return svc.movimentacoes(db, processo_id)


@rotas.post("/processos/{processo_id}/movimentacoes", response_model=Movimentacao, status_code=201)
def nova_movimentacao(processo_id: uuid.UUID, dados: MovimentacaoCriar, request: Request,
                      ctx: Contexto = Depends(_processos), db: Session = Depends(obter_db)) -> JSONResponse:
    return _gravar(db, ctx, request, lambda: svc.registrar_movimentacao(
        db, ctx.usuario, svc.obter(db, processo_id), dados, ctx.ip), 201)


@rotas.get("/processos/{processo_id}/historico", response_model=list[ItemAuditoria])
def historico(processo_id: uuid.UUID, ctx: Contexto = Depends(_processos),
              db: Session = Depends(obter_db)) -> list[ItemAuditoria]:
    svc.obter(db, processo_id)
    linhas = db.execute(
        select(Auditoria, Usuario.nome_completo)
        .outerjoin(Usuario, Usuario.id == Auditoria.usuario_id)
        .where(Auditoria.entidade == "processo", Auditoria.entidade_id == str(processo_id))
        .order_by(Auditoria.ocorrido_em.desc(), Auditoria.id.desc()).limit(500)
    ).all()
    return [ItemAuditoria(id=a.id, ocorrido_em=a.ocorrido_em, usuario_id=a.usuario_id, usuario_nome=nome,
                          acao=a.acao, entidade=a.entidade, entidade_id=a.entidade_id, detalhes=a.detalhes,
                          ip=None) for a, nome in linhas]


@rotas.get("/clientes-opcoes", response_model=list[OpcaoCliente])
def clientes_opcoes(q: str = Query(..., max_length=100), ctx: Contexto = Depends(_escolher_cliente),
                    db: Session = Depends(obter_db)) -> list[OpcaoCliente]:
    """Somente id, nome e situação, para escolher o cliente de um processo ou documento."""
    termo = " ".join(q.split())
    if len(termo) < 3:
        raise HTTPException(422, "Digite pelo menos 3 caracteres para pesquisar.")
    cond = svc_clientes.filtro_texto(termo)
    if cond is None:
        return []
    clientes = db.scalars(select(Cliente).where(cond).order_by(Cliente.nome_completo).limit(30)).all()
    return [OpcaoCliente(id=c.id, nome=c.nome_completo, situacao=c.situacao) for c in clientes]


@rotas.get("/clientes-opcoes/{cliente_id}", response_model=OpcaoCliente)
def cliente_opcao(cliente_id: uuid.UUID, ctx: Contexto = Depends(_escolher_cliente),
                  db: Session = Depends(obter_db)) -> OpcaoCliente:
    c = svc_clientes.obter(db, cliente_id)
    return OpcaoCliente(id=c.id, nome=c.nome_completo, situacao=c.situacao)


@rotas.get("/processos-opcoes", response_model=list[OpcaoProcesso])
def processos_opcoes(cliente_id: uuid.UUID, ctx: Contexto = Depends(_escolher_processo),
                     db: Session = Depends(obter_db)) -> list[OpcaoProcesso]:
    return [OpcaoProcesso(id=i, rotulo=r) for i, r in svc.opcoes(db, cliente_id)]
