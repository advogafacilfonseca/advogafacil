"""Assistente de migração do servidor (somente a Advogada Master) e importação no servidor novo."""

from __future__ import annotations

import logging
import threading
import uuid

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request
from fastapi.responses import Response
from sqlalchemy.orm import Session

from advoga_shared.esquemas import (
    AndamentoImportacao,
    CancelarMigracao,
    ConcluirMigracao,
    EstadoMigracao,
    ExportarMigracao,
    ImportarMigracao,
    Migracao,
    SituacaoDestino,
)

from ..core.config import Configuracoes
from ..core.db import obter_sessao
from ..models import Migracao as MigracaoModelo
from ..services import auditoria, backup
from ..services import migracao as svc
from .deps import Contexto, exige_master, ip_cliente, obter_cfg, obter_db

rotas = APIRouter(prefix="/api/migracao", tags=["migracao"])
rotas_setup = APIRouter(prefix="/api/setup", tags=["migracao"])
log = logging.getLogger("advoga.migracao")


@rotas.get("/estado", response_model=EstadoMigracao)
def estado(ctx: Contexto = Depends(exige_master), db: Session = Depends(obter_db)) -> EstadoMigracao:
    return svc.estado(db)


@rotas.get("/verificar-destino", response_model=SituacaoDestino)
def verificar_destino(caminho: str = Query(min_length=2, max_length=400), ctx: Contexto = Depends(exige_master)
                      ) -> SituacaoDestino:
    return backup.situacao_destino(caminho.strip())


@rotas.post("/exportar", status_code=202, response_model=Migracao)
def exportar(dados: ExportarMigracao, ctx: Contexto = Depends(exige_master), db: Session = Depends(obter_db),
             cfg: Configuracoes = Depends(obter_cfg)) -> Migracao:
    m = svc.iniciar_exportacao(db, cfg, ctx.usuario, dados, ctx.ip)
    saida = svc.saida(db, m)
    migracao_id, senha = m.id, dados.senha

    def rodar() -> None:
        gerador = obter_sessao()
        sessao = next(gerador)
        try:
            svc.executar_exportacao(sessao, cfg, migracao_id, senha)
        except Exception:  # noqa: BLE001
            log.exception("Erro na exportação da migração")
        finally:
            gerador.close()

    threading.Thread(target=rodar, name="exportacao-migracao", daemon=True).start()
    return saida


@rotas.post("/concluir", response_model=Migracao)
def concluir(dados: ConcluirMigracao, ctx: Contexto = Depends(exige_master), db: Session = Depends(obter_db)
             ) -> Migracao:
    return svc.saida(db, svc.concluir(db, ctx.usuario, dados.codigo, dados.senha_master, ctx.ip))


@rotas.post("/cancelar", response_model=Migracao)
def cancelar(dados: CancelarMigracao, ctx: Contexto = Depends(exige_master), db: Session = Depends(obter_db)
             ) -> Migracao:
    return svc.saida(db, svc.cancelar(db, ctx.usuario, dados.senha_master, ctx.ip))


@rotas.get("/{migracao_id}/relatorio.pdf")
def relatorio(migracao_id: uuid.UUID, ctx: Contexto = Depends(exige_master), db: Session = Depends(obter_db)
              ) -> Response:
    m = db.get(MigracaoModelo, migracao_id)
    if m is None:
        raise HTTPException(404, "Migração não encontrada.")
    conteudo = svc.relatorio_pdf(db, m, ctx.usuario.nome_completo)
    auditoria.registrar(db, "migracao.relatorio", usuario_id=ctx.usuario.id, entidade="migracao",
                        entidade_id=m.id, ip=ctx.ip)
    db.commit()
    nome = f"relatorio_migracao_{m.tipo}_{m.iniciado_em:%Y-%m-%d}.pdf"
    return Response(conteudo, media_type="application/pdf",
                    headers={"Content-Disposition": f'attachment; filename="{nome}"'})


# --------------------------------------------- servidor novo (antes de existir a conta Master)
@rotas_setup.post("/importar", status_code=202)
def importar(dados: ImportarMigracao, request: Request, db: Session = Depends(obter_db),
             cfg: Configuracoes = Depends(obter_cfg)) -> dict:
    svc.iniciar_importacao(db, cfg, dados.codigo_instalacao, dados.pacote, dados.senha, ip_cliente(request))
    return {"mensagem": "Importação iniciada."}


@rotas_setup.get("/importacao", response_model=AndamentoImportacao)
def importacao(x_codigo_instalacao: str | None = Header(default=None), db: Session = Depends(obter_db)
               ) -> AndamentoImportacao:
    return svc.consultar_importacao(db, x_codigo_instalacao)
