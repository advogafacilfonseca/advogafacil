"""Gravações idempotentes: a mesma chave nunca gera dois registros."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from fastapi import HTTPException, Request
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..models import ChaveIdempotencia
from .deps import Contexto

CABECALHO = "Idempotency-Key"


def executar_gravacao(
    db: Session,
    ctx: Contexto,
    request: Request,
    acao: Callable[[], Any],
    status_sucesso: int = 200,
) -> JSONResponse:
    """Executa `acao` (que não faz commit) e grava tudo numa única transação.

    Se o aplicativo reenviar a operação com a mesma chave (ex.: a conexão caiu antes da
    resposta chegar), devolve a resposta original sem repetir a gravação.
    """
    chave = request.headers.get(CABECALHO)
    rota = f"{request.method} {request.url.path}"[:120]
    if chave is not None:
        chave = chave.strip()
        if not 8 <= len(chave) <= 64:
            raise HTTPException(400, "Chave de operação inválida.")
        anterior = db.get(ChaveIdempotencia, (ctx.usuario.id, chave))
        if anterior is not None:
            if anterior.rota != rota:
                raise HTTPException(409, "Chave de operação já utilizada em outra operação.")
            return JSONResponse(anterior.corpo, status_code=anterior.status)

    try:
        resultado = acao()
        corpo = jsonable_encoder(resultado)
        if chave is not None:
            db.add(ChaveIdempotencia(usuario_id=ctx.usuario.id, chave=chave, rota=rota,
                                     status=status_sucesso, corpo=corpo))
        db.commit()
    except IntegrityError:
        db.rollback()
        if chave is not None:
            anterior = db.get(ChaveIdempotencia, (ctx.usuario.id, chave))
            if anterior is not None:
                return JSONResponse(anterior.corpo, status_code=anterior.status)
        raise
    except Exception:
        db.rollback()
        raise
    return JSONResponse(corpo, status_code=status_sucesso)
