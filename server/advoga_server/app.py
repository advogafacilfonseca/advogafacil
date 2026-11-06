"""Criação da aplicação FastAPI."""

from __future__ import annotations

import logging

from fastapi import FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from advoga_shared import __version__

from .api import rotas_auth, rotas_sistema
from .core.config import Configuracoes, obter_configuracoes
from .core.db import configurar_banco

log = logging.getLogger("advoga_server")

_NOMES_CAMPOS = {
    "nome_completo": "Nome completo",
    "nome_usuario": "Nome de usuário",
    "email": "E-mail",
    "senha": "Senha",
    "senha_confirmacao": "Confirmação de senha",
    "codigo_instalacao": "Código de instalação",
    "senha_atual": "Senha atual",
    "nova_senha": "Nova senha",
    "nova_senha_confirmacao": "Confirmação da nova senha",
}


def _mensagem_validacao(erro: dict) -> str:
    campo = next((str(p) for p in reversed(erro.get("loc", ())) if isinstance(p, str) and p != "body"), "")
    nome = _NOMES_CAMPOS.get(campo, campo)
    tipo = erro.get("type", "")
    if tipo == "missing":
        return f"{nome}: campo obrigatório."
    if tipo == "string_too_short":
        return f"{nome}: preenchimento muito curto."
    if tipo == "string_too_long":
        return f"{nome}: preenchimento muito longo."
    if campo == "email":
        return "Informe um e-mail válido."
    msg = str(erro.get("msg", "Dados inválidos."))
    msg = msg.removeprefix("Value error, ")
    return f"{nome}: {msg}" if nome and not msg.startswith(nome) and tipo != "value_error" else msg


def criar_app(cfg: Configuracoes | None = None) -> FastAPI:
    cfg = cfg or obter_configuracoes()
    configurar_banco(cfg.url_banco())

    app = FastAPI(
        title="Advoga Fácil — Servidor",
        version=__version__,
        docs_url=None,  # documentação interativa desligada em produção
        redoc_url=None,
        openapi_url=None,
    )

    @app.exception_handler(RequestValidationError)
    async def _validacao(_: Request, exc: RequestValidationError) -> JSONResponse:
        mensagens = [_mensagem_validacao(e) for e in exc.errors()]
        return JSONResponse(
            status_code=422,
            content=jsonable_encoder({"detail": " ".join(dict.fromkeys(mensagens))}),
        )

    app.include_router(rotas_sistema.rotas)
    app.include_router(rotas_auth.rotas)
    return app
