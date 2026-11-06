from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from advoga_shared.esquemas import Login, Mensagem, SessaoCriada, TrocarSenha, UsuarioPublico

from ..core.config import Configuracoes
from ..services import autenticacao
from .conversao import usuario_publico
from .deps import Contexto, ip_cliente, obter_cfg, obter_db, usuario_atual

rotas = APIRouter(prefix="/api/auth", tags=["autenticação"])


@rotas.post("/login", response_model=SessaoCriada)
def login(
    dados: Login,
    request: Request,
    db: Session = Depends(obter_db),
    cfg: Configuracoes = Depends(obter_cfg),
) -> SessaoCriada:
    try:
        r = autenticacao.login(db, dados.nome_usuario, dados.senha, cfg, ip_cliente(request),
                               dados.dispositivo)
    except autenticacao.ErroAutenticacao as exc:
        raise HTTPException(exc.status, exc.mensagem) from exc
    return SessaoCriada(token=r.token, expira_em=r.sessao.expira_em, usuario=usuario_publico(r.usuario))


@rotas.post("/logout", response_model=Mensagem)
def logout(ctx: Contexto = Depends(usuario_atual), db: Session = Depends(obter_db)) -> Mensagem:
    autenticacao.encerrar_sessao(db, ctx.sessao)
    return Mensagem(mensagem="Sessão encerrada.")


@rotas.get("/eu", response_model=UsuarioPublico)
def eu(ctx: Contexto = Depends(usuario_atual)) -> UsuarioPublico:
    return usuario_publico(ctx.usuario)


@rotas.post("/trocar-senha", response_model=Mensagem)
def trocar_senha(
    dados: TrocarSenha, ctx: Contexto = Depends(usuario_atual), db: Session = Depends(obter_db)
) -> Mensagem:
    try:
        autenticacao.trocar_senha(db, ctx.usuario, ctx.sessao, dados.senha_atual, dados.nova_senha, ctx.ip)
    except autenticacao.ErroAutenticacao as exc:
        raise HTTPException(exc.status, exc.mensagem) from exc
    return Mensagem(mensagem="Senha alterada com sucesso.")
