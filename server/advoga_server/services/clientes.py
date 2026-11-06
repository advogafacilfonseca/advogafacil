"""Clientes: cadastro, edição com controle de edição simultânea, encerramento e pesquisa."""

from __future__ import annotations

import re
import uuid
from datetime import UTC, date, datetime

from fastapi import HTTPException
from sqlalchemy import and_, case, func, or_, select
from sqlalchemy.orm import Session

from advoga_shared.esquemas import (
    Cliente as ClienteSaida,
    ClienteAtualizar,
    ClienteCriar,
    ClienteResumo,
)
from advoga_shared.validacoes import formatar_cpf, formatar_telefone, somente_digitos

from ..models import Cliente, Usuario
from . import auditoria

CAMPOS_EDITAVEIS = [
    "nome_completo", "cpf", "rg", "data_nascimento", "telefone_principal", "telefone_secundario",
    "email", "cep", "logradouro", "numero", "complemento", "bairro", "cidade", "uf", "observacoes",
    "data_inicio_atendimento", "advogado_responsavel_id",
]
MSG_CONFLITO = ("Este cliente foi alterado por outra pessoa enquanto você editava. "
                "Reabra a ficha para ver a versão atual antes de salvar.")


def _nome_usuario(db: Session, usuario_id: uuid.UUID | None) -> str | None:
    if usuario_id is None:
        return None
    u = db.get(Usuario, usuario_id)
    return u.nome_completo if u else None


def saida(db: Session, c: Cliente) -> ClienteSaida:
    dados = {campo: getattr(c, campo) for campo in ClienteSaida.model_fields if hasattr(c, campo)}
    dados["advogado_responsavel_nome"] = _nome_usuario(db, c.advogado_responsavel_id)
    return ClienteSaida(**dados)


def resumo(c: Cliente, advogado: str | None = None) -> ClienteResumo:
    return ClienteResumo(id=c.id, nome_completo=c.nome_completo, cpf=c.cpf, telefone_principal=c.telefone_principal,
                         cidade=c.cidade, uf=c.uf, situacao=c.situacao, advogado_responsavel_nome=advogado)


def obter(db: Session, cliente_id: uuid.UUID) -> Cliente:
    c = db.get(Cliente, cliente_id)
    if c is None:
        raise HTTPException(404, "Cliente não encontrado.")
    return c


def _valor_auditavel(v):
    if isinstance(v, (date, datetime)):
        return v.isoformat()
    if isinstance(v, uuid.UUID):
        return str(v)
    return v


def _validar_responsavel(db: Session, usuario_id: uuid.UUID | None) -> None:
    if usuario_id is None:
        return
    u = db.get(Usuario, usuario_id)
    if u is None or not u.ativo:
        raise HTTPException(422, "Advogado responsável inválido ou desativado.")


def _verificar_cpf(db: Session, cpf: str | None, ignorar: uuid.UUID | None = None) -> None:
    if not cpf:
        return
    q = select(Cliente).where(Cliente.cpf == cpf)
    if ignorar:
        q = q.where(Cliente.id != ignorar)
    existente = db.scalar(q)
    if existente:
        raise HTTPException(409, f"Já existe cliente cadastrado com este CPF: {existente.nome_completo}.")


def criar(db: Session, ator: Usuario, dados: ClienteCriar, ip: str | None) -> Cliente:
    _verificar_cpf(db, dados.cpf)
    _validar_responsavel(db, dados.advogado_responsavel_id)
    if not dados.confirmar_possivel_duplicidade:
        candidatos = db.scalars(
            select(Cliente).where(func.f_normalizar(Cliente.nome_completo) == func.f_normalizar(dados.nome_completo))
        ).all()
        for c in candidatos:
            mesma_pessoa_possivel = (c.data_nascimento is None or dados.data_nascimento is None
                                     or c.data_nascimento == dados.data_nascimento)
            cpfs_distintos = c.cpf and dados.cpf and c.cpf != dados.cpf
            if mesma_pessoa_possivel and not cpfs_distintos:
                nasc = c.data_nascimento.strftime("%d/%m/%Y") if c.data_nascimento else "sem data de nascimento"
                raise HTTPException(
                    428,
                    f"Já existe um cliente chamado {c.nome_completo} ({nasc}"
                    f"{', CPF ' + formatar_cpf(c.cpf) if c.cpf else ''}). "
                    "Se for outra pessoa, confirme o cadastro.",
                )
    c = Cliente(id=uuid.uuid4(), criado_por=ator.id,
                **dados.model_dump(exclude={"confirmar_possivel_duplicidade"}))
    if c.email:
        c.email = c.email.lower()
    db.add(c)
    db.flush()
    auditoria.registrar(db, "cliente.criado", usuario_id=ator.id, entidade="cliente", entidade_id=c.id,
                        detalhes={"nome": c.nome_completo}, ip=ip)
    return c


def _conferir_versao(c: Cliente, versao: int) -> None:
    if c.versao != versao:
        raise HTTPException(409, MSG_CONFLITO)


def atualizar(db: Session, ator: Usuario, c: Cliente, dados: ClienteAtualizar, ip: str | None) -> Cliente:
    _conferir_versao(c, dados.versao)
    novos = dados.model_dump(exclude_unset=True, exclude={"versao"})
    if "nome_completo" in novos and not novos["nome_completo"]:
        raise HTTPException(422, "Nome completo: campo obrigatório.")
    if "cpf" in novos:
        _verificar_cpf(db, novos["cpf"], ignorar=c.id)
    if "advogado_responsavel_id" in novos:
        _validar_responsavel(db, novos["advogado_responsavel_id"])
    if novos.get("email"):
        novos["email"] = str(novos["email"]).lower()
    mudancas = {}
    for campo, valor in novos.items():
        if campo in CAMPOS_EDITAVEIS and getattr(c, campo) != valor:
            mudancas[campo] = {"antes": _valor_auditavel(getattr(c, campo)), "depois": _valor_auditavel(valor)}
            setattr(c, campo, valor)
    if mudancas:
        db.flush()  # versão incrementada; se outra pessoa salvou no mesmo instante, falha aqui
        auditoria.registrar(db, "cliente.editado", usuario_id=ator.id, entidade="cliente", entidade_id=c.id,
                            detalhes=mudancas, ip=ip)
    return c


def encerrar(db: Session, ator: Usuario, c: Cliente, motivo: str, versao: int, ip: str | None) -> Cliente:
    _conferir_versao(c, versao)
    if c.situacao == "encerrado":
        raise HTTPException(400, "O atendimento deste cliente já está encerrado.")
    c.situacao = "encerrado"
    c.encerrado_em = datetime.now(UTC)
    c.motivo_encerramento = motivo.strip()
    db.flush()
    auditoria.registrar(db, "cliente.encerrado", usuario_id=ator.id, entidade="cliente", entidade_id=c.id,
                        detalhes={"motivo": c.motivo_encerramento}, ip=ip)
    return c


def reativar(db: Session, ator: Usuario, c: Cliente, versao: int, ip: str | None) -> Cliente:
    _conferir_versao(c, versao)
    if c.situacao == "ativo":
        raise HTTPException(400, "O atendimento deste cliente já está ativo.")
    c.situacao = "ativo"
    c.encerrado_em = None
    c.motivo_encerramento = None
    db.flush()
    auditoria.registrar(db, "cliente.reativado", usuario_id=ator.id, entidade="cliente", entidade_id=c.id, ip=ip)
    return c


# ------------------------------------------------------------------ pesquisa


def _escapar_like(t: str) -> str:
    return t.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def filtro_texto(termo: str):
    """Condição de pesquisa: todas as palavras no nome (sem acento) OU dígitos no CPF/telefones."""
    termo = (termo or "").strip()
    palavras = [p for p in re.split(r"\s+", termo) if p and not p.isdigit()]
    condicoes = []
    if palavras:
        condicoes.append(and_(*[
            func.f_normalizar(Cliente.nome_completo).like(
                func.concat("%", func.f_normalizar(_escapar_like(p)), "%"), escape="\\")
            for p in palavras
        ]))
    digitos = somente_digitos(termo)
    if len(digitos) >= 3 and not re.search(r"[A-Za-zÀ-ÿ]", termo):
        padrao = f"%{digitos}%"
        condicoes.append(or_(Cliente.cpf.like(padrao), Cliente.telefone_principal.like(padrao),
                             Cliente.telefone_secundario.like(padrao)))
    return or_(*condicoes) if condicoes else None


def buscar(db: Session, termo: str | None, situacao: str | None, pagina: int, por_pagina: int,
           offset: int | None = None) -> tuple[list[ClienteResumo], int]:
    filtros = []
    if termo:
        cond = filtro_texto(termo)
        if cond is None:
            return [], 0
        filtros.append(cond)
    if situacao in ("ativo", "encerrado"):
        filtros.append(Cliente.situacao == situacao)
    total = db.scalar(select(func.count()).select_from(Cliente).where(*filtros)) or 0
    ordem = [func.f_normalizar(Cliente.nome_completo)]
    if termo:
        prefixo = func.f_normalizar(Cliente.nome_completo).like(
            func.concat(func.f_normalizar(_escapar_like(termo.strip())), "%"), escape="\\")
        ordem.insert(0, case((prefixo, 0), else_=1))
    linhas = db.execute(
        select(Cliente, Usuario.nome_completo)
        .outerjoin(Usuario, Usuario.id == Cliente.advogado_responsavel_id)
        .where(*filtros).order_by(*ordem, Cliente.id)
        .offset((pagina - 1) * por_pagina if offset is None else offset).limit(por_pagina)
    ).all()
    return [resumo(c, adv) for c, adv in linhas], total


def descricao_curta(c: ClienteResumo) -> str:
    partes = []
    if c.cpf:
        partes.append(f"CPF {formatar_cpf(c.cpf)}")
    if c.telefone_principal:
        partes.append(formatar_telefone(c.telefone_principal))
    if c.cidade:
        partes.append(f"{c.cidade}/{c.uf}" if c.uf else c.cidade)
    if c.situacao == "encerrado":
        partes.append("Atendimento encerrado")
    return "  ·  ".join(partes) or "Sem documentos ou telefones cadastrados"
