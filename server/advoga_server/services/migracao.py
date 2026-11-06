"""Assistente de migração do servidor: leva TODO o sistema para um computador servidor novo.

Fluxo:

1. No servidor ANTIGO, a Master exporta. O servidor entra em "migração" (somente leitura: ninguém
   grava mais nada nele) e gera um pacote criptografado (.afmig) com o banco inteiro e todos os
   documentos e comprovantes, conferidos um a um. O banco é exportado com as tabelas travadas
   para gravação, então nenhuma alteração fica para trás.
2. No servidor NOVO (recém-instalado, sem a conta Master), a importação abre o pacote com a
   senha, confere tudo, importa o banco, confere cada tabela (quantidade de registros e impressão
   digital do conteúdo), copia e confere os documentos e ativa o servidor novo com uma identidade
   nova. Ela mostra um relatório e um CÓDIGO DE CONFIRMAÇÃO.
3. No servidor antigo, a Master informa o código de confirmação. O servidor antigo é DESATIVADO
   de forma definitiva: não aceita mais login nem gravação. Assim nunca há duas bases oficiais.

Segredos não são transferidos: a autorização do Google (conta de envio) e a senha da cópia
criptografada dos backups são removidas no servidor novo, e a Master as configura de novo lá.
Todas as sessões abertas são encerradas; os usuários entram com as mesmas senhas.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
import secrets
import shutil
import tarfile
import tempfile
import threading
import uuid
from datetime import UTC, datetime
from pathlib import Path

from fastapi import HTTPException
from sqlalchemy import create_engine, select, text, update
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import NullPool

from advoga_shared import __version__
from advoga_shared.esquemas import (
    CATEGORIA_BACKUP,
    AndamentoImportacao,
    EstadoMigracao,
    ExportarMigracao,
    Migracao as MigracaoSaida,
    Relatorio,
    ColunaRelatorio,
    TabelaConferida,
    TotalRelatorio,
)

from ..core.config import Configuracoes
from ..core.seguranca import comparar_seguro, hash_token, verificar_senha
from ..models import Configuracao, IdentidadeServidor, Migracao, Notificacao, Sessao, Usuario
from . import auditoria, backup
from .arquivo_cifrado import ArquivoInvalido, Cifrador, derivar_chave
from .servidor import CHAVE_CODIGO, definir_status_cache, obter_identidade, sistema_configurado

log = logging.getLogger("advoga.migracao")

EXTENSAO = ".afmig"
PASTA_PACOTE = "migracao"
ALFABETO = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"

NOMES_TABELAS = {
    "usuarios": "Usuários",
    "permissoes_usuario": "Permissões dos usuários",
    "clientes": "Clientes",
    "processos": "Processos",
    "movimentacoes_processo": "Movimentações dos processos",
    "documentos": "Documentos (registros)",
    "contratos": "Contratos",
    "parcelas": "Parcelas",
    "pagamentos": "Pagamentos",
    "comprovantes": "Comprovantes (registros)",
    "despesas": "Despesas",
    "compromissos": "Agenda, prazos e pendências",
    "notificacoes": "Avisos e histórico de envios",
    "destinatarios_notificacao": "Destinatários dos avisos",
    "configuracoes": "Configurações",
    "auditoria": "Histórico de atividades (auditoria)",
    "sessoes": "Sessões de acesso",
    "chaves_idempotencia": "Controle de gravação segura",
    "backups_execucoes": "Histórico de backups",
    "migracoes": "Histórico de migrações",
    "identidade_servidor": "Identidade do servidor",
}
ORDEM = list(NOMES_TABELAS)

CHAVE_EMAIL = "email.servico"


class FalhaMigracao(Exception):
    pass


def agora() -> datetime:
    return datetime.now(UTC)


def codigo_confirmacao(segredo: str) -> str:
    d = hmac.new(bytes.fromhex(segredo), b"advoga-facil:migracao-concluida", hashlib.sha256).digest()
    bruto = "".join(ALFABETO[b % len(ALFABETO)] for b in d[:12])
    return f"{bruto[:4]}-{bruto[4:8]}-{bruto[8:]}"


def normalizar_codigo(codigo: str) -> str:
    bruto = "".join(ch for ch in (codigo or "").upper() if ch.isalnum())
    return f"{bruto[:4]}-{bruto[4:8]}-{bruto[8:]}" if len(bruto) == 12 else bruto


def _nome_tabela(t: str) -> str:
    return NOMES_TABELAS.get(t, t)


def _ordenar(tabelas) -> list[str]:
    return sorted(tabelas, key=lambda t: (ORDEM.index(t) if t in ORDEM else len(ORDEM), t))


# ============================================================================== consultas
def saida(db: Session, m: Migracao) -> MigracaoSaida:
    autor = db.get(Usuario, m.iniciado_por) if m.iniciado_por else None
    r = m.relatorio or {}
    return MigracaoSaida(
        id=m.id, tipo=m.tipo, situacao=m.situacao, iniciado_em=m.iniciado_em, concluido_em=m.concluido_em,
        iniciado_por_nome=autor.nome_completo if autor else None, servidor_origem=m.servidor_origem,
        servidor_destino=m.servidor_destino, arquivo=m.arquivo, etapa=m.etapa, mensagem=m.mensagem,
        tabelas=[TabelaConferida(**t) for t in r.get("tabelas", [])], arquivos_total=r.get("arquivos_total", 0),
        arquivos_conferidos=r.get("arquivos_conferidos", 0), pendencias=r.get("pendencias", []),
        tem_relatorio=bool(r.get("tabelas")),
    )


def exportacao_aberta(db: Session) -> Migracao | None:
    return db.scalar(select(Migracao).where(Migracao.tipo == "exportacao",
                                            Migracao.situacao.in_(("em_andamento", "exportada")))
                     .order_by(Migracao.iniciado_em.desc()).limit(1))


def estado(db: Session) -> EstadoMigracao:
    ident = obter_identidade(db)
    aberta = exportacao_aberta(db)
    linhas = db.scalars(select(Migracao).order_by(Migracao.iniciado_em.desc()).limit(50)).all()
    return EstadoMigracao(servidor_id=ident.servidor_id, servidor_status=ident.status, migrado_de=ident.migrado_de,
                          migrado_em=ident.migrado_em, atual=saida(db, aberta) if aberta else None,
                          historico=[saida(db, m) for m in linhas])


def _conferir_master(db: Session, ator: Usuario, senha: str, ip: str | None) -> None:
    if not verificar_senha(ator.senha_hash, senha):
        auditoria.registrar(db, "migracao.senha_incorreta", usuario_id=ator.id, ip=ip)
        db.commit()
        raise HTTPException(403, "Senha da Master incorreta.")


def _backup_em_andamento(db: Session) -> bool:
    if backup._trava_local.locked():
        return True
    return bool(db.scalar(text(
        f"SELECT count(*) FROM pg_locks WHERE locktype = 'advisory' AND objid = {backup.TRAVA} "
        "AND database = (SELECT oid FROM pg_database WHERE datname = current_database())")))


# ============================================================================ exportação
def iniciar_exportacao(db: Session, cfg: Configuracoes, ator: Usuario, dados: ExportarMigracao,
                       ip: str | None) -> Migracao:
    """Validações e passagem para o modo de migração (somente leitura). O trabalho pesado roda
    depois, em `executar_exportacao`."""
    ident = obter_identidade(db)
    if ident.status == "em_migracao" or exportacao_aberta(db) is not None:
        raise HTTPException(409, "Já existe uma migração em andamento neste servidor.")
    if ident.status != "ativo":
        raise HTTPException(409, "Este servidor foi desativado e não pode ser exportado de novo.")
    _conferir_master(db, ator, dados.senha_master, ip)
    destino = backup._validar_caminho(dados.destino, "Pasta do pacote")
    s = backup.situacao_destino(destino)
    if not s.disponivel:
        raise HTTPException(422, s.mensagem)
    if _backup_em_andamento(db):
        raise HTTPException(409, "Há um backup em andamento. Aguarde terminar e tente de novo.")
    m = Migracao(id=uuid.uuid4(), tipo="exportacao", situacao="em_andamento", iniciado_por=ator.id,
                 servidor_origem=ident.servidor_id, arquivo=destino, etapa="Preparando a exportação")
    db.add(m)
    ident.status = "em_migracao"
    db.flush()
    auditoria.registrar(db, "migracao.exportacao_iniciada", usuario_id=ator.id, entidade="migracao",
                        entidade_id=m.id, detalhes={"destino": destino}, ip=ip)
    db.commit()
    definir_status_cache("em_migracao")
    return m


def _etapa(db: Session, m: Migracao, texto: str) -> None:
    m.etapa = texto[:200]
    db.commit()
    log.info("Migração: %s", texto)


def executar_exportacao(db: Session, cfg: Configuracoes, migracao_id: uuid.UUID, senha: str) -> Migracao:
    m = db.get(Migracao, migracao_id)
    assert m is not None and m.situacao == "em_andamento"
    url = cfg.url_banco()
    trava = None
    temp = Path(tempfile.mkdtemp(prefix="advoga-migracao-", dir=cfg.pasta_dados))
    parcial: Path | None = None
    try:
        trava = backup._com_trava(url)
        if trava is None:
            raise FalhaMigracao("Há um backup em andamento. Aguarde terminar e tente de novo.")
        _etapa(db, m, "Exportando o banco de dados (as gravações estão bloqueadas)")
        dump = temp / "banco.dump"
        # Nada pode gravar nesta sessão enquanto as tabelas estiverem travadas pela exportação.
        inst = backup._exportar_banco(cfg, url, dump, migracao=True)
        args, env = backup._conexao_pg(url)
        backup._rodar([cfg.programa_postgres("pg_restore"), "--list", str(dump)], env,
                      "A cópia do banco não pôde ser lida (verificação)")
        sha_banco = backup._sha256_arquivo(dump)

        _etapa(db, m, f"Conferindo {len(inst.arquivos)} documento(s) e comprovante(s) no servidor")
        problemas = []
        for a in inst.arquivos:
            rel = Path(a["caminho"])
            origem = cfg.pasta_documentos / rel
            if rel.is_absolute() or ".." in rel.parts:
                problemas.append(f"caminho inválido: {a['caminho']}")
            elif not origem.exists():
                problemas.append(f"arquivo ausente: {a['caminho']}")
            elif backup._sha256_arquivo(origem) != a["sha256"]:
                problemas.append(f"arquivo alterado ou corrompido: {a['caminho']}")
        if problemas:
            raise FalhaMigracao(
                f"{len(problemas)} arquivo(s) com problema no servidor ({'; '.join(problemas[:5])}). "
                "Nada foi exportado. Recupere os arquivos pelo backup (guia de recuperação) e tente de novo.")

        pasta = Path(m.arquivo or "")
        pasta.mkdir(parents=True, exist_ok=True)
        estimado = sum(a["tamanho"] for a in inst.arquivos) + dump.stat().st_size
        if shutil.disk_usage(pasta).free < estimado + backup.ESPACO_MINIMO:
            raise FalhaMigracao(f"Sem espaço na pasta do pacote: são necessários cerca de "
                                f"{backup._tamanho_legivel(estimado + backup.ESPACO_MINIMO)}.")
        segredo = secrets.token_hex(32)
        tabelas = _ordenar(inst.contagens)
        manifesto = {
            "formato": 1, "tipo": "migracao", "versao": PASTA_PACOTE, "migracao_id": str(m.id),
            "criado_em": agora().isoformat(), "sistema": __version__, "revisao_banco": inst.revisao,
            "servidor_id": inst.servidor_id, "segredo": segredo,
            "banco": {"arquivo": "banco.dump", "sha256": sha_banco, "tamanho": dump.stat().st_size,
                      "contagens": inst.contagens, "somas": inst.somas},
            "documentos": [{"caminho": a["caminho"], "sha256": a["sha256"], "tamanho": a["tamanho"]}
                           for a in inst.arquivos],
        }
        (temp / "manifesto.json").write_text(json.dumps(manifesto, ensure_ascii=False, indent=1), encoding="utf-8")

        _etapa(db, m, "Gravando o pacote criptografado")
        nome = f"AdvogaFacil_Migracao_{agora():%Y-%m-%d_%H%M%S}{EXTENSAO}"
        final = pasta / nome
        parcial = pasta / (nome + ".parcial")
        sal = os.urandom(16)
        chave = derivar_chave(senha, sal)
        with open(parcial, "wb") as f:
            cif = Cifrador(f, chave, sal, {"tipo": "migracao", "sistema": __version__, "migracao_id": str(m.id)})
            with tarfile.open(fileobj=cif, mode="w|") as tar:
                tar.add(dump, arcname=f"{PASTA_PACOTE}/banco.dump")
                tar.add(temp / "manifesto.json", arcname=f"{PASTA_PACOTE}/manifesto.json")
                for a in manifesto["documentos"]:
                    tar.add(cfg.pasta_documentos / a["caminho"], arcname=f"{PASTA_PACOTE}/documentos/{a['caminho']}")
            cif.finalizar()
            f.flush()
            os.fsync(f.fileno())

        _etapa(db, m, "Conferindo o pacote gravado (abre e confere cada arquivo)")
        backup.verificar_copia_cifrada(parcial, chave=chave)
        os.replace(parcial, final)
        parcial = None

        m.situacao = "exportada"
        m.arquivo = str(final)
        m.etapa = "Aguardando a importação no servidor novo"
        m.codigo_hash = hash_token(codigo_confirmacao(segredo))
        m.relatorio = {
            "tabelas": [{"tabela": t, "nome": _nome_tabela(t), "origem": inst.contagens[t]} for t in tabelas],
            "arquivos_total": len(manifesto["documentos"]), "arquivos_conferidos": len(manifesto["documentos"]),
            "tamanho_pacote": final.stat().st_size,
            "pendencias": [
                "Copie o pacote para o computador servidor novo (HD externo ou pen drive).",
                "Instale o Advoga Fácil Servidor no computador novo e escolha \"Importar dados de outro servidor\".",
                "Informe aqui o código de confirmação mostrado no servidor novo para concluir a migração.",
            ],
        }
        total = sum(inst.contagens.values())
        m.mensagem = (f"Pacote gravado e conferido: {final.name} ({backup._tamanho_legivel(final.stat().st_size)}), "
                      f"{total} registros em {len(tabelas)} tabelas e {len(manifesto['documentos'])} arquivo(s). "
                      "Este servidor está em modo somente leitura até a conclusão ou o cancelamento.")
        auditoria.registrar(db, "migracao.exportada", usuario_id=m.iniciado_por, entidade="migracao",
                            entidade_id=m.id, detalhes={"arquivo": str(final), "registros": total,
                                                        "arquivos": len(manifesto["documentos"])})
        db.commit()
        return m
    except Exception as exc:  # noqa: BLE001
        db.rollback()
        if not isinstance(exc, (FalhaMigracao, backup.FalhaBackup)):
            log.exception("Erro inesperado na exportação da migração")
            texto = f"Erro inesperado: {exc.__class__.__name__}: {exc}"
        else:
            texto = str(exc)
        m = db.get(Migracao, migracao_id)
        m.situacao, m.etapa, m.concluido_em = "falhou", None, agora()
        m.mensagem = f"A exportação não foi concluída: {texto} O servidor voltou ao funcionamento normal."
        ident = obter_identidade(db)
        ident.status = "ativo"
        auditoria.registrar(db, "migracao.exportacao_falhou", usuario_id=m.iniciado_por, entidade="migracao",
                            entidade_id=m.id, detalhes={"erro": texto[:500]})
        db.commit()
        definir_status_cache("ativo")
        return m
    finally:
        if parcial is not None:
            parcial.unlink(missing_ok=True)
        if trava is not None:
            backup._soltar(trava)
        shutil.rmtree(temp, ignore_errors=True)


def concluir(db: Session, ator: Usuario, codigo: str, senha_master: str, ip: str | None) -> Migracao:
    """Desativa este servidor de forma definitiva, depois que o servidor novo confirmou a importação."""
    m = exportacao_aberta(db)
    if m is None or m.situacao != "exportada":
        raise HTTPException(409, "Não há uma exportação aguardando conclusão neste servidor.")
    _conferir_master(db, ator, senha_master, ip)
    if not m.codigo_hash or not comparar_seguro(m.codigo_hash, hash_token(normalizar_codigo(codigo))):
        auditoria.registrar(db, "migracao.codigo_invalido", usuario_id=ator.id, entidade="migracao",
                            entidade_id=m.id, ip=ip)
        db.commit()
        raise HTTPException(403, "Código de confirmação inválido. Use o código mostrado no relatório da importação "
                                 "do servidor novo.")
    momento = agora()
    ident = obter_identidade(db)
    ident.status = "desativado"
    ident.desativado_em = momento
    ident.observacao = f"Substituído por outro servidor (migração concluída em {momento:%d/%m/%Y %H:%M} UTC)."
    m.situacao, m.etapa, m.concluido_em = "concluida", None, momento
    m.mensagem = ("Migração concluída. Este servidor foi desativado: não aceita mais login nem gravação. "
                  "O servidor oficial agora é o computador novo.")
    db.execute(update(Sessao).where(Sessao.encerrada_em.is_(None))
               .values(encerrada_em=momento, motivo_encerramento="servidor_desativado"))
    auditoria.registrar(db, "migracao.concluida", usuario_id=ator.id, entidade="migracao", entidade_id=m.id, ip=ip)
    db.commit()
    definir_status_cache("desativado")
    return m


def cancelar(db: Session, ator: Usuario, senha_master: str, ip: str | None) -> Migracao:
    m = exportacao_aberta(db)
    if m is None:
        raise HTTPException(409, "Não há migração em andamento neste servidor.")
    if m.situacao == "em_andamento":
        raise HTTPException(409, "A exportação ainda está em andamento. Aguarde terminar.")
    _conferir_master(db, ator, senha_master, ip)
    apagado = False
    if m.arquivo and m.arquivo.endswith(EXTENSAO):
        try:
            Path(m.arquivo).unlink(missing_ok=True)
            apagado = True
        except OSError:
            log.warning("Não foi possível apagar o pacote %s", m.arquivo)
    ident = obter_identidade(db)
    ident.status = "ativo"
    m.situacao, m.etapa, m.concluido_em = "cancelada", None, agora()
    m.mensagem = ("Migração cancelada. Este servidor voltou a ser o servidor oficial. "
                  + ("O pacote gerado foi apagado. " if apagado else "")
                  + "Não importe cópias desse pacote em outro computador.")
    auditoria.registrar(db, "migracao.cancelada", usuario_id=ator.id, entidade="migracao", entidade_id=m.id, ip=ip)
    db.commit()
    definir_status_cache("ativo")
    return m


# ============================================================================ importação
def _revisoes_conhecidas() -> set[str]:
    from alembic.script import ScriptDirectory

    from ..core.migracoes import config_alembic

    return {r.revision for r in ScriptDirectory.from_config(config_alembic("")).walk_revisions()}


def _limpar_banco(url: str) -> None:
    eng = create_engine(url, poolclass=NullPool, isolation_level="AUTOCOMMIT")
    try:
        with eng.connect() as c:
            c.execute(text("DROP SCHEMA public CASCADE"))
            c.execute(text("CREATE SCHEMA public"))
    finally:
        eng.dispose()


def _hash_codigo_atual(url: str) -> str | None:
    eng = create_engine(url, poolclass=NullPool)
    try:
        with eng.connect() as c:
            existe = c.execute(text("SELECT to_regclass('public.configuracoes')")).scalar()
            if not existe:
                return None
            v = c.execute(text("SELECT valor FROM configuracoes WHERE chave = :k"), {"k": CHAVE_CODIGO}).scalar()
            return str(v) if v is not None else None
    finally:
        eng.dispose()


def _conferir_tabelas(url: str, manifesto: dict) -> list[dict]:
    esperado_n = manifesto["banco"]["contagens"]
    esperado_s = manifesto["banco"].get("somas") or {}
    eng = create_engine(url, poolclass=NullPool)
    try:
        with eng.connect() as c:
            presentes = backup.tabelas_do_banco(c)
            contagens = {t: c.execute(text(f'SELECT count(*) FROM "{t}"')).scalar_one() for t in presentes}
            somas = backup.somas_tabelas(c, presentes)
            c.rollback()
    finally:
        eng.dispose()
    linhas = []
    for t in _ordenar(set(esperado_n) | set(presentes)):
        ok = (t in esperado_n and t in contagens and esperado_n[t] == contagens[t]
              and esperado_s.get(t) == somas.get(t))
        linhas.append({"tabela": t, "nome": _nome_tabela(t), "origem": esperado_n.get(t, 0),
                       "destino": contagens.get(t), "conferida": ok})
    return linhas


def importar(cfg: Configuracoes, pacote: Path, senha: str, aviso=print, url: str | None = None,
             hash_codigo: str | None = None) -> dict:
    """Importa um pacote de migração num servidor recém-instalado. Confere tudo antes e depois.
    Em caso de falha, o banco novo volta a ficar vazio (pronto para tentar de novo)."""
    from ..core.migracoes import atualizar_banco

    url = url or cfg.url_banco()
    pacote = Path(pacote)
    if not pacote.is_file():
        raise FalhaMigracao(f"Pacote não encontrado no computador servidor: {pacote}")
    hash_codigo = hash_codigo or _hash_codigo_atual(url)
    temp = Path(tempfile.mkdtemp(prefix="advoga-importacao-", dir=cfg.pasta_dados))
    banco_alterado = False
    try:
        aviso("Abrindo o pacote e conferindo cada arquivo")
        try:
            manifesto = backup.verificar_copia_cifrada(pacote, senha=senha, extrair_em=temp)
        except ArquivoInvalido as exc:
            raise FalhaMigracao(str(exc).replace("cópia criptografada", "pacote de migração")) from exc
        except (tarfile.TarError, backup.FalhaBackup) as exc:
            raise FalhaMigracao(f"Pacote danificado: {str(exc).replace('cópia criptografada', 'pacote')}") from exc
        if manifesto.get("tipo") != "migracao":
            raise FalhaMigracao("Este arquivo não é um pacote de migração. Para restaurar um backup, siga o guia "
                                "de recuperação de dados.")
        if manifesto.get("revisao_banco") not in _revisoes_conhecidas():
            raise FalhaMigracao(f"O pacote foi criado por uma versão mais nova do Advoga Fácil "
                                f"({manifesto.get('sistema')}). Atualize o servidor novo e tente de novo.")
        pasta = temp / PASTA_PACOTE

        aviso("Preparando o banco de dados do servidor novo")
        try:
            backup._preparar_banco_destino(url, lambda _t: None)
        except backup.FalhaBackup as exc:
            raise FalhaMigracao("O servidor novo já tem dados. A importação só é feita num servidor recém-instalado, "
                                "sem a conta Master.") from exc
        banco_alterado = True
        aviso("Importando o banco de dados")
        backup._restaurar_banco(cfg, pasta / "banco.dump", url)

        aviso("Conferindo cada tabela (registros e conteúdo)")
        tabelas = _conferir_tabelas(url, manifesto)
        erradas = [t for t in tabelas if not t["conferida"]]
        if erradas:
            raise FalhaMigracao("A conferência do banco falhou em: " + ", ".join(
                f"{t['nome']} (origem {t['origem']}, importado {t['destino']})" for t in erradas[:5]))

        documentos = manifesto["documentos"]
        aviso(f"Copiando e conferindo {len(documentos)} documento(s) e comprovante(s)")
        eng = create_engine(url, poolclass=NullPool)
        try:
            with eng.connect() as c:
                no_banco = {(r[0], r[1]) for r in c.execute(text("SELECT caminho, sha256 FROM documentos"))}
                no_banco |= {("_financeiro/" + r[0], r[1]) for r in c.execute(text(
                    "SELECT caminho, sha256 FROM comprovantes"))}
        finally:
            eng.dispose()
        if no_banco != {(a["caminho"], a["sha256"]) for a in documentos}:
            raise FalhaMigracao("A lista de documentos do pacote não confere com o banco importado.")
        conferidos = 0
        for a in documentos:
            rel = Path(a["caminho"])
            if rel.is_absolute() or ".." in rel.parts:
                raise FalhaMigracao(f"Caminho inválido no pacote: {a['caminho']}")
            destino = cfg.pasta_documentos / rel
            destino.parent.mkdir(parents=True, exist_ok=True)
            if not (destino.exists() and backup._sha256_arquivo(destino) == a["sha256"]):
                shutil.copyfile(pasta / "documentos" / rel, destino)
            if backup._sha256_arquivo(destino) != a["sha256"]:
                raise FalhaMigracao(f"Documento não confere depois da cópia: {a['caminho']}")
            conferidos += 1

        aviso("Atualizando a estrutura do banco")
        atualizar_banco(url)

        aviso("Ativando este computador como o novo servidor oficial")
        resultado = _ativar(cfg, url, pacote, manifesto, tabelas, conferidos)
        if cfg.arquivo_codigo_instalacao.exists():
            cfg.arquivo_codigo_instalacao.unlink()
        _gravar_relatorio_texto(cfg, resultado)
        definir_status_cache("ativo")
        return resultado
    except Exception:
        if banco_alterado:
            # Volta ao estado de servidor recém-instalado (mesmo código de instalação), para tentar de novo.
            try:
                _limpar_banco(url)
                atualizar_banco(url)
                if hash_codigo:
                    eng = create_engine(url, poolclass=NullPool)
                    with eng.begin() as c:
                        c.execute(text("INSERT INTO configuracoes (chave, valor) VALUES (:k, to_jsonb(CAST(:v AS text)))"),
                                  {"k": CHAVE_CODIGO, "v": hash_codigo})
                    eng.dispose()
            except Exception:  # noqa: BLE001
                log.exception("Não foi possível limpar o banco depois da falha na importação")
        raise
    finally:
        shutil.rmtree(temp, ignore_errors=True)


def _ativar(cfg: Configuracoes, url: str, pacote: Path, manifesto: dict, tabelas: list[dict],
            conferidos: int) -> dict:
    eng = create_engine(url, poolclass=NullPool)
    fabrica = sessionmaker(bind=eng, expire_on_commit=False)
    db = fabrica()
    try:
        momento = agora()
        ident = db.get(IdentidadeServidor, 1)
        origem = ident.servidor_id
        ident.servidor_id = uuid.uuid4()
        ident.status = "ativo"
        ident.migrado_de = origem
        ident.migrado_em = momento
        ident.desativado_em = None
        ident.observacao = f"Recebeu os dados do servidor anterior em {momento:%d/%m/%Y %H:%M} UTC."
        exportacao = db.get(Migracao, uuid.UUID(manifesto["migracao_id"]))
        if exportacao is not None:
            exportacao.situacao = "importada"
            exportacao.etapa = None
            exportacao.servidor_destino = ident.servidor_id
            exportacao.mensagem = "Pacote exportado no servidor anterior e importado neste servidor."

        pendencias = ["Nos computadores do escritório, informe o endereço deste servidor novo (se mudou)."]
        email = db.get(Configuracao, CHAVE_EMAIL)
        if email is not None:
            db.delete(email)
            pendencias.append("Conecte de novo a conta de envio de e-mail (Notificações > Conta de envio). "
                              "Por segurança, a autorização do Google não é transferida.")
        senha_copia = db.get(Configuracao, backup.CHAVE_SENHA)
        if senha_copia is not None:
            db.delete(senha_copia)
            pendencias.append("Defina de novo a senha da cópia criptografada (Central de Backups).")
        if backup.obter_config(db).destino:
            pendencias.append("Confira na Central de Backups se o HD de backup está ligado neste computador "
                              "e faça um backup completo.")
        pendencias.append("No servidor antigo, informe o código de confirmação para desativá-lo.")
        db.execute(update(Sessao).where(Sessao.encerrada_em.is_(None))
                   .values(encerrada_em=momento, motivo_encerramento="migracao"))
        segredo = manifesto["segredo"]
        codigo = codigo_confirmacao(segredo)
        relatorio = {"tabelas": tabelas, "arquivos_total": len(manifesto["documentos"]),
                     "arquivos_conferidos": conferidos, "pendencias": pendencias,
                     "migracao_id": manifesto["migracao_id"], "sistema_origem": manifesto.get("sistema"),
                     "exportado_em": manifesto.get("criado_em")}
        total = sum(t["destino"] or 0 for t in tabelas)
        m = Migracao(id=uuid.uuid4(), tipo="importacao", situacao="importada", servidor_origem=origem,
                     servidor_destino=ident.servidor_id, arquivo=str(pacote), concluido_em=momento,
                     mensagem=(f"Importação concluída: {total} registros em {len(tabelas)} tabelas e {conferidos} "
                               "arquivo(s), tudo conferido. Usuários, permissões, clientes, processos, contratos, "
                               "parcelas, pagamentos, agenda, pendências, configurações e histórico preservados."),
                     relatorio=relatorio)
        db.add(m)
        db.flush()
        for u in db.scalars(select(Usuario).where(Usuario.is_master, Usuario.ativo)):
            db.add(Notificacao(chave=f"migracao:{m.id}:{u.id}", categoria=CATEGORIA_BACKUP, usuario_id=u.id,
                               titulo="Migração do servidor concluída",
                               mensagem="Os dados chegaram ao servidor novo e foram conferidos. Falta: "
                                        + " ".join(pendencias[1:]),
                               entidade="migracao", email_destino=None))
        auditoria.registrar(db, "migracao.importada", entidade="migracao", entidade_id=m.id,
                            detalhes={"servidor_origem": str(origem), "registros": total, "arquivos": conferidos})
        db.commit()
        return {"migracao_id": str(m.id), "codigo": codigo, "servidor_origem": str(origem),
                "servidor_id": str(ident.servidor_id), "tabelas": tabelas, "arquivos": conferidos,
                "registros": total, "pendencias": pendencias, "mensagem": m.mensagem}
    finally:
        db.close()
        eng.dispose()


def _gravar_relatorio_texto(cfg: Configuracoes, r: dict) -> Path:
    pasta = cfg.pasta_dados / "migracoes"
    pasta.mkdir(parents=True, exist_ok=True)
    arq = pasta / f"relatorio_importacao_{agora():%Y-%m-%d_%H%M%S}.txt"
    linhas = ["RELATÓRIO DA MIGRAÇÃO DO ADVOGA FÁCIL (importação no servidor novo)", "",
              f"Resultado: SUCESSO. {r['mensagem']}", "",
              f"CÓDIGO DE CONFIRMAÇÃO (informe no servidor antigo): {r['codigo']}", "",
              f"{'Dados':45} {'Origem':>10} {'Novo':>10}  Conferência"]
    for t in r["tabelas"]:
        linhas.append(f"{t['nome'][:45]:45} {t['origem']:>10} {t['destino'] if t['destino'] is not None else '-':>10}"
                      f"  {'OK' if t['conferida'] else 'DIFERENTE'}")
    linhas += ["", f"Documentos e comprovantes conferidos: {r['arquivos']}", "", "O que falta fazer:"]
    linhas += [f"- {p}" for p in r["pendencias"]]
    arq.write_text("\n".join(linhas) + "\n", encoding="utf-8")
    return arq


# ======================================================== importação pela tela (sem login)
class _Andamento:
    def __init__(self) -> None:
        self.trava = threading.Lock()
        self.situacao = "parada"
        self.etapa: str | None = None
        self.mensagem: str | None = None
        self.codigo: str | None = None
        self.migracao_id: str | None = None
        self.hash_acesso: str | None = None

    def zerar(self) -> None:
        self.__init__()


andamento = _Andamento()


def iniciar_importacao(db: Session, cfg: Configuracoes, codigo_instalacao: str, pacote: str, senha: str,
                       ip: str | None) -> None:
    if sistema_configurado(db):
        raise HTTPException(409, "Este servidor já está configurado. A importação só pode ser feita num servidor "
                                 "recém-instalado, antes de criar a conta Master.")
    registro = db.get(Configuracao, CHAVE_CODIGO)
    codigo = normalizar_codigo(codigo_instalacao)
    if registro is None or not comparar_seguro(str(registro.valor), hash_token(codigo)):
        auditoria.registrar(db, "setup.codigo_invalido", ip=ip, detalhes={"origem": "importacao"})
        db.commit()
        raise HTTPException(403, "Código de instalação inválido. Ele está no arquivo CODIGO_DE_INSTALACAO.txt do "
                                 "computador servidor.")
    caminho = Path(pacote.strip())
    if not caminho.is_absolute():
        raise HTTPException(422, "Informe o caminho completo do pacote no computador servidor "
                                 "(ex.: E:\\AdvogaFacil_Migracao_2026-11-06_120000.afmig).")
    if caminho.suffix.lower() != EXTENSAO or not caminho.is_file():
        raise HTTPException(422, f"Pacote de migração (.afmig) não encontrado no computador servidor: {caminho}")
    hash_codigo = str(registro.valor)
    with andamento.trava:
        if andamento.situacao == "em_andamento":
            raise HTTPException(409, "Já existe uma importação em andamento.")
        andamento.zerar()
        andamento.situacao = "em_andamento"
        andamento.etapa = "Iniciando"
        andamento.hash_acesso = hash_token(codigo)
    db.close()

    def etapa(texto: str) -> None:
        andamento.etapa = texto
        log.info("Importação: %s", texto)

    def rodar() -> None:
        try:
            r = importar(cfg, caminho, senha, aviso=etapa, hash_codigo=hash_codigo)
            andamento.codigo = r["codigo"]
            andamento.migracao_id = r["migracao_id"]
            andamento.mensagem = r["mensagem"]
            andamento.situacao = "sucesso"
            andamento.etapa = None
        except Exception as exc:  # noqa: BLE001
            if not isinstance(exc, FalhaMigracao | backup.FalhaBackup):
                log.exception("Erro inesperado na importação")
                andamento.mensagem = f"Erro inesperado: {exc.__class__.__name__}: {exc}"
            else:
                andamento.mensagem = str(exc)
            andamento.mensagem += " Nada foi gravado: o servidor novo continua vazio e você pode tentar de novo."
            andamento.situacao = "falhou"
            andamento.etapa = None

    threading.Thread(target=rodar, name="importacao-migracao", daemon=True).start()


def consultar_importacao(db: Session, codigo_instalacao: str | None) -> AndamentoImportacao:
    if andamento.hash_acesso is None or not codigo_instalacao or not comparar_seguro(
            andamento.hash_acesso, hash_token(normalizar_codigo(codigo_instalacao))):
        raise HTTPException(403, "Informe o código de instalação usado na importação.")
    relatorio = None
    if andamento.situacao == "sucesso" and andamento.migracao_id:
        m = db.get(Migracao, uuid.UUID(andamento.migracao_id))
        relatorio = saida(db, m) if m else None
    return AndamentoImportacao(situacao=andamento.situacao, etapa=andamento.etapa, mensagem=andamento.mensagem,
                               codigo_confirmacao=andamento.codigo, relatorio=relatorio)


# =================================================================== relatório em PDF
def relatorio_pdf(db: Session, m: Migracao, gerado_por: str) -> bytes:
    from .exportar_relatorio import pdf

    s = saida(db, m)
    importacao = m.tipo == "importacao"
    titulo = "Relatório de migração: importação" if importacao else "Relatório de migração: exportação"
    filtros = [f"Situação: {s.situacao.replace('_', ' ')}",
               f"Iniciada em {s.iniciado_em.astimezone():%d/%m/%Y %H:%M}"]
    if s.arquivo:
        filtros.append(f"Pacote: {s.arquivo}")
    if s.servidor_origem:
        filtros.append(f"Servidor de origem: {s.servidor_origem}")
    if s.servidor_destino:
        filtros.append(f"Servidor novo: {s.servidor_destino}")
    colunas = [ColunaRelatorio(titulo="Dados", largura=4), ColunaRelatorio(titulo="Registros na origem",
                                                                           tipo="numero", largura=2)]
    if importacao:
        colunas += [ColunaRelatorio(titulo="Registros no servidor novo", tipo="numero", largura=2),
                    ColunaRelatorio(titulo="Conferência", largura=2)]
    linhas = []
    for t in s.tabelas:
        linha: list = [t.nome, t.origem]
        if importacao:
            linha += [t.destino, "Idêntico" if t.conferida else "DIFERENTE"]
        linhas.append(linha)
    totais = [TotalRelatorio(rotulo="Registros", valor=str(sum(t.origem for t in s.tabelas))),
              TotalRelatorio(rotulo="Documentos e comprovantes conferidos", valor=str(s.arquivos_conferidos))]
    obs = (s.mensagem or "")
    if s.pendencias:
        obs += " O que falta fazer: " + " ".join(f"({i}) {p}" for i, p in enumerate(s.pendencias, 1))
    rel = Relatorio(tipo="migracao", titulo=titulo, gerado_em=agora(), gerado_por=gerado_por, filtros=filtros,
                    colunas=colunas, linhas=linhas, totais=totais, observacao=obs or None)
    return pdf(rel)
