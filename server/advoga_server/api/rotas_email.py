"""Conta oficial de envio dos avisos por e-mail (somente a Master)."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from advoga_shared.esquemas import AutorizacaoGoogle, ConcluirGoogle, EstadoEmail, IniciarGoogle, TesteEmail

from ..core.config import Configuracoes
from ..services import email_google as svc
from .deps import Contexto, exige_master, obter_cfg, obter_db

rotas = APIRouter(prefix="/api/email", tags=["email"])


@rotas.get("/estado", response_model=EstadoEmail)
def estado(ctx: Contexto = Depends(exige_master), db: Session = Depends(obter_db),
           cfg: Configuracoes = Depends(obter_cfg)) -> EstadoEmail:
    return svc.estado(db, cfg)


@rotas.post("/google/iniciar", response_model=AutorizacaoGoogle)
def iniciar_google(dados: IniciarGoogle, ctx: Contexto = Depends(exige_master)) -> AutorizacaoGoogle:
    return svc.iniciar(dados, ctx.usuario)


@rotas.post("/google/concluir", response_model=EstadoEmail)
def concluir_google(dados: ConcluirGoogle, ctx: Contexto = Depends(exige_master), db: Session = Depends(obter_db),
                    cfg: Configuracoes = Depends(obter_cfg)) -> EstadoEmail:
    r = svc.concluir(db, cfg, ctx.usuario, dados, ctx.ip)
    db.commit()
    return r


@rotas.post("/testar")
def testar(dados: TesteEmail, ctx: Contexto = Depends(exige_master), db: Session = Depends(obter_db),
           cfg: Configuracoes = Depends(obter_cfg)) -> dict:
    destino = svc.enviar_teste(db, cfg, ctx.usuario, dados.para, ctx.ip)
    db.commit()
    return {"enviado_para": destino}


@rotas.post("/desconectar", response_model=EstadoEmail)
def desconectar(ctx: Contexto = Depends(exige_master), db: Session = Depends(obter_db),
                cfg: Configuracoes = Depends(obter_cfg)) -> EstadoEmail:
    svc.desconectar(db, ctx.usuario, ctx.ip)
    db.commit()
    return svc.estado(db, cfg)
