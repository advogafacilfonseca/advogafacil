"""Agenda e Central de Pendências.

Compromissos nunca são apagados: são concluídos ou cancelados. Editar, reagendar, atribuir,
concluir e cancelar ficam na auditoria (histórico do compromisso).

A "próxima audiência ou prazo" do cadastro de um processo vira automaticamente um compromisso
da agenda (do_processo). Reagendar, concluir ou cancelar esse compromisso atualiza o processo,
e alterar a data no processo reagenda o compromisso.
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, time, timedelta

from advoga_shared.esquemas import (
    TIPOS_COMPROMISSO,
    AvisoAgenda,
    CentralPendencias,
    CompromissoAtribuir,
    CompromissoAtualizar,
    CompromissoCancelar,
    CompromissoConcluir,
    CompromissoCriar,
    CompromissoReagendar,
    ItemPendencia,
    nome_parcela,
)
from advoga_shared.esquemas import (
    Compromisso as CompromissoSaida,
)
from fastapi import HTTPException
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session, aliased

from ..models import Cliente, Compromisso, Processo, Usuario
from . import auditoria
from .clientes import _escapar_like, _validar_responsavel, _valor_auditavel
from .processos import rotulo as rotulo_processo

MSG_CONFLITO = ("Este compromisso foi alterado por outra pessoa enquanto você editava. "
                "Reabra a agenda para ver a versão atual.")
CAMPOS_EDITAVEIS = ["titulo", "tipo", "cliente_id", "processo_id", "responsavel_id", "inicio", "dia_inteiro",
                    "duracao_minutos", "local", "prioridade", "observacoes"]
ORDEM_PRIORIDADE = {"urgente": 0, "alta": 1, "normal": 2, "baixa": 3}


# ================================================================================ tempo
def agora() -> datetime:
    """Hora local do servidor (o servidor fica no escritório)."""
    return datetime.now(UTC).astimezone()


def hoje() -> date:
    return agora().date()


def inicio_do_dia(d: date) -> datetime:
    return datetime.combine(d, time.min).astimezone()


def _local(dt: datetime) -> datetime:
    return dt.astimezone(agora().tzinfo)


def esta_atrasado(c: Compromisso) -> bool:
    if c.situacao != "agendado":
        return False
    if c.dia_inteiro:
        return _local(c.inicio).date() < hoje()
    return c.inicio < agora()


# =============================================================================== saída
def saida(db: Session, c: Compromisso) -> CompromissoSaida:
    nomes = {}
    for uid in {c.responsavel_id, c.concluido_por, c.criado_por} - {None}:
        u = db.get(Usuario, uid)
        nomes[uid] = u.nome_completo if u else None
    cli = db.get(Cliente, c.cliente_id) if c.cliente_id else None
    proc = db.get(Processo, c.processo_id) if c.processo_id else None
    return CompromissoSaida(
        id=c.id, titulo=c.titulo, tipo=c.tipo, cliente_id=c.cliente_id, cliente_nome=cli.nome_completo if cli else None,
        processo_id=c.processo_id, processo_rotulo=rotulo_processo(proc) if proc else None,
        responsavel_id=c.responsavel_id, responsavel_nome=nomes.get(c.responsavel_id), inicio=c.inicio,
        dia_inteiro=c.dia_inteiro, duracao_minutos=c.duracao_minutos, local=c.local, prioridade=c.prioridade,
        observacoes=c.observacoes, situacao=c.situacao, atrasado=esta_atrasado(c), do_processo=c.do_processo,
        reagendamentos=c.reagendamentos, concluido_em=c.concluido_em, concluido_por_nome=nomes.get(c.concluido_por),
        observacao_conclusao=c.observacao_conclusao, cancelado_em=c.cancelado_em,
        motivo_cancelamento=c.motivo_cancelamento, criado_por_nome=nomes.get(c.criado_por), criado_em=c.criado_em,
        versao=c.versao)


def obter(db: Session, compromisso_id: uuid.UUID, travar: bool = False) -> Compromisso:
    q = select(Compromisso).where(Compromisso.id == compromisso_id)
    if travar:
        q = q.with_for_update()
    c = db.scalar(q)
    if c is None:
        raise HTTPException(404, "Compromisso não encontrado.")
    return c


# =========================================================================== validações
def _normalizar_inicio(inicio: datetime, dia_inteiro: bool) -> datetime:
    return inicio_do_dia(_local(inicio).date()) if dia_inteiro else inicio


def _validar_vinculos(db: Session, campos: dict, atual: Compromisso | None = None) -> None:
    cliente_id = campos.get("cliente_id", atual.cliente_id if atual else None)
    processo_id = campos.get("processo_id", atual.processo_id if atual else None)
    if cliente_id is not None and db.get(Cliente, cliente_id) is None:
        raise HTTPException(422, "Cliente vinculado não encontrado.")
    if processo_id is not None:
        p = db.get(Processo, processo_id)
        if p is None:
            raise HTTPException(422, "Processo vinculado não encontrado.")
        if cliente_id is None:
            campos["cliente_id"] = p.cliente_id
        elif p.cliente_id != cliente_id:
            raise HTTPException(422, "O processo escolhido não pertence a este cliente.")
    if "responsavel_id" in campos:
        try:
            _validar_responsavel(db, campos["responsavel_id"])
        except HTTPException as exc:
            raise HTTPException(422, "Responsável inválido ou desativado.") from exc


def _exigir_agendado(c: Compromisso) -> None:
    if c.situacao != "agendado":
        raise HTTPException(409, "Este compromisso já foi "
                                 f"{'concluído' if c.situacao == 'concluido' else 'cancelado'} e não pode ser alterado.")


def _conferir_versao(c: Compromisso, versao: int) -> None:
    if c.versao != versao:
        raise HTTPException(409, MSG_CONFLITO)


def _registrar(db: Session, acao: str, ator: Usuario | None, c: Compromisso, detalhes: dict, ip: str | None) -> None:
    auditoria.registrar(db, acao, usuario_id=ator.id if ator else None, entidade="compromisso", entidade_id=c.id,
                        detalhes=detalhes, ip=ip)


# =================================================================== reflexo no processo
def _refletir_no_processo(db: Session, c: Compromisso, ator: Usuario, ip: str | None) -> None:
    """Compromisso espelho do processo: reagendar muda a data no processo; concluir/cancelar libera o campo."""
    if not c.do_processo or c.processo_id is None:
        return
    p = db.get(Processo, c.processo_id)
    if p is None:
        return
    if c.situacao == "agendado":
        if p.proximo_evento_em != c.inicio:
            antes = p.proximo_evento_em
            p.proximo_evento_em = c.inicio
            auditoria.registrar(db, "processo.editado", usuario_id=ator.id, entidade="processo", entidade_id=p.id,
                                detalhes={"proximo_evento_em": {"antes": _valor_auditavel(antes),
                                                                "depois": _valor_auditavel(c.inicio)},
                                          "origem": "agenda"}, ip=ip)
    elif p.proximo_evento_em is not None:
        antes = {"proximo_evento_tipo": p.proximo_evento_tipo, "proximo_evento_em": _valor_auditavel(p.proximo_evento_em)}
        p.proximo_evento_tipo = p.proximo_evento_em = p.proximo_evento_descricao = None
        auditoria.registrar(db, "processo.editado", usuario_id=ator.id, entidade="processo", entidade_id=p.id,
                            detalhes={"proximo_evento_em": {"antes": antes["proximo_evento_em"], "depois": None},
                                      "proximo_evento_tipo": {"antes": antes["proximo_evento_tipo"], "depois": None},
                                      "origem": f"agenda ({'concluído' if c.situacao == 'concluido' else 'cancelado'})"},
                            ip=ip)
    db.flush()


def _titulo_do_processo(p: Processo) -> str:
    base = TIPOS_COMPROMISSO.get(p.proximo_evento_tipo or "", "Compromisso")
    return p.proximo_evento_descricao or f"{base} · {rotulo_processo(p)}"


def sincronizar_processo(db: Session, ator: Usuario, p: Processo, ip: str | None) -> None:
    """Chamado ao criar/editar um processo: mantém o compromisso espelho da próxima audiência ou prazo."""
    atual = db.scalar(select(Compromisso).where(Compromisso.processo_id == p.id, Compromisso.do_processo,
                                                Compromisso.situacao == "agendado").with_for_update())
    if p.proximo_evento_em is None or p.proximo_evento_tipo is None:
        if atual is not None:
            atual.situacao = "cancelado"
            atual.cancelado_em = agora()
            atual.cancelado_por = ator.id
            atual.motivo_cancelamento = "Próxima audiência ou prazo retirado do cadastro do processo."
            db.flush()
            _registrar(db, "compromisso.cancelado", ator, atual,
                       {"motivo": atual.motivo_cancelamento, "origem": "processo"}, ip)
        return
    if atual is None:
        c = Compromisso(id=uuid.uuid4(), titulo=_titulo_do_processo(p), tipo=p.proximo_evento_tipo,
                        cliente_id=p.cliente_id, processo_id=p.id, responsavel_id=p.advogado_responsavel_id,
                        inicio=p.proximo_evento_em, dia_inteiro=False, prioridade="alta", do_processo=True,
                        criado_por=ator.id)
        db.add(c)
        db.flush()
        _registrar(db, "compromisso.criado", ator, c, {"titulo": c.titulo, "origem": "processo"}, ip)
        return
    mudancas = {}
    novos = {"titulo": _titulo_do_processo(p), "tipo": p.proximo_evento_tipo, "cliente_id": p.cliente_id,
             "responsavel_id": p.advogado_responsavel_id, "inicio": p.proximo_evento_em}
    for campo, valor in novos.items():
        if getattr(atual, campo) != valor:
            mudancas[campo] = {"antes": _valor_auditavel(getattr(atual, campo)), "depois": _valor_auditavel(valor)}
            setattr(atual, campo, valor)
    if mudancas:
        if "inicio" in mudancas:
            atual.reagendamentos += 1
        db.flush()
        _registrar(db, "compromisso.reagendado" if "inicio" in mudancas else "compromisso.editado", ator, atual,
                   mudancas | {"origem": "processo"}, ip)


# ============================================================================ operações
def criar(db: Session, ator: Usuario, dados: CompromissoCriar, ip: str | None) -> Compromisso:
    campos = dados.model_dump()
    if not campos.get("titulo"):
        raise HTTPException(422, "Título: campo obrigatório.")
    _validar_vinculos(db, campos)
    campos["inicio"] = _normalizar_inicio(campos["inicio"], campos["dia_inteiro"])
    c = Compromisso(id=uuid.uuid4(), criado_por=ator.id, **campos)
    db.add(c)
    db.flush()
    _registrar(db, "compromisso.criado", ator, c, {"titulo": c.titulo, "tipo": c.tipo,
                                                   "inicio": _valor_auditavel(c.inicio)}, ip)
    return c


def atualizar(db: Session, ator: Usuario, c: Compromisso, dados: CompromissoAtualizar, ip: str | None) -> Compromisso:
    _conferir_versao(c, dados.versao)
    _exigir_agendado(c)
    novos = dados.model_dump(exclude_unset=True, exclude={"versao"})
    for obrigatorio, nome in (("titulo", "Título"), ("tipo", "Tipo"), ("inicio", "Data"), ("prioridade", "Prioridade"),
                              ("dia_inteiro", "Dia inteiro")):
        if obrigatorio in novos and novos[obrigatorio] is None:
            raise HTTPException(422, f"{nome}: campo obrigatório.")
    if c.do_processo and ("processo_id" in novos and novos["processo_id"] != c.processo_id
                          or "tipo" in novos and novos["tipo"] != c.tipo):
        raise HTTPException(422, "Este compromisso vem do cadastro do processo: o tipo e o processo são alterados "
                                 "na ficha do processo.")
    _validar_vinculos(db, novos, c)
    if "inicio" in novos or "dia_inteiro" in novos:
        novos["inicio"] = _normalizar_inicio(novos.get("inicio", c.inicio), novos.get("dia_inteiro", c.dia_inteiro))
    mudancas = {}
    for campo, valor in novos.items():
        if campo in CAMPOS_EDITAVEIS and getattr(c, campo) != valor:
            mudancas[campo] = {"antes": _valor_auditavel(getattr(c, campo)), "depois": _valor_auditavel(valor)}
            setattr(c, campo, valor)
    if mudancas:
        if "inicio" in mudancas:
            c.reagendamentos += 1
        db.flush()
        _registrar(db, "compromisso.editado", ator, c, mudancas, ip)
        _refletir_no_processo(db, c, ator, ip)
    return c


def reagendar(db: Session, ator: Usuario, c: Compromisso, dados: CompromissoReagendar, ip: str | None) -> Compromisso:
    _conferir_versao(c, dados.versao)
    _exigir_agendado(c)
    dia_inteiro = c.dia_inteiro if dados.dia_inteiro is None else dados.dia_inteiro
    novo = _normalizar_inicio(dados.inicio, dia_inteiro)
    if novo == c.inicio and dia_inteiro == c.dia_inteiro:
        raise HTTPException(422, "Escolha uma data ou horário diferente do atual.")
    antes = c.inicio
    c.inicio, c.dia_inteiro = novo, dia_inteiro
    c.reagendamentos += 1
    db.flush()
    _registrar(db, "compromisso.reagendado", ator, c, {"inicio": {"antes": _valor_auditavel(antes),
                                                                   "depois": _valor_auditavel(novo)},
                                                        "motivo": (dados.motivo or "").strip() or None}, ip)
    _refletir_no_processo(db, c, ator, ip)
    return c


def concluir(db: Session, ator: Usuario, c: Compromisso, dados: CompromissoConcluir, ip: str | None) -> Compromisso:
    _conferir_versao(c, dados.versao)
    _exigir_agendado(c)
    c.situacao = "concluido"
    c.concluido_em = agora()
    c.concluido_por = ator.id
    c.observacao_conclusao = (dados.observacao or "").strip() or None
    db.flush()
    _registrar(db, "compromisso.concluido", ator, c, {"observacao": c.observacao_conclusao}, ip)
    _refletir_no_processo(db, c, ator, ip)
    return c


def cancelar(db: Session, ator: Usuario, c: Compromisso, dados: CompromissoCancelar, ip: str | None) -> Compromisso:
    _conferir_versao(c, dados.versao)
    _exigir_agendado(c)
    motivo = dados.motivo.strip()
    if len(motivo) < 3:
        raise HTTPException(422, "Informe o motivo do cancelamento.")
    c.situacao = "cancelado"
    c.cancelado_em = agora()
    c.cancelado_por = ator.id
    c.motivo_cancelamento = motivo
    db.flush()
    _registrar(db, "compromisso.cancelado", ator, c, {"motivo": motivo}, ip)
    _refletir_no_processo(db, c, ator, ip)
    return c


def atribuir(db: Session, ator: Usuario, c: Compromisso, dados: CompromissoAtribuir, ip: str | None) -> Compromisso:
    _conferir_versao(c, dados.versao)
    _exigir_agendado(c)
    _validar_vinculos(db, {"responsavel_id": dados.responsavel_id}, c)
    if c.responsavel_id == dados.responsavel_id:
        return c
    antes = c.responsavel_id
    c.responsavel_id = dados.responsavel_id
    db.flush()
    novo = db.get(Usuario, dados.responsavel_id) if dados.responsavel_id else None
    _registrar(db, "compromisso.atribuido", ator, c, {"responsavel_id": {"antes": _valor_auditavel(antes),
                                                                         "depois": _valor_auditavel(dados.responsavel_id)},
                                                      "responsavel": novo.nome_completo if novo else None}, ip)
    return c


# ============================================================================= consultas
def _consulta(inicio: datetime | None = None, fim: datetime | None = None, responsavel_id: uuid.UUID | None = None,
              cliente_id: uuid.UUID | None = None, processo_id: uuid.UUID | None = None, tipo: str | None = None,
              situacao: str | None = None, prioridade: str | None = None, termo: str | None = None,
              sem_responsavel: bool = False):
    q = select(Compromisso)
    if inicio is not None:
        q = q.where(Compromisso.inicio >= inicio)
    if fim is not None:
        q = q.where(Compromisso.inicio < fim)
    if responsavel_id is not None:
        q = q.where(Compromisso.responsavel_id == responsavel_id)
    if sem_responsavel:
        q = q.where(Compromisso.responsavel_id.is_(None))
    if cliente_id is not None:
        q = q.where(Compromisso.cliente_id == cliente_id)
    if processo_id is not None:
        q = q.where(Compromisso.processo_id == processo_id)
    if tipo:
        q = q.where(Compromisso.tipo == tipo)
    if prioridade:
        q = q.where(Compromisso.prioridade == prioridade)
    if situacao == "atrasado":
        limite_dia = inicio_do_dia(hoje())
        q = q.where(Compromisso.situacao == "agendado",
                    or_(Compromisso.inicio < limite_dia, (~Compromisso.dia_inteiro) & (Compromisso.inicio < agora())))
    elif situacao:
        q = q.where(Compromisso.situacao == situacao)
    if termo:
        cli = aliased(Cliente)
        q = q.outerjoin(cli, cli.id == Compromisso.cliente_id)
        for palavra in termo.split():
            padrao = f"%{_escapar_like(palavra)}%"
            q = q.where(or_(func.f_normalizar(Compromisso.titulo).like(func.f_normalizar(padrao)),
                            func.f_normalizar(func.coalesce(Compromisso.local, "")).like(func.f_normalizar(padrao)),
                            func.f_normalizar(func.coalesce(cli.nome_completo, "")).like(func.f_normalizar(padrao))))
    return q


def listar(db: Session, limite: int = 500, offset: int = 0, **filtros) -> tuple[list[Compromisso], int]:
    q = _consulta(**filtros)
    total = db.scalar(select(func.count()).select_from(q.subquery())) or 0
    itens = db.scalars(q.order_by(Compromisso.inicio, Compromisso.titulo, Compromisso.id).offset(offset).limit(limite)).all()
    return list(itens), total


# =============================================================================== avisos
def _rotulo_aviso(c: Compromisso, dia: date) -> tuple[str, str] | None:
    """(tipo, título) do aviso para um compromisso agendado, ou None."""
    d = _local(c.inicio).date()
    amanha = dia + timedelta(days=1)
    if c.tipo == "ligacao" and d <= dia:
        return "pendente", "VOCÊ TEM UMA LIGAÇÃO PENDENTE"
    if c.tipo == "retorno" and d <= dia:
        return "pendente", "EXISTE UM RETORNO DE CLIENTE PENDENTE"
    if esta_atrasado(c):
        return "atrasado", f"ATRASADO: {TIPOS_COMPROMISSO[c.tipo].upper()}"
    nomes = {"audiencia": "AUDIÊNCIA", "reuniao": "REUNIÃO", "consulta": "CONSULTA", "diligencia": "DILIGÊNCIA",
             "entrega_documentos": "ENTREGA DE DOCUMENTOS"}
    if d == dia:
        if c.tipo == "prazo":
            return "hoje", "PRAZO VENCE HOJE"
        return "hoje", f"HOJE TEM {nomes[c.tipo]}" if c.tipo in nomes else "COMPROMISSO HOJE"
    if d == amanha:
        if c.tipo == "prazo":
            return "amanha", "PRAZO VENCE AMANHÃ"
        return "amanha", f"AMANHÃ TEM {nomes[c.tipo]}" if c.tipo in nomes else "COMPROMISSO AMANHÃ"
    return None


def avisos(db: Session, responsavel_id: uuid.UUID | None = None) -> list[AvisoAgenda]:
    dia = hoje()
    fim = inicio_do_dia(dia + timedelta(days=2))
    itens, _ = listar(db, fim=fim, situacao="agendado", responsavel_id=responsavel_id, limite=1000)
    saida_ = []
    for c in itens:
        r = _rotulo_aviso(c, dia)
        if r:
            saida_.append(AvisoAgenda(tipo=r[0], titulo=r[1], compromisso=saida(db, c)))
    ordem = {"atrasado": 0, "hoje": 1, "pendente": 2, "amanha": 3}
    return sorted(saida_, key=lambda a: (ordem[a.tipo], a.compromisso.inicio))


# ================================================================== central de pendências
def _grupo(c: Compromisso, dia: date) -> str:
    if esta_atrasado(c):
        return "atrasado"
    d = _local(c.inicio).date()
    if d == dia:
        return "hoje"
    if d == dia + timedelta(days=1):
        return "amanha"
    return "proximos"


def central(db: Session, usuario: Usuario, financeiro: bool, *, ate: date | None = None, desde: date | None = None,
            responsavel_id: uuid.UUID | None = None, sem_responsavel: bool = False, cliente_id: uuid.UUID | None = None,
            processo_id: uuid.UUID | None = None, tipo: str | None = None, prioridade: str | None = None,
            situacao: str = "pendente") -> CentralPendencias:
    dia = hoje()
    ate = ate or dia + timedelta(days=14)
    fim = inicio_do_dia(ate + timedelta(days=1))
    ini = inicio_do_dia(desde) if desde else None
    filtros = dict(responsavel_id=responsavel_id, sem_responsavel=sem_responsavel, cliente_id=cliente_id,
                   processo_id=processo_id, tipo=tipo if tipo != "financeiro" else "__nenhum__", prioridade=prioridade)
    if situacao in ("pendente", "atrasado"):
        compromissos, _ = listar(db, inicio=ini, fim=fim, situacao="agendado" if situacao == "pendente" else "atrasado",
                                 limite=2000, **filtros)
    else:
        compromissos, _ = listar(db, inicio=ini, fim=fim, situacao=situacao, limite=2000, **filtros)
    itens: list[ItemPendencia] = []
    for c in compromissos:
        s = saida(db, c)
        grupo = _grupo(c, dia) if c.situacao == "agendado" else c.situacao
        itens.append(ItemPendencia(origem="compromisso", grupo=grupo, titulo=c.titulo, tipo=c.tipo, quando=c.inicio,
                                   cliente_nome=s.cliente_nome, processo_rotulo=s.processo_rotulo,
                                   responsavel_nome=s.responsavel_nome, prioridade=c.prioridade, compromisso=s))
    # Parcelas: somente para quem tem a permissão Financeiro, e sem filtros que não se aplicam a elas.
    incluir_parcelas = (financeiro and situacao in ("pendente", "atrasado") and tipo in (None, "financeiro")
                        and not (responsavel_id or sem_responsavel or processo_id or prioridade))
    if incluir_parcelas:
        from .financeiro import listar_parcelas

        parcelas, _ = listar_parcelas(db, filtro="abertas", fim=min(ate, dia + timedelta(days=1)), limite=1000,
                                      cliente_id=cliente_id)
        for p in parcelas:
            if desde and p.vencimento < desde:
                continue
            grupo = "atrasado" if p.atrasada else ("hoje" if p.vencimento == dia else "amanha")
            if situacao == "atrasado" and grupo != "atrasado":
                continue
            nome = nome_parcela(p.tipo, p.numero)
            itens.append(ItemPendencia(origem="parcela", grupo=grupo, titulo=f"{nome} · {p.servico_contratado or ''}",
                                       tipo="financeiro", vencimento=p.vencimento, cliente_nome=p.cliente_nome,
                                       parcela=p))
    ordem_grupo = {"atrasado": 0, "hoje": 1, "amanha": 2, "proximos": 3, "concluido": 4, "cancelado": 5}

    def chave(i: ItemPendencia):
        quando = i.quando or inicio_do_dia(i.vencimento)
        return (ordem_grupo.get(i.grupo, 9), ORDEM_PRIORIDADE.get(i.prioridade or "normal", 2), quando)

    itens.sort(key=chave)
    contagem: dict[str, int] = {}
    for i in itens:
        contagem[i.grupo] = contagem.get(i.grupo, 0) + 1
    return CentralPendencias(itens=itens, contagem=contagem, financeiro_visivel=financeiro)
