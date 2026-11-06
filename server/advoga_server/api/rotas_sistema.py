from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from advoga_shared import __version__
from advoga_shared.esquemas import CriarMaster, Saude, SetupStatus, UsuarioPublico

from ..core.config import Configuracoes
from ..services import autenticacao
from ..services.servidor import obter_identidade, sistema_configurado
from .conversao import usuario_publico
from .deps import ip_cliente, obter_cfg, obter_db

rotas = APIRouter(prefix="/api", tags=["sistema"])


@rotas.get("/saude", response_model=Saude)
def saude(db: Session = Depends(obter_db)) -> Saude:
    try:
        db.execute(text("SELECT 1"))
        ident = obter_identidade(db)
        return Saude(
            status="ok",
            versao=__version__,
            banco="ok",
            servidor_id=ident.servidor_id,
            servidor_status=ident.status,
            configurado=sistema_configurado(db),
        )
    except SQLAlchemyError as exc:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "O servidor está no ar, mas o banco de dados não respondeu.",
        ) from exc


@rotas.get("/setup/status", response_model=SetupStatus)
def setup_status(db: Session = Depends(obter_db)) -> SetupStatus:
    return SetupStatus(configurado=sistema_configurado(db))


@rotas.post("/setup/master", response_model=UsuarioPublico, status_code=201)
def criar_master(
    dados: CriarMaster,
    request: Request,
    db: Session = Depends(obter_db),
    cfg: Configuracoes = Depends(obter_cfg),
) -> UsuarioPublico:
    try:
        usuario = autenticacao.criar_master(db, dados, cfg, ip_cliente(request))
    except autenticacao.ErroAutenticacao as exc:
        raise HTTPException(exc.status, exc.mensagem) from exc
    return usuario_publico(usuario)
