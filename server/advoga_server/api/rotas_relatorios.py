"""Painel inicial e relatórios (visualizar, exportar em PDF e Excel)."""

from __future__ import annotations

import uuid
from datetime import date
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response
from sqlalchemy.orm import Session

from advoga_shared.esquemas import FORMATOS_RELATORIO, PERMISSOES_RELATORIO, TIPOS_RELATORIO, Painel, Relatorio

from ..services import auditoria
from ..services import exportar_relatorio as exportar
from ..services import relatorios as svc
from .deps import Contexto, obter_db, usuario_atual

rotas = APIRouter(prefix="/api", tags=["relatorios"])

TIPOS_ARQUIVO = {
    "pdf": "application/pdf",
    "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
}


@rotas.get("/painel", response_model=Painel)
def painel(ctx: Contexto = Depends(usuario_atual), db: Session = Depends(obter_db)) -> Painel:
    return svc.painel(db, ctx.permissoes)


@rotas.get("/relatorios/disponiveis", response_model=dict[str, str])
def disponiveis(ctx: Contexto = Depends(usuario_atual)) -> dict[str, str]:
    """Somente os relatórios que esta pessoa pode gerar."""
    return {t: n for t, n in TIPOS_RELATORIO.items() if svc.pode_gerar(t, ctx.permissoes)}


@rotas.get("/relatorios/{tipo}", response_model=Relatorio)
def relatorio(
    tipo: str,
    formato: str = Query("json"),
    inicio: date | None = None,
    fim: date | None = None,
    responsavel_id: uuid.UUID | None = None,
    cliente_id: uuid.UUID | None = None,
    situacao: str | None = Query(None, max_length=30),
    ctx: Contexto = Depends(usuario_atual),
    db: Session = Depends(obter_db),
):
    if tipo not in TIPOS_RELATORIO:
        raise HTTPException(404, "Relatório não encontrado.")
    if formato not in FORMATOS_RELATORIO:
        raise HTTPException(422, "Formato inválido. Use PDF ou Excel.")
    if not svc.pode_gerar(tipo, ctx.permissoes):
        auditoria.registrar(db, "acesso.negado", usuario_id=ctx.usuario.id,
                            detalhes={"relatorio": tipo, "permissao": [p.value for p in PERMISSOES_RELATORIO[tipo]]},
                            ip=ctx.ip)
        db.commit()
        raise HTTPException(403, "Você não tem permissão para acessar esta área.")
    filtros = svc.Filtros(inicio=inicio, fim=fim, responsavel_id=responsavel_id, cliente_id=cliente_id,
                          situacao=situacao or None)
    rel = svc.gerar(db, tipo, filtros, ctx.usuario, ctx.permissoes)
    if formato == "json":
        return rel
    conteudo = exportar.pdf(rel) if formato == "pdf" else exportar.xlsx(rel)
    auditoria.registrar(db, "relatorio.exportado", usuario_id=ctx.usuario.id, entidade="relatorio", entidade_id=tipo,
                        detalhes={"tipo": tipo, "formato": formato, "linhas": len(rel.linhas),
                                  "filtros": svc.descricao_curta(filtros)}, ip=ctx.ip)
    db.commit()
    nome = svc.nome_arquivo(tipo, formato, rel.gerado_em)
    return Response(conteudo, media_type=TIPOS_ARQUIVO[formato],
                    headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quote(nome)}",
                             "Cache-Control": "no-store"})
