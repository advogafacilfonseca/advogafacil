"""Central de Backups: cópias do banco e dos documentos, verificação, retenção, teste de restauração.

Estrutura no HD externo (pasta escolhida pela Master, no computador servidor):

    AdvogaFacil-Backups/
        LEIA-ME.txt
        documentos/...                      cópia única de cada arquivo (documentos e comprovantes)
        versoes/2026-11-06_230000_completo/
            banco.dump                      cópia completa do banco (pg_dump, formato custom)
            manifesto.json                  conferência: hash do banco, contagens e hash de cada arquivo

- Cada versão é um ponto completo de restauração: o banco sai inteiro e os documentos ficam
  guardados uma única vez (documentos nunca mudam de conteúdo), então os backups rápidos durante
  o dia são o "incremental equivalente": só copiam os arquivos novos.
- O backup completo diário confere de novo TODOS os arquivos, no servidor e no HD, pelo hash.
- A cópia criptografada (.afbk) vai para um segundo destino, separado do HD externo.
- O banco é exportado num instantâneo consistente: as contagens e a lista de arquivos do
  manifesto são lidas no mesmo instante do pg_dump.
"""

from __future__ import annotations

import base64
import hashlib
import io
import json
import logging
import os
import re
import secrets
import shutil
import subprocess
import tarfile
import tempfile
import threading
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path

from fastapi import HTTPException
from sqlalchemy import create_engine, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session
from sqlalchemy.pool import NullPool

from advoga_shared import __version__
from advoga_shared.esquemas import (
    CATEGORIA_BACKUP,
    ConfiguracaoBackup,
    EstadoBackups,
    ExecucaoBackup as ExecucaoSaida,
    SituacaoDestino,
)

from ..core.cofre import SegredoIndisponivel, cifrar, decifrar
from ..core.config import Configuracoes
from ..models import Base, Configuracao, ExecucaoBackup, Notificacao, Usuario
from . import auditoria
from .arquivo_cifrado import Cifrador, Decifrador, derivar_chave

log = logging.getLogger("advoga.backup")

RAIZ = "AdvogaFacil-Backups"
CHAVE_CONFIG = "backups.config"
CHAVE_SENHA = "backups.chave"
TRAVA = 7400018
PADRAO_VERSAO = re.compile(r"^\d{4}-\d{2}-\d{2}_\d{6}_(rapido|completo)$")
PADRAO_COPIA = re.compile(r"^AdvogaFacil_\d{4}-\d{2}-\d{2}_\d{6}\.afbk$")
MANTER_COMPLETOS = 3
ESPACO_MINIMO = 200 * 1024 * 1024  # folga além do tamanho estimado


class FalhaBackup(Exception):
    pass


def agora() -> datetime:
    return datetime.now(UTC).astimezone()


def _sha256_arquivo(caminho: Path) -> str:
    h = hashlib.sha256()
    with open(caminho, "rb") as f:
        while bloco := f.read(1024 * 1024):
            h.update(bloco)
    return h.hexdigest()


def _tamanho_legivel(n: int | None) -> str:
    if n is None:
        return "—"
    for unidade in ("bytes", "KB", "MB", "GB", "TB"):
        if n < 1024 or unidade == "TB":
            return f"{n:.0f} {unidade}" if unidade == "bytes" else f"{n:.1f} {unidade}".replace(".", ",")
        n /= 1024
    return str(n)


# ========================================================================= configuração
def obter_config(db: Session, cfg: Configuracoes | None = None) -> ConfiguracaoBackup:
    linha = db.get(Configuracao, CHAVE_CONFIG)
    c = ConfiguracaoBackup.model_validate(linha.valor) if linha else ConfiguracaoBackup()
    c.senha_copia_definida = db.get(Configuracao, CHAVE_SENHA) is not None
    return c


def _validar_caminho(caminho: str | None, nome: str) -> str | None:
    if not caminho or not caminho.strip():
        return None
    caminho = caminho.strip()
    p = Path(caminho)
    if not p.is_absolute():
        raise HTTPException(422, f"{nome}: informe o caminho completo da pasta (ex.: E:\\Backups).")
    return caminho


def salvar_config(db: Session, cfg: Configuracoes, ator: Usuario, dados: ConfiguracaoBackup,
                  ip: str | None) -> ConfiguracaoBackup:
    dados.destino = _validar_caminho(dados.destino, "Destino do backup")
    dados.destino_secundario = _validar_caminho(dados.destino_secundario, "Destino da cópia criptografada")
    if dados.ativo and not dados.destino:
        raise HTTPException(422, "Informe a pasta de destino (HD externo) para ligar os backups automáticos.")
    if dados.copia_secundaria_ativa:
        if not dados.destino_secundario:
            raise HTTPException(422, "Informe a pasta da cópia criptografada.")
        if db.get(Configuracao, CHAVE_SENHA) is None:
            raise HTTPException(422, "Defina a senha da cópia criptografada antes de ligá-la.")
    if dados.destino and dados.destino_secundario and \
            Path(dados.destino).resolve() == Path(dados.destino_secundario).resolve():
        raise HTTPException(422, "A cópia criptografada precisa ir para um local diferente do backup principal.")
    valor = dados.model_dump(exclude={"senha_copia_definida"})
    linha = db.get(Configuracao, CHAVE_CONFIG)
    antes = linha.valor if linha else None
    if linha is None:
        db.add(Configuracao(chave=CHAVE_CONFIG, valor=valor, atualizado_por=ator.id))
    else:
        linha.valor, linha.atualizado_por = valor, ator.id
    db.flush()
    auditoria.registrar(db, "backups.configurados", usuario_id=ator.id, entidade="configuracao",
                        entidade_id=CHAVE_CONFIG, detalhes={"antes": antes, "depois": valor}, ip=ip)
    return obter_config(db)


def definir_senha_copia(db: Session, cfg: Configuracoes, ator: Usuario, senha: str, ip: str | None) -> None:
    """Guarda a chave derivada da senha, cifrada com a chave deste servidor. A senha não é guardada."""
    sal = os.urandom(16)
    chave = derivar_chave(senha, sal)
    valor = {"sal": base64.b64encode(sal).decode(), "chave": cifrar(cfg, base64.b64encode(chave).decode()),
             "definida_em": agora().isoformat()}
    linha = db.get(Configuracao, CHAVE_SENHA)
    if linha is None:
        db.add(Configuracao(chave=CHAVE_SENHA, valor=valor, atualizado_por=ator.id))
    else:
        linha.valor, linha.atualizado_por = valor, ator.id
    db.flush()
    auditoria.registrar(db, "backups.senha_copia_definida", usuario_id=ator.id, ip=ip)


def _chave_copia(db: Session, cfg: Configuracoes) -> tuple[bytes, bytes]:
    linha = db.get(Configuracao, CHAVE_SENHA)
    if linha is None:
        raise FalhaBackup("A senha da cópia criptografada não foi definida.")
    try:
        chave = base64.b64decode(decifrar(cfg, linha.valor["chave"]))
    except SegredoIndisponivel as exc:
        raise FalhaBackup("A senha da cópia criptografada precisa ser definida de novo neste servidor.") from exc
    return chave, base64.b64decode(linha.valor["sal"])


# ============================================================================== destino
def _raiz_unidade(p: Path) -> Path | None:
    """Unidade do destino (ex.: E:\\). Se ela não existe, o HD externo está desconectado."""
    return Path(p.anchor) if p.anchor else None


def situacao_destino(caminho: str | None) -> SituacaoDestino:
    if not caminho:
        return SituacaoDestino(caminho=None, disponivel=False, mensagem="Nenhum destino configurado.")
    p = Path(caminho)
    ancora = _raiz_unidade(p)
    if ancora is None or not ancora.exists():
        return SituacaoDestino(caminho=caminho, disponivel=False,
                               mensagem=f"HD externo desconectado: a unidade {p.anchor or caminho} não foi encontrada.")
    existente = p
    while not existente.exists() and existente != existente.parent:
        existente = existente.parent
    try:
        uso = shutil.disk_usage(existente)
    except OSError as exc:
        return SituacaoDestino(caminho=caminho, disponivel=False, mensagem=f"Destino inacessível: {exc.strerror or exc}.")
    if existente.exists() and not existente.is_dir():
        return SituacaoDestino(caminho=caminho, disponivel=False, mensagem="O destino informado não é uma pasta.")
    msg = (f"Disponível: {_tamanho_legivel(uso.free)} livres de {_tamanho_legivel(uso.total)}."
           if p.exists() else f"A pasta será criada no primeiro backup. Livre: {_tamanho_legivel(uso.free)}.")
    return SituacaoDestino(caminho=caminho, disponivel=True, livre_bytes=uso.free, total_bytes=uso.total, mensagem=msg)


def _preparar_destino(caminho: str, necessario: int) -> Path:
    s = situacao_destino(caminho)
    if not s.disponivel:
        raise FalhaBackup(s.mensagem)
    raiz = Path(caminho) / RAIZ
    try:
        (raiz / "versoes").mkdir(parents=True, exist_ok=True)
        (raiz / "documentos").mkdir(parents=True, exist_ok=True)
        teste = raiz / f".teste-gravacao-{secrets.token_hex(4)}"
        teste.write_bytes(b"ok")
        teste.unlink()
    except OSError as exc:
        raise FalhaBackup(f"Não foi possível gravar no destino {caminho}: {exc.strerror or exc}.") from exc
    livre = shutil.disk_usage(raiz).free
    if livre < necessario + ESPACO_MINIMO:
        raise FalhaBackup(f"Sem espaço no destino: são necessários cerca de "
                          f"{_tamanho_legivel(necessario + ESPACO_MINIMO)} e há {_tamanho_legivel(livre)} livres.")
    leia = raiz / "LEIA-ME.txt"
    if not leia.exists():
        leia.write_text(LEIA_ME, encoding="utf-8")
    return raiz


LEIA_ME = """BACKUPS DO ADVOGA FÁCIL
=======================

Esta pasta contém cópias de segurança do Advoga Fácil (banco de dados e documentos).
Contém informações confidenciais de clientes: guarde este HD em local seguro e, se possível,
proteja-o com o BitLocker To Go do Windows.

- versoes/: cada pasta é um ponto completo de restauração (banco.dump + manifesto.json).
- documentos/: os arquivos dos documentos e comprovantes (uma cópia de cada).

Para restaurar, siga o "Guia de recuperação de dados" (docs/manuais/recuperacao-de-dados.md):
    AdvogaFacilServidor.exe restaurar --origem "<pasta da versão>"
Não apague nem altere arquivos desta pasta manualmente.
"""


# ================================================================== execução (registro)
def _iniciar_registro(db: Session, tipo: str, origem: str, usuario_id: uuid.UUID | None,
                      destino: str | None) -> ExecucaoBackup:
    e = ExecucaoBackup(tipo=tipo, origem=origem, situacao="em_andamento", destino=destino, iniciado_por=usuario_id,
                       iniciado_em=agora())
    db.add(e)
    db.commit()
    return e


def _alertar_master(db: Session, titulo: str, mensagem: str, chave: str) -> None:
    """Aviso no aplicativo (e por e-mail, se configurado) para a Master. Sem duplicar."""
    for u in db.scalars(select(Usuario).where(Usuario.is_master, Usuario.ativo)):
        k = f"{chave}:{u.id}"[:200]
        if db.scalar(select(Notificacao.id).where(Notificacao.chave == k)) is None:
            db.add(Notificacao(chave=k, categoria=CATEGORIA_BACKUP, usuario_id=u.id, titulo=titulo[:200],
                               mensagem=mensagem, entidade="backup", email_destino=u.email))
    db.commit()


def _finalizar(db: Session, e: ExecucaoBackup, situacao: str, mensagem: str, **campos) -> ExecucaoBackup:
    e.situacao, e.mensagem, e.concluido_em = situacao, mensagem, agora()
    for k, v in campos.items():
        setattr(e, k, v)
    db.commit()
    if situacao == "falhou":
        nome = {"rapido": "BACKUP", "completo": "BACKUP COMPLETO", "teste_restauracao": "TESTE DE RESTAURAÇÃO"}[e.tipo]
        _alertar_master(db, f"FALHA NO {nome}", mensagem, f"backup:{e.id}")
    return e


# ============================================================================ pg_dump
def _conexao_pg(url: str) -> tuple[list[str], dict]:
    u = make_url(url)
    args = ["-h", u.host or "127.0.0.1", "-p", str(u.port or 5432), "-U", u.username or "postgres"]
    env = dict(os.environ)
    if u.password:
        env["PGPASSWORD"] = u.password
    env["PGCONNECT_TIMEOUT"] = "15"
    return args, env


def _rodar(cmd: list[str], env: dict, descricao: str, timeout: int = 3600) -> subprocess.CompletedProcess:
    try:
        r = subprocess.run(cmd, env=env, capture_output=True, timeout=timeout,
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise FalhaBackup(f"{descricao}: {exc}") from exc
    if r.returncode != 0:
        erro = (r.stderr or b"").decode("utf-8", "replace").strip().splitlines()
        raise FalhaBackup(f"{descricao}: {erro[-1] if erro else 'erro ' + str(r.returncode)}")
    return r


@dataclass
class Instantaneo:
    contagens: dict[str, int]
    arquivos: list[dict]  # {"caminho", "sha256", "tamanho", "origem": "documentos"|"_financeiro"}
    revisao: str | None
    servidor_id: str | None
    tamanho_banco: int
    somas: dict[str, str] = field(default_factory=dict)  # impressão digital do conteúdo de cada tabela


def tabelas_do_banco(c) -> list[str]:
    return [r[0] for r in c.execute(text(
        "SELECT table_name FROM information_schema.tables WHERE table_schema = 'public' "
        "AND table_type = 'BASE TABLE' AND table_name <> 'alembic_version' ORDER BY table_name"))]


def somas_tabelas(c, tabelas: list[str]) -> dict[str, str]:
    """Impressão digital (MD5) do conteúdo de cada tabela, independente da ordem física das linhas.
    Usada na migração para provar que o banco novo é idêntico ao exportado."""
    c.execute(text("SET LOCAL TimeZone = 'UTC'"))
    c.execute(text("SET LOCAL DateStyle = 'ISO, YMD'"))
    c.execute(text("SET LOCAL IntervalStyle = 'postgres'"))
    c.execute(text("SET LOCAL extra_float_digits = 3"))
    return {t: c.execute(text(f"SELECT md5(coalesce(string_agg(md5(x::text), '' ORDER BY md5(x::text)), '')) "
                              f'FROM "{t}" x')).scalar_one() for t in tabelas}


def _exportar_banco(cfg: Configuracoes, url: str, destino: Path, migracao: bool = False) -> Instantaneo:
    """pg_dump num instantâneo; contagens e lista de arquivos lidas no mesmo instante.

    Na migração, as tabelas ficam travadas para gravação até o fim da exportação (as gravações em
    andamento terminam antes do instantâneo) e é calculada a impressão digital de cada tabela."""
    eng = create_engine(url, isolation_level="REPEATABLE READ", poolclass=NullPool)
    try:
        with eng.connect() as c:
            c.execute(text("SET TRANSACTION READ ONLY"))
            nomes = [t.name for t in Base.metadata.sorted_tables]
            if migracao:
                # LOCK antes de qualquer SELECT: o instantâneo só é fixado depois da trava.
                c.execute(text("LOCK TABLE " + ", ".join(f'"{t}"' for t in nomes) + " IN SHARE MODE"))
            snapshot = c.execute(text("SELECT pg_export_snapshot()")).scalar_one()
            contagens = {t: c.execute(text(f'SELECT count(*) FROM "{t}"')).scalar_one() for t in nomes}
            somas = somas_tabelas(c, nomes) if migracao else {}
            arquivos = [{"caminho": r[0], "sha256": r[1], "tamanho": r[2], "origem": "documentos"}
                        for r in c.execute(text("SELECT caminho, sha256, tamanho FROM documentos"))]
            arquivos += [{"caminho": "_financeiro/" + r[0], "sha256": r[1], "tamanho": r[2], "origem": "_financeiro"}
                         for r in c.execute(text("SELECT caminho, sha256, tamanho FROM comprovantes"))]
            revisao = c.execute(text("SELECT version_num FROM alembic_version")).scalar()
            servidor_id = c.execute(text("SELECT servidor_id::text FROM identidade_servidor WHERE id = 1")).scalar()
            tamanho = c.execute(text("SELECT pg_database_size(current_database())")).scalar_one()
            args, env = _conexao_pg(url)
            _rodar([cfg.programa_postgres("pg_dump"), *args, "-d", make_url(url).database, "-Fc", "-Z", "6",
                    "--no-owner", "--no-privileges", f"--snapshot={snapshot}", "-f", str(destino)],
                   env, "Falha ao exportar o banco de dados")
            c.rollback()
    finally:
        eng.dispose()
    return Instantaneo(contagens, arquivos, revisao, servidor_id, tamanho, somas)


# =============================================================================== backup
@dataclass
class _Resultado:
    novos: int = 0
    bytes_copiados: int = 0
    problemas: list[str] = field(default_factory=list)


def _copiar_documentos(cfg: Configuracoes, raiz: Path, arquivos: list[dict], completo: bool) -> _Resultado:
    res = _Resultado()
    loja = raiz / "documentos"
    origem_raiz = cfg.pasta_documentos
    for a in arquivos:
        rel = Path(a["caminho"])
        if rel.is_absolute() or ".." in rel.parts:
            res.problemas.append(f"Caminho inválido ignorado: {a['caminho']}")
            continue
        origem = origem_raiz / rel
        destino = loja / rel
        if destino.exists() and destino.stat().st_size == a["tamanho"]:
            if not completo:
                continue
            # Completo: confere de novo a cópia do HD e o original no servidor
            if _sha256_arquivo(destino) != a["sha256"]:
                res.problemas.append(f"Cópia danificada no HD (será refeita): {a['caminho']}")
                destino.unlink()
            else:
                if not origem.exists():
                    res.problemas.append(f"Arquivo ausente no servidor (há cópia no backup): {a['caminho']}")
                elif _sha256_arquivo(origem) != a["sha256"]:
                    res.problemas.append(f"Arquivo alterado ou corrompido no servidor (a cópia boa está no "
                                         f"backup): {a['caminho']}")
                continue
        if not origem.exists():
            res.problemas.append(f"Arquivo ausente no servidor e sem cópia no backup: {a['caminho']}")
            continue
        destino.parent.mkdir(parents=True, exist_ok=True)
        parcial = destino.with_name(destino.name + ".copiando")
        h = hashlib.sha256()
        with open(origem, "rb") as fo, open(parcial, "wb") as fd:
            while bloco := fo.read(1024 * 1024):
                h.update(bloco)
                fd.write(bloco)
            fd.flush()
            os.fsync(fd.fileno())
        if h.hexdigest() != a["sha256"]:
            parcial.unlink(missing_ok=True)
            res.problemas.append(f"Arquivo corrompido no servidor (não copiado): {a['caminho']}")
            continue
        if _sha256_arquivo(parcial) != a["sha256"]:
            parcial.unlink(missing_ok=True)
            raise FalhaBackup(f"A cópia gravada no HD não confere com o original ({a['caminho']}). "
                              "O HD pode estar com defeito.")
        os.replace(parcial, destino)
        res.novos += 1
        res.bytes_copiados += a["tamanho"]
    return res


def _aplicar_retencao(raiz: Path, reter_dias: int, atual: str) -> list[str]:
    versoes = sorted(d for d in (raiz / "versoes").iterdir() if d.is_dir() and PADRAO_VERSAO.match(d.name))
    completos = [v.name for v in versoes if v.name.endswith("_completo")]
    protegidos = set(completos[-MANTER_COMPLETOS:]) | {atual}
    limite = (agora() - timedelta(days=reter_dias)).strftime("%Y-%m-%d_%H%M%S")
    removidas = []
    for v in versoes:
        if v.name in protegidos or v.name[:17] >= limite:
            continue
        shutil.rmtree(v, ignore_errors=True)
        removidas.append(v.name)
    # Sobras de backups interrompidos
    for v in (raiz / "versoes").iterdir():
        if v.name.endswith(".parcial") and v.name[:-8] != atual:
            shutil.rmtree(v, ignore_errors=True)
    return removidas


def _gravar_copia_cifrada(db: Session, cfg: Configuracoes, conf: ConfiguracaoBackup, raiz: Path, versao: str,
                          manifesto: dict) -> str:
    chave, sal = _chave_copia(db, cfg)
    s = situacao_destino(conf.destino_secundario)
    if not s.disponivel:
        raise FalhaBackup(f"Cópia criptografada: {s.mensagem}")
    pasta = Path(conf.destino_secundario)
    pasta.mkdir(parents=True, exist_ok=True)
    estimado = sum(a["tamanho"] for a in manifesto["documentos"]) + manifesto["banco"]["tamanho"]
    if shutil.disk_usage(pasta).free < estimado + ESPACO_MINIMO:
        raise FalhaBackup("Cópia criptografada: sem espaço no destino.")
    nome = f"AdvogaFacil_{versao[:17]}.afbk"
    final = pasta / nome
    parcial = pasta / (nome + ".parcial")
    pasta_versao = raiz / "versoes" / versao
    with open(parcial, "wb") as f:
        cif = Cifrador(f, chave, sal, {"versao": versao, "sistema": __version__})
        with tarfile.open(fileobj=cif, mode="w|") as tar:
            tar.add(pasta_versao / "banco.dump", arcname=f"{versao}/banco.dump")
            tar.add(pasta_versao / "manifesto.json", arcname=f"{versao}/manifesto.json")
            for a in manifesto["documentos"]:
                tar.add(raiz / "documentos" / a["caminho"], arcname=f"{versao}/documentos/{a['caminho']}")
        cif.finalizar()
        f.flush()
        os.fsync(f.fileno())
    # Verificação: abre a cópia inteira e confere cada arquivo pelo hash
    try:
        verificar_copia_cifrada(parcial, chave=chave)
    except Exception:
        parcial.unlink(missing_ok=True)
        raise
    os.replace(parcial, final)
    copias = sorted(p for p in pasta.iterdir() if PADRAO_COPIA.match(p.name))
    for antiga in copias[:-conf.reter_copias_secundarias]:
        antiga.unlink(missing_ok=True)
    return f"Gravada e conferida: {final} ({_tamanho_legivel(final.stat().st_size)})."


def verificar_copia_cifrada(arquivo: Path, senha: str | None = None, chave: bytes | None = None,
                            extrair_em: Path | None = None) -> dict:
    """Abre a cópia .afbk, confere o banco e cada documento pelo manifesto. Pode extrair."""
    hashes: dict[str, str] = {}
    manifesto = None
    with open(arquivo, "rb") as f:
        dec = io.BufferedReader(Decifrador(f, senha=senha, chave=chave), buffer_size=1024 * 1024)
        with tarfile.open(fileobj=dec, mode="r|") as tar:
            for membro in tar:
                if not membro.isfile():
                    continue
                partes = Path(membro.name).parts
                if len(partes) < 2 or ".." in partes or Path(membro.name).is_absolute():
                    raise FalhaBackup("Conteúdo inesperado na cópia criptografada.")
                origem = tar.extractfile(membro)
                h = hashlib.sha256()
                destino = None
                if extrair_em is not None:
                    destino = extrair_em / membro.name
                    destino.parent.mkdir(parents=True, exist_ok=True)
                saida = open(destino, "wb") if destino else None
                dados = bytearray() if partes[-1] == "manifesto.json" and len(partes) == 2 else None
                try:
                    while bloco := origem.read(1024 * 1024):
                        h.update(bloco)
                        if saida:
                            saida.write(bloco)
                        if dados is not None:
                            dados.extend(bloco)
                finally:
                    if saida:
                        saida.close()
                rel = "/".join(partes[1:])
                hashes[rel] = h.hexdigest()
                if dados is not None:
                    manifesto = json.loads(bytes(dados))
    if manifesto is None:
        raise FalhaBackup("A cópia criptografada não contém o manifesto.")
    if hashes.get("banco.dump") != manifesto["banco"]["sha256"]:
        raise FalhaBackup("O banco dentro da cópia criptografada não confere.")
    for a in manifesto["documentos"]:
        if hashes.get("documentos/" + a["caminho"]) != a["sha256"]:
            raise FalhaBackup(f"Documento não confere na cópia criptografada: {a['caminho']}")
    return manifesto


_trava_local = threading.Lock()


def _com_trava(url: str):
    """Trava no banco: um backup ou teste por vez, mesmo com mais de um processo do servidor."""
    eng = create_engine(url, poolclass=NullPool)
    conn = eng.connect()
    if not conn.execute(text(f"SELECT pg_try_advisory_lock({TRAVA})")).scalar_one():
        conn.close()
        eng.dispose()
        return None
    return eng, conn


def _soltar(trava) -> None:
    eng, conn = trava
    try:
        conn.execute(text(f"SELECT pg_advisory_unlock({TRAVA})"))
    finally:
        conn.close()
        eng.dispose()


def executar(db: Session, cfg: Configuracoes, tipo: str, origem: str = "automatico",
             usuario_id: uuid.UUID | None = None) -> ExecucaoBackup:
    """Faz um backup (rapido|completo). Sempre registra o resultado; em falha avisa a Master."""
    if not _trava_local.acquire(blocking=False):
        raise HTTPException(409, "Já existe um backup em andamento.")
    try:
        url = cfg.url_banco()
        trava = _com_trava(url)
        if trava is None:
            raise HTTPException(409, "Já existe um backup em andamento.")
        try:
            return _executar(db, cfg, url, tipo, origem, usuario_id)
        finally:
            _soltar(trava)
    finally:
        _trava_local.release()


def _executar(db: Session, cfg: Configuracoes, url: str, tipo: str, origem: str,
              usuario_id: uuid.UUID | None) -> ExecucaoBackup:
    conf = obter_config(db)
    e = _iniciar_registro(db, tipo, origem, usuario_id, conf.destino)
    completo = tipo == "completo"
    try:
        if not conf.destino:
            raise FalhaBackup("Nenhum destino de backup configurado.")
        tamanho_banco = db.scalar(text("SELECT pg_database_size(current_database())")) or 0
        raiz = _preparar_destino(conf.destino, tamanho_banco)
        versao = f"{agora():%Y-%m-%d_%H%M%S}_{tipo}"
        while (raiz / "versoes" / versao).exists() or (raiz / "versoes" / (versao + ".parcial")).exists():
            import time

            time.sleep(1)  # dois backups no mesmo segundo: o nome da versão precisa ser único
            versao = f"{agora():%Y-%m-%d_%H%M%S}_{tipo}"
        pasta = raiz / "versoes" / (versao + ".parcial")
        pasta.mkdir(parents=True)
        dump = pasta / "banco.dump"
        inst = _exportar_banco(cfg, url, dump)
        args, env = _conexao_pg(url)
        _rodar([cfg.programa_postgres("pg_restore"), "--list", str(dump)], env,
               "A cópia do banco não pôde ser lida (verificação)")
        sha_banco = _sha256_arquivo(dump)
        necessario = sum(a["tamanho"] for a in inst.arquivos if not (raiz / "documentos" / a["caminho"]).exists())
        if shutil.disk_usage(raiz).free < necessario + ESPACO_MINIMO:
            raise FalhaBackup(f"Sem espaço no destino para os documentos novos "
                              f"({_tamanho_legivel(necessario)} necessários).")
        res = _copiar_documentos(cfg, raiz, inst.arquivos, completo)
        manifesto = {
            "formato": 1, "versao": versao, "tipo": tipo, "criado_em": agora().isoformat(), "sistema": __version__,
            "revisao_banco": inst.revisao, "servidor_id": inst.servidor_id,
            "banco": {"arquivo": "banco.dump", "sha256": sha_banco, "tamanho": dump.stat().st_size,
                      "contagens": inst.contagens},
            "documentos": [{"caminho": a["caminho"], "sha256": a["sha256"], "tamanho": a["tamanho"]}
                           for a in inst.arquivos if (raiz / "documentos" / a["caminho"]).exists()],
            "problemas": res.problemas,
        }
        (pasta / "manifesto.json").write_text(json.dumps(manifesto, ensure_ascii=False, indent=1), encoding="utf-8")
        # Confere o que ficou gravado no HD (o banco sempre; os documentos novos já foram conferidos)
        if _sha256_arquivo(dump) != sha_banco:
            raise FalhaBackup("A cópia do banco gravada no HD não confere. O HD pode estar com defeito.")
        tamanho_dump = dump.stat().st_size
        os.replace(pasta, raiz / "versoes" / versao)
        removidas = _aplicar_retencao(raiz, conf.reter_dias, versao)
        tamanho = tamanho_dump + res.bytes_copiados
        copia = None
        if completo and conf.copia_secundaria_ativa:
            try:
                copia = _gravar_copia_cifrada(db, cfg, conf, raiz, versao, manifesto)
            except Exception as exc:  # noqa: BLE001 - a cópia principal continua válida
                copia = f"FALHOU: {exc}"
                log.exception("Falha na cópia criptografada")
        elif completo:
            copia = "Desligada."
        detalhes = {"contagens": inst.contagens, "versoes_removidas": removidas, "problemas": res.problemas[:200],
                    "banco_sha256": sha_banco}
        total = len(manifesto["documentos"])
        msg = (f"Versão {versao}: banco ({_tamanho_legivel(tamanho_dump)}) e {total} arquivo(s), "
               f"{res.novos} novo(s). Integridade conferida.")
        if res.problemas or (copia or "").startswith("FALHOU"):
            partes = []
            if res.problemas:
                partes.append(f"{len(res.problemas)} problema(s) nos arquivos: " + "; ".join(res.problemas[:5]))
            if (copia or "").startswith("FALHOU"):
                partes.append(f"Cópia criptografada {copia}")
            return _finalizar(db, e, "falhou", "Backup gravado com alertas. " + " ".join(partes), versao=versao,
                              tamanho_bytes=tamanho, arquivos_novos=res.novos, arquivos_total=total,
                              copia_secundaria=(copia or "")[:500] or None, detalhes=detalhes)
        return _finalizar(db, e, "sucesso", msg, versao=versao, tamanho_bytes=tamanho, arquivos_novos=res.novos,
                          arquivos_total=total, copia_secundaria=(copia or "")[:500] or None, detalhes=detalhes)
    except FalhaBackup as exc:
        db.rollback()
        return _finalizar(db, e, "falhou", str(exc))
    except Exception as exc:  # noqa: BLE001
        db.rollback()
        log.exception("Erro inesperado no backup")
        return _finalizar(db, e, "falhou", f"Erro inesperado: {exc.__class__.__name__}: {exc}")


# ================================================================= teste de restauração
def ultima_versao(raiz: Path) -> Path | None:
    pasta = raiz / "versoes"
    if not pasta.exists():
        return None
    versoes = sorted(d for d in pasta.iterdir() if d.is_dir() and PADRAO_VERSAO.match(d.name)
                     and (d / "manifesto.json").exists())
    return versoes[-1] if versoes else None


def conferir_versao(pasta_versao: Path, raiz_documentos: Path) -> dict:
    """Confere o banco e TODOS os documentos de uma versão pelo manifesto. Retorna o manifesto."""
    try:
        manifesto = json.loads((pasta_versao / "manifesto.json").read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise FalhaBackup(f"Manifesto ausente ou danificado em {pasta_versao}.") from exc
    if _sha256_arquivo(pasta_versao / "banco.dump") != manifesto["banco"]["sha256"]:
        raise FalhaBackup("A cópia do banco desta versão está danificada (hash não confere).")
    for a in manifesto["documentos"]:
        arq = raiz_documentos / a["caminho"]
        if not arq.exists():
            raise FalhaBackup(f"Documento ausente no backup: {a['caminho']}")
        if _sha256_arquivo(arq) != a["sha256"]:
            raise FalhaBackup(f"Documento danificado no backup: {a['caminho']}")
    return manifesto


def _restaurar_banco(cfg: Configuracoes, dump: Path, url_destino: str) -> None:
    args, env = _conexao_pg(url_destino)
    _rodar([cfg.programa_postgres("pg_restore"), *args, "-d", make_url(url_destino).database, "--no-owner",
            "--no-privileges", "--exit-on-error", "--single-transaction", str(dump)],
           env, "Falha ao restaurar o banco")


def _contar(url: str) -> dict[str, int]:
    eng = create_engine(url, poolclass=NullPool)
    try:
        with eng.connect() as c:
            return {t.name: c.execute(text(f'SELECT count(*) FROM "{t.name}"')).scalar_one()
                    for t in Base.metadata.sorted_tables}
    finally:
        eng.dispose()


def testar_restauracao(db: Session, cfg: Configuracoes, origem: str = "automatico",
                       usuario_id: uuid.UUID | None = None) -> ExecucaoBackup:
    """Restaura a última versão num banco temporário, confere tudo e apaga o banco temporário."""
    if not _trava_local.acquire(blocking=False):
        raise HTTPException(409, "Já existe um backup em andamento.")
    try:
        url = cfg.url_banco()
        trava = _com_trava(url)
        if trava is None:
            raise HTTPException(409, "Já existe um backup em andamento.")
        try:
            return _testar(db, cfg, url, origem, usuario_id)
        finally:
            _soltar(trava)
    finally:
        _trava_local.release()


def _testar(db: Session, cfg: Configuracoes, url: str, origem: str, usuario_id: uuid.UUID | None) -> ExecucaoBackup:
    conf = obter_config(db)
    e = _iniciar_registro(db, "teste_restauracao", origem, usuario_id, conf.destino)
    nome_banco = f"advoga_teste_restauracao_{secrets.token_hex(4)}"
    admin = None
    criado = False
    try:
        s = situacao_destino(conf.destino)
        if not s.disponivel:
            raise FalhaBackup(s.mensagem)
        raiz = Path(conf.destino) / RAIZ
        versao = ultima_versao(raiz)
        if versao is None:
            raise FalhaBackup("Ainda não há nenhuma versão de backup para testar.")
        manifesto = conferir_versao(versao, raiz / "documentos")
        app_url = make_url(url)
        admin = create_engine(cfg.url_admin(), isolation_level="AUTOCOMMIT", poolclass=NullPool)
        with admin.connect() as c:
            c.execute(text(f'CREATE DATABASE "{nome_banco}" OWNER "{app_url.username}" ENCODING \'UTF8\' '
                           f"TEMPLATE template0"))
        criado = True
        url_teste = app_url.set(database=nome_banco).render_as_string(hide_password=False)
        _restaurar_banco(cfg, versao / "banco.dump", url_teste)
        contagens = _contar(url_teste)
        esperado = manifesto["banco"]["contagens"]
        diferencas = [f"{t}: esperado {esperado.get(t)}, restaurado {contagens.get(t)}"
                      for t in esperado if esperado.get(t) != contagens.get(t)]
        if diferencas:
            raise FalhaBackup("A restauração não trouxe todos os registros: " + "; ".join(diferencas[:5]))
        total = sum(contagens.values())
        return _finalizar(db, e, "sucesso",
                          f"Versão {versao.name} restaurada num banco de teste: {total} registros em "
                          f"{len(contagens)} tabelas e {len(manifesto['documentos'])} arquivo(s) conferidos.",
                          versao=versao.name, arquivos_total=len(manifesto["documentos"]),
                          detalhes={"contagens": contagens})
    except FalhaBackup as exc:
        db.rollback()
        return _finalizar(db, e, "falhou", str(exc))
    except Exception as exc:  # noqa: BLE001
        db.rollback()
        log.exception("Erro inesperado no teste de restauração")
        return _finalizar(db, e, "falhou", f"Erro inesperado: {exc.__class__.__name__}: {exc}")
    finally:
        if admin is not None:
            if criado:
                try:
                    with admin.connect() as c:
                        c.execute(text(f'DROP DATABASE IF EXISTS "{nome_banco}" WITH (FORCE)'))
                except Exception:  # noqa: BLE001
                    log.exception("Não foi possível apagar o banco de teste %s", nome_banco)
            admin.dispose()


# ========================================================================== restauração
def _preparar_banco_destino(url: str, aviso) -> None:
    """Só restaura num banco vazio ou recém-instalado (sem Master e sem nenhum dado).
    Um banco com dados nunca é apagado."""
    eng = create_engine(url, poolclass=NullPool, isolation_level="AUTOCOMMIT")
    try:
        with eng.connect() as c:
            tabelas = {r[0] for r in c.execute(text(
                "SELECT table_name FROM information_schema.tables WHERE table_schema = 'public'"))}
            if not tabelas:
                return
            com_dados = "usuarios" not in tabelas
            if not com_dados:
                for t in ("usuarios", "clientes", "processos", "contratos", "documentos", "compromissos"):
                    if t in tabelas and c.execute(text(f'SELECT EXISTS (SELECT 1 FROM "{t}")')).scalar_one():
                        com_dados = True
                        break
            if com_dados:
                raise FalhaBackup("O banco de destino não está vazio. Por segurança, a restauração só é feita "
                                  "num banco novo ou recém-instalado (veja o guia de recuperação).")
            aviso("Banco recém-instalado e sem dados: preparando para receber a restauração...")
            c.execute(text("DROP SCHEMA public CASCADE"))
            c.execute(text("CREATE SCHEMA public"))
    finally:
        eng.dispose()


def restaurar(cfg: Configuracoes, origem: Path, url_destino: str, senha: str | None = None,
              aviso=print) -> dict:
    """Restaura uma versão (pasta) ou uma cópia criptografada (.afbk) num banco VAZIO e na pasta
    de documentos deste servidor. Confere tudo antes e depois. Usado pela linha de comando."""
    origem = Path(origem)
    temporaria = None
    try:
        if origem.is_file() and origem.suffix.lower() == ".afbk":
            temporaria = Path(tempfile.mkdtemp(prefix="advoga-restauracao-", dir=cfg.pasta_dados))
            aviso("Abrindo e conferindo a cópia criptografada...")
            manifesto = verificar_copia_cifrada(origem, senha=senha, extrair_em=temporaria)
            pasta_versao = temporaria / manifesto["versao"]
            raiz_docs = pasta_versao / "documentos"
        else:
            pasta_versao = origem
            if not (pasta_versao / "manifesto.json").exists():
                ultima = (ultima_versao(origem / RAIZ) or ultima_versao(origem)) if origem.exists() else None
                if ultima is None:
                    raise FalhaBackup(f"Nenhuma versão de backup encontrada em {origem}.")
                pasta_versao = ultima
            raiz_docs = pasta_versao.parent.parent / "documentos"
            aviso(f"Conferindo a versão {pasta_versao.name} (banco e documentos)...")
            manifesto = conferir_versao(pasta_versao, raiz_docs)
        _preparar_banco_destino(url_destino, aviso)
        aviso("Restaurando o banco de dados...")
        _restaurar_banco(cfg, pasta_versao / "banco.dump", url_destino)
        contagens = _contar(url_destino)
        diferencas = [t for t, n in manifesto["banco"]["contagens"].items() if contagens.get(t) != n]
        if diferencas:
            raise FalhaBackup("Contagens diferentes após restaurar: " + ", ".join(diferencas))
        aviso(f"Copiando {len(manifesto['documentos'])} arquivo(s)...")
        for a in manifesto["documentos"]:
            destino = cfg.pasta_documentos / a["caminho"]
            destino.parent.mkdir(parents=True, exist_ok=True)
            if destino.exists() and _sha256_arquivo(destino) == a["sha256"]:
                continue
            shutil.copyfile(raiz_docs / a["caminho"], destino)
            if _sha256_arquivo(destino) != a["sha256"]:
                raise FalhaBackup(f"Documento não confere após a cópia: {a['caminho']}")
        return {"versao": manifesto["versao"], "registros": sum(contagens.values()),
                "arquivos": len(manifesto["documentos"]), "servidor_id": manifesto.get("servidor_id")}
    finally:
        if temporaria is not None:
            shutil.rmtree(temporaria, ignore_errors=True)


# ============================================================================== consultas
def saida(db: Session, e: ExecucaoBackup) -> ExecucaoSaida:
    autor = db.get(Usuario, e.iniciado_por) if e.iniciado_por else None
    return ExecucaoSaida(id=e.id, tipo=e.tipo, origem=e.origem, situacao=e.situacao, iniciado_em=e.iniciado_em,
                         concluido_em=e.concluido_em, versao=e.versao, destino=e.destino, tamanho_bytes=e.tamanho_bytes,
                         arquivos_novos=e.arquivos_novos, arquivos_total=e.arquivos_total,
                         copia_secundaria=e.copia_secundaria, mensagem=e.mensagem,
                         iniciado_por_nome=autor.nome_completo if autor else None)


def historico(db: Session, limite: int = 200) -> list[ExecucaoSaida]:
    return [saida(db, e) for e in db.scalars(select(ExecucaoBackup).order_by(ExecucaoBackup.iniciado_em.desc())
                                             .limit(limite))]


def _ultimo(db: Session, *condicoes) -> ExecucaoBackup | None:
    return db.scalars(select(ExecucaoBackup).where(*condicoes).order_by(ExecucaoBackup.iniciado_em.desc())
                      .limit(1)).first()


def estado(db: Session, cfg: Configuracoes) -> EstadoBackups:
    conf = obter_config(db)
    destino = situacao_destino(conf.destino)
    secundario = situacao_destino(conf.destino_secundario) if conf.copia_secundaria_ativa else None
    sucesso = _ultimo(db, ExecucaoBackup.situacao == "sucesso", ExecucaoBackup.tipo != "teste_restauracao")
    completo = _ultimo(db, ExecucaoBackup.situacao == "sucesso", ExecucaoBackup.tipo == "completo")
    teste = _ultimo(db, ExecucaoBackup.tipo == "teste_restauracao", ExecucaoBackup.situacao != "em_andamento")
    andamento = _ultimo(db, ExecucaoBackup.situacao == "em_andamento",
                        ExecucaoBackup.iniciado_em > agora() - timedelta(hours=12))
    falha = _ultimo(db, ExecucaoBackup.situacao != "em_andamento", ExecucaoBackup.tipo != "teste_restauracao")
    alertas: list[str] = []
    if not conf.ativo:
        alertas.append("Os backups automáticos estão DESLIGADOS.")
    if conf.destino and not destino.disponivel:
        alertas.append(destino.mensagem)
    if secundario and not secundario.disponivel:
        alertas.append("Cópia criptografada: " + secundario.mensagem)
    if destino.disponivel and destino.livre_bytes is not None and sucesso and sucesso.tamanho_bytes and \
            destino.livre_bytes < 3 * (sucesso.tamanho_bytes + ESPACO_MINIMO):
        alertas.append(f"Pouco espaço no HD de backup: {_tamanho_legivel(destino.livre_bytes)} livres.")
    if completo is None:
        alertas.append("Ainda não existe nenhum backup completo.")
    elif completo.concluido_em and completo.concluido_em < agora() - timedelta(hours=26):
        horas = int((agora() - completo.concluido_em).total_seconds() // 3600)
        alertas.append(f"O último backup completo foi há {horas} horas.")
    if falha is not None and falha.situacao == "falhou":
        alertas.append(f"O último backup falhou: {falha.mensagem}")
    if teste is not None and teste.situacao == "falhou":
        alertas.append(f"O último teste de restauração falhou: {teste.mensagem}")
    return EstadoBackups(configuracao=conf, destino=destino, destino_secundario=secundario,
                         ultimo_sucesso=saida(db, sucesso) if sucesso else None,
                         ultimo_completo=saida(db, completo) if completo else None,
                         ultimo_teste=saida(db, teste) if teste else None,
                         em_andamento=saida(db, andamento) if andamento else None, alertas=alertas)


# ============================================================================ agendamento
def tarefa_devida(db: Session, momento: datetime | None = None) -> str | None:
    """Qual tarefa automática deve rodar agora: completo, rapido, teste_restauracao ou None."""
    conf = obter_config(db)
    if not conf.ativo or not conf.destino:
        return None
    momento = momento or agora()
    h, m = map(int, conf.hora_completo.split(":"))
    marco = momento.replace(hour=h, minute=m, second=0, microsecond=0)
    if marco > momento:
        marco -= timedelta(days=1)
    tentativa_completo = _ultimo(db, ExecucaoBackup.tipo == "completo", ExecucaoBackup.origem == "automatico")
    sucesso_completo = _ultimo(db, ExecucaoBackup.tipo == "completo", ExecucaoBackup.situacao == "sucesso")
    # Completo diário: depois do horário, se ainda não houve um completo bem-sucedido desde então.
    # Após uma falha, tenta de novo a cada 30 minutos.
    if sucesso_completo is None or sucesso_completo.iniciado_em < marco:
        if tentativa_completo is None or tentativa_completo.iniciado_em < marco or \
                tentativa_completo.iniciado_em < momento - timedelta(minutes=30):
            return "completo"
    if conf.teste_restauracao_dias and sucesso_completo is not None:
        teste = _ultimo(db, ExecucaoBackup.tipo == "teste_restauracao")
        if teste is None or teste.iniciado_em < momento - timedelta(days=conf.teste_restauracao_dias):
            return "teste_restauracao"
    if conf.intervalo_horas:
        ultimo = _ultimo(db, ExecucaoBackup.tipo.in_(("rapido", "completo")))
        if ultimo is None or ultimo.iniciado_em < momento - timedelta(hours=conf.intervalo_horas):
            return "rapido"
    return None


def verificar_destino_periodicamente(db: Session) -> None:
    """Avisa a Master (uma vez por dia) se o HD de backup estiver desconectado."""
    conf = obter_config(db)
    if not conf.ativo or not conf.destino:
        return
    s = situacao_destino(conf.destino)
    if not s.disponivel:
        _alertar_master(db, "HD DE BACKUP DESCONECTADO", s.mensagem + " Os backups automáticos não podem ser feitos.",
                        f"backup:destino:{agora():%Y-%m-%d}")
