"""Documentos: anexar, listar, baixar, alterar e remover (de forma controlada).
Acesso exige a permissão "documentos"; consultar e restaurar removidos é exclusivo da Master."""

from __future__ import annotations

import uuid
from pathlib import Path
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import FileResponse, JSONResponse
from sqlalchemy.orm import Session
from sqlalchemy.orm.exc import StaleDataError
from starlette.concurrency import run_in_threadpool

from advoga_shared.esquemas import Documento, DocumentoAtualizar, DocumentoRemover, PaginaDocumentos
from advoga_shared.permissoes import Permissao

from ..core.config import Configuracoes
from ..services import auditoria
from ..services import documentos as svc
from .deps import Contexto, exige_permissao, obter_cfg, obter_db
from .idempotencia import executar_gravacao

rotas = APIRouter(prefix="/api", tags=["documentos"])
_documentos = exige_permissao(Permissao.DOCUMENTOS)


def _gravar(db, ctx, request, acao, status=200) -> JSONResponse:
    try:
        return executar_gravacao(db, ctx, request, acao, status)
    except StaleDataError as exc:
        db.rollback()
        raise HTTPException(409, svc.MSG_CONFLITO) from exc


def _exigir_master(ctx: Contexto) -> None:
    if not ctx.usuario.is_master:
        raise HTTPException(403, "Somente a Advogada Master pode consultar e restaurar documentos removidos.")


@rotas.get("/documentos", response_model=PaginaDocumentos)
def listar(
    q: str | None = Query(default=None, max_length=100),
    cliente_id: uuid.UUID | None = None,
    processo_id: uuid.UUID | None = None,
    somente_geral: bool = False,
    removidos: bool = False,
    pagina: int = Query(default=1, ge=1),
    por_pagina: int = Query(default=50, ge=1, le=200),
    ctx: Contexto = Depends(_documentos),
    db: Session = Depends(obter_db),
) -> PaginaDocumentos:
    if removidos:
        _exigir_master(ctx)
    itens, total = svc.buscar(db, termo=q, cliente_id=cliente_id, processo_id=processo_id,
                              somente_geral=somente_geral, removidos=removidos,
                              offset=(pagina - 1) * por_pagina, limite=por_pagina)
    return PaginaDocumentos(itens=itens, total=total, pagina=pagina, por_pagina=por_pagina)


@rotas.post("/documentos", response_model=Documento, status_code=201)
async def anexar(
    request: Request,
    cliente_id: uuid.UUID,
    nome: str = Query(..., min_length=1, max_length=255),
    processo_id: uuid.UUID | None = None,
    descricao: str | None = Query(default=None, max_length=500),
    ctx: Contexto = Depends(_documentos),
    db: Session = Depends(obter_db),
    cfg: Configuracoes = Depends(obter_cfg),
) -> JSONResponse:
    """O conteúdo do arquivo vai no corpo da requisição (sem conversões), gravado em partes."""
    nome_ok = svc.validar_nome(nome)
    await run_in_threadpool(svc.validar_vinculo, db, cliente_id, processo_id)
    tamanho_declarado = request.headers.get("content-length")
    if tamanho_declarado and tamanho_declarado.isdigit() and int(tamanho_declarado) > svc.TAMANHO_MAXIMO:
        raise HTTPException(413, "Arquivo grande demais (máximo de 200 MB por arquivo).")
    raiz: Path = cfg.pasta_documentos
    temporario, tamanho, sha = await svc.receber_arquivo(raiz, request.stream())
    doc_id = uuid.uuid4()
    instalado: list[Path] = []
    tipo = request.headers.get("content-type", "application/octet-stream").split(";")[0].strip()

    def acao():
        caminho = svc.instalar_arquivo(raiz, temporario, doc_id, nome_ok, cliente_id, processo_id)
        instalado.append(raiz / caminho)
        d = svc.criar(db, ctx.usuario, doc_id=doc_id, cliente_id=cliente_id, processo_id=processo_id,
                      nome=nome_ok, descricao=(descricao or "").strip() or None, tipo=tipo, tamanho=tamanho,
                      sha256=sha, caminho=caminho, ip=ctx.ip)
        return svc.saida(db, d)

    try:
        resposta = await run_in_threadpool(executar_gravacao, db, ctx, request, acao, 201)
    except BaseException:
        for p in instalado:
            p.unlink(missing_ok=True)  # nada fica órfão se a gravação no banco falhar
        raise
    finally:
        temporario.unlink(missing_ok=True)  # só existe se a operação já tinha sido feita antes
    return resposta


@rotas.get("/documentos/{doc_id}", response_model=Documento)
def obter(doc_id: uuid.UUID, ctx: Contexto = Depends(_documentos), db: Session = Depends(obter_db)) -> Documento:
    return svc.saida(db, svc.obter(db, doc_id, incluir_removido=ctx.usuario.is_master))


@rotas.get("/documentos/{doc_id}/arquivo")
def baixar(doc_id: uuid.UUID, ctx: Contexto = Depends(_documentos), db: Session = Depends(obter_db),
           cfg: Configuracoes = Depends(obter_cfg)) -> FileResponse:
    d = svc.obter(db, doc_id, incluir_removido=ctx.usuario.is_master)
    caminho = svc.caminho_absoluto(cfg.pasta_documentos, d)
    if not caminho.is_file():
        raise HTTPException(410, "O arquivo deste documento não foi encontrado no servidor. "
                                 "Avise a Advogada Master para restaurar a partir da cópia de segurança.")
    auditoria.registrar(db, "documento.baixado", usuario_id=ctx.usuario.id, entidade="documento",
                        entidade_id=d.id, detalhes={"nome": d.nome_arquivo}, ip=ctx.ip)
    db.commit()
    return FileResponse(caminho, media_type=d.tipo_conteudo or "application/octet-stream",
                        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quote(d.nome_arquivo)}",
                                 "X-Documento-SHA256": d.sha256})


@rotas.patch("/documentos/{doc_id}", response_model=Documento)
def atualizar(doc_id: uuid.UUID, dados: DocumentoAtualizar, request: Request,
              ctx: Contexto = Depends(_documentos), db: Session = Depends(obter_db),
              cfg: Configuracoes = Depends(obter_cfg)) -> JSONResponse:
    movido: list = []

    def acao():
        d, mov = svc.atualizar(db, cfg.pasta_documentos, ctx.usuario, svc.obter(db, doc_id), dados, ctx.ip)
        if mov:
            movido.append(mov)
        return svc.saida(db, d)

    try:
        return _gravar(db, ctx, request, acao)
    except BaseException:
        import os
        for destino, origem in movido:  # desfaz a mudança de pasta se o banco não gravou
            if destino.exists():
                os.replace(destino, origem)
        raise


@rotas.post("/documentos/{doc_id}/remover", response_model=Documento)
def remover(doc_id: uuid.UUID, dados: DocumentoRemover, request: Request,
            ctx: Contexto = Depends(_documentos), db: Session = Depends(obter_db)) -> JSONResponse:
    return _gravar(db, ctx, request, lambda: svc.saida(
        db, svc.remover(db, ctx.usuario, svc.obter(db, doc_id), dados.motivo, dados.versao, ctx.ip)))


@rotas.post("/documentos/{doc_id}/restaurar", response_model=Documento)
def restaurar(doc_id: uuid.UUID, request: Request, versao: int = Query(...),
              ctx: Contexto = Depends(_documentos), db: Session = Depends(obter_db)) -> JSONResponse:
    _exigir_master(ctx)
    return _gravar(db, ctx, request, lambda: svc.saida(
        db, svc.restaurar(db, ctx.usuario, svc.obter(db, doc_id, incluir_removido=True), versao, ctx.ip)))
