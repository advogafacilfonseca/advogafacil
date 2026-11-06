"""Notificações: avisos do próprio usuário, configuração de destinatários (Master) e histórico
de envios."""

from __future__ import annotations

import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from advoga_shared.esquemas import (
    CATEGORIAS_NOTIFICACAO,
    SITUACOES_EMAIL,
    ConfiguracaoNotificacoes,
    ConfiguracaoNotificacoesSalvar,
    Notificacao,
    PaginaNotificacoes,
    ResultadoCiclo,
)
from advoga_shared.permissoes import Permissao

from ..models import Notificacao as NotificacaoModelo
from ..services import notificacoes as svc
from ..services.agenda import agora
from ..core.config import Configuracoes
from .deps import Contexto, exige_master, obter_cfg, obter_db, usuario_atual
from .idempotencia import executar_gravacao

rotas = APIRouter(prefix="/api/notificacoes", tags=["notificacoes"])


class MarcarLidas(BaseModel):
    ids: list[uuid.UUID] | None = Field(default=None, max_length=1000)  # None: todas


@rotas.get("/minhas", response_model=PaginaNotificacoes)
def minhas(somente_nao_lidas: bool = False, limite: int = Query(default=100, ge=1, le=500),
           ctx: Contexto = Depends(usuario_atual), db: Session = Depends(obter_db)) -> PaginaNotificacoes:
    itens, total, nao_lidas = svc.minhas(db, ctx.usuario, somente_nao_lidas, limite)
    return PaginaNotificacoes(itens=[svc.saida(n) for n in itens], total=total, nao_lidas=nao_lidas)


@rotas.post("/lidas")
def marcar_lidas(dados: MarcarLidas, ctx: Contexto = Depends(usuario_atual), db: Session = Depends(obter_db)) -> dict:
    n = svc.marcar_lidas(db, ctx.usuario, dados.ids, agora())
    db.commit()
    return {"marcadas": n}


@rotas.get("/configuracao", response_model=ConfiguracaoNotificacoes)
def obter_configuracao(ctx: Contexto = Depends(exige_master), db: Session = Depends(obter_db)) -> ConfiguracaoNotificacoes:
    return svc.obter_configuracao(db)


@rotas.put("/configuracao", response_model=ConfiguracaoNotificacoes)
def salvar_configuracao(dados: ConfiguracaoNotificacoesSalvar, request: Request, ctx: Contexto = Depends(exige_master),
                        db: Session = Depends(obter_db)) -> JSONResponse:
    return executar_gravacao(db, ctx, request, lambda: svc.salvar_configuracao(db, ctx.usuario, dados, ctx.ip))


@rotas.get("/historico", response_model=PaginaNotificacoes)
def historico(
    usuario_id: uuid.UUID | None = None,
    categoria: str | None = Query(default=None, pattern="^(" + "|".join([*CATEGORIAS_NOTIFICACAO, "backups"]) + ")$"),
    situacao: str | None = Query(default=None, pattern="^(" + "|".join(SITUACOES_EMAIL) + ")$"),
    desde: datetime | None = None,
    pagina: int = Query(default=1, ge=1),
    por_pagina: int = Query(default=200, ge=1, le=500),
    ctx: Contexto = Depends(exige_master),
    db: Session = Depends(obter_db),
) -> PaginaNotificacoes:
    if desde is not None and desde.tzinfo is None:
        raise HTTPException(422, "Data e hora sem fuso horário.")
    linhas, total = svc.historico(db, ctx.pode(Permissao.FINANCEIRO), usuario_id=usuario_id, categoria=categoria,
                                  situacao=situacao, desde=desde, offset=(pagina - 1) * por_pagina, limite=por_pagina)
    return PaginaNotificacoes(itens=[svc.saida(n, nome) for n, nome in linhas], total=total, nao_lidas=0)


@rotas.post("/{notificacao_id}/reenviar", response_model=Notificacao)
def reenviar(notificacao_id: uuid.UUID, request: Request, ctx: Contexto = Depends(exige_master),
             db: Session = Depends(obter_db)) -> JSONResponse:
    def acao():
        n = db.get(NotificacaoModelo, notificacao_id, with_for_update=True)
        if n is None:
            raise HTTPException(404, "Aviso não encontrado.")
        return svc.saida(svc.reenviar(db, ctx.usuario, n, ctx.ip))

    return executar_gravacao(db, ctx, request, acao)


@rotas.post("/verificar-agora", response_model=ResultadoCiclo)
def verificar_agora(ctx: Contexto = Depends(exige_master), db: Session = Depends(obter_db),
                    cfg: Configuracoes = Depends(obter_cfg)) -> ResultadoCiclo:
    """Roda o ciclo do serviço de avisos imediatamente (o serviço também roda sozinho)."""
    r = svc.executar_ciclo(db, cfg=cfg)
    if r is None:
        raise HTTPException(409, "A verificação de avisos já está em andamento. Tente de novo em instantes.")
    return r
