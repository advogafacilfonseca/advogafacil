"""Processos: cadastro vinculado ao cliente, edição com controle de edição simultânea,
movimentações (histórico imutável) e pesquisa por número CNJ ou parte contrária."""

from __future__ import annotations

import re
import uuid
from fastapi import HTTPException
from sqlalchemy import and_, func, or_, select
from sqlalchemy.orm import Session, aliased

from advoga_shared.esquemas import (
    SITUACOES_PROCESSO,
    Movimentacao,
    MovimentacaoCriar,
    Processo as ProcessoSaida,
    ProcessoAtualizar,
    ProcessoCriar,
    ProcessoResumo,
)
from advoga_shared.validacoes import formatar_cnj, somente_digitos

from ..models import Cliente, MovimentacaoProcesso, Processo, Usuario
from . import auditoria
from .clientes import _escapar_like, _nome_usuario, _validar_responsavel, _valor_auditavel

CAMPOS_EDITAVEIS = [
    "numero_cnj", "cliente_id", "tipo_acao", "area_juridica", "tribunal", "comarca", "vara", "parte_contraria",
    "advogado_responsavel_id", "data_distribuicao", "situacao", "fase_processual", "proximo_evento_tipo",
    "proximo_evento_em", "proximo_evento_descricao", "descricao", "observacoes",
]
MSG_CONFLITO = ("Este processo foi alterado por outra pessoa enquanto você editava. "
                "Reabra o processo para ver a versão atual antes de salvar.")


def rotulo(p: Processo | ProcessoResumo) -> str:
    numero = formatar_cnj(p.numero_cnj) if p.numero_cnj else "Sem número"
    return f"{numero} · {p.tipo_acao}" if p.tipo_acao else numero


def saida(db: Session, p: Processo) -> ProcessoSaida:
    dados = {campo: getattr(p, campo) for campo in ProcessoSaida.model_fields if hasattr(p, campo)}
    dados["advogado_responsavel_nome"] = _nome_usuario(db, p.advogado_responsavel_id)
    c = db.get(Cliente, p.cliente_id)
    dados["cliente_nome"] = c.nome_completo if c else None
    return ProcessoSaida(**dados)


def obter(db: Session, processo_id: uuid.UUID) -> Processo:
    p = db.get(Processo, processo_id)
    if p is None:
        raise HTTPException(404, "Processo não encontrado.")
    return p


def _validar_cliente(db: Session, cliente_id: uuid.UUID) -> None:
    if db.get(Cliente, cliente_id) is None:
        raise HTTPException(422, "Cliente vinculado não encontrado.")


def _verificar_numero(db: Session, numero: str | None, ignorar: uuid.UUID | None = None) -> None:
    if not numero:
        return
    q = select(Processo, Cliente.nome_completo).join(Cliente, Cliente.id == Processo.cliente_id).where(
        Processo.numero_cnj == numero)
    if ignorar:
        q = q.where(Processo.id != ignorar)
    existente = db.execute(q).first()
    if existente:
        raise HTTPException(409, f"Este número de processo já está cadastrado (cliente: {existente[1]}).")


def _validar_evento(tipo: str | None, quando) -> None:
    if (tipo is None) != (quando is None):
        raise HTTPException(422, "Próxima audiência ou prazo: informe o tipo e a data juntos.")


def criar(db: Session, ator: Usuario, dados: ProcessoCriar, ip: str | None) -> Processo:
    _validar_cliente(db, dados.cliente_id)
    _verificar_numero(db, dados.numero_cnj)
    _validar_responsavel(db, dados.advogado_responsavel_id)
    _validar_evento(dados.proximo_evento_tipo, dados.proximo_evento_em)
    p = Processo(id=uuid.uuid4(), criado_por=ator.id, **dados.model_dump())
    db.add(p)
    db.flush()
    auditoria.registrar(db, "processo.criado", usuario_id=ator.id, entidade="processo", entidade_id=p.id,
                        detalhes={"numero": formatar_cnj(p.numero_cnj) or None, "cliente_id": str(p.cliente_id)},
                        ip=ip)
    _sincronizar_agenda(db, ator, p, ip)
    return p


def atualizar(db: Session, ator: Usuario, p: Processo, dados: ProcessoAtualizar, ip: str | None) -> Processo:
    if p.versao != dados.versao:
        raise HTTPException(409, MSG_CONFLITO)
    novos = dados.model_dump(exclude_unset=True, exclude={"versao"})
    if "cliente_id" in novos:
        if novos["cliente_id"] is None:
            raise HTTPException(422, "Cliente vinculado: campo obrigatório.")
        _validar_cliente(db, novos["cliente_id"])
    if "situacao" in novos and novos["situacao"] is None:
        raise HTTPException(422, "Situação: campo obrigatório.")
    if "numero_cnj" in novos:
        _verificar_numero(db, novos["numero_cnj"], ignorar=p.id)
    if "advogado_responsavel_id" in novos:
        _validar_responsavel(db, novos["advogado_responsavel_id"])
    _validar_evento(novos.get("proximo_evento_tipo", p.proximo_evento_tipo),
                    novos.get("proximo_evento_em", p.proximo_evento_em))
    mudancas = {}
    for campo, valor in novos.items():
        if campo in CAMPOS_EDITAVEIS and getattr(p, campo) != valor:
            mudancas[campo] = {"antes": _valor_auditavel(getattr(p, campo)), "depois": _valor_auditavel(valor)}
            setattr(p, campo, valor)
    if mudancas:
        db.flush()
        auditoria.registrar(db, "processo.editado", usuario_id=ator.id, entidade="processo", entidade_id=p.id,
                            detalhes=mudancas, ip=ip)
        if mudancas.keys() & {"proximo_evento_tipo", "proximo_evento_em", "proximo_evento_descricao", "cliente_id",
                              "advogado_responsavel_id", "numero_cnj", "tipo_acao"}:
            _sincronizar_agenda(db, ator, p, ip)
    return p


def _sincronizar_agenda(db: Session, ator: Usuario, p: Processo, ip: str | None) -> None:
    from .agenda import sincronizar_processo  # importação tardia: agenda também usa este módulo

    sincronizar_processo(db, ator, p, ip)


# ------------------------------------------------------------- movimentações
def movimentacoes(db: Session, processo_id: uuid.UUID) -> list[Movimentacao]:
    linhas = db.execute(
        select(MovimentacaoProcesso, Usuario.nome_completo)
        .outerjoin(Usuario, Usuario.id == MovimentacaoProcesso.registrado_por)
        .where(MovimentacaoProcesso.processo_id == processo_id)
        .order_by(MovimentacaoProcesso.data_movimentacao.desc(), MovimentacaoProcesso.id.desc())
    ).all()
    return [Movimentacao(id=m.id, processo_id=m.processo_id, data_movimentacao=m.data_movimentacao,
                         descricao=m.descricao, registrado_por_nome=nome, registrado_em=m.registrado_em)
            for m, nome in linhas]


def registrar_movimentacao(db: Session, ator: Usuario, p: Processo, dados: MovimentacaoCriar,
                           ip: str | None) -> Movimentacao:
    m = MovimentacaoProcesso(processo_id=p.id, data_movimentacao=dados.data_movimentacao,
                             descricao=dados.descricao, registrado_por=ator.id)
    db.add(m)
    db.flush()
    db.refresh(m)
    auditoria.registrar(db, "processo.movimentacao", usuario_id=ator.id, entidade="processo", entidade_id=p.id,
                        detalhes={"data": dados.data_movimentacao.isoformat(), "descricao": dados.descricao[:300]},
                        ip=ip)
    return Movimentacao(id=m.id, processo_id=p.id, data_movimentacao=m.data_movimentacao, descricao=m.descricao,
                        registrado_por_nome=ator.nome_completo, registrado_em=m.registrado_em)


# ------------------------------------------------------------------ pesquisa
def _texto_processo():
    return func.f_normalizar(func.coalesce(Processo.parte_contraria, "") + " " + func.coalesce(Processo.tipo_acao, ""))


def filtro_texto(termo: str):
    """Número do processo (com ou sem pontuação) OU todas as palavras na parte contrária / tipo de ação."""
    termo = (termo or "").strip()
    condicoes = []
    digitos = somente_digitos(termo)
    if len(digitos) >= 3 and not re.search(r"[A-Za-zÀ-ÿ]", termo):
        condicoes.append(Processo.numero_cnj.like(f"%{digitos}%"))
    palavras = [p for p in re.split(r"\s+", termo) if re.search(r"[A-Za-zÀ-ÿ]", p)]
    if palavras:
        condicoes.append(and_(*[
            _texto_processo().like(func.concat("%", func.f_normalizar(_escapar_like(p)), "%"), escape="\\")
            for p in palavras
        ]))
    return or_(*condicoes) if condicoes else None


def buscar(db: Session, *, termo: str | None = None, cliente_id: uuid.UUID | None = None,
           situacao: str | None = None, responsavel_id: uuid.UUID | None = None,
           offset: int = 0, limite: int = 50) -> tuple[list[ProcessoResumo], int]:
    filtros = []
    if termo:
        cond = filtro_texto(termo)
        if cond is None:
            return [], 0
        filtros.append(cond)
    if cliente_id:
        filtros.append(Processo.cliente_id == cliente_id)
    if situacao in SITUACOES_PROCESSO:
        filtros.append(Processo.situacao == situacao)
    if responsavel_id:
        filtros.append(Processo.advogado_responsavel_id == responsavel_id)
    total = db.scalar(select(func.count()).select_from(Processo).where(*filtros)) or 0
    adv = aliased(Usuario)
    linhas = db.execute(
        select(Processo, Cliente.nome_completo, adv.nome_completo)
        .join(Cliente, Cliente.id == Processo.cliente_id)
        .outerjoin(adv, adv.id == Processo.advogado_responsavel_id)
        .where(*filtros)
        .order_by(Processo.proximo_evento_em.asc().nulls_last(), func.f_normalizar(Cliente.nome_completo), Processo.id)
        .offset(offset).limit(limite)
    ).all()
    itens = [ProcessoResumo(id=p.id, numero_cnj=p.numero_cnj, cliente_id=p.cliente_id, cliente_nome=cli,
                            tipo_acao=p.tipo_acao, parte_contraria=p.parte_contraria, situacao=p.situacao,
                            fase_processual=p.fase_processual, proximo_evento_tipo=p.proximo_evento_tipo,
                            proximo_evento_em=p.proximo_evento_em, advogado_responsavel_nome=nome_adv)
             for p, cli, nome_adv in linhas]
    return itens, total


def descricao_curta(p: ProcessoResumo) -> str:
    partes = [f"Cliente: {p.cliente_nome}"]
    if p.parte_contraria:
        partes.append(f"Parte contrária: {p.parte_contraria}")
    partes.append(SITUACOES_PROCESSO.get(p.situacao, p.situacao))
    return "  ·  ".join(partes)


def opcoes(db: Session, cliente_id: uuid.UUID) -> list[tuple[uuid.UUID, str]]:
    ps = db.scalars(select(Processo).where(Processo.cliente_id == cliente_id)
                    .order_by(Processo.data_distribuicao.desc().nulls_last(), Processo.criado_em.desc())).all()
    return [(p.id, rotulo(p)) for p in ps]

