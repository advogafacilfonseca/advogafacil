"""Contratos e financeiro.

Princípios:
- Contrato firmado não é dinheiro recebido. O contrato gera parcelas (a receber); o dinheiro só
  entra quando um recebimento é registrado (baixa), parcial ou integral.
- Nada é apagado: recebimento errado se corrige por estorno; parcela por cancelamento ou
  renegociação, sempre com motivo e auditoria.
- Sempre vale: valor contratado = recebido + a receber + cancelado.
"""

from __future__ import annotations

import calendar
import uuid
from datetime import UTC, date, datetime, timedelta
from decimal import ROUND_DOWN, Decimal

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from advoga_shared.esquemas import (
    AvisoFinanceiro,
    CATEGORIAS_DESPESA,
    Contrato as ContratoSaida,
    ContratoAtualizar,
    ContratoCriar,
    Despesa as DespesaSaida,
    DespesaAtualizar,
    DespesaCriar,
    Pagamento as PagamentoSaida,
    PagamentoCriar,
    Parcela as ParcelaSaida,
    ParcelaPlano,
    Renegociar,
    ResumoFinanceiro,
    TotaisContrato,
)

from ..models import Cliente, Comprovante, Contrato, Despesa, Pagamento, Parcela, Processo, Usuario
from . import auditoria
from .clientes import _nome_usuario, _validar_responsavel, _valor_auditavel
from .processos import rotulo as rotulo_processo

CENTAVO = Decimal("0.01")
ZERO = Decimal("0.00")
MSG_CONFLITO = ("Este registro financeiro foi alterado por outra pessoa enquanto você trabalhava. "
                "Atualize a tela antes de continuar.")


def reais(v: Decimal) -> str:
    texto = f"{v:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return f"R$ {texto}"


def hoje() -> date:
    return date.today()


# ====================================================================== plano de parcelas
def _somar_meses(d: date, meses: int, dia: int) -> date:
    mes = d.month - 1 + meses
    ano = d.year + mes // 12
    mes = mes % 12 + 1
    return date(ano, mes, min(dia, calendar.monthrange(ano, mes)[1]))


def _dividir(valor: Decimal, n: int) -> list[Decimal]:
    """Divide em n partes de centavos exatos; a diferença de arredondamento vai na última."""
    base = (valor / n).quantize(CENTAVO, rounding=ROUND_DOWN)
    partes = [base] * n
    partes[-1] = valor - base * (n - 1)
    return partes


def plano_parcelas(valor: Decimal, quantidade: int | None, valor_parcela: Decimal | None,
                   primeiro: date | None, dia: int | None, personalizadas: list[ParcelaPlano] | None
                   ) -> list[tuple[Decimal, date]]:
    """Gera (valor, vencimento) das parcelas que somam exatamente `valor`."""
    if valor <= 0:
        if quantidade or personalizadas:
            raise HTTPException(422, "Não há saldo para parcelar: a entrada já cobre o valor total.")
        return []
    if personalizadas:
        soma = sum((p.valor for p in personalizadas), ZERO)
        if soma != valor:
            raise HTTPException(422, f"A soma das parcelas ({reais(soma)}) deve ser igual ao valor a parcelar "
                                     f"({reais(valor)}).")
        return [(p.valor, p.vencimento) for p in personalizadas]
    if not quantidade:
        raise HTTPException(422, f"Informe a quantidade de parcelas para o saldo de {reais(valor)}.")
    if primeiro is None:
        raise HTTPException(422, "Informe a data do primeiro vencimento.")
    if valor_parcela is not None:
        if valor_parcela * quantidade != valor:
            raise HTTPException(
                422, f"{quantidade} parcelas de {reais(valor_parcela)} somam {reais(valor_parcela * quantidade)}, "
                     f"mas o saldo a parcelar é {reais(valor)}. Ajuste os valores ou use vencimentos personalizados.")
        valores = [valor_parcela] * quantidade
    else:
        valores = _dividir(valor, quantidade)
    dia = dia or primeiro.day
    return [(v, primeiro if i == 0 else _somar_meses(primeiro, i, dia)) for i, v in enumerate(valores)]


# ================================================================================ leitura
def _pagos(db: Session, parcela_ids: list[uuid.UUID]) -> dict[uuid.UUID, Decimal]:
    if not parcela_ids:
        return {}
    linhas = db.execute(
        select(Pagamento.parcela_id, func.coalesce(func.sum(Pagamento.valor), 0))
        .where(Pagamento.parcela_id.in_(parcela_ids), Pagamento.estornado_em.is_(None))
        .group_by(Pagamento.parcela_id)
    ).all()
    return {pid: Decimal(v) for pid, v in linhas}


def _parcela_saida(p: Parcela, pago: Decimal, extra: dict | None = None) -> ParcelaSaida:
    restante = (p.valor - pago - p.valor_baixado) if p.situacao == "aberta" else ZERO
    return ParcelaSaida(
        id=p.id, contrato_id=p.contrato_id, numero=p.numero, tipo=p.tipo, valor=p.valor, vencimento=p.vencimento,
        situacao=p.situacao, valor_pago=pago, valor_restante=restante, valor_baixado=p.valor_baixado,
        atrasada=p.situacao == "aberta" and p.vencimento < hoje() and restante > 0, versao=p.versao,
        **(extra or {}))


def parcelas_do_contrato(db: Session, contrato_id: uuid.UUID) -> list[ParcelaSaida]:
    ps = db.scalars(select(Parcela).where(Parcela.contrato_id == contrato_id).order_by(Parcela.numero)).all()
    pagos = _pagos(db, [p.id for p in ps])
    return [_parcela_saida(p, pagos.get(p.id, ZERO)) for p in ps]


def totais(contrato: Contrato, parcelas: list[ParcelaSaida]) -> TotaisContrato:
    recebido = sum((p.valor_pago for p in parcelas), ZERO)
    a_receber = sum((p.valor_restante for p in parcelas), ZERO)
    vencido = sum((p.valor_restante for p in parcelas if p.atrasada), ZERO)
    cancelado = sum((p.valor_baixado for p in parcelas if p.situacao == "cancelada"), ZERO)
    return TotaisContrato(contratado=contrato.valor_total, recebido=recebido, a_receber=a_receber,
                          vencido=vencido, cancelado=cancelado)


def contrato_saida(db: Session, c: Contrato, financeiro: bool) -> ContratoSaida:
    cliente = db.get(Cliente, c.cliente_id)
    processo = db.get(Processo, c.processo_id) if c.processo_id else None
    dados = dict(
        id=c.id, cliente_id=c.cliente_id, cliente_nome=cliente.nome_completo if cliente else None,
        processo_id=c.processo_id, processo_rotulo=rotulo_processo(processo) if processo else None,
        servico_contratado=c.servico_contratado, advogado_responsavel_id=c.advogado_responsavel_id,
        advogado_responsavel_nome=_nome_usuario(db, c.advogado_responsavel_id), data_inicio=c.data_inicio,
        observacoes=c.observacoes, situacao=c.situacao, motivo_cancelamento=c.motivo_cancelamento,
        criado_em=c.criado_em, versao=c.versao, financeiro_visivel=financeiro,
    )
    if financeiro:
        parcelas = parcelas_do_contrato(db, c.id)
        dados["parcelas"] = parcelas
        dados["totais"] = totais(c, parcelas)
    return ContratoSaida(**dados)


def obter_contrato(db: Session, contrato_id: uuid.UUID, travar: bool = False) -> Contrato:
    q = select(Contrato).where(Contrato.id == contrato_id)
    if travar:
        q = q.with_for_update()
    c = db.scalar(q)
    if c is None:
        raise HTTPException(404, "Contrato não encontrado.")
    return c


def listar_contratos(db: Session, *, cliente_id: uuid.UUID | None, situacao: str | None, offset: int,
                     limite: int) -> tuple[list[Contrato], int]:
    filtros = []
    if cliente_id:
        filtros.append(Contrato.cliente_id == cliente_id)
    if situacao:
        filtros.append(Contrato.situacao == situacao)
    total = db.scalar(select(func.count()).select_from(Contrato).where(*filtros)) or 0
    cs = db.scalars(select(Contrato).join(Cliente, Cliente.id == Contrato.cliente_id).where(*filtros)
                    .order_by(Contrato.data_inicio.desc(), Contrato.criado_em.desc()).offset(offset).limit(limite)).all()
    return list(cs), total


# ============================================================================== contratos
def _validar_vinculos(db: Session, cliente_id: uuid.UUID | None, processo_id: uuid.UUID | None) -> None:
    if cliente_id is not None and db.get(Cliente, cliente_id) is None:
        raise HTTPException(422, "Cliente não encontrado.")
    if processo_id is not None:
        p = db.get(Processo, processo_id)
        if p is None or (cliente_id is not None and p.cliente_id != cliente_id):
            raise HTTPException(422, "O processo escolhido não pertence a este cliente.")


def criar_contrato(db: Session, ator: Usuario, dados: ContratoCriar, ip: str | None) -> Contrato:
    _validar_vinculos(db, dados.cliente_id, dados.processo_id)
    _validar_responsavel(db, dados.advogado_responsavel_id)
    if dados.valor_entrada > dados.valor_total:
        raise HTTPException(422, "A entrada não pode ser maior que o valor total do contrato.")
    saldo = dados.valor_total - dados.valor_entrada
    plano = plano_parcelas(saldo, dados.quantidade_parcelas, dados.valor_parcela, dados.primeiro_vencimento,
                           dados.dia_vencimento, dados.parcelas_personalizadas)
    c = Contrato(id=uuid.uuid4(), cliente_id=dados.cliente_id, processo_id=dados.processo_id,
                 servico_contratado=dados.servico_contratado, advogado_responsavel_id=dados.advogado_responsavel_id,
                 data_inicio=dados.data_inicio, valor_total=dados.valor_total, valor_original=dados.valor_total,
                 observacoes=dados.observacoes, criado_por=ator.id)
    db.add(c)
    db.flush()
    if dados.valor_entrada > 0:
        db.add(Parcela(contrato_id=c.id, numero=0, tipo="entrada", valor=dados.valor_entrada,
                       vencimento=dados.vencimento_entrada or dados.data_inicio))
    for i, (valor, venc) in enumerate(plano, start=1):
        db.add(Parcela(contrato_id=c.id, numero=i, tipo="parcela", valor=valor, vencimento=venc))
    db.flush()
    auditoria.registrar(db, "contrato.criado", usuario_id=ator.id, entidade="contrato", entidade_id=c.id,
                        detalhes={"cliente_id": str(c.cliente_id), "servico": c.servico_contratado,
                                  "valor_total": str(c.valor_total), "entrada": str(dados.valor_entrada),
                                  "parcelas": len(plano)}, ip=ip)
    return c


def atualizar_contrato(db: Session, ator: Usuario, c: Contrato, dados: ContratoAtualizar, ip: str | None) -> Contrato:
    if c.versao != dados.versao:
        raise HTTPException(409, MSG_CONFLITO)
    novos = dados.model_dump(exclude_unset=True, exclude={"versao"})
    if "processo_id" in novos:
        _validar_vinculos(db, c.cliente_id, novos["processo_id"])
    if "advogado_responsavel_id" in novos:
        _validar_responsavel(db, novos["advogado_responsavel_id"])
    if "servico_contratado" in novos and not (novos["servico_contratado"] or "").strip():
        raise HTTPException(422, "Informe o serviço contratado.")
    mudancas = {}
    for campo, valor in novos.items():
        if isinstance(valor, str):
            valor = valor.strip() or None
        if getattr(c, campo) != valor:
            mudancas[campo] = {"antes": _valor_auditavel(getattr(c, campo)), "depois": _valor_auditavel(valor)}
            setattr(c, campo, valor)
    if mudancas:
        db.flush()
        auditoria.registrar(db, "contrato.editado", usuario_id=ator.id, entidade="contrato", entidade_id=c.id,
                            detalhes=mudancas, ip=ip)
    return c


def _travar_parcela(db: Session, parcela_id: uuid.UUID) -> Parcela:
    p = db.scalar(select(Parcela).where(Parcela.id == parcela_id).with_for_update())
    if p is None:
        raise HTTPException(404, "Parcela não encontrada.")
    return p


def _atualizar_situacao_contrato(db: Session, contrato_id: uuid.UUID) -> None:
    c = obter_contrato(db, contrato_id)
    abertas = db.scalar(select(func.count()).select_from(Parcela).where(
        Parcela.contrato_id == contrato_id, Parcela.situacao == "aberta")) or 0
    if c.situacao == "ativo" and abertas == 0:
        c.situacao = "quitado"
    elif c.situacao == "quitado" and abertas > 0:
        c.situacao = "ativo"
    db.flush()


def _baixar_parcela(db: Session, p: Parcela, situacao: str, motivo: str) -> Decimal:
    pago = _pagos(db, [p.id]).get(p.id, ZERO)
    restante = p.valor - pago
    p.valor_baixado = restante
    p.situacao = situacao
    p.motivo_baixa = motivo
    return restante


def cancelar_parcela(db: Session, ator: Usuario, parcela_id: uuid.UUID, motivo: str, versao: int,
                     ip: str | None) -> Parcela:
    p = _travar_parcela(db, parcela_id)
    c = obter_contrato(db, p.contrato_id, travar=True)
    if p.versao != versao:
        raise HTTPException(409, MSG_CONFLITO)
    if p.situacao != "aberta":
        raise HTTPException(400, "Somente parcelas em aberto podem ser canceladas.")
    restante = _baixar_parcela(db, p, "cancelada", motivo.strip())
    db.flush()
    _atualizar_situacao_contrato(db, c.id)
    auditoria.registrar(db, "financeiro.parcela_cancelada", usuario_id=ator.id, entidade="contrato",
                        entidade_id=c.id, detalhes={"parcela": p.numero, "valor_cancelado": str(restante),
                                                    "motivo": p.motivo_baixa}, ip=ip)
    return p


def cancelar_contrato(db: Session, ator: Usuario, c: Contrato, motivo: str, versao: int, ip: str | None) -> Contrato:
    if c.versao != versao:
        raise HTTPException(409, MSG_CONFLITO)
    if c.situacao == "cancelado":
        raise HTTPException(400, "Este contrato já está cancelado.")
    total = ZERO
    for p in db.scalars(select(Parcela).where(Parcela.contrato_id == c.id, Parcela.situacao == "aberta")
                        .with_for_update()).all():
        total += _baixar_parcela(db, p, "cancelada", f"Contrato cancelado: {motivo.strip()}")
    c.situacao = "cancelado"
    c.cancelado_em = datetime.now(UTC)
    c.motivo_cancelamento = motivo.strip()
    db.flush()
    auditoria.registrar(db, "contrato.cancelado", usuario_id=ator.id, entidade="contrato", entidade_id=c.id,
                        detalhes={"motivo": c.motivo_cancelamento, "valor_cancelado": str(total)}, ip=ip)
    return c


def renegociar(db: Session, ator: Usuario, c: Contrato, dados: Renegociar, ip: str | None) -> Contrato:
    c = obter_contrato(db, c.id, travar=True)
    if c.versao != dados.versao:
        raise HTTPException(409, MSG_CONFLITO)
    if c.situacao != "ativo":
        raise HTTPException(400, "Somente contratos ativos podem ser renegociados.")
    antigas = db.scalars(select(Parcela).where(Parcela.id.in_(dados.parcelas_ids)).with_for_update()).all()
    if len(antigas) != len(set(dados.parcelas_ids)) or any(p.contrato_id != c.id for p in antigas):
        raise HTTPException(422, "Parcelas inválidas para este contrato.")
    if any(p.situacao != "aberta" for p in antigas):
        raise HTTPException(400, "Somente parcelas em aberto podem ser renegociadas.")
    saldo = sum((_baixar_parcela(db, p, "renegociada", dados.motivo.strip()) for p in antigas), ZERO)
    plano = plano_parcelas(dados.novo_valor, dados.quantidade_parcelas, None, dados.primeiro_vencimento,
                           dados.dia_vencimento, dados.parcelas_personalizadas)
    proximo = (db.scalar(select(func.max(Parcela.numero)).where(Parcela.contrato_id == c.id)) or 0) + 1
    for i, (valor, venc) in enumerate(plano):
        db.add(Parcela(contrato_id=c.id, numero=proximo + i, tipo="parcela", valor=valor, vencimento=venc))
    c.valor_total = c.valor_total + dados.novo_valor - saldo
    db.flush()
    auditoria.registrar(db, "contrato.renegociado", usuario_id=ator.id, entidade="contrato", entidade_id=c.id,
                        detalhes={"parcelas_renegociadas": sorted(p.numero for p in antigas),
                                  "saldo_anterior": str(saldo), "novo_valor": str(dados.novo_valor),
                                  "novas_parcelas": len(plano), "motivo": dados.motivo.strip(),
                                  "valor_contratado": str(c.valor_total)}, ip=ip)
    return c


# ============================================================================ recebimentos
def _validar_comprovante(db: Session, comprovante_id: uuid.UUID | None) -> None:
    if comprovante_id is not None and db.get(Comprovante, comprovante_id) is None:
        raise HTTPException(422, "Comprovante não encontrado. Envie o arquivo novamente.")


def registrar_pagamento(db: Session, ator: Usuario, dados: PagamentoCriar, ip: str | None) -> Pagamento:
    # A parcela fica travada até o fim da transação: dois recebimentos simultâneos nunca
    # ultrapassam o valor devido.
    p = _travar_parcela(db, dados.parcela_id)
    c = obter_contrato(db, p.contrato_id)
    if p.situacao != "aberta":
        raise HTTPException(400, f"Esta parcela está {p.situacao} e não aceita recebimentos.")
    _validar_comprovante(db, dados.comprovante_id)
    pago = _pagos(db, [p.id]).get(p.id, ZERO)
    restante = p.valor - pago
    if dados.valor > restante:
        raise HTTPException(422, f"O valor informado ({reais(dados.valor)}) é maior que o restante desta parcela "
                                 f"({reais(restante)}).")
    pg = Pagamento(id=uuid.uuid4(), parcela_id=p.id, contrato_id=c.id, cliente_id=c.cliente_id, valor=dados.valor,
                   data_recebimento=dados.data_recebimento, forma_pagamento=dados.forma_pagamento,
                   observacoes=(dados.observacoes or "").strip() or None, comprovante_id=dados.comprovante_id,
                   registrado_por=ator.id)
    db.add(pg)
    if dados.valor == restante:
        p.situacao = "paga"
    p.versao += 1  # sinaliza a alteração para quem estiver com a parcela aberta na tela
    db.flush()
    _atualizar_situacao_contrato(db, c.id)
    auditoria.registrar(db, "financeiro.recebimento", usuario_id=ator.id, entidade="contrato", entidade_id=c.id,
                        detalhes={"parcela": p.numero, "valor": str(dados.valor), "forma": dados.forma_pagamento,
                                  "data": dados.data_recebimento.isoformat(),
                                  "parcial": dados.valor < restante}, ip=ip)
    return pg


def estornar_pagamento(db: Session, ator: Usuario, pagamento_id: uuid.UUID, motivo: str, ip: str | None) -> Pagamento:
    pg = db.get(Pagamento, pagamento_id)
    if pg is None:
        raise HTTPException(404, "Recebimento não encontrado.")
    p = _travar_parcela(db, pg.parcela_id)
    db.refresh(pg)
    if pg.estornado_em is not None:
        raise HTTPException(400, "Este recebimento já foi estornado.")
    if p.situacao in ("cancelada", "renegociada"):
        raise HTTPException(400, "A parcela deste recebimento foi cancelada ou renegociada; o estorno não é "
                                 "possível. Registre um ajuste com a Advogada Master.")
    pg.estornado_em = datetime.now(UTC)
    pg.estornado_por = ator.id
    pg.motivo_estorno = motivo.strip()
    if p.situacao == "paga":
        p.situacao = "aberta"
    p.versao += 1
    db.flush()
    _atualizar_situacao_contrato(db, pg.contrato_id)
    auditoria.registrar(db, "financeiro.estorno", usuario_id=ator.id, entidade="contrato", entidade_id=pg.contrato_id,
                        detalhes={"parcela": p.numero, "valor": str(pg.valor), "motivo": pg.motivo_estorno}, ip=ip)
    return pg


def pagamento_saida(db: Session, pg: Pagamento) -> PagamentoSaida:
    p = db.get(Parcela, pg.parcela_id)
    cli = db.get(Cliente, pg.cliente_id)
    comp = db.get(Comprovante, pg.comprovante_id) if pg.comprovante_id else None
    return PagamentoSaida(
        id=pg.id, parcela_id=pg.parcela_id, parcela_numero=p.numero, contrato_id=pg.contrato_id,
        cliente_id=pg.cliente_id, cliente_nome=cli.nome_completo if cli else None, valor=pg.valor,
        data_recebimento=pg.data_recebimento, forma_pagamento=pg.forma_pagamento, observacoes=pg.observacoes,
        comprovante_id=pg.comprovante_id, comprovante_nome=comp.nome_arquivo if comp else None,
        registrado_por_nome=_nome_usuario(db, pg.registrado_por), registrado_em=pg.registrado_em,
        estornado_em=pg.estornado_em, estornado_por_nome=_nome_usuario(db, pg.estornado_por),
        motivo_estorno=pg.motivo_estorno)


def listar_pagamentos(db: Session, *, contrato_id: uuid.UUID | None = None, cliente_id: uuid.UUID | None = None,
                      inicio: date | None = None, fim: date | None = None, offset: int = 0, limite: int = 100
                      ) -> tuple[list[PagamentoSaida], int]:
    filtros = []
    if contrato_id:
        filtros.append(Pagamento.contrato_id == contrato_id)
    if cliente_id:
        filtros.append(Pagamento.cliente_id == cliente_id)
    if inicio:
        filtros.append(Pagamento.data_recebimento >= inicio)
    if fim:
        filtros.append(Pagamento.data_recebimento <= fim)
    total = db.scalar(select(func.count()).select_from(Pagamento).where(*filtros)) or 0
    pgs = db.scalars(select(Pagamento).where(*filtros)
                     .order_by(Pagamento.data_recebimento.desc(), Pagamento.registrado_em.desc())
                     .offset(offset).limit(limite)).all()
    return [pagamento_saida(db, pg) for pg in pgs], total


# ============================================================================== parcelas
def listar_parcelas(db: Session, *, filtro: str = "abertas", cliente_id: uuid.UUID | None = None,
                    inicio: date | None = None, fim: date | None = None, offset: int = 0, limite: int = 100
                    ) -> tuple[list[ParcelaSaida], int]:
    """filtro: abertas | vencidas | a_vencer | pagas | todas (vencimento entre início e fim)."""
    filtros = [Contrato.situacao != "cancelado"] if filtro != "todas" else []
    if filtro in ("abertas", "vencidas", "a_vencer"):
        filtros.append(Parcela.situacao == "aberta")
    if filtro == "vencidas":
        filtros.append(Parcela.vencimento < hoje())
    elif filtro == "a_vencer":
        filtros.append(Parcela.vencimento >= hoje())
    elif filtro == "pagas":
        filtros.append(Parcela.situacao == "paga")
    if cliente_id:
        filtros.append(Contrato.cliente_id == cliente_id)
    if inicio:
        filtros.append(Parcela.vencimento >= inicio)
    if fim:
        filtros.append(Parcela.vencimento <= fim)
    base = select(Parcela, Contrato, Cliente.nome_completo).join(Contrato, Contrato.id == Parcela.contrato_id) \
        .join(Cliente, Cliente.id == Contrato.cliente_id).where(*filtros)
    total = db.scalar(select(func.count()).select_from(base.subquery())) or 0
    linhas = db.execute(base.order_by(Parcela.vencimento, Cliente.nome_completo, Parcela.numero)
                        .offset(offset).limit(limite)).all()
    pagos = _pagos(db, [p.id for p, _c, _n in linhas])
    return [_parcela_saida(p, pagos.get(p.id, ZERO), {"cliente_id": c.cliente_id, "cliente_nome": nome,
                                                      "servico_contratado": c.servico_contratado})
            for p, c, nome in linhas], total


def avisos(db: Session) -> list[AvisoFinanceiro]:
    """AMANHÃ TEM PAGAMENTO, PAGAMENTO VENCE HOJE e parcelas atrasadas (somente abertas)."""
    amanha = hoje() + timedelta(days=1)
    itens, _ = listar_parcelas(db, filtro="abertas", fim=amanha, limite=500)
    saida = []
    for p in itens:
        if p.valor_restante <= 0:
            continue
        if p.vencimento == amanha:
            saida.append(AvisoFinanceiro(tipo="amanha", titulo="AMANHÃ TEM PAGAMENTO", parcela=p))
        elif p.vencimento == hoje():
            saida.append(AvisoFinanceiro(tipo="hoje", titulo="PAGAMENTO VENCE HOJE", parcela=p))
        else:
            dias = (hoje() - p.vencimento).days
            saida.append(AvisoFinanceiro(tipo="atrasada", titulo=f"PARCELA ATRASADA HÁ {dias} DIA{'S' if dias > 1 else ''}",
                                         parcela=p))
    ordem = {"hoje": 0, "amanha": 1, "atrasada": 2}
    return sorted(saida, key=lambda a: (ordem[a.tipo], a.parcela.vencimento))


# ============================================================================== despesas
def _validar_despesa(db: Session, dados) -> None:
    campos = dados.model_dump(exclude_unset=True)
    if "responsavel_id" in campos:
        _validar_responsavel(db, campos["responsavel_id"])
    if isinstance(dados, DespesaCriar):
        _validar_vinculos(db, campos.get("cliente_id"), campos.get("processo_id"))
    if "comprovante_id" in campos:
        _validar_comprovante(db, campos["comprovante_id"])


def criar_despesa(db: Session, ator: Usuario, dados: DespesaCriar, ip: str | None) -> Despesa:
    _validar_despesa(db, dados)
    d = Despesa(id=uuid.uuid4(), registrado_por=ator.id, **dados.model_dump())
    if d.responsavel_id is None:
        d.responsavel_id = ator.id
    d.observacoes = (d.observacoes or "").strip() or None
    db.add(d)
    db.flush()
    auditoria.registrar(db, "financeiro.despesa_lancada", usuario_id=ator.id, entidade="despesa", entidade_id=d.id,
                        detalhes={"descricao": d.descricao, "valor": str(d.valor), "categoria": d.categoria}, ip=ip)
    return d


def obter_despesa(db: Session, despesa_id: uuid.UUID) -> Despesa:
    d = db.get(Despesa, despesa_id)
    if d is None:
        raise HTTPException(404, "Despesa não encontrada.")
    return d


def atualizar_despesa(db: Session, ator: Usuario, d: Despesa, dados: DespesaAtualizar, ip: str | None) -> Despesa:
    if d.versao != dados.versao:
        raise HTTPException(409, MSG_CONFLITO)
    if d.cancelada_em is not None:
        raise HTTPException(400, "Despesa cancelada não pode ser alterada.")
    _validar_despesa(db, dados)
    novos = dados.model_dump(exclude_unset=True, exclude={"versao"})
    if "processo_id" in novos or "cliente_id" in novos:
        _validar_vinculos(db, novos.get("cliente_id", d.cliente_id), novos.get("processo_id", d.processo_id))
    for campo in ("descricao", "categoria", "valor", "data"):
        if campo in novos and novos[campo] is None:
            raise HTTPException(422, "Descrição, categoria, valor e data são obrigatórios.")
    mudancas = {}
    for campo, valor in novos.items():
        if isinstance(valor, str):
            valor = valor.strip() or None
        if getattr(d, campo) != valor:
            mudancas[campo] = {"antes": _valor_auditavel(str(getattr(d, campo)) if isinstance(getattr(d, campo), Decimal)
                                                         else getattr(d, campo)),
                               "depois": _valor_auditavel(str(valor) if isinstance(valor, Decimal) else valor)}
            setattr(d, campo, valor)
    if mudancas:
        db.flush()
        auditoria.registrar(db, "financeiro.despesa_alterada", usuario_id=ator.id, entidade="despesa",
                            entidade_id=d.id, detalhes=mudancas, ip=ip)
    return d


def cancelar_despesa(db: Session, ator: Usuario, d: Despesa, motivo: str, versao: int, ip: str | None) -> Despesa:
    if d.versao != versao:
        raise HTTPException(409, MSG_CONFLITO)
    if d.cancelada_em is not None:
        raise HTTPException(400, "Esta despesa já está cancelada.")
    d.cancelada_em = datetime.now(UTC)
    d.cancelada_por = ator.id
    d.motivo_cancelamento = motivo.strip()
    db.flush()
    auditoria.registrar(db, "financeiro.despesa_cancelada", usuario_id=ator.id, entidade="despesa",
                        entidade_id=d.id, detalhes={"valor": str(d.valor), "motivo": d.motivo_cancelamento}, ip=ip)
    return d


def despesa_saida(db: Session, d: Despesa) -> DespesaSaida:
    cli = db.get(Cliente, d.cliente_id) if d.cliente_id else None
    proc = db.get(Processo, d.processo_id) if d.processo_id else None
    comp = db.get(Comprovante, d.comprovante_id) if d.comprovante_id else None
    return DespesaSaida(
        id=d.id, descricao=d.descricao, categoria=d.categoria, valor=d.valor, data=d.data,
        responsavel_id=d.responsavel_id, responsavel_nome=_nome_usuario(db, d.responsavel_id),
        cliente_id=d.cliente_id, cliente_nome=cli.nome_completo if cli else None, processo_id=d.processo_id,
        processo_rotulo=rotulo_processo(proc) if proc else None, comprovante_id=d.comprovante_id,
        comprovante_nome=comp.nome_arquivo if comp else None, observacoes=d.observacoes,
        cancelada_em=d.cancelada_em, motivo_cancelamento=d.motivo_cancelamento,
        registrado_por_nome=_nome_usuario(db, d.registrado_por), criado_em=d.criado_em, versao=d.versao)


def listar_despesas(db: Session, *, inicio: date | None, fim: date | None, categoria: str | None,
                    cliente_id: uuid.UUID | None, incluir_canceladas: bool, offset: int, limite: int
                    ) -> tuple[list[DespesaSaida], int]:
    filtros = []
    if not incluir_canceladas:
        filtros.append(Despesa.cancelada_em.is_(None))
    if inicio:
        filtros.append(Despesa.data >= inicio)
    if fim:
        filtros.append(Despesa.data <= fim)
    if categoria:
        filtros.append(Despesa.categoria == categoria)
    if cliente_id:
        filtros.append(Despesa.cliente_id == cliente_id)
    total = db.scalar(select(func.count()).select_from(Despesa).where(*filtros)) or 0
    ds = db.scalars(select(Despesa).where(*filtros).order_by(Despesa.data.desc(), Despesa.criado_em.desc())
                    .offset(offset).limit(limite)).all()
    return [despesa_saida(db, d) for d in ds], total


# ================================================================================ resumo
def resumo(db: Session, inicio: date, fim: date) -> ResumoFinanceiro:
    def soma(q) -> Decimal:
        return Decimal(db.scalar(q) or 0).quantize(CENTAVO)

    vigentes = Contrato.situacao.in_(("ativo", "quitado"))
    total_contratado = soma(select(func.sum(Contrato.valor_total)).where(vigentes))
    total_recebido = soma(select(func.sum(Pagamento.valor)).where(Pagamento.estornado_em.is_(None)))
    recebido_periodo = soma(select(func.sum(Pagamento.valor)).where(
        Pagamento.estornado_em.is_(None), Pagamento.data_recebimento.between(inicio, fim)))

    pago_sub = (select(Pagamento.parcela_id, func.sum(Pagamento.valor).label("pago"))
                .where(Pagamento.estornado_em.is_(None)).group_by(Pagamento.parcela_id).subquery())
    restante = Parcela.valor - func.coalesce(pago_sub.c.pago, 0)
    abertas = (select(Parcela.vencimento, restante.label("restante"))
               .outerjoin(pago_sub, pago_sub.c.parcela_id == Parcela.id)
               .join(Contrato, Contrato.id == Parcela.contrato_id)
               .where(Parcela.situacao == "aberta", Contrato.situacao != "cancelado")).subquery()
    total_a_receber = soma(select(func.sum(abertas.c.restante)))
    total_vencido = soma(select(func.sum(abertas.c.restante)).where(abertas.c.vencimento < hoje()))
    vencidas = db.scalar(select(func.count()).select_from(abertas).where(abertas.c.vencimento < hoje())) or 0
    a_vencer = db.scalar(select(func.count()).select_from(abertas).where(abertas.c.vencimento >= hoje())) or 0
    previsto = soma(select(func.sum(abertas.c.restante)).where(abertas.c.vencimento.between(inicio, fim)))
    desp = db.execute(select(Despesa.categoria, func.sum(Despesa.valor)).where(
        Despesa.cancelada_em.is_(None), Despesa.data.between(inicio, fim)).group_by(Despesa.categoria)).all()
    por_categoria = {CATEGORIAS_DESPESA.get(cat, cat): Decimal(v).quantize(CENTAVO) for cat, v in desp}
    despesas_periodo = sum(por_categoria.values(), ZERO)
    return ResumoFinanceiro(
        inicio=inicio, fim=fim, total_contratado=total_contratado, total_recebido=total_recebido,
        total_a_receber=total_a_receber, total_vencido=total_vencido, parcelas_vencidas=vencidas,
        parcelas_a_vencer=a_vencer, recebido_no_periodo=recebido_periodo, previsto_no_periodo=previsto,
        despesas_no_periodo=despesas_periodo, saldo_liquido_periodo=recebido_periodo - despesas_periodo,
        despesas_por_categoria=por_categoria, avisos=avisos(db))

