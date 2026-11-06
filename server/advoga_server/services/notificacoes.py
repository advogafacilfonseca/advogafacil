"""Notificações automáticas: geradas por um serviço que roda no servidor (funciona mesmo com
todos os aplicativos fechados), sem duplicidade, com registro do resultado de cada envio.

- A Master escolhe quem recebe cada categoria. Só recebe quem tem a permissão "Recebimento de
  notificações" e acesso à área do aviso (agenda/pendências; avisos financeiros exigem Financeiro).
- Cada aviso tem uma chave única por usuário: o mesmo aviso nunca é gerado duas vezes.
- Antes de enviar o e-mail, o serviço confere se o aviso ainda vale (parcela paga, compromisso
  concluído/cancelado/reagendado): se não valer mais, não envia.
- Avisos não mostram valores em reais.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, time, timedelta

from advoga_shared.esquemas import (
    CATEGORIA_BACKUP,
    CATEGORIAS_FINANCEIRAS,
    CATEGORIAS_NOTIFICACAO,
    TIPOS_COMPROMISSO,
    CategoriaNotificacao,
    ConfiguracaoNotificacoes,
    ConfiguracaoNotificacoesSalvar,
    ResultadoCiclo,
    UsuarioNotificavel,
    nome_parcela,
)
from advoga_shared.esquemas import (
    Notificacao as NotificacaoSaida,
)
from advoga_shared.permissoes import Permissao
from fastapi import HTTPException
from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..models import (
    Compromisso,
    Configuracao,
    DestinatarioNotificacao,
    Notificacao,
    Parcela,
    Usuario,
)
from . import auditoria
from .autenticacao import permissoes_efetivas
from .email import Enviador, ErroEnvio, Mensagem, obter_enviador

log = logging.getLogger("advoga.notificacoes")
TRAVA_SERVICO = 7_400_017  # pg_advisory_lock: só um ciclo por vez, mesmo com mais de um processo
MAX_TENTATIVAS = 5
CHAVE_CONFIG = "notificacoes"
PADRAO_CONFIG = {"email_ativo": True, "hora_inicio": "07:00", "incluir_responsavel": [
    "audiencias", "reunioes", "prazos", "ligacoes_retornos", "outros_compromissos", "atrasados"]}
CATEGORIA_POR_TIPO = {"audiencia": "audiencias", "reuniao": "reunioes", "prazo": "prazos",
                      "ligacao": "ligacoes_retornos", "retorno": "ligacoes_retornos"}


# ================================================================================ regras
def _config(db: Session) -> dict:
    c = db.get(Configuracao, CHAVE_CONFIG)
    return PADRAO_CONFIG | (c.valor if c else {})


def pode_receber(u: Usuario, categoria: str) -> bool:
    if not u.ativo:
        return False
    if categoria == CATEGORIA_BACKUP:  # falhas de backup e HD desconectado: somente a Master
        return u.is_master
    perms = permissoes_efetivas(u)
    if Permissao.NOTIFICACOES not in perms:
        return False
    if categoria in CATEGORIAS_FINANCEIRAS:
        return Permissao.FINANCEIRO in perms
    return bool(perms & {Permissao.AGENDA, Permissao.PENDENCIAS})


def _usuario_saida(u: Usuario) -> UsuarioNotificavel:
    perms = permissoes_efetivas(u)
    return UsuarioNotificavel(id=u.id, nome=u.nome_completo, email=u.email,
                              recebe_notificacoes=Permissao.NOTIFICACOES in perms,
                              acessa_agenda=bool(perms & {Permissao.AGENDA, Permissao.PENDENCIAS}),
                              acessa_financeiro=Permissao.FINANCEIRO in perms)


def obter_configuracao(db: Session) -> ConfiguracaoNotificacoes:
    cfg = _config(db)
    escolhidos: dict[str, list[uuid.UUID]] = {}
    for d in db.scalars(select(DestinatarioNotificacao)):
        escolhidos.setdefault(d.categoria, []).append(d.usuario_id)
    usuarios = db.scalars(select(Usuario).where(Usuario.ativo).order_by(Usuario.is_master.desc(),
                                                                         Usuario.nome_completo)).all()
    return ConfiguracaoNotificacoes(
        categorias=[CategoriaNotificacao(
            categoria=k, rotulo=v, restrita_financeiro=k in CATEGORIAS_FINANCEIRAS,
            incluir_responsavel=None if k in CATEGORIAS_FINANCEIRAS else k in cfg["incluir_responsavel"],
            usuarios_ids=escolhidos.get(k, [])) for k, v in CATEGORIAS_NOTIFICACAO.items()],
        usuarios=[_usuario_saida(u) for u in usuarios], email_ativo=cfg["email_ativo"], hora_inicio=cfg["hora_inicio"])


def salvar_configuracao(db: Session, ator: Usuario, dados: ConfiguracaoNotificacoesSalvar,
                        ip: str | None) -> ConfiguracaoNotificacoes:
    vistas = set()
    for cat in dados.categorias:
        if cat.categoria not in CATEGORIAS_NOTIFICACAO:
            raise HTTPException(422, f"Categoria de aviso desconhecida: {cat.categoria}.")
        if cat.categoria in vistas:
            raise HTTPException(422, "Categoria repetida.")
        vistas.add(cat.categoria)
        for uid in cat.usuarios_ids:
            u = db.get(Usuario, uid)
            if u is None or not u.ativo:
                raise HTTPException(422, "Usuário inválido ou desativado na lista de destinatários.")
            if not pode_receber(u, cat.categoria):
                motivo = ("não tem a permissão Financeiro" if cat.categoria in CATEGORIAS_FINANCEIRAS and
                          Permissao.NOTIFICACOES in permissoes_efetivas(u) else
                          "não tem a permissão \"Recebimento de notificações\"" if Permissao.NOTIFICACOES
                          not in permissoes_efetivas(u) else "não tem acesso à agenda nem às pendências")
                raise HTTPException(422, f"{u.nome_completo} não pode receber \"{CATEGORIAS_NOTIFICACAO[cat.categoria]}\":"
                                         f" {motivo}.")
    antes = obter_configuracao(db)
    for cat in dados.categorias:
        db.execute(DestinatarioNotificacao.__table__.delete().where(
            DestinatarioNotificacao.categoria == cat.categoria))
        for uid in dict.fromkeys(cat.usuarios_ids):
            db.add(DestinatarioNotificacao(categoria=cat.categoria, usuario_id=uid))
    cfg = _config(db)
    incluir = set(cfg["incluir_responsavel"])
    for cat in dados.categorias:
        if cat.categoria not in CATEGORIAS_FINANCEIRAS:
            (incluir.add if cat.incluir_responsavel else incluir.discard)(cat.categoria)
    novo = {"email_ativo": dados.email_ativo, "hora_inicio": dados.hora_inicio, "incluir_responsavel": sorted(incluir)}
    linha = db.get(Configuracao, CHAVE_CONFIG)
    if linha is None:
        db.add(Configuracao(chave=CHAVE_CONFIG, valor=novo, atualizado_por=ator.id))
    else:
        linha.valor = novo
        linha.atualizado_por = ator.id
    db.flush()
    depois = obter_configuracao(db)
    nomes = {u.id: u.nome for u in depois.usuarios}
    mudancas = {}
    for a, d in zip(antes.categorias, depois.categorias):
        if set(a.usuarios_ids) != set(d.usuarios_ids) or a.incluir_responsavel != d.incluir_responsavel:
            mudancas[d.categoria] = {"destinatarios": sorted(nomes.get(i, str(i)) for i in d.usuarios_ids),
                                     "incluir_responsavel": d.incluir_responsavel}
    if antes.email_ativo != depois.email_ativo:
        mudancas["email_ativo"] = depois.email_ativo
    if antes.hora_inicio != depois.hora_inicio:
        mudancas["hora_inicio"] = depois.hora_inicio
    if mudancas:
        auditoria.registrar(db, "notificacoes.configuradas", usuario_id=ator.id, entidade="configuracao",
                            entidade_id=CHAVE_CONFIG, detalhes=mudancas, ip=ip)
    return depois


# =============================================================================== geração
def _destinatarios(db: Session, categoria: str, responsavel_id: uuid.UUID | None, incluir_resp: bool) -> list[Usuario]:
    ids = set(db.scalars(select(DestinatarioNotificacao.usuario_id).where(
        DestinatarioNotificacao.categoria == categoria)))
    if incluir_resp and responsavel_id:
        ids.add(responsavel_id)
    usuarios = [db.get(Usuario, i) for i in ids]
    return [u for u in usuarios if u is not None and pode_receber(u, categoria)]


def _texto_compromisso(c) -> str:
    local = c.inicio.astimezone()
    quando = local.strftime("%d/%m/%Y") + ("" if c.dia_inteiro else local.strftime(" às %H:%M"))
    linhas = [f"{TIPOS_COMPROMISSO.get(c.tipo, c.tipo)}: {c.titulo}", f"Quando: {quando}"]
    for rot, v in (("Cliente", c.cliente_nome), ("Processo", c.processo_rotulo), ("Local", c.local),
                   ("Responsável", c.responsavel_nome)):
        if v:
            linhas.append(f"{rot}: {v}")
    return "\n".join(linhas)


def _criar(db: Session, chave: str, categoria: str, u: Usuario, titulo: str, mensagem: str, entidade: str,
           entidade_id: str, email_ativo: bool) -> bool:
    chave_completa = f"{chave}:{u.id}"
    if db.scalar(select(Notificacao.id).where(Notificacao.chave == chave_completa)):
        return False
    n = Notificacao(id=uuid.uuid4(), chave=chave_completa, categoria=categoria, usuario_id=u.id, titulo=titulo,
                    mensagem=mensagem, entidade=entidade, entidade_id=entidade_id,
                    email_situacao="pendente" if email_ativo else "desativado", email_destino=u.email)
    try:
        with db.begin_nested():
            db.add(n)
    except IntegrityError:  # outro processo gerou o mesmo aviso ao mesmo tempo
        return False
    return True


def gerar(db: Session, agora: datetime | None = None) -> int:
    """Gera os avisos de agenda e financeiros que ainda não existem. Retorna quantos foram criados."""
    from . import agenda, financeiro

    cfg = _config(db)
    agora = agora or agenda.agora()
    hora = time.fromisoformat(cfg["hora_inicio"])
    if agora.time() < hora:
        return 0
    incluir = set(cfg["incluir_responsavel"])
    criadas = 0
    for a in agenda.avisos(db):
        c = a.compromisso
        categoria = "atrasados" if a.tipo == "atrasado" else CATEGORIA_POR_TIPO.get(c.tipo, "outros_compromissos")
        chave = f"agenda:{a.tipo}:{c.id}:{c.inicio.isoformat()}"
        for u in _destinatarios(db, categoria, c.responsavel_id, categoria in incluir):
            criadas += _criar(db, chave, categoria, u, a.titulo, _texto_compromisso(c), "compromisso", str(c.id),
                              cfg["email_ativo"])
    usuarios_fin = _destinatarios(db, "financeiro", None, False)
    if usuarios_fin:
        for a in financeiro.avisos(db):
            p = a.parcela
            nome = nome_parcela(p.tipo, p.numero)
            msg = (f"{nome} do contrato \"{p.servico_contratado or ''}\"\nCliente: {p.cliente_nome or '—'}\n"
                   f"Vencimento: {p.vencimento.strftime('%d/%m/%Y')}\n"
                   "Consulte o valor no Advoga Fácil (área Financeiro).")
            chave = f"fin:{a.tipo}:{p.id}:{p.vencimento.isoformat()}"
            for u in usuarios_fin:
                criadas += _criar(db, chave, "financeiro", u, a.titulo, msg, "parcela", str(p.id), cfg["email_ativo"])
    db.flush()
    return criadas


# ================================================================================= envio
def _ainda_vale(db: Session, n: Notificacao) -> bool:
    if n.entidade == "parcela":
        p = db.get(Parcela, uuid.UUID(n.entidade_id))
        return p is not None and p.situacao == "aberta"
    if n.entidade == "compromisso":
        c = db.get(Compromisso, uuid.UUID(n.entidade_id))
        if c is None or c.situacao != "agendado":
            return False
        # chave: agenda:<tipo>:<id>:<inicio>:<usuario>; se foi reagendado, o aviso antigo não vale mais
        partes = n.chave.split(":", 3)
        return len(partes) < 4 or partes[3].startswith(c.inicio.isoformat())
    return True


def enviar_pendentes(db: Session, enviador: Enviador | None, agora: datetime, limite: int = 200) -> ResultadoCiclo:
    pendentes = db.scalars(select(Notificacao).where(
        Notificacao.email_situacao == "pendente",
        (Notificacao.proxima_tentativa_em.is_(None)) | (Notificacao.proxima_tentativa_em <= agora))
        .order_by(Notificacao.criada_em).limit(limite).with_for_update(skip_locked=True)).all()
    enviadas = falhas = nao = 0
    for n in pendentes:
        u = db.get(Usuario, n.usuario_id)
        if not _ainda_vale(db, n):
            n.email_situacao, n.email_erro = "cancelado", "O aviso deixou de valer antes do envio."
            nao += 1
        elif u is None or not pode_receber(u, n.categoria):
            n.email_situacao, n.email_erro = "cancelado", "O usuário não pode mais receber este aviso."
            nao += 1
        elif not u.email:
            n.email_situacao = "sem_email"
            nao += 1
        elif enviador is None:
            n.email_situacao = "nao_configurado"
            n.email_erro = "Serviço de envio de e-mail não configurado."
            nao += 1
        else:
            n.email_tentativas += 1
            n.email_destino = u.email
            try:
                enviador.enviar(Mensagem(para=u.email, assunto=f"[Advoga Fácil] {n.titulo}",
                                         texto=f"{n.titulo}\n\n{n.mensagem}\n\n—\nAviso automático do Advoga Fácil. "
                                               "Não responda este e-mail."))
            except ErroEnvio as exc:
                n.email_erro = exc.mensagem[:500]
                if not exc.temporaria:
                    n.email_situacao = "rejeitado"
                elif n.email_tentativas >= MAX_TENTATIVAS:
                    n.email_situacao = "falhou"
                else:
                    n.proxima_tentativa_em = agora + timedelta(minutes=5 * 2 ** (n.email_tentativas - 1))
                falhas += 1
            except Exception as exc:  # noqa: BLE001 - registrar qualquer falha inesperada e seguir
                log.exception("Falha inesperada ao enviar e-mail")
                n.email_erro = f"Erro inesperado: {exc}"[:500]
                n.email_situacao = "falhou" if n.email_tentativas >= MAX_TENTATIVAS else "pendente"
                n.proxima_tentativa_em = agora + timedelta(minutes=15)
                falhas += 1
            else:
                n.email_situacao, n.email_enviado_em, n.email_erro = "enviado", agora, None
                enviadas += 1
        db.commit()  # cada envio fica registrado na hora, mesmo que o próximo falhe
    return ResultadoCiclo(geradas=0, enviadas=enviadas, falhas=falhas, nao_enviadas=nao)


def executar_ciclo(db: Session, enviador: Enviador | None = None, agora: datetime | None = None,
                   usar_configurado: bool = True, cfg=None) -> ResultadoCiclo | None:
    """Um ciclo do serviço: gera avisos novos e envia os pendentes. None se outro ciclo está rodando."""
    from .agenda import agora as agora_local

    agora = agora or agora_local()
    if not db.scalar(text("SELECT pg_try_advisory_lock(:k)"), {"k": TRAVA_SERVICO}):
        return None
    try:
        geradas = gerar(db, agora)
        db.commit()
        if enviador is None and usar_configurado:
            from ..core.config import obter_configuracoes

            enviador = obter_enviador(db, cfg or obter_configuracoes())
        r = enviar_pendentes(db, enviador, agora)
        r.geradas = geradas
        return r
    finally:
        db.rollback()
        db.execute(text("SELECT pg_advisory_unlock(:k)"), {"k": TRAVA_SERVICO})
        db.commit()


# ============================================================================== consultas
def saida(n: Notificacao, nome: str | None = None) -> NotificacaoSaida:
    return NotificacaoSaida(id=n.id, categoria=n.categoria, titulo=n.titulo, mensagem=n.mensagem, entidade=n.entidade,
                            entidade_id=n.entidade_id, usuario_id=n.usuario_id, usuario_nome=nome,
                            criada_em=n.criada_em, lida_em=n.lida_em, email_situacao=n.email_situacao,
                            email_tentativas=n.email_tentativas, email_erro=n.email_erro,
                            email_enviado_em=n.email_enviado_em)


def minhas(db: Session, usuario: Usuario, somente_nao_lidas: bool, limite: int) -> tuple[list[Notificacao], int, int]:
    """Avisos do próprio usuário. Avisos financeiros deixam de aparecer se ele perder a permissão."""
    cats = [c for c in CATEGORIAS_NOTIFICACAO if c not in CATEGORIAS_FINANCEIRAS or pode_receber(usuario, c)]
    if usuario.is_master:
        cats.append(CATEGORIA_BACKUP)
    base = select(Notificacao).where(Notificacao.usuario_id == usuario.id, Notificacao.categoria.in_(cats))
    nao_lidas = db.scalar(select(func.count()).select_from(base.where(Notificacao.lida_em.is_(None)).subquery())) or 0
    q = base.where(Notificacao.lida_em.is_(None)) if somente_nao_lidas else base
    total = db.scalar(select(func.count()).select_from(q.subquery())) or 0
    itens = db.scalars(q.order_by(Notificacao.criada_em.desc()).limit(limite)).all()
    return list(itens), total, nao_lidas


def marcar_lidas(db: Session, usuario: Usuario, ids: list[uuid.UUID] | None, agora: datetime) -> int:
    q = select(Notificacao).where(Notificacao.usuario_id == usuario.id, Notificacao.lida_em.is_(None))
    if ids is not None:
        q = q.where(Notificacao.id.in_(ids))
    itens = db.scalars(q).all()
    for n in itens:
        n.lida_em = agora
    db.flush()
    return len(itens)


def historico(db: Session, ver_financeiro: bool, *, usuario_id: uuid.UUID | None = None, categoria: str | None = None,
              situacao: str | None = None, desde: datetime | None = None, offset: int = 0,
              limite: int = 200) -> tuple[list[tuple[Notificacao, str]], int]:
    q = select(Notificacao, Usuario.nome_completo).join(Usuario, Usuario.id == Notificacao.usuario_id)
    if not ver_financeiro:
        q = q.where(Notificacao.categoria.not_in(list(CATEGORIAS_FINANCEIRAS)))
    if usuario_id:
        q = q.where(Notificacao.usuario_id == usuario_id)
    if categoria:
        q = q.where(Notificacao.categoria == categoria)
    if situacao:
        q = q.where(Notificacao.email_situacao == situacao)
    if desde:
        q = q.where(Notificacao.criada_em >= desde)
    total = db.scalar(select(func.count()).select_from(q.subquery())) or 0
    linhas = db.execute(q.order_by(Notificacao.criada_em.desc()).offset(offset).limit(limite)).all()
    return [(n, nome) for n, nome in linhas], total


def reenviar(db: Session, ator: Usuario, n: Notificacao, ip: str | None) -> Notificacao:
    if n.email_situacao not in ("falhou", "rejeitado", "nao_configurado"):
        raise HTTPException(409, "Só é possível reenviar avisos que falharam ou não foram enviados.")
    n.email_situacao, n.email_tentativas, n.proxima_tentativa_em, n.email_erro = "pendente", 0, None, None
    db.flush()
    auditoria.registrar(db, "notificacoes.reenvio", usuario_id=ator.id, entidade="notificacao", entidade_id=n.id,
                        detalhes={"titulo": n.titulo}, ip=ip)
    return n
