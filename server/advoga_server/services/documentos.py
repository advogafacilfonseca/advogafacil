"""Documentos anexados aos clientes e processos.

O arquivo fica na pasta de documentos do servidor, organizado por cliente e processo
(<documentos>/<cliente>/<processo ou "geral">/<id do documento>.<extensão>), fora de pastas
temporárias. O banco guarda nome, tamanho, tipo e a impressão SHA-256 do conteúdo.
Remover é uma operação controlada: o arquivo é preservado, o documento sai das listas e
somente a Master pode consultá-lo e restaurá-lo. Tudo fica na auditoria.
"""

from __future__ import annotations

import hashlib
import os
import re
import unicodedata
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from pathlib import Path

from fastapi import HTTPException
from sqlalchemy import and_, func, select
from sqlalchemy.orm import Session, aliased

from advoga_shared.esquemas import Documento as DocumentoSaida, DocumentoAtualizar

from ..models import Cliente, Documento, Processo, Usuario
from . import auditoria
from .clientes import _escapar_like
from .processos import rotulo as rotulo_processo

TAMANHO_MAXIMO = 200 * 1024 * 1024  # 200 MB por arquivo
# Formatos que executam programas no Windows não são aceitos (proteção contra vírus).
EXTENSOES_BLOQUEADAS = {
    ".exe", ".msi", ".bat", ".cmd", ".com", ".scr", ".pif", ".ps1", ".psm1", ".vbs", ".vbe", ".js", ".jse",
    ".wsf", ".wsh", ".hta", ".cpl", ".dll", ".jar", ".lnk", ".reg", ".msc", ".sys", ".inf", ".application",
    ".gadget", ".msp", ".scf", ".url",
}
MSG_CONFLITO = ("Este documento foi alterado por outra pessoa enquanto você editava. "
                "Atualize a lista antes de salvar.")


def nome_seguro(nome: str | None) -> str:
    """Nome para exibição: sem pastas, sem caracteres de controle, até 255 caracteres."""
    nome = unicodedata.normalize("NFC", (nome or "").replace("\\", "/").split("/")[-1])
    nome = re.sub(r"[\x00-\x1f\x7f<>:\"|?*]", "", nome).strip(" .")
    return nome[:255]


def extensao(nome: str) -> str:
    ext = Path(nome).suffix.lower()
    return ext if re.fullmatch(r"\.[a-z0-9]{1,10}", ext or "") else ""


def validar_nome(nome: str) -> str:
    nome = nome_seguro(nome)
    if not nome:
        raise HTTPException(422, "Nome do arquivo inválido.")
    if extensao(nome) in EXTENSOES_BLOQUEADAS or Path(nome).suffix.lower() in EXTENSOES_BLOQUEADAS:
        raise HTTPException(422, "Este tipo de arquivo não é aceito por segurança (programas e scripts).")
    return nome


def _pasta_relativa(cliente_id: uuid.UUID, processo_id: uuid.UUID | None) -> Path:
    return Path(str(cliente_id)) / (str(processo_id) if processo_id else "geral")


def caminho_absoluto(raiz: Path, d: Documento) -> Path:
    caminho = (raiz / d.caminho).resolve()
    if raiz.resolve() not in caminho.parents:
        raise HTTPException(500, "Caminho de documento inválido.")
    return caminho


def validar_vinculo(db: Session, cliente_id: uuid.UUID, processo_id: uuid.UUID | None) -> None:
    if db.get(Cliente, cliente_id) is None:
        raise HTTPException(422, "Cliente não encontrado.")
    if processo_id is not None:
        p = db.get(Processo, processo_id)
        if p is None or p.cliente_id != cliente_id:
            raise HTTPException(422, "O processo escolhido não pertence a este cliente.")


async def receber_arquivo(raiz: Path, fluxo: AsyncIterator[bytes]) -> tuple[Path, int, str]:
    """Grava o conteúdo recebido em arquivo provisório dentro da pasta de documentos."""
    pasta = raiz / ".recebendo"
    pasta.mkdir(parents=True, exist_ok=True)
    temporario = pasta / f"{uuid.uuid4().hex}.parte"
    h = hashlib.sha256()
    tamanho = 0
    try:
        with open(temporario, "wb") as f:
            async for bloco in fluxo:
                tamanho += len(bloco)
                if tamanho > TAMANHO_MAXIMO:
                    raise HTTPException(413, "Arquivo grande demais (máximo de 200 MB por arquivo).")
                h.update(bloco)
                f.write(bloco)
            f.flush()
            os.fsync(f.fileno())
    except BaseException:
        temporario.unlink(missing_ok=True)
        raise
    if tamanho == 0:
        temporario.unlink(missing_ok=True)
        raise HTTPException(422, "O arquivo está vazio.")
    return temporario, tamanho, h.hexdigest()


def instalar_arquivo(raiz: Path, temporario: Path, doc_id: uuid.UUID, nome: str, cliente_id: uuid.UUID,
                     processo_id: uuid.UUID | None) -> str:
    relativo = _pasta_relativa(cliente_id, processo_id) / f"{doc_id}{extensao(nome)}"
    destino = raiz / relativo
    destino.parent.mkdir(parents=True, exist_ok=True)
    os.replace(temporario, destino)
    return relativo.as_posix()


def criar(db: Session, ator: Usuario, *, doc_id: uuid.UUID, cliente_id: uuid.UUID, processo_id: uuid.UUID | None,
          nome: str, descricao: str | None, tipo: str | None, tamanho: int, sha256: str, caminho: str,
          ip: str | None) -> Documento:
    d = Documento(id=doc_id, cliente_id=cliente_id, processo_id=processo_id, nome_arquivo=nome,
                  descricao=descricao, tipo_conteudo=(tipo or None) and tipo[:150], tamanho=tamanho,
                  sha256=sha256, caminho=caminho, enviado_por=ator.id)
    db.add(d)
    db.flush()
    auditoria.registrar(db, "documento.anexado", usuario_id=ator.id, entidade="documento", entidade_id=d.id,
                        detalhes={"nome": nome, "cliente_id": str(cliente_id),
                                  "processo_id": str(processo_id) if processo_id else None,
                                  "tamanho": tamanho, "sha256": sha256}, ip=ip)
    return d


def obter(db: Session, doc_id: uuid.UUID, incluir_removido: bool = False) -> Documento:
    d = db.get(Documento, doc_id)
    if d is None or (d.removido_em is not None and not incluir_removido):
        raise HTTPException(404, "Documento não encontrado.")
    return d


def _conferir_versao(d: Documento, versao: int) -> None:
    if d.versao != versao:
        raise HTTPException(409, MSG_CONFLITO)


def atualizar(db: Session, raiz: Path, ator: Usuario, d: Documento, dados: DocumentoAtualizar,
              ip: str | None) -> tuple[Documento, tuple[Path, Path] | None]:
    """Altera nome, descrição ou processo vinculado. Devolve a movimentação de arquivo feita
    (para desfazer caso a gravação no banco falhe)."""
    _conferir_versao(d, dados.versao)
    novos = dados.model_dump(exclude_unset=True, exclude={"versao"})
    mudancas = {}
    if "nome_arquivo" in novos:
        novos["nome_arquivo"] = validar_nome(novos["nome_arquivo"] or "")
        if extensao(novos["nome_arquivo"]) != extensao(d.nome_arquivo):
            raise HTTPException(422, "Não é possível mudar a extensão do arquivo (ex.: .pdf).")
    if "descricao" in novos:
        novos["descricao"] = (novos["descricao"] or "").strip() or None
    movido = None
    if "processo_id" in novos and novos["processo_id"] != d.processo_id:
        validar_vinculo(db, d.cliente_id, novos["processo_id"])
        origem = caminho_absoluto(raiz, d)
        relativo = _pasta_relativa(d.cliente_id, novos["processo_id"]) / origem.name
        destino = raiz / relativo
        destino.parent.mkdir(parents=True, exist_ok=True)
        os.replace(origem, destino)
        movido = (destino, origem)
        mudancas["processo_id"] = {"antes": str(d.processo_id) if d.processo_id else None,
                                   "depois": str(novos["processo_id"]) if novos["processo_id"] else None}
        d.processo_id = novos["processo_id"]
        d.caminho = relativo.as_posix()
    for campo in ("nome_arquivo", "descricao"):
        if campo in novos and getattr(d, campo) != novos[campo]:
            mudancas[campo] = {"antes": getattr(d, campo), "depois": novos[campo]}
            setattr(d, campo, novos[campo])
    if mudancas:
        db.flush()
        auditoria.registrar(db, "documento.alterado", usuario_id=ator.id, entidade="documento", entidade_id=d.id,
                            detalhes=mudancas, ip=ip)
    return d, movido


def remover(db: Session, ator: Usuario, d: Documento, motivo: str, versao: int, ip: str | None) -> Documento:
    _conferir_versao(d, versao)
    d.removido_em = datetime.now(UTC)
    d.removido_por = ator.id
    d.motivo_remocao = motivo.strip()
    db.flush()
    auditoria.registrar(db, "documento.removido", usuario_id=ator.id, entidade="documento", entidade_id=d.id,
                        detalhes={"nome": d.nome_arquivo, "motivo": d.motivo_remocao}, ip=ip)
    return d


def restaurar(db: Session, ator: Usuario, d: Documento, versao: int, ip: str | None) -> Documento:
    _conferir_versao(d, versao)
    if d.removido_em is None:
        raise HTTPException(400, "Este documento não está removido.")
    d.removido_em = None
    d.removido_por = None
    d.motivo_remocao = None
    db.flush()
    auditoria.registrar(db, "documento.restaurado", usuario_id=ator.id, entidade="documento", entidade_id=d.id,
                        detalhes={"nome": d.nome_arquivo}, ip=ip)
    return d


def saida(db: Session, d: Documento) -> DocumentoSaida:
    cliente = db.get(Cliente, d.cliente_id)
    processo = db.get(Processo, d.processo_id) if d.processo_id else None
    enviado = db.get(Usuario, d.enviado_por) if d.enviado_por else None
    removido = db.get(Usuario, d.removido_por) if d.removido_por else None
    return DocumentoSaida(
        id=d.id, cliente_id=d.cliente_id, cliente_nome=cliente.nome_completo if cliente else None,
        processo_id=d.processo_id, processo_rotulo=rotulo_processo(processo) if processo else None,
        nome_arquivo=d.nome_arquivo, descricao=d.descricao, tipo_conteudo=d.tipo_conteudo, tamanho=d.tamanho,
        sha256=d.sha256, enviado_por_nome=enviado.nome_completo if enviado else None, criado_em=d.criado_em,
        removido_em=d.removido_em, removido_por_nome=removido.nome_completo if removido else None,
        motivo_remocao=d.motivo_remocao, versao=d.versao)


def _texto_documento():
    return func.f_normalizar(Documento.nome_arquivo + " " + func.coalesce(Documento.descricao, ""))


def filtro_texto(termo: str):
    palavras = [p for p in re.split(r"\s+", (termo or "").strip()) if p]
    if not palavras:
        return None
    return and_(*[_texto_documento().like(func.concat("%", func.f_normalizar(_escapar_like(p)), "%"), escape="\\")
                  for p in palavras])


def buscar(db: Session, *, termo: str | None = None, cliente_id: uuid.UUID | None = None,
           processo_id: uuid.UUID | None = None, somente_geral: bool = False, removidos: bool = False,
           offset: int = 0, limite: int = 50) -> tuple[list[DocumentoSaida], int]:
    filtros = [Documento.removido_em.is_not(None) if removidos else Documento.removido_em.is_(None)]
    if termo:
        cond = filtro_texto(termo)
        if cond is None:
            return [], 0
        filtros.append(cond)
    if cliente_id:
        filtros.append(Documento.cliente_id == cliente_id)
    if processo_id:
        filtros.append(Documento.processo_id == processo_id)
    elif somente_geral:
        filtros.append(Documento.processo_id.is_(None))
    total = db.scalar(select(func.count()).select_from(Documento).where(*filtros)) or 0
    env, rem = aliased(Usuario), aliased(Usuario)
    linhas = db.execute(
        select(Documento, Cliente.nome_completo, Processo, env.nome_completo, rem.nome_completo)
        .join(Cliente, Cliente.id == Documento.cliente_id)
        .outerjoin(Processo, Processo.id == Documento.processo_id)
        .outerjoin(env, env.id == Documento.enviado_por)
        .outerjoin(rem, rem.id == Documento.removido_por)
        .where(*filtros).order_by(Documento.criado_em.desc(), Documento.id).offset(offset).limit(limite)
    ).all()
    itens = [DocumentoSaida(
        id=d.id, cliente_id=d.cliente_id, cliente_nome=cli, processo_id=d.processo_id,
        processo_rotulo=rotulo_processo(p) if p else None, nome_arquivo=d.nome_arquivo, descricao=d.descricao,
        tipo_conteudo=d.tipo_conteudo, tamanho=d.tamanho, sha256=d.sha256, enviado_por_nome=nome_env,
        criado_em=d.criado_em, removido_em=d.removido_em, removido_por_nome=nome_rem,
        motivo_remocao=d.motivo_remocao, versao=d.versao)
        for d, cli, p, nome_env, nome_rem in linhas]
    return itens, total


def descricao_curta(d: DocumentoSaida) -> str:
    partes = [f"Cliente: {d.cliente_nome}"]
    if d.processo_rotulo:
        partes.append(f"Processo {d.processo_rotulo}")
    if d.descricao:
        partes.append(d.descricao)
    return "  ·  ".join(partes)
