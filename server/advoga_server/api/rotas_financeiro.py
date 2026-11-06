"""Contratos e financeiro.

- Dados do contrato sem valores: permissão "Contratos".
- Qualquer valor (parcelas, recebimentos, despesas, resumos, comprovantes): permissão "Financeiro".
  Sem ela, os valores não saem do servidor (nem em listas, históricos ou pesquisa).
"""

from __future__ import annotations

import uuid
from datetime import date
from pathlib import Path
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import FileResponse, JSONResponse
from sqlalchemy import select
from sqlalchemy.orm import Session
from sqlalchemy.orm.exc import StaleDataError
from starlette.concurrency import run_in_threadpool

from advoga_shared.esquemas import (
    CATEGORIAS_DESPESA,
    Comprovante as ComprovanteSaida,
    Contrato,
    ContratoAtualizar,
    ContratoCancelar,
    ContratoCriar,
    Despesa,
    DespesaAtualizar,
    DespesaCancelar,
    DespesaCriar,
    ItemAuditoria,
    PaginaContratos,
    Pagamento,
    PagamentoCriar,
    PagamentoEstornar,
    Parcela,
    ParcelaCancelar,
    Renegociar,
    ResumoFinanceiro,
)
from advoga_shared.permissoes import Permissao

from ..core.config import Configuracoes
from ..models import Auditoria, Comprovante, Usuario
from ..services import auditoria
from ..services import documentos as svc_docs
from ..services import financeiro as svc
from .deps import Contexto, exige_alguma_permissao, exige_permissao, obter_cfg, obter_db
from .idempotencia import executar_gravacao

rotas = APIRouter(prefix="/api", tags=["financeiro"])
_contratos_ou_fin = exige_alguma_permissao(Permissao.CONTRATOS, Permissao.FINANCEIRO)
_contratos = exige_permissao(Permissao.CONTRATOS)
_financeiro = exige_permissao(Permissao.FINANCEIRO)


def _gravar(db, ctx, request, acao, status=200) -> JSONResponse:
    try:
        return executar_gravacao(db, ctx, request, acao, status)
    except StaleDataError as exc:
        db.rollback()
        raise HTTPException(409, svc.MSG_CONFLITO) from exc


def _exigir_financeiro(ctx: Contexto, db: Session) -> None:
    if not ctx.pode(Permissao.FINANCEIRO):
        auditoria.registrar(db, "acesso.negado", usuario_id=ctx.usuario.id,
                            detalhes={"permissao": Permissao.FINANCEIRO.value}, ip=ctx.ip)
        db.commit()
        raise HTTPException(403, "Esta operação envolve valores e exige a permissão Financeiro.")


def _pagina(pagina: int, por_pagina: int) -> tuple[int, int]:
    return (pagina - 1) * por_pagina, por_pagina


# ============================================================================== contratos
@rotas.get("/contratos", response_model=PaginaContratos)
def listar_contratos(cliente_id: uuid.UUID | None = None,
                     situacao: str | None = Query(default=None, pattern="^(ativo|quitado|cancelado)$"),
                     pagina: int = Query(default=1, ge=1), por_pagina: int = Query(default=50, ge=1, le=200),
                     ctx: Contexto = Depends(_contratos_ou_fin), db: Session = Depends(obter_db)) -> PaginaContratos:
    off, lim = _pagina(pagina, por_pagina)
    cs, total = svc.listar_contratos(db, cliente_id=cliente_id, situacao=situacao, offset=off, limite=lim)
    fin = ctx.pode(Permissao.FINANCEIRO)
    return PaginaContratos(itens=[svc.contrato_saida(db, c, fin) for c in cs], total=total, pagina=pagina,
                           por_pagina=por_pagina)


@rotas.get("/contratos/{contrato_id}", response_model=Contrato)
def obter_contrato(contrato_id: uuid.UUID, ctx: Contexto = Depends(_contratos_ou_fin),
                   db: Session = Depends(obter_db)) -> Contrato:
    return svc.contrato_saida(db, svc.obter_contrato(db, contrato_id), ctx.pode(Permissao.FINANCEIRO))


@rotas.post("/contratos", response_model=Contrato, status_code=201)
def criar_contrato(dados: ContratoCriar, request: Request, ctx: Contexto = Depends(_contratos),
                   db: Session = Depends(obter_db)) -> JSONResponse:
    _exigir_financeiro(ctx, db)  # o contrato gera parcelas (valores)
    return _gravar(db, ctx, request, lambda: svc.contrato_saida(
        db, svc.criar_contrato(db, ctx.usuario, dados, ctx.ip), True), 201)


@rotas.patch("/contratos/{contrato_id}", response_model=Contrato)
def atualizar_contrato(contrato_id: uuid.UUID, dados: ContratoAtualizar, request: Request,
                       ctx: Contexto = Depends(_contratos), db: Session = Depends(obter_db)) -> JSONResponse:
    return _gravar(db, ctx, request, lambda: svc.contrato_saida(db, svc.atualizar_contrato(
        db, ctx.usuario, svc.obter_contrato(db, contrato_id), dados, ctx.ip), ctx.pode(Permissao.FINANCEIRO)))


@rotas.post("/contratos/{contrato_id}/cancelar", response_model=Contrato)
def cancelar_contrato(contrato_id: uuid.UUID, dados: ContratoCancelar, request: Request,
                      ctx: Contexto = Depends(_contratos), db: Session = Depends(obter_db)) -> JSONResponse:
    _exigir_financeiro(ctx, db)
    return _gravar(db, ctx, request, lambda: svc.contrato_saida(db, svc.cancelar_contrato(
        db, ctx.usuario, svc.obter_contrato(db, contrato_id, travar=True), dados.motivo, dados.versao, ctx.ip), True))


@rotas.post("/contratos/{contrato_id}/renegociar", response_model=Contrato)
def renegociar(contrato_id: uuid.UUID, dados: Renegociar, request: Request,
               ctx: Contexto = Depends(_financeiro), db: Session = Depends(obter_db)) -> JSONResponse:
    return _gravar(db, ctx, request, lambda: svc.contrato_saida(db, svc.renegociar(
        db, ctx.usuario, svc.obter_contrato(db, contrato_id), dados, ctx.ip), True))


@rotas.get("/contratos/{contrato_id}/historico", response_model=list[ItemAuditoria])
def historico_contrato(contrato_id: uuid.UUID, ctx: Contexto = Depends(_contratos_ou_fin),
                       db: Session = Depends(obter_db)) -> list[ItemAuditoria]:
    svc.obter_contrato(db, contrato_id)
    fin = ctx.pode(Permissao.FINANCEIRO)
    linhas = db.execute(
        select(Auditoria, Usuario.nome_completo).outerjoin(Usuario, Usuario.id == Auditoria.usuario_id)
        .where(Auditoria.entidade == "contrato", Auditoria.entidade_id == str(contrato_id))
        .order_by(Auditoria.ocorrido_em.desc(), Auditoria.id.desc()).limit(500)).all()
    itens = []
    for a, nome in linhas:
        if not fin and a.acao.startswith("financeiro."):
            continue  # recebimentos, estornos e cancelamentos de parcela: só para o financeiro
        detalhes = a.detalhes if (fin or a.acao == "contrato.editado") else None
        itens.append(ItemAuditoria(id=a.id, ocorrido_em=a.ocorrido_em, usuario_id=a.usuario_id, usuario_nome=nome,
                                   acao=a.acao, entidade=a.entidade, entidade_id=a.entidade_id, detalhes=detalhes,
                                   ip=None))
    return itens


# ============================================================================== parcelas
@rotas.get("/financeiro/parcelas", response_model=dict)
def listar_parcelas(filtro: str = Query(default="abertas", pattern="^(abertas|vencidas|a_vencer|pagas|todas)$"),
                    cliente_id: uuid.UUID | None = None, inicio: date | None = None, fim: date | None = None,
                    pagina: int = Query(default=1, ge=1), por_pagina: int = Query(default=100, ge=1, le=500),
                    ctx: Contexto = Depends(_financeiro), db: Session = Depends(obter_db)) -> dict:
    off, lim = _pagina(pagina, por_pagina)
    itens, total = svc.listar_parcelas(db, filtro=filtro, cliente_id=cliente_id, inicio=inicio, fim=fim,
                                       offset=off, limite=lim)
    return {"itens": [i.model_dump(mode="json") for i in itens], "total": total, "pagina": pagina,
            "por_pagina": por_pagina}


@rotas.get("/financeiro/parcelas/{parcela_id}", response_model=Parcela)
def obter_parcela(parcela_id: uuid.UUID, ctx: Contexto = Depends(_financeiro), db: Session = Depends(obter_db)):
    from ..models import Parcela as ParcelaModelo

    p = db.get(ParcelaModelo, parcela_id)
    if p is None:
        raise HTTPException(404, "Parcela não encontrada.")
    return svc._parcela_saida(p, svc._pagos(db, [p.id]).get(p.id, svc.ZERO))


@rotas.post("/financeiro/parcelas/{parcela_id}/cancelar", response_model=Parcela)
def cancelar_parcela(parcela_id: uuid.UUID, dados: ParcelaCancelar, request: Request,
                     ctx: Contexto = Depends(_financeiro), db: Session = Depends(obter_db)) -> JSONResponse:
    def acao():
        p = svc.cancelar_parcela(db, ctx.usuario, parcela_id, dados.motivo, dados.versao, ctx.ip)
        return svc._parcela_saida(p, svc._pagos(db, [p.id]).get(p.id, svc.ZERO))
    return _gravar(db, ctx, request, acao)


# ========================================================================== recebimentos
@rotas.get("/financeiro/pagamentos", response_model=dict)
def listar_pagamentos(contrato_id: uuid.UUID | None = None, cliente_id: uuid.UUID | None = None,
                      inicio: date | None = None, fim: date | None = None,
                      pagina: int = Query(default=1, ge=1), por_pagina: int = Query(default=100, ge=1, le=500),
                      ctx: Contexto = Depends(_financeiro), db: Session = Depends(obter_db)) -> dict:
    off, lim = _pagina(pagina, por_pagina)
    itens, total = svc.listar_pagamentos(db, contrato_id=contrato_id, cliente_id=cliente_id, inicio=inicio, fim=fim,
                                         offset=off, limite=lim)
    return {"itens": [i.model_dump(mode="json") for i in itens], "total": total, "pagina": pagina,
            "por_pagina": por_pagina}


@rotas.post("/financeiro/pagamentos", response_model=Pagamento, status_code=201)
def registrar_pagamento(dados: PagamentoCriar, request: Request, ctx: Contexto = Depends(_financeiro),
                        db: Session = Depends(obter_db)) -> JSONResponse:
    return _gravar(db, ctx, request, lambda: svc.pagamento_saida(
        db, svc.registrar_pagamento(db, ctx.usuario, dados, ctx.ip)), 201)


@rotas.post("/financeiro/pagamentos/{pagamento_id}/estornar", response_model=Pagamento)
def estornar_pagamento(pagamento_id: uuid.UUID, dados: PagamentoEstornar, request: Request,
                       ctx: Contexto = Depends(_financeiro), db: Session = Depends(obter_db)) -> JSONResponse:
    return _gravar(db, ctx, request, lambda: svc.pagamento_saida(
        db, svc.estornar_pagamento(db, ctx.usuario, pagamento_id, dados.motivo, ctx.ip)))


# ============================================================================== despesas
@rotas.get("/financeiro/despesas", response_model=dict)
def listar_despesas(inicio: date | None = None, fim: date | None = None, categoria: str | None = None,
                    cliente_id: uuid.UUID | None = None, incluir_canceladas: bool = False,
                    pagina: int = Query(default=1, ge=1), por_pagina: int = Query(default=100, ge=1, le=500),
                    ctx: Contexto = Depends(_financeiro), db: Session = Depends(obter_db)) -> dict:
    if categoria and categoria not in CATEGORIAS_DESPESA:
        raise HTTPException(422, "Categoria inválida.")
    off, lim = _pagina(pagina, por_pagina)
    itens, total = svc.listar_despesas(db, inicio=inicio, fim=fim, categoria=categoria, cliente_id=cliente_id,
                                       incluir_canceladas=incluir_canceladas, offset=off, limite=lim)
    return {"itens": [i.model_dump(mode="json") for i in itens], "total": total, "pagina": pagina,
            "por_pagina": por_pagina}


@rotas.post("/financeiro/despesas", response_model=Despesa, status_code=201)
def criar_despesa(dados: DespesaCriar, request: Request, ctx: Contexto = Depends(_financeiro),
                  db: Session = Depends(obter_db)) -> JSONResponse:
    return _gravar(db, ctx, request, lambda: svc.despesa_saida(db, svc.criar_despesa(db, ctx.usuario, dados, ctx.ip)),
                   201)


@rotas.patch("/financeiro/despesas/{despesa_id}", response_model=Despesa)
def atualizar_despesa(despesa_id: uuid.UUID, dados: DespesaAtualizar, request: Request,
                      ctx: Contexto = Depends(_financeiro), db: Session = Depends(obter_db)) -> JSONResponse:
    return _gravar(db, ctx, request, lambda: svc.despesa_saida(db, svc.atualizar_despesa(
        db, ctx.usuario, svc.obter_despesa(db, despesa_id), dados, ctx.ip)))


@rotas.post("/financeiro/despesas/{despesa_id}/cancelar", response_model=Despesa)
def cancelar_despesa(despesa_id: uuid.UUID, dados: DespesaCancelar, request: Request,
                     ctx: Contexto = Depends(_financeiro), db: Session = Depends(obter_db)) -> JSONResponse:
    return _gravar(db, ctx, request, lambda: svc.despesa_saida(db, svc.cancelar_despesa(
        db, ctx.usuario, svc.obter_despesa(db, despesa_id), dados.motivo, dados.versao, ctx.ip)))


@rotas.get("/financeiro/despesas/{despesa_id}/historico", response_model=list[ItemAuditoria])
def historico_despesa(despesa_id: uuid.UUID, ctx: Contexto = Depends(_financeiro),
                      db: Session = Depends(obter_db)) -> list[ItemAuditoria]:
    svc.obter_despesa(db, despesa_id)
    linhas = db.execute(
        select(Auditoria, Usuario.nome_completo).outerjoin(Usuario, Usuario.id == Auditoria.usuario_id)
        .where(Auditoria.entidade == "despesa", Auditoria.entidade_id == str(despesa_id))
        .order_by(Auditoria.ocorrido_em.desc(), Auditoria.id.desc())).all()
    return [ItemAuditoria(id=a.id, ocorrido_em=a.ocorrido_em, usuario_id=a.usuario_id, usuario_nome=nome,
                          acao=a.acao, entidade=a.entidade, entidade_id=a.entidade_id, detalhes=a.detalhes, ip=None)
            for a, nome in linhas]


# ================================================================================ resumo
@rotas.get("/financeiro/resumo", response_model=ResumoFinanceiro)
def resumo(inicio: date, fim: date, ctx: Contexto = Depends(_financeiro),
           db: Session = Depends(obter_db)) -> ResumoFinanceiro:
    if fim < inicio:
        raise HTTPException(422, "A data final deve ser igual ou posterior à inicial.")
    return svc.resumo(db, inicio, fim)


# ========================================================================== comprovantes
def _pasta_comprovantes(cfg: Configuracoes) -> Path:
    return cfg.pasta_documentos / "_financeiro"


@rotas.post("/financeiro/comprovantes", response_model=ComprovanteSaida, status_code=201)
async def enviar_comprovante(request: Request, nome: str = Query(..., min_length=1, max_length=255),
                             ctx: Contexto = Depends(_financeiro), db: Session = Depends(obter_db),
                             cfg: Configuracoes = Depends(obter_cfg)) -> JSONResponse:
    nome_ok = svc_docs.validar_nome(nome)
    raiz = _pasta_comprovantes(cfg)
    temporario, tamanho, sha = await svc_docs.receber_arquivo(raiz, request.stream())
    cid = uuid.uuid4()
    hoje = date.today()
    relativo = Path(f"{hoje:%Y}") / f"{hoje:%m}" / f"{cid}{svc_docs.extensao(nome_ok)}"
    instalado: list[Path] = []
    tipo = request.headers.get("content-type", "application/octet-stream").split(";")[0].strip()

    def acao():
        destino = raiz / relativo
        destino.parent.mkdir(parents=True, exist_ok=True)
        temporario.replace(destino)
        instalado.append(destino)
        db.add(Comprovante(id=cid, nome_arquivo=nome_ok, tipo_conteudo=tipo[:150], tamanho=tamanho, sha256=sha,
                           caminho=relativo.as_posix(), enviado_por=ctx.usuario.id))
        db.flush()
        auditoria.registrar(db, "financeiro.comprovante_enviado", usuario_id=ctx.usuario.id, entidade="comprovante",
                            entidade_id=cid, detalhes={"nome": nome_ok, "sha256": sha}, ip=ctx.ip)
        return ComprovanteSaida(id=cid, nome_arquivo=nome_ok, tamanho=tamanho, sha256=sha)

    try:
        return await run_in_threadpool(executar_gravacao, db, ctx, request, acao, 201)
    except BaseException:
        for p in instalado:
            p.unlink(missing_ok=True)
        raise
    finally:
        temporario.unlink(missing_ok=True)


@rotas.get("/financeiro/comprovantes/{comprovante_id}/arquivo")
def baixar_comprovante(comprovante_id: uuid.UUID, ctx: Contexto = Depends(_financeiro),
                       db: Session = Depends(obter_db), cfg: Configuracoes = Depends(obter_cfg)) -> FileResponse:
    c = db.get(Comprovante, comprovante_id)
    if c is None:
        raise HTTPException(404, "Comprovante não encontrado.")
    raiz = _pasta_comprovantes(cfg).resolve()
    caminho = (raiz / c.caminho).resolve()
    if raiz not in caminho.parents or not caminho.is_file():
        raise HTTPException(410, "O arquivo deste comprovante não foi encontrado no servidor. "
                                 "Avise a Advogada Master para restaurar a partir da cópia de segurança.")
    return FileResponse(caminho, media_type=c.tipo_conteudo or "application/octet-stream",
                        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quote(c.nome_arquivo)}",
                                 "X-Documento-SHA256": c.sha256})
