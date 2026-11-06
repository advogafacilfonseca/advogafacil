"""Criação da aplicação FastAPI."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from advoga_shared import __version__

from .api import (
    rotas_agenda,
    rotas_auditoria,
    rotas_auth,
    rotas_clientes,
    rotas_documentos,
    rotas_email,
    rotas_relatorios,
    rotas_financeiro,
    rotas_notificacoes,
    rotas_processos,
    rotas_sistema,
    rotas_usuarios,
)
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
    "senha_provisoria": "Senha provisória",
    "nome_exibicao": "Nome de exibição",
    "cargo": "Cargo",
    "permissoes": "Permissões",
    "cpf": "CPF",
    "rg": "RG",
    "data_nascimento": "Data de nascimento",
    "telefone_principal": "Telefone principal",
    "telefone_secundario": "Segundo telefone",
    "cep": "CEP",
    "uf": "UF",
    "motivo": "Motivo",
    "versao": "Versão",
    "numero_cnj": "Número CNJ",
    "cliente_id": "Cliente vinculado",
    "tipo_acao": "Tipo de ação",
    "area_juridica": "Área jurídica",
    "parte_contraria": "Parte contrária",
    "data_distribuicao": "Data de distribuição",
    "situacao": "Situação",
    "fase_processual": "Fase processual",
    "proximo_evento_tipo": "Próxima audiência ou prazo",
    "proximo_evento_em": "Data da próxima audiência ou prazo",
    "data_movimentacao": "Data da movimentação",
    "descricao": "Descrição",
    "nome_arquivo": "Nome do arquivo",
    "nome": "Nome do arquivo",
    "servico_contratado": "Serviço contratado",
    "data_inicio": "Data de início",
    "valor_total": "Valor total do contrato",
    "valor_entrada": "Valor da entrada",
    "quantidade_parcelas": "Quantidade de parcelas",
    "valor_parcela": "Valor de cada parcela",
    "primeiro_vencimento": "Primeiro vencimento",
    "dia_vencimento": "Dia dos vencimentos seguintes",
    "valor": "Valor",
    "data_recebimento": "Data de recebimento",
    "forma_pagamento": "Forma de pagamento",
    "categoria": "Categoria",
    "data": "Data",
    "novo_valor": "Novo valor",
    "parcelas_ids": "Parcelas",
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
    if tipo.startswith("date") or tipo.startswith("uuid"):
        return f"{nome}: valor inválido."
    if tipo in ("greater_than", "greater_than_equal"):
        limite = (erro.get("ctx") or {}).get("gt", (erro.get("ctx") or {}).get("ge"))
        return f"{nome}: deve ser maior que {limite}." if tipo == "greater_than" else f"{nome}: não pode ser negativo."
    if tipo in ("less_than_equal", "less_than"):
        return f"{nome}: valor acima do permitido."
    if tipo in ("decimal_parsing", "decimal_type", "int_parsing", "int_type", "float_parsing"):
        return f"{nome}: informe um número válido."
    if tipo in ("decimal_max_places", "decimal_max_digits", "decimal_whole_digits"):
        return f"{nome}: use no máximo 2 casas decimais."
    if tipo == "too_short" and campo == "parcelas_ids":
        return "Escolha pelo menos uma parcela."
    if campo == "email":
        return "Informe um e-mail válido."
    msg = str(erro.get("msg", "Dados inválidos."))
    msg = msg.removeprefix("Value error, ")
    return f"{nome}: {msg}" if nome and not msg.startswith(nome) and tipo != "value_error" else msg


def criar_app(cfg: Configuracoes | None = None) -> FastAPI:
    cfg = cfg or obter_configuracoes()
    configurar_banco(cfg.url_banco())

    @asynccontextmanager
    async def ciclo_de_vida(_app: FastAPI):
        servico = None
        if cfg.servico_avisos:
            from .services.servico_avisos import ServicoAvisos

            servico = ServicoAvisos(cfg.avisos_intervalo_segundos, cfg)
            servico.iniciar()
        try:
            yield
        finally:
            if servico:
                servico.parar()

    app = FastAPI(
        lifespan=ciclo_de_vida,
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
    app.include_router(rotas_usuarios.rotas)
    app.include_router(rotas_auditoria.rotas)
    app.include_router(rotas_clientes.rotas)
    app.include_router(rotas_processos.rotas)
    app.include_router(rotas_documentos.rotas)
    app.include_router(rotas_financeiro.rotas)
    app.include_router(rotas_agenda.rotas)
    app.include_router(rotas_notificacoes.rotas)
    app.include_router(rotas_email.rotas)
    app.include_router(rotas_relatorios.rotas)
    return app
