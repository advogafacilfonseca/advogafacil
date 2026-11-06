"""Central de Backups (somente a Advogada Master)."""

from __future__ import annotations

import logging
import threading

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.orm import Session

from advoga_shared.esquemas import (
    ConfiguracaoBackup,
    EstadoBackups,
    ExecucaoBackup,
    ExecutarBackup,
    SenhaCopiaBackup,
    SituacaoDestino,
)

from ..core.config import Configuracoes
from ..core.db import obter_sessao
from ..services import auditoria
from ..services import backup as svc
from .deps import Contexto, exige_master, obter_cfg, obter_db

rotas = APIRouter(prefix="/api/backups", tags=["backups"])
log = logging.getLogger("advoga.backup")


@rotas.get("/estado", response_model=EstadoBackups)
def estado(ctx: Contexto = Depends(exige_master), db: Session = Depends(obter_db),
           cfg: Configuracoes = Depends(obter_cfg)) -> EstadoBackups:
    return svc.estado(db, cfg)


@rotas.put("/configuracao", response_model=ConfiguracaoBackup)
def salvar(dados: ConfiguracaoBackup, ctx: Contexto = Depends(exige_master), db: Session = Depends(obter_db),
           cfg: Configuracoes = Depends(obter_cfg)) -> ConfiguracaoBackup:
    c = svc.salvar_config(db, cfg, ctx.usuario, dados, ctx.ip)
    db.commit()
    return c


@rotas.post("/senha-copia")
def senha_copia(dados: SenhaCopiaBackup, ctx: Contexto = Depends(exige_master), db: Session = Depends(obter_db),
                cfg: Configuracoes = Depends(obter_cfg)) -> dict:
    svc.definir_senha_copia(db, cfg, ctx.usuario, dados.senha, ctx.ip)
    db.commit()
    return {"mensagem": "Senha da cópia criptografada definida. Guarde-a em local seguro: sem ela, a cópia "
                        "criptografada não pode ser aberta."}


@rotas.get("/verificar-destino", response_model=SituacaoDestino)
def verificar_destino(caminho: str = Query(min_length=2, max_length=400), ctx: Contexto = Depends(exige_master)
                      ) -> SituacaoDestino:
    """Confere a pasta como o computador SERVIDOR a vê (HD conectado, espaço livre)."""
    return svc.situacao_destino(caminho.strip())


@rotas.get("/historico", response_model=list[ExecucaoBackup])
def historico(limite: int = Query(200, ge=1, le=1000), ctx: Contexto = Depends(exige_master),
              db: Session = Depends(obter_db)) -> list[ExecucaoBackup]:
    return svc.historico(db, limite)


def _em_segundo_plano(funcao, cfg: Configuracoes, *args) -> None:
    def rodar() -> None:
        gerador = obter_sessao()
        db = next(gerador)
        try:
            funcao(db, cfg, *args)
        except HTTPException:
            pass
        except Exception:  # noqa: BLE001
            log.exception("Erro no backup solicitado pela Master")
        finally:
            gerador.close()

    threading.Thread(target=rodar, name="backup-manual", daemon=True).start()


def _livre(db: Session) -> None:
    from sqlalchemy import text

    if svc._trava_local.locked():
        raise HTTPException(409, "Já existe um backup em andamento. Aguarde terminar.")
    em_uso = db.scalar(text(f"SELECT count(*) FROM pg_locks WHERE locktype = 'advisory' AND objid = {svc.TRAVA} "
                               "AND database = (SELECT oid FROM pg_database WHERE datname = current_database())"))
    if em_uso:
        raise HTTPException(409, "Já existe um backup em andamento. Aguarde terminar.")


@rotas.post("/executar", status_code=202)
def executar(dados: ExecutarBackup, request: Request, ctx: Contexto = Depends(exige_master),
             db: Session = Depends(obter_db), cfg: Configuracoes = Depends(obter_cfg)) -> dict:
    if not svc.obter_config(db).destino:
        raise HTTPException(422, "Configure a pasta de destino antes de fazer um backup.")
    _livre(db)
    auditoria.registrar(db, "backups.executar", usuario_id=ctx.usuario.id, detalhes={"tipo": dados.tipo}, ip=ctx.ip)
    db.commit()
    _em_segundo_plano(svc.executar, cfg, dados.tipo, "manual", ctx.usuario.id)
    return {"mensagem": "Backup iniciado. Acompanhe o resultado no histórico."}


@rotas.post("/testar-restauracao", status_code=202)
def testar(ctx: Contexto = Depends(exige_master), db: Session = Depends(obter_db),
           cfg: Configuracoes = Depends(obter_cfg)) -> dict:
    _livre(db)
    auditoria.registrar(db, "backups.testar_restauracao", usuario_id=ctx.usuario.id, ip=ctx.ip)
    db.commit()
    _em_segundo_plano(svc.testar_restauracao, cfg, "manual", ctx.usuario.id)
    return {"mensagem": "Teste de restauração iniciado. Acompanhe o resultado no histórico."}
