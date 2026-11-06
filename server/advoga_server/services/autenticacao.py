"""Login, sessões e criação protegida da conta Master."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import select, text, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from advoga_shared.esquemas import CriarMaster
from advoga_shared.permissoes import TODAS_AS_PERMISSOES, Permissao

from ..core.config import Configuracoes
from ..core.seguranca import (
    comparar_seguro,
    gerar_hash_senha,
    gerar_token,
    hash_token,
    precisa_rehash,
    verificar_senha,
)
from ..models import Configuracao, Sessao, Usuario
from . import auditoria
from .servidor import CHAVE_CODIGO

# Chave fixa do bloqueio que serializa a criação da Master.
_TRAVA_CRIACAO_MASTER = 7_310_001


class ErroAutenticacao(Exception):
    def __init__(self, mensagem: str, status: int = 401) -> None:
        super().__init__(mensagem)
        self.mensagem = mensagem
        self.status = status


def agora() -> datetime:
    return datetime.now(UTC)


def permissoes_efetivas(usuario: Usuario) -> set[Permissao]:
    if usuario.is_master:
        return set(TODAS_AS_PERMISSOES)
    validas = {p.value for p in Permissao}
    return {Permissao(p.permissao) for p in usuario.permissoes if p.permissao in validas}


def criar_master(db: Session, dados: CriarMaster, cfg: Configuracoes, ip: str | None) -> Usuario:
    # Serializa tentativas simultâneas: só uma pode criar a Master.
    db.execute(text("SELECT pg_advisory_xact_lock(:k)"), {"k": _TRAVA_CRIACAO_MASTER})

    if db.scalar(select(Usuario.id).where(Usuario.is_master).limit(1)) is not None:
        db.rollback()
        raise ErroAutenticacao("A conta Master já foi criada. Utilize a tela de login.", 409)

    registro = db.get(Configuracao, CHAVE_CODIGO)
    codigo = dados.codigo_instalacao.strip().upper()
    if registro is None or not comparar_seguro(str(registro.valor), hash_token(codigo)):
        auditoria.registrar(db, "setup.codigo_invalido", ip=ip)
        db.commit()
        raise ErroAutenticacao(
            "Código de instalação inválido. Ele está no arquivo CODIGO_DE_INSTALACAO.txt "
            "do computador servidor.",
            403,
        )

    if db.scalar(select(Usuario.id).where(Usuario.nome_usuario == dados.nome_usuario)):
        db.rollback()
        raise ErroAutenticacao("Este nome de usuário já está em uso.", 409)

    db.execute(text("SET LOCAL advoga.criacao_master = 'autorizada'"))
    usuario = Usuario(
        id=uuid.uuid4(),
        nome_completo=dados.nome_completo,
        nome_exibicao=dados.nome_completo.split(" ")[0],
        cargo="Advogada Master",
        nome_usuario=dados.nome_usuario,
        email=str(dados.email).lower(),
        senha_hash=gerar_hash_senha(dados.senha),
        is_master=True,
        ativo=True,
    )
    db.add(usuario)
    db.delete(registro)  # o código de instalação deixa de existir
    db.flush()
    auditoria.registrar(
        db, "setup.master_criada", usuario_id=usuario.id, entidade="usuario",
        entidade_id=usuario.id, ip=ip,
    )
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise ErroAutenticacao("A conta Master já foi criada.", 409) from exc

    if cfg.arquivo_codigo_instalacao.exists():
        cfg.arquivo_codigo_instalacao.unlink()
    db.refresh(usuario)
    return usuario


@dataclass
class ResultadoLogin:
    token: str
    sessao: Sessao
    usuario: Usuario


def login(
    db: Session,
    nome_usuario: str,
    senha: str,
    cfg: Configuracoes,
    ip: str | None,
    dispositivo: str | None,
) -> ResultadoLogin:
    nome = (nome_usuario or "").strip().lower()
    usuario = db.scalar(select(Usuario).where(Usuario.nome_usuario == nome).with_for_update())
    momento = agora()
    falha_generica = ErroAutenticacao("Usuário ou senha incorretos.")

    if usuario is None:
        verificar_senha(None, senha)  # mesmo tempo de resposta
        auditoria.registrar(db, "login.falha", detalhes={"motivo": "usuario_inexistente"}, ip=ip)
        db.commit()
        raise falha_generica

    if usuario.bloqueado_ate and usuario.bloqueado_ate > momento:
        minutos = max(1, int((usuario.bloqueado_ate - momento).total_seconds() // 60) + 1)
        db.rollback()
        raise ErroAutenticacao(
            "Acesso bloqueado temporariamente por excesso de tentativas. "
            f"Tente novamente em {minutos} minuto(s).",
            423,
        )

    if not verificar_senha(usuario.senha_hash, senha):
        usuario.tentativas_falhas += 1
        detalhes = {"motivo": "senha_incorreta", "tentativas": usuario.tentativas_falhas}
        if usuario.tentativas_falhas >= cfg.login_max_tentativas:
            usuario.bloqueado_ate = momento + timedelta(minutes=cfg.login_bloqueio_minutos)
            usuario.tentativas_falhas = 0
            detalhes["bloqueado"] = True
        auditoria.registrar(db, "login.falha", usuario_id=usuario.id, detalhes=detalhes, ip=ip)
        db.commit()
        raise falha_generica

    if not usuario.ativo:
        auditoria.registrar(
            db, "login.falha", usuario_id=usuario.id, detalhes={"motivo": "usuario_desativado"}, ip=ip
        )
        db.commit()
        raise ErroAutenticacao("Este usuário está desativado. Procure a Advogada Master.", 403)

    if precisa_rehash(usuario.senha_hash):
        usuario.senha_hash = gerar_hash_senha(senha)
    usuario.tentativas_falhas = 0
    usuario.bloqueado_ate = None
    usuario.ultimo_login_em = momento

    token = gerar_token()
    sessao = Sessao(
        usuario_id=usuario.id,
        token_hash=hash_token(token),
        criada_em=momento,
        ultimo_uso_em=momento,
        expira_em=momento + timedelta(hours=cfg.sessao_maxima_horas),
        ip=ip,
        dispositivo=dispositivo,
    )
    db.add(sessao)
    auditoria.registrar(db, "login.sucesso", usuario_id=usuario.id, ip=ip,
                        detalhes={"dispositivo": dispositivo} if dispositivo else None)
    db.commit()
    db.refresh(usuario)
    return ResultadoLogin(token=token, sessao=sessao, usuario=usuario)


def validar_sessao(db: Session, token: str, cfg: Configuracoes) -> tuple[Sessao, Usuario]:
    sessao = db.scalar(select(Sessao).where(Sessao.token_hash == hash_token(token)))
    momento = agora()
    expirada = ErroAutenticacao("Sua sessão expirou. Entre novamente.")
    if sessao is None or sessao.encerrada_em is not None:
        raise expirada
    inatividade = timedelta(minutes=cfg.sessao_inatividade_minutos)
    if sessao.expira_em <= momento or momento - sessao.ultimo_uso_em > inatividade:
        sessao.encerrada_em = momento
        sessao.motivo_encerramento = "expirada"
        db.commit()
        raise expirada
    usuario = db.get(Usuario, sessao.usuario_id)
    if usuario is None or not usuario.ativo:
        sessao.encerrada_em = momento
        sessao.motivo_encerramento = "usuario_desativado"
        db.commit()
        raise ErroAutenticacao("Este usuário está desativado. Procure a Advogada Master.", 403)
    if momento - sessao.ultimo_uso_em > timedelta(minutes=1):
        sessao.ultimo_uso_em = momento
        db.commit()
    return sessao, usuario


def encerrar_sessao(db: Session, sessao: Sessao, motivo: str = "logout") -> None:
    sessao.encerrada_em = agora()
    sessao.motivo_encerramento = motivo
    auditoria.registrar(db, "logout", usuario_id=sessao.usuario_id)
    db.commit()


def encerrar_sessoes_do_usuario(db: Session, usuario_id: uuid.UUID, motivo: str) -> int:
    resultado = db.execute(
        update(Sessao)
        .where(Sessao.usuario_id == usuario_id, Sessao.encerrada_em.is_(None))
        .values(encerrada_em=agora(), motivo_encerramento=motivo)
    )
    return resultado.rowcount or 0


def trocar_senha(
    db: Session, usuario: Usuario, sessao_atual: Sessao, senha_atual: str, nova: str, ip: str | None
) -> None:
    if not verificar_senha(usuario.senha_hash, senha_atual):
        raise ErroAutenticacao("A senha atual está incorreta.", 400)
    if verificar_senha(usuario.senha_hash, nova):
        raise ErroAutenticacao("A nova senha deve ser diferente da atual.", 400)
    usuario.senha_hash = gerar_hash_senha(nova)
    usuario.deve_trocar_senha = False
    # Outras sessões abertas deste usuário são encerradas por segurança.
    db.execute(
        update(Sessao)
        .where(
            Sessao.usuario_id == usuario.id,
            Sessao.encerrada_em.is_(None),
            Sessao.id != sessao_atual.id,
        )
        .values(encerrada_em=agora(), motivo_encerramento="senha_alterada")
    )
    auditoria.registrar(db, "usuario.senha_alterada", usuario_id=usuario.id,
                        entidade="usuario", entidade_id=usuario.id, ip=ip)
    db.commit()
