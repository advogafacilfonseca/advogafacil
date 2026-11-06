"""Painel inicial e relatórios.

Regras de acesso (sempre no servidor):
- Cada relatório exige a permissão da sua área (advoga_shared.esquemas.PERMISSOES_RELATORIO).
- Relatórios com valores (parcelas, recebimentos, despesas, resultado) exigem "Financeiro".
- O relatório de contratos sai SEM valores para quem tem só "Contratos".
- O painel só traz os blocos das áreas liberadas para a pessoa; valores só com "Financeiro".
"""

from __future__ import annotations

import calendar
import uuid
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal

from fastapi import HTTPException
from sqlalchemy import Date, cast, func, select
from sqlalchemy.orm import Session

from advoga_shared.esquemas import (
    CATEGORIAS_DESPESA,
    FORMAS_PAGAMENTO,
    PRIORIDADES,
    SITUACOES_CONTRATO,
    SITUACOES_PARCELA,
    SITUACOES_PROCESSO,
    SITUACOES_RELATORIO,
    TIPOS_COMPROMISSO,
    TIPOS_PROXIMO_EVENTO,
    TIPOS_RELATORIO,
    ColunaRelatorio,
    CompromissoPainel,
    FinanceiroPainel,
    Painel,
    Relatorio,
    TotalRelatorio,
    relatorio_permitido,
)
from advoga_shared.permissoes import Permissao
from advoga_shared.validacoes import formatar_cnj, formatar_cpf, formatar_telefone

from ..models import Cliente, Compromisso, Contrato, Despesa, Pagamento, Parcela, Processo, Usuario
from . import agenda
from .financeiro import CENTAVO, ZERO, reais, resumo

LIMITE_LINHAS = 5000
_MESES = ["janeiro", "fevereiro", "março", "abril", "maio", "junho", "julho", "agosto", "setembro", "outubro",
          "novembro", "dezembro"]


@dataclass
class Filtros:
    inicio: date | None = None
    fim: date | None = None
    responsavel_id: uuid.UUID | None = None
    cliente_id: uuid.UUID | None = None
    situacao: str | None = None


def pode_gerar(tipo: str, permissoes: set[Permissao]) -> bool:
    return relatorio_permitido(tipo, permissoes)


def _br(d: date | None) -> str:
    return d.strftime("%d/%m/%Y") if d else ""


def _nomes_usuarios(db: Session) -> dict[uuid.UUID, str]:
    return dict(db.execute(select(Usuario.id, Usuario.nome_completo)).all())


def _validar(tipo: str, f: Filtros) -> None:
    if f.inicio and f.fim and f.fim < f.inicio:
        raise HTTPException(422, "A data final do período não pode ser anterior à data inicial.")
    if f.situacao and f.situacao not in SITUACOES_RELATORIO[tipo]:
        raise HTTPException(422, "Situação inválida para este relatório.")
    if tipo == "resultado_financeiro" and (f.responsavel_id or f.cliente_id or f.situacao):
        raise HTTPException(422, "O resultado financeiro é do escritório inteiro: use somente o período.")


def _descricao_filtros(db: Session, tipo: str, f: Filtros) -> list[str]:
    itens = []
    if f.inicio or f.fim:
        if f.inicio and f.fim:
            itens.append(f"Período: {_br(f.inicio)} a {_br(f.fim)}")
        elif f.inicio:
            itens.append(f"Período: a partir de {_br(f.inicio)}")
        else:
            itens.append(f"Período: até {_br(f.fim)}")
    else:
        itens.append("Período: todos")
    if f.responsavel_id:
        u = db.get(Usuario, f.responsavel_id)
        itens.append(f"Responsável: {u.nome_completo if u else 'não encontrado'}")
    if f.cliente_id:
        c = db.get(Cliente, f.cliente_id)
        itens.append(f"Cliente: {c.nome_completo if c else 'não encontrado'}")
    if f.situacao:
        itens.append(f"Situação: {SITUACOES_RELATORIO[tipo][f.situacao]}")
    return itens


def _limitar(q, total_q, db: Session) -> tuple[list, bool]:
    total = db.scalar(select(func.count()).select_from(total_q.subquery())) or 0
    return list(db.execute(q.limit(LIMITE_LINHAS)).all()), total > LIMITE_LINHAS


# ============================================================================ relatórios
def _clientes(db: Session, f: Filtros, nomes: dict, _fin: bool):
    ref = func.coalesce(Cliente.data_inicio_atendimento, cast(Cliente.criado_em, Date))
    q = select(Cliente)
    if f.inicio:
        q = q.where(ref >= f.inicio)
    if f.fim:
        q = q.where(ref <= f.fim)
    if f.responsavel_id:
        q = q.where(Cliente.advogado_responsavel_id == f.responsavel_id)
    if f.cliente_id:
        q = q.where(Cliente.id == f.cliente_id)
    if f.situacao:
        q = q.where(Cliente.situacao == f.situacao)
    linhas, limitado = _limitar(q.order_by(func.f_normalizar(Cliente.nome_completo)), q, db)
    colunas = [ColunaRelatorio(titulo="Nome", largura=3), ColunaRelatorio(titulo="CPF", largura=2),
               ColunaRelatorio(titulo="Telefone", largura=2), ColunaRelatorio(titulo="E-mail", largura=3),
               ColunaRelatorio(titulo="Cidade/UF", largura=2), ColunaRelatorio(titulo="Responsável", largura=2),
               ColunaRelatorio(titulo="Início do atendimento", tipo="data", largura=2),
               ColunaRelatorio(titulo="Situação", largura=1)]
    out = []
    for (c,) in linhas:
        cidade = "/".join(p for p in (c.cidade, c.uf) if p)
        out.append([c.nome_completo, formatar_cpf(c.cpf) or None, formatar_telefone(c.telefone_principal) or None,
                    c.email, cidade or None, nomes.get(c.advogado_responsavel_id),
                    c.data_inicio_atendimento or c.criado_em.date(),
                    "Ativo" if c.situacao == "ativo" else "Encerrado"])
    ativos = sum(1 for r in out if r[-1] == "Ativo")
    totais = [TotalRelatorio(rotulo="Clientes", valor=str(len(out))),
              TotalRelatorio(rotulo="Ativos", valor=str(ativos)),
              TotalRelatorio(rotulo="Encerrados", valor=str(len(out) - ativos))]
    return colunas, out, totais, "Período pela data de início do atendimento (ou do cadastro).", limitado


def _processos(db: Session, f: Filtros, nomes: dict, _fin: bool):
    ref = func.coalesce(Processo.data_distribuicao, cast(Processo.criado_em, Date))
    q = select(Processo, Cliente.nome_completo).join(Cliente, Cliente.id == Processo.cliente_id)
    if f.inicio:
        q = q.where(ref >= f.inicio)
    if f.fim:
        q = q.where(ref <= f.fim)
    if f.responsavel_id:
        q = q.where(Processo.advogado_responsavel_id == f.responsavel_id)
    if f.cliente_id:
        q = q.where(Processo.cliente_id == f.cliente_id)
    if f.situacao:
        q = q.where(Processo.situacao == f.situacao)
    linhas, limitado = _limitar(q.order_by(func.f_normalizar(Cliente.nome_completo), Processo.criado_em), q, db)
    colunas = [ColunaRelatorio(titulo="Número", largura=3), ColunaRelatorio(titulo="Cliente", largura=3),
               ColunaRelatorio(titulo="Tipo de ação", largura=2), ColunaRelatorio(titulo="Comarca / Vara", largura=3),
               ColunaRelatorio(titulo="Responsável", largura=2),
               ColunaRelatorio(titulo="Distribuição", tipo="data", largura=2),
               ColunaRelatorio(titulo="Situação", largura=2), ColunaRelatorio(titulo="Próximo evento", largura=2),
               ColunaRelatorio(titulo="Data do próximo evento", tipo="data_hora", largura=2)]
    out = []
    contagem: dict[str, int] = {}
    for p, cliente in linhas:
        local = " / ".join(x for x in (p.comarca, p.vara) if x)
        situacao = SITUACOES_PROCESSO.get(p.situacao, p.situacao)
        contagem[situacao] = contagem.get(situacao, 0) + 1
        evento = TIPOS_PROXIMO_EVENTO.get(p.proximo_evento_tipo or "", None)
        if evento and p.proximo_evento_descricao:
            evento = f"{evento}: {p.proximo_evento_descricao}"
        out.append([formatar_cnj(p.numero_cnj) if p.numero_cnj else "Sem número", cliente, p.tipo_acao,
                    local or None, nomes.get(p.advogado_responsavel_id), p.data_distribuicao, situacao, evento,
                    p.proximo_evento_em])
    totais = [TotalRelatorio(rotulo="Processos", valor=str(len(out)))]
    totais += [TotalRelatorio(rotulo=k, valor=str(v)) for k, v in sorted(contagem.items())]
    return colunas, out, totais, "Período pela data de distribuição (ou do cadastro).", limitado


def _situacao_compromisso(c: Compromisso) -> str:
    if agenda.esta_atrasado(c):
        return "Atrasado"
    return {"agendado": "Agendado", "concluido": "Concluído", "cancelado": "Cancelado"}.get(c.situacao, c.situacao)


def _compromissos(tipo_compromisso: str):
    def gerar(db: Session, f: Filtros, nomes: dict, _fin: bool):
        q = agenda._consulta(inicio=agenda.inicio_do_dia(f.inicio) if f.inicio else None,
                             fim=agenda.inicio_do_dia(f.fim + timedelta(days=1)) if f.fim else None,
                             responsavel_id=f.responsavel_id, cliente_id=f.cliente_id, tipo=tipo_compromisso,
                             situacao=f.situacao)
        q = q.add_columns(Cliente.nome_completo, Processo).outerjoin(Cliente, Cliente.id == Compromisso.cliente_id) \
            .outerjoin(Processo, Processo.id == Compromisso.processo_id)
        linhas, limitado = _limitar(q.order_by(Compromisso.inicio, Compromisso.titulo), q, db)
        quando = "Data e hora" if tipo_compromisso == "audiencia" else "Vencimento"
        colunas = [ColunaRelatorio(titulo=quando, tipo="data_hora", largura=2),
                   ColunaRelatorio(titulo="Título", largura=3), ColunaRelatorio(titulo="Cliente", largura=3),
                   ColunaRelatorio(titulo="Processo", largura=3), ColunaRelatorio(titulo="Local", largura=2),
                   ColunaRelatorio(titulo="Responsável", largura=2), ColunaRelatorio(titulo="Situação", largura=1)]
        out = []
        contagem: dict[str, int] = {}
        for c, cliente, proc in linhas:
            sit = _situacao_compromisso(c)
            contagem[sit] = contagem.get(sit, 0) + 1
            inicio = agenda._local(c.inicio)
            out.append([inicio.date() if c.dia_inteiro else inicio, c.titulo, cliente,
                        agenda.rotulo_processo(proc) if proc else None, c.local, nomes.get(c.responsavel_id), sit])
        nome = "Audiências" if tipo_compromisso == "audiencia" else "Prazos"
        totais = [TotalRelatorio(rotulo=nome, valor=str(len(out)))]
        totais += [TotalRelatorio(rotulo=k, valor=str(v)) for k, v in sorted(contagem.items())]
        return colunas, out, totais, None, limitado
    return gerar


_GRUPOS = {"atrasado": "Atrasado", "hoje": "Hoje", "amanha": "Amanhã", "proximos": "Próximos dias"}


def _pendencias(db: Session, f: Filtros, nomes: dict, fin: bool, usuario: Usuario | None = None):
    ate = f.fim or (agenda.hoje() + timedelta(days=14))
    c = agenda.central(db, usuario, fin, ate=ate, desde=f.inicio, responsavel_id=f.responsavel_id,
                       cliente_id=f.cliente_id, situacao="atrasado" if f.situacao == "atrasado" else "pendente")
    colunas = [ColunaRelatorio(titulo="Situação", largura=1), ColunaRelatorio(titulo="Quando", tipo="data_hora", largura=2),
               ColunaRelatorio(titulo="Tipo", largura=2), ColunaRelatorio(titulo="Título", largura=4),
               ColunaRelatorio(titulo="Cliente", largura=3), ColunaRelatorio(titulo="Responsável", largura=2),
               ColunaRelatorio(titulo="Prioridade", largura=1)]
    out = []
    contagem: dict[str, int] = {}
    for i in c.itens[:LIMITE_LINHAS]:
        grupo = _GRUPOS.get(i.grupo, i.grupo)
        contagem[grupo] = contagem.get(grupo, 0) + 1
        if i.origem == "parcela":
            quando, tipo = i.vencimento, "Financeiro"
        else:
            local = agenda._local(i.quando)
            quando = local.date() if i.compromisso and i.compromisso.dia_inteiro else local
            tipo = TIPOS_COMPROMISSO.get(i.tipo, i.tipo)
        out.append([grupo, quando, tipo, i.titulo, i.cliente_nome, i.responsavel_nome,
                    PRIORIDADES.get(i.prioridade or "", None)])
    totais = [TotalRelatorio(rotulo="Pendências", valor=str(len(out)))]
    totais += [TotalRelatorio(rotulo=g, valor=str(contagem[g])) for g in _GRUPOS.values() if g in contagem]
    obs = f"Compromissos não concluídos até {_br(ate)}."
    if fin:
        obs += " Parcelas aparecem até o dia seguinte ao de hoje, sem valores."
    return colunas, out, totais, obs, len(c.itens) > LIMITE_LINHAS


def _pagos_por(db: Session, coluna) -> dict:
    return dict(db.execute(select(coluna, func.sum(Pagamento.valor)).where(Pagamento.estornado_em.is_(None))
                           .group_by(coluna)).all())


def _contratos(db: Session, f: Filtros, nomes: dict, fin: bool):
    q = select(Contrato, Cliente.nome_completo).join(Cliente, Cliente.id == Contrato.cliente_id)
    if f.inicio:
        q = q.where(Contrato.data_inicio >= f.inicio)
    if f.fim:
        q = q.where(Contrato.data_inicio <= f.fim)
    if f.responsavel_id:
        q = q.where(Contrato.advogado_responsavel_id == f.responsavel_id)
    if f.cliente_id:
        q = q.where(Contrato.cliente_id == f.cliente_id)
    if f.situacao:
        q = q.where(Contrato.situacao == f.situacao)
    linhas, limitado = _limitar(q.order_by(Contrato.data_inicio.desc(), func.f_normalizar(Cliente.nome_completo)),
                                q, db)
    colunas = [ColunaRelatorio(titulo="Início", tipo="data", largura=2), ColunaRelatorio(titulo="Cliente", largura=3),
               ColunaRelatorio(titulo="Serviço contratado", largura=4), ColunaRelatorio(titulo="Responsável", largura=2),
               ColunaRelatorio(titulo="Situação", largura=1)]
    totais = [TotalRelatorio(rotulo="Contratos", valor=str(len(linhas)))]
    out = []
    if not fin:
        for c, cliente in linhas:
            out.append([c.data_inicio, cliente, c.servico_contratado, nomes.get(c.advogado_responsavel_id),
                        SITUACOES_CONTRATO.get(c.situacao, c.situacao)])
        return colunas, out, totais, "Valores não exibidos: exigem a permissão Financeiro.", limitado
    colunas += [ColunaRelatorio(titulo="Valor total", tipo="valor", largura=2),
                ColunaRelatorio(titulo="Recebido", tipo="valor", largura=2),
                ColunaRelatorio(titulo="A receber", tipo="valor", largura=2)]
    pagos = _pagos_por(db, Pagamento.contrato_id)
    pago_parcela = _pagos_por(db, Pagamento.parcela_id)
    abertas: dict[uuid.UUID, Decimal] = {}
    for p in db.scalars(select(Parcela).where(Parcela.situacao == "aberta")):
        abertas[p.contrato_id] = abertas.get(p.contrato_id, ZERO) + p.valor - Decimal(pago_parcela.get(p.id, 0))
    soma_total = soma_rec = soma_rec_aberto = ZERO
    for c, cliente in linhas:
        recebido = Decimal(pagos.get(c.id, 0)).quantize(CENTAVO)
        a_receber = (abertas.get(c.id, ZERO) if c.situacao != "cancelado" else ZERO).quantize(CENTAVO)
        if c.situacao != "cancelado":
            soma_total += c.valor_total
        soma_rec += recebido
        soma_rec_aberto += a_receber
        out.append([c.data_inicio, cliente, c.servico_contratado, nomes.get(c.advogado_responsavel_id),
                    SITUACOES_CONTRATO.get(c.situacao, c.situacao), c.valor_total, recebido, a_receber])
    totais += [TotalRelatorio(rotulo="Total contratado (sem cancelados)", valor=reais(soma_total)),
               TotalRelatorio(rotulo="Total recebido", valor=reais(soma_rec)),
               TotalRelatorio(rotulo="Total a receber", valor=reais(soma_rec_aberto))]
    return colunas, out, totais, None, limitado


def _parcelas(db: Session, f: Filtros, nomes: dict, _fin: bool):
    hoje = agenda.hoje()
    q = select(Parcela, Contrato, Cliente.nome_completo).join(Contrato, Contrato.id == Parcela.contrato_id) \
        .join(Cliente, Cliente.id == Contrato.cliente_id)
    if f.inicio:
        q = q.where(Parcela.vencimento >= f.inicio)
    if f.fim:
        q = q.where(Parcela.vencimento <= f.fim)
    if f.responsavel_id:
        q = q.where(Contrato.advogado_responsavel_id == f.responsavel_id)
    if f.cliente_id:
        q = q.where(Contrato.cliente_id == f.cliente_id)
    if f.situacao == "vencida":
        q = q.where(Parcela.situacao == "aberta", Parcela.vencimento < hoje)
    elif f.situacao:
        q = q.where(Parcela.situacao == f.situacao)
    linhas, limitado = _limitar(q.order_by(Parcela.vencimento, func.f_normalizar(Cliente.nome_completo),
                                           Parcela.numero), q, db)
    pagos = _pagos_por(db, Pagamento.parcela_id)
    colunas = [ColunaRelatorio(titulo="Vencimento", tipo="data", largura=2), ColunaRelatorio(titulo="Cliente", largura=3),
               ColunaRelatorio(titulo="Serviço contratado", largura=3), ColunaRelatorio(titulo="Parcela", largura=1),
               ColunaRelatorio(titulo="Valor", tipo="valor", largura=2), ColunaRelatorio(titulo="Pago", tipo="valor", largura=2),
               ColunaRelatorio(titulo="Restante", tipo="valor", largura=2), ColunaRelatorio(titulo="Situação", largura=2)]
    out = []
    pago_t = aberto_t = vencido_t = ZERO
    for p, c, cliente in linhas:
        pago = Decimal(pagos.get(p.id, 0)).quantize(CENTAVO)
        restante = (p.valor - pago).quantize(CENTAVO) if p.situacao == "aberta" else ZERO
        situacao = SITUACOES_PARCELA.get(p.situacao, p.situacao)
        if p.situacao == "aberta" and p.vencimento < hoje:
            situacao = "Vencida"
            vencido_t += restante
        pago_t += pago
        aberto_t += restante
        out.append([p.vencimento, cliente, c.servico_contratado, "Entrada" if p.tipo == "entrada" else str(p.numero),
                    p.valor, pago, restante, situacao])
    totais = [TotalRelatorio(rotulo="Parcelas", valor=str(len(out))),
              TotalRelatorio(rotulo="Total pago", valor=reais(pago_t)),
              TotalRelatorio(rotulo="Total em aberto", valor=reais(aberto_t)),
              TotalRelatorio(rotulo="Em atraso", valor=reais(vencido_t))]
    return colunas, out, totais, "Período pela data de vencimento.", limitado


def _recebimentos(db: Session, f: Filtros, nomes: dict, _fin: bool):
    q = select(Pagamento, Contrato, Parcela, Cliente.nome_completo) \
        .join(Contrato, Contrato.id == Pagamento.contrato_id).join(Parcela, Parcela.id == Pagamento.parcela_id) \
        .join(Cliente, Cliente.id == Pagamento.cliente_id)
    if f.inicio:
        q = q.where(Pagamento.data_recebimento >= f.inicio)
    if f.fim:
        q = q.where(Pagamento.data_recebimento <= f.fim)
    if f.responsavel_id:
        q = q.where(Pagamento.registrado_por == f.responsavel_id)
    if f.cliente_id:
        q = q.where(Pagamento.cliente_id == f.cliente_id)
    if f.situacao == "valido":
        q = q.where(Pagamento.estornado_em.is_(None))
    elif f.situacao == "estornado":
        q = q.where(Pagamento.estornado_em.is_not(None))
    linhas, limitado = _limitar(q.order_by(Pagamento.data_recebimento, Pagamento.registrado_em), q, db)
    colunas = [ColunaRelatorio(titulo="Data", tipo="data", largura=2), ColunaRelatorio(titulo="Cliente", largura=3),
               ColunaRelatorio(titulo="Serviço contratado", largura=3), ColunaRelatorio(titulo="Parcela", largura=1),
               ColunaRelatorio(titulo="Forma", largura=2), ColunaRelatorio(titulo="Valor", tipo="valor", largura=2),
               ColunaRelatorio(titulo="Lançado por", largura=2), ColunaRelatorio(titulo="Situação", largura=2)]
    out = []
    valido = estornado = ZERO
    por_forma: dict[str, Decimal] = {}
    for pg, c, p, cliente in linhas:
        forma = FORMAS_PAGAMENTO.get(pg.forma_pagamento, pg.forma_pagamento)
        if pg.estornado_em:
            estornado += pg.valor
            sit = "Estornado" + (f" ({pg.motivo_estorno})" if pg.motivo_estorno else "")
        else:
            valido += pg.valor
            por_forma[forma] = por_forma.get(forma, ZERO) + pg.valor
            sit = "Válido"
        out.append([pg.data_recebimento, cliente, c.servico_contratado,
                    "Entrada" if p.tipo == "entrada" else str(p.numero), forma, pg.valor,
                    nomes.get(pg.registrado_por), sit])
    totais = [TotalRelatorio(rotulo="Recebimentos", valor=str(len(out))),
              TotalRelatorio(rotulo="Total recebido (válidos)", valor=reais(valido))]
    if estornado:
        totais.append(TotalRelatorio(rotulo="Estornados (não somam)", valor=reais(estornado)))
    totais += [TotalRelatorio(rotulo=f"Por {k}", valor=reais(v)) for k, v in sorted(por_forma.items())]
    return colunas, out, totais, "Responsável = quem registrou o recebimento.", limitado


def _despesas(db: Session, f: Filtros, nomes: dict, _fin: bool):
    q = select(Despesa, Cliente.nome_completo).outerjoin(Cliente, Cliente.id == Despesa.cliente_id)
    if f.inicio:
        q = q.where(Despesa.data >= f.inicio)
    if f.fim:
        q = q.where(Despesa.data <= f.fim)
    if f.responsavel_id:
        q = q.where(Despesa.responsavel_id == f.responsavel_id)
    if f.cliente_id:
        q = q.where(Despesa.cliente_id == f.cliente_id)
    if f.situacao == "valida":
        q = q.where(Despesa.cancelada_em.is_(None))
    elif f.situacao == "cancelada":
        q = q.where(Despesa.cancelada_em.is_not(None))
    linhas, limitado = _limitar(q.order_by(Despesa.data, Despesa.criado_em), q, db)
    colunas = [ColunaRelatorio(titulo="Data", tipo="data", largura=2), ColunaRelatorio(titulo="Descrição", largura=4),
               ColunaRelatorio(titulo="Categoria", largura=2), ColunaRelatorio(titulo="Cliente", largura=3),
               ColunaRelatorio(titulo="Responsável", largura=2), ColunaRelatorio(titulo="Valor", tipo="valor", largura=2),
               ColunaRelatorio(titulo="Situação", largura=2)]
    out = []
    total = ZERO
    por_cat: dict[str, Decimal] = {}
    for d, cliente in linhas:
        cat = CATEGORIAS_DESPESA.get(d.categoria, d.categoria)
        if d.cancelada_em is None:
            total += d.valor
            por_cat[cat] = por_cat.get(cat, ZERO) + d.valor
        out.append([d.data, d.descricao, cat, cliente, nomes.get(d.responsavel_id), d.valor,
                    "Válida" if d.cancelada_em is None else "Cancelada"])
    totais = [TotalRelatorio(rotulo="Despesas", valor=str(len(out))),
              TotalRelatorio(rotulo="Total (sem canceladas)", valor=reais(total))]
    totais += [TotalRelatorio(rotulo=k, valor=reais(v)) for k, v in sorted(por_cat.items())]
    return colunas, out, totais, None, limitado


def _meses(inicio: date, fim: date) -> list[tuple[date, date]]:
    meses = []
    d = inicio.replace(day=1)
    while d <= fim:
        ultimo = d.replace(day=calendar.monthrange(d.year, d.month)[1])
        meses.append((max(d, inicio), min(ultimo, fim)))
        d = ultimo + timedelta(days=1)
    return meses


def _resultado(db: Session, f: Filtros, nomes: dict, _fin: bool):
    hoje = agenda.hoje()
    if f.inicio is None and f.fim is None:  # padrão: mês atual
        inicio = hoje.replace(day=1)
        fim = inicio.replace(day=calendar.monthrange(inicio.year, inicio.month)[1])
    elif f.inicio is None:
        inicio, fim = f.fim.replace(day=1), f.fim
    elif f.fim is None:
        inicio = f.inicio
        fim = hoje if f.inicio <= hoje else f.inicio.replace(day=calendar.monthrange(f.inicio.year, f.inicio.month)[1])
    else:
        inicio, fim = f.inicio, f.fim
    if (fim - inicio).days > 366 * 10:
        raise HTTPException(422, "Período longo demais para o resultado financeiro (máximo de 10 anos).")
    r = resumo(db, inicio, fim)
    mes_rec = cast(func.date_trunc("month", Pagamento.data_recebimento), Date)
    rec = dict(db.execute(select(mes_rec, func.sum(Pagamento.valor))
                          .where(Pagamento.estornado_em.is_(None), Pagamento.data_recebimento.between(inicio, fim))
                          .group_by(mes_rec)).all())
    mes_desp = cast(func.date_trunc("month", Despesa.data), Date)
    desp = dict(db.execute(select(mes_desp, func.sum(Despesa.valor))
                           .where(Despesa.cancelada_em.is_(None), Despesa.data.between(inicio, fim))
                           .group_by(mes_desp)).all())
    rec = {k: Decimal(v) for k, v in rec.items()}
    desp = {k: Decimal(v) for k, v in desp.items()}
    colunas = [ColunaRelatorio(titulo="Mês", largura=3), ColunaRelatorio(titulo="Recebido", tipo="valor", largura=2),
               ColunaRelatorio(titulo="Despesas", tipo="valor", largura=2),
               ColunaRelatorio(titulo="Saldo líquido", tipo="valor", largura=2)]
    out = []
    for a, b in _meses(inicio, fim):
        chave = a.replace(day=1)
        rv, dv = rec.get(chave, ZERO).quantize(CENTAVO), desp.get(chave, ZERO).quantize(CENTAVO)
        nome = f"{_MESES[a.month - 1].capitalize()} de {a.year}"
        if a.day != 1 or b.day != calendar.monthrange(b.year, b.month)[1]:
            nome += f" ({a.day:02d} a {b.day:02d})"
        out.append([nome, rv, dv, rv - dv])
    f.inicio, f.fim = inicio, fim
    totais = [TotalRelatorio(rotulo="Recebido no período", valor=reais(r.recebido_no_periodo)),
              TotalRelatorio(rotulo="Despesas no período", valor=reais(r.despesas_no_periodo)),
              TotalRelatorio(rotulo="Saldo líquido do período", valor=reais(r.saldo_liquido_periodo)),
              TotalRelatorio(rotulo="Previsto a receber no período", valor=reais(r.previsto_no_periodo)),
              TotalRelatorio(rotulo="Total contratado (vigentes)", valor=reais(r.total_contratado)),
              TotalRelatorio(rotulo="Total já recebido (geral)", valor=reais(r.total_recebido)),
              TotalRelatorio(rotulo="Total a receber hoje", valor=reais(r.total_a_receber)),
              TotalRelatorio(rotulo=f"Em atraso hoje ({r.parcelas_vencidas} parcelas)", valor=reais(r.total_vencido))]
    totais += [TotalRelatorio(rotulo=f"Despesas: {k}", valor=reais(v)) for k, v in sorted(r.despesas_por_categoria.items())]
    return colunas, out, totais, "Saldo líquido = recebido − despesas. Estornos e despesas canceladas não entram.", False


_GERADORES = {
    "clientes": _clientes, "processos": _processos, "audiencias": _compromissos("audiencia"),
    "prazos": _compromissos("prazo"), "pendencias": _pendencias, "contratos": _contratos, "parcelas": _parcelas,
    "recebimentos": _recebimentos, "despesas": _despesas, "resultado_financeiro": _resultado,
}


def gerar(db: Session, tipo: str, filtros: Filtros, usuario: Usuario, permissoes: set[Permissao]) -> Relatorio:
    if tipo not in TIPOS_RELATORIO:
        raise HTTPException(404, "Relatório não encontrado.")
    if not pode_gerar(tipo, permissoes):  # a rota já bloqueia; conferido de novo aqui
        raise HTTPException(403, "Você não tem permissão para acessar esta área.")
    _validar(tipo, filtros)
    fin = Permissao.FINANCEIRO in permissoes
    nomes = _nomes_usuarios(db)
    if tipo == "pendencias":
        colunas, linhas, totais, obs, limitado = _pendencias(db, filtros, nomes, fin, usuario)
    else:
        colunas, linhas, totais, obs, limitado = _GERADORES[tipo](db, filtros, nomes, fin)
    if limitado:
        obs = ((obs + " ") if obs else "") + (f"Mostrando as primeiras {LIMITE_LINHAS} linhas: use os filtros para "
                                              "reduzir o resultado.")
    return Relatorio(tipo=tipo, titulo=f"Relatório de {TIPOS_RELATORIO[tipo].lower()}"
                     if tipo != "resultado_financeiro" else "Resultado financeiro",
                     gerado_em=agenda.agora(), gerado_por=usuario.nome_completo,
                     filtros=_descricao_filtros(db, tipo, filtros), colunas=colunas, linhas=linhas, totais=totais,
                     observacao=obs, limitado=limitado,
                     confidencial=tipo in ("parcelas", "recebimentos", "despesas", "resultado_financeiro")
                     or (tipo == "contratos" and fin))


# ================================================================================ painel
def _item_painel(db: Session, c: Compromisso, nomes: dict) -> CompromissoPainel:
    cli = db.get(Cliente, c.cliente_id) if c.cliente_id else None
    return CompromissoPainel(id=c.id, titulo=c.titulo, tipo=c.tipo, inicio=c.inicio, dia_inteiro=c.dia_inteiro,
                             cliente_nome=cli.nome_completo if cli else None,
                             responsavel_nome=nomes.get(c.responsavel_id), atrasado=agenda.esta_atrasado(c))


def painel(db: Session, permissoes: set[Permissao]) -> Painel:
    p = Painel()
    if Permissao.CLIENTES in permissoes:
        p.clientes_ativos = db.scalar(select(func.count()).select_from(Cliente).where(Cliente.situacao == "ativo")) or 0
    if Permissao.PROCESSOS in permissoes:
        p.processos_em_andamento = db.scalar(select(func.count()).select_from(Processo)
                                             .where(Processo.situacao == "em_andamento")) or 0
    if Permissao.AGENDA in permissoes or Permissao.PENDENCIAS in permissoes:
        nomes = _nomes_usuarios(db)
        dia = agenda.hoje()
        amanha = agenda.inicio_do_dia(dia + timedelta(days=1))
        em_7 = agenda.inicio_do_dia(dia + timedelta(days=8))
        hoje_itens, _ = agenda.listar(db, inicio=agenda.inicio_do_dia(dia), fim=amanha, situacao="agendado", limite=30)
        p.compromissos_hoje = [_item_painel(db, c, nomes) for c in hoje_itens]
        atrasados, total = agenda.listar(db, situacao="atrasado", limite=30)
        p.atrasados = [_item_painel(db, c, nomes) for c in atrasados]
        p.total_atrasados = total
        aud, _ = agenda.listar(db, inicio=amanha, fim=em_7, tipo="audiencia", situacao="agendado", limite=10)
        p.proximas_audiencias = [_item_painel(db, c, nomes) for c in aud]
        prz, _ = agenda.listar(db, inicio=amanha, fim=em_7, tipo="prazo", situacao="agendado", limite=10)
        p.proximos_prazos = [_item_painel(db, c, nomes) for c in prz]
    if Permissao.FINANCEIRO in permissoes:
        dia = agenda.hoje()
        ini = dia.replace(day=1)
        fim = dia.replace(day=calendar.monthrange(dia.year, dia.month)[1])
        r = resumo(db, ini, fim)
        vencem = db.scalar(select(func.count()).select_from(Parcela).join(Contrato, Contrato.id == Parcela.contrato_id)
                           .where(Parcela.situacao == "aberta", Contrato.situacao != "cancelado",
                                  Parcela.vencimento.between(dia, dia + timedelta(days=7)))) or 0
        p.financeiro = FinanceiroPainel(recebido_no_mes=r.recebido_no_periodo, despesas_no_mes=r.despesas_no_periodo,
                                        saldo_do_mes=r.saldo_liquido_periodo, total_a_receber=r.total_a_receber,
                                        total_vencido=r.total_vencido, parcelas_vencidas=r.parcelas_vencidas,
                                        vencem_em_7_dias=vencem)
    return p


def descricao_curta(f: Filtros) -> dict:
    return {k: (str(v) if v is not None else None) for k, v in vars(f).items()}


def nome_arquivo(tipo: str, formato: str, quando: datetime) -> str:
    return f"relatorio-{tipo.replace('_', '-')}-{quando:%Y-%m-%d-%H%M}.{formato}"
