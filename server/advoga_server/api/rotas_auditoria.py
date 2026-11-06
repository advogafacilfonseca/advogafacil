"""Consulta dos registros de auditoria (somente a Master)."""

from __future__ import annotations

import uuid
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from advoga_shared.esquemas import ItemAuditoria, PaginaAuditoria

from ..models import Auditoria, Usuario
from .deps import Contexto, exige_master, obter_db

rotas = APIRouter(prefix="/api/auditoria", tags=["auditoria"])
FUSO = ZoneInfo("America/Sao_Paulo")


@rotas.get("", response_model=PaginaAuditoria)
def consultar(
    inicio: date | None = None,
    fim: date | None = None,
    usuario_id: uuid.UUID | None = None,
    acao: str | None = Query(default=None, max_length=60),
    pagina: int = Query(default=1, ge=1),
    por_pagina: int = Query(default=50, ge=1, le=200),
    ctx: Contexto = Depends(exige_master),
    db: Session = Depends(obter_db),
) -> PaginaAuditoria:
    filtros = []
    if inicio:
        filtros.append(Auditoria.ocorrido_em >= datetime.combine(inicio, time.min, FUSO))
    if fim:
        filtros.append(Auditoria.ocorrido_em < datetime.combine(fim + timedelta(days=1), time.min, FUSO))
    if usuario_id:
        filtros.append(Auditoria.usuario_id == usuario_id)
    if acao:
        filtros.append(Auditoria.acao.startswith(acao))
    total = db.scalar(select(func.count()).select_from(Auditoria).where(*filtros)) or 0
    linhas = db.execute(
        select(Auditoria, Usuario.nome_completo)
        .outerjoin(Usuario, Usuario.id == Auditoria.usuario_id)
        .where(*filtros)
        .order_by(Auditoria.ocorrido_em.desc(), Auditoria.id.desc())
        .offset((pagina - 1) * por_pagina)
        .limit(por_pagina)
    ).all()
    itens = [
        ItemAuditoria(id=a.id, ocorrido_em=a.ocorrido_em, usuario_id=a.usuario_id, usuario_nome=nome,
                      acao=a.acao, entidade=a.entidade, entidade_id=a.entidade_id, detalhes=a.detalhes, ip=a.ip)
        for a, nome in linhas
    ]
    return PaginaAuditoria(itens=itens, total=total, pagina=pagina, por_pagina=por_pagina)
