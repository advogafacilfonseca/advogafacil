"""Gerenciamento de usuários e permissões.

Regras:
- O nome e o cargo exibidos nunca concedem permissão.
- Somente a Master concede, altera ou retira permissões.
- Ninguém altera os próprios privilégios.
- A conta Master não é editada por outros, não é desativada e não tem permissões alteráveis.
- Usuários nunca são apagados: são desativados e o histórico é preservado.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from advoga_shared.esquemas import UsuarioAtualizar, UsuarioCriar, UsuarioDetalhe
from advoga_shared.permissoes import Permissao

from ..core.seguranca import gerar_hash_senha
from ..models import PermissaoUsuario, Sessao, Usuario
from . import auditoria
from .autenticacao import encerrar_sessoes_do_usuario, permissoes_efetivas

PERMISSOES_ADMINISTRATIVAS = {Permissao.ADMIN_USUARIOS, Permissao.CONFIGURACOES}


def _agora() -> datetime:
    return datetime.now(UTC)


def detalhe(db: Session, u: Usuario) -> UsuarioDetalhe:
    ativas = db.scalar(
        select(func.count()).select_from(Sessao).where(
            Sessao.usuario_id == u.id, Sessao.encerrada_em.is_(None), Sessao.expira_em > func.now()
        )
    ) or 0
    return UsuarioDetalhe(
        id=u.id, nome_completo=u.nome_completo, nome_exibicao=u.nome_exibicao,
        nome_usuario=u.nome_usuario, email=u.email, cargo=u.cargo, is_master=u.is_master,
        ativo=u.ativo, permissoes=sorted(permissoes_efetivas(u), key=lambda p: p.value),
        deve_trocar_senha=u.deve_trocar_senha, criado_em=u.criado_em,
        ultimo_login_em=u.ultimo_login_em, desativado_em=u.desativado_em, sessoes_ativas=ativas,
    )


def obter(db: Session, usuario_id: uuid.UUID) -> Usuario:
    u = db.get(Usuario, usuario_id)
    if u is None:
        raise HTTPException(404, "Usuário não encontrado.")
    return u


def listar(db: Session) -> list[Usuario]:
    return list(db.scalars(select(Usuario).order_by(Usuario.is_master.desc(), Usuario.ativo.desc(),
                                                    func.lower(Usuario.nome_completo))))


def _e_administrador(u: Usuario) -> bool:
    return u.is_master or bool(permissoes_efetivas(u) & PERMISSOES_ADMINISTRATIVAS)


def _exigir_pode_gerenciar(ator: Usuario, alvo: Usuario, acao: str) -> None:
    if alvo.is_master and not ator.is_master:
        raise HTTPException(403, "A conta Master só pode ser alterada pela própria Master.")
    if not ator.is_master and alvo.id != ator.id and _e_administrador(alvo):
        raise HTTPException(403, f"Somente a Master pode {acao} um usuário com acesso administrativo.")


def criar(db: Session, ator: Usuario, dados: UsuarioCriar, ip: str | None) -> Usuario:
    if dados.permissoes and not ator.is_master:
        raise HTTPException(403, "Somente a Master pode conceder permissões.")
    if db.scalar(select(Usuario.id).where(Usuario.nome_usuario == dados.nome_usuario)):
        raise HTTPException(409, "Este nome de usuário já está em uso.")
    u = Usuario(
        id=uuid.uuid4(),
        nome_completo=dados.nome_completo,
        nome_exibicao=dados.nome_exibicao or dados.nome_completo.split(" ")[0],
        cargo=dados.cargo,
        nome_usuario=dados.nome_usuario,
        email=str(dados.email).lower(),
        senha_hash=gerar_hash_senha(dados.senha_provisoria),
        deve_trocar_senha=True,
    )
    u.permissoes = [PermissaoUsuario(permissao=p.value, concedida_por=ator.id)
                    for p in sorted(set(dados.permissoes), key=lambda p: p.value)]
    db.add(u)
    db.flush()
    auditoria.registrar(db, "usuario.criado", usuario_id=ator.id, entidade="usuario", entidade_id=u.id,
                        detalhes={"nome_usuario": u.nome_usuario, "cargo": u.cargo,
                                  "permissoes": sorted(p.value for p in dados.permissoes)}, ip=ip)
    return u


def atualizar(db: Session, ator: Usuario, alvo: Usuario, dados: UsuarioAtualizar, ip: str | None) -> Usuario:
    _exigir_pode_gerenciar(ator, alvo, "editar")
    mudancas: dict[str, dict[str, str | None]] = {}
    for campo, valor in dados.model_dump(exclude_unset=True).items():
        if campo == "email" and valor is not None:
            valor = str(valor).lower()
        if campo in ("nome_completo", "nome_exibicao", "email") and valor is None:
            raise HTTPException(422, "Este campo não pode ficar em branco.")
        antigo = getattr(alvo, campo)
        if antigo != valor:
            mudancas[campo] = {"antes": antigo, "depois": valor}
            setattr(alvo, campo, valor)
    if mudancas:
        auditoria.registrar(db, "usuario.editado", usuario_id=ator.id, entidade="usuario",
                            entidade_id=alvo.id, detalhes=mudancas, ip=ip)
    db.flush()
    return alvo


def definir_permissoes(db: Session, ator: Usuario, alvo: Usuario, novas: list[Permissao], ip: str | None) -> Usuario:
    if not ator.is_master:
        raise HTTPException(403, "Somente a Master pode conceder, alterar ou retirar permissões.")
    if alvo.is_master:
        raise HTTPException(400, "A Master tem todas as permissões; elas não podem ser alteradas.")
    if alvo.id == ator.id:
        raise HTTPException(403, "Ninguém pode alterar os próprios privilégios.")
    antes = sorted(p.permissao for p in alvo.permissoes)
    alvo_conjunto = {p.value for p in novas}
    alvo.permissoes = [p for p in alvo.permissoes if p.permissao in alvo_conjunto]
    existentes = {p.permissao for p in alvo.permissoes}
    for p in sorted(alvo_conjunto - existentes):
        alvo.permissoes.append(PermissaoUsuario(permissao=p, concedida_por=ator.id))
    depois = sorted(alvo_conjunto)
    if antes != depois:
        auditoria.registrar(db, "usuario.permissoes_alteradas", usuario_id=ator.id, entidade="usuario",
                            entidade_id=alvo.id, detalhes={"antes": antes, "depois": depois}, ip=ip)
    db.flush()
    return alvo


def alterar_situacao(db: Session, ator: Usuario, alvo: Usuario, ativo: bool, ip: str | None) -> Usuario:
    if alvo.is_master:
        raise HTTPException(400, "A conta Master não pode ser desativada.")
    if alvo.id == ator.id:
        raise HTTPException(403, "Você não pode desativar a própria conta.")
    _exigir_pode_gerenciar(ator, alvo, "desativar ou reativar")
    if alvo.ativo == ativo:
        return alvo
    alvo.ativo = ativo
    alvo.desativado_em = None if ativo else _agora()
    if not ativo:
        encerrar_sessoes_do_usuario(db, alvo.id, "usuario_desativado")
    auditoria.registrar(db, "usuario.reativado" if ativo else "usuario.desativado", usuario_id=ator.id,
                        entidade="usuario", entidade_id=alvo.id, ip=ip)
    db.flush()
    return alvo


def redefinir_senha(db: Session, ator: Usuario, alvo: Usuario, senha: str, ip: str | None) -> Usuario:
    if alvo.is_master:
        raise HTTPException(400, "A Master altera a própria senha em \"Alterar minha senha\".")
    if alvo.id == ator.id:
        raise HTTPException(400, "Para trocar a sua senha, use \"Alterar minha senha\".")
    _exigir_pode_gerenciar(ator, alvo, "redefinir a senha de")
    alvo.senha_hash = gerar_hash_senha(senha)
    alvo.deve_trocar_senha = True
    alvo.tentativas_falhas = 0
    alvo.bloqueado_ate = None
    encerrar_sessoes_do_usuario(db, alvo.id, "senha_redefinida")
    auditoria.registrar(db, "usuario.senha_redefinida", usuario_id=ator.id, entidade="usuario",
                        entidade_id=alvo.id, ip=ip)
    db.flush()
    return alvo
