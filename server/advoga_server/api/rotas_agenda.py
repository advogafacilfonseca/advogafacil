"""Agenda (permissão "agenda") e Central de Pendências (permissão "pendencias").

Quem tem só "pendencias" consulta os compromissos e pode concluir, reagendar e atribuir;
criar, editar e cancelar exigem "agenda". Parcelas só aparecem na central com "financeiro".
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import JSONResponse
from sqlalchemy import select
from sqlalchemy.orm import Session
from sqlalchemy.orm.exc import StaleDataError

from advoga_shared.esquemas import (
    PRIORIDADES,
    TIPOS_COMPROMISSO,
    AvisoAgenda,
    CentralPendencias,
    Compromisso,
    CompromissoAtribuir,
    CompromissoAtualizar,
    CompromissoCancelar,
    CompromissoConcluir,
    CompromissoCriar,
    CompromissoReagendar,
    ItemAuditoria,
    PaginaCompromissos,
)
from advoga_shared.permissoes import Permissao

from ..models import Auditoria, Usuario
from ..services import agenda as svc
from .deps import Contexto, exige_alguma_permissao, exige_permissao, obter_db
from .idempotencia import executar_gravacao

rotas = APIRouter(prefix="/api", tags=["agenda"])
_agenda = exige_permissao(Permissao.AGENDA)
_consultar = exige_alguma_permissao(Permissao.AGENDA, Permissao.PENDENCIAS)
_pendencias = exige_permissao(Permissao.PENDENCIAS)
_PADRAO_TIPO = "^(" + "|".join(TIPOS_COMPROMISSO) + ")$"
_PADRAO_PRIORIDADE = "^(" + "|".join(PRIORIDADES) + ")$"


def _gravar(db, ctx, request, acao, status=200) -> JSONResponse:
    try:
        return executar_gravacao(db, ctx, request, acao, status)
    except StaleDataError as exc:
        db.rollback()
        raise HTTPException(409, svc.MSG_CONFLITO) from exc


def _validar_periodo(inicio: datetime | None, fim: datetime | None) -> None:
    for v in (inicio, fim):
        if v is not None and v.tzinfo is None:
            raise HTTPException(422, "Data e hora sem fuso horário.")
    if inicio and fim and fim <= inicio:
        raise HTTPException(422, "Período inválido: o fim deve ser depois do início.")
    if inicio and fim and fim - inicio > timedelta(days=400):
        raise HTTPException(422, "Período muito longo: consulte no máximo 400 dias por vez.")


@rotas.get("/agenda/compromissos", response_model=PaginaCompromissos)
def listar(
    inicio: datetime | None = None,
    fim: datetime | None = None,
    responsavel_id: uuid.UUID | None = None,
    cliente_id: uuid.UUID | None = None,
    processo_id: uuid.UUID | None = None,
    tipo: str | None = Query(default=None, pattern=_PADRAO_TIPO),
    situacao: str | None = Query(default=None, pattern="^(agendado|concluido|cancelado|atrasado)$"),
    prioridade: str | None = Query(default=None, pattern=_PADRAO_PRIORIDADE),
    q: str | None = Query(default=None, max_length=100),
    pagina: int = Query(default=1, ge=1),
    por_pagina: int = Query(default=500, ge=1, le=1000),
    ctx: Contexto = Depends(_consultar),
    db: Session = Depends(obter_db),
) -> PaginaCompromissos:
    _validar_periodo(inicio, fim)
    itens, total = svc.listar(db, inicio=inicio, fim=fim, responsavel_id=responsavel_id, cliente_id=cliente_id,
                              processo_id=processo_id, tipo=tipo, situacao=situacao, prioridade=prioridade,
                              termo=" ".join((q or "").split()) or None, offset=(pagina - 1) * por_pagina,
                              limite=por_pagina)
    return PaginaCompromissos(itens=[svc.saida(db, c) for c in itens], total=total)


@rotas.get("/agenda/avisos", response_model=list[AvisoAgenda])
def avisos(somente_meus: bool = False, ctx: Contexto = Depends(_consultar),
           db: Session = Depends(obter_db)) -> list[AvisoAgenda]:
    return svc.avisos(db, ctx.usuario.id if somente_meus else None)


@rotas.get("/agenda/compromissos/{compromisso_id}", response_model=Compromisso)
def obter(compromisso_id: uuid.UUID, ctx: Contexto = Depends(_consultar),
          db: Session = Depends(obter_db)) -> Compromisso:
    return svc.saida(db, svc.obter(db, compromisso_id))


@rotas.post("/agenda/compromissos", response_model=Compromisso, status_code=201)
def criar(dados: CompromissoCriar, request: Request, ctx: Contexto = Depends(_agenda),
          db: Session = Depends(obter_db)) -> JSONResponse:
    return _gravar(db, ctx, request, lambda: svc.saida(db, svc.criar(db, ctx.usuario, dados, ctx.ip)), 201)


@rotas.patch("/agenda/compromissos/{compromisso_id}", response_model=Compromisso)
def atualizar(compromisso_id: uuid.UUID, dados: CompromissoAtualizar, request: Request,
              ctx: Contexto = Depends(_agenda), db: Session = Depends(obter_db)) -> JSONResponse:
    return _gravar(db, ctx, request, lambda: svc.saida(
        db, svc.atualizar(db, ctx.usuario, svc.obter(db, compromisso_id, travar=True), dados, ctx.ip)))


@rotas.post("/agenda/compromissos/{compromisso_id}/reagendar", response_model=Compromisso)
def reagendar(compromisso_id: uuid.UUID, dados: CompromissoReagendar, request: Request,
              ctx: Contexto = Depends(_consultar), db: Session = Depends(obter_db)) -> JSONResponse:
    return _gravar(db, ctx, request, lambda: svc.saida(
        db, svc.reagendar(db, ctx.usuario, svc.obter(db, compromisso_id, travar=True), dados, ctx.ip)))


@rotas.post("/agenda/compromissos/{compromisso_id}/concluir", response_model=Compromisso)
def concluir(compromisso_id: uuid.UUID, dados: CompromissoConcluir, request: Request,
             ctx: Contexto = Depends(_consultar), db: Session = Depends(obter_db)) -> JSONResponse:
    return _gravar(db, ctx, request, lambda: svc.saida(
        db, svc.concluir(db, ctx.usuario, svc.obter(db, compromisso_id, travar=True), dados, ctx.ip)))


@rotas.post("/agenda/compromissos/{compromisso_id}/atribuir", response_model=Compromisso)
def atribuir(compromisso_id: uuid.UUID, dados: CompromissoAtribuir, request: Request,
             ctx: Contexto = Depends(_consultar), db: Session = Depends(obter_db)) -> JSONResponse:
    return _gravar(db, ctx, request, lambda: svc.saida(
        db, svc.atribuir(db, ctx.usuario, svc.obter(db, compromisso_id, travar=True), dados, ctx.ip)))


@rotas.post("/agenda/compromissos/{compromisso_id}/cancelar", response_model=Compromisso)
def cancelar(compromisso_id: uuid.UUID, dados: CompromissoCancelar, request: Request,
             ctx: Contexto = Depends(_agenda), db: Session = Depends(obter_db)) -> JSONResponse:
    return _gravar(db, ctx, request, lambda: svc.saida(
        db, svc.cancelar(db, ctx.usuario, svc.obter(db, compromisso_id, travar=True), dados, ctx.ip)))


@rotas.get("/agenda/compromissos/{compromisso_id}/historico", response_model=list[ItemAuditoria])
def historico(compromisso_id: uuid.UUID, ctx: Contexto = Depends(_consultar),
              db: Session = Depends(obter_db)) -> list[ItemAuditoria]:
    svc.obter(db, compromisso_id)
    linhas = db.execute(
        select(Auditoria, Usuario.nome_completo)
        .outerjoin(Usuario, Usuario.id == Auditoria.usuario_id)
        .where(Auditoria.entidade == "compromisso", Auditoria.entidade_id == str(compromisso_id))
        .order_by(Auditoria.ocorrido_em.desc(), Auditoria.id.desc()).limit(500)
    ).all()
    return [ItemAuditoria(id=a.id, ocorrido_em=a.ocorrido_em, usuario_id=a.usuario_id, usuario_nome=nome,
                          acao=a.acao, entidade=a.entidade, entidade_id=a.entidade_id, detalhes=a.detalhes,
                          ip=None) for a, nome in linhas]


@rotas.get("/pendencias", response_model=CentralPendencias)
def central(
    desde: date | None = None,
    ate: date | None = None,
    responsavel_id: uuid.UUID | None = None,
    sem_responsavel: bool = False,
    cliente_id: uuid.UUID | None = None,
    processo_id: uuid.UUID | None = None,
    tipo: str | None = Query(default=None, pattern=_PADRAO_TIPO[:-2] + "|financeiro)$"),
    prioridade: str | None = Query(default=None, pattern=_PADRAO_PRIORIDADE),
    situacao: str = Query(default="pendente", pattern="^(pendente|atrasado|concluido|cancelado)$"),
    ctx: Contexto = Depends(_pendencias),
    db: Session = Depends(obter_db),
) -> CentralPendencias:
    if desde and ate and ate < desde:
        raise HTTPException(422, "Período inválido: a data final é anterior à inicial.")
    return svc.central(db, ctx.usuario, ctx.pode(Permissao.FINANCEIRO), ate=ate, desde=desde,
                       responsavel_id=responsavel_id, sem_responsavel=sem_responsavel, cliente_id=cliente_id,
                       processo_id=processo_id, tipo=tipo, prioridade=prioridade, situacao=situacao)
