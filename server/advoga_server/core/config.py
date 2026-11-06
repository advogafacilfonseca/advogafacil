"""Configuração do servidor.

Os dados (banco, documentos, configurações e backups) ficam sempre fora da pasta
do código e do programa instalado. No Windows: C:\\ProgramData\\AdvogaFacil.
"""

from __future__ import annotations

import glob
import json
import os
import shutil
import sys
from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


def pasta_dados_padrao() -> Path:
    if sys.platform == "win32":
        base = os.environ.get("PROGRAMDATA", r"C:\ProgramData")
        return Path(base) / "AdvogaFacil"
    return Path("/var/lib/advogafacil")


class Configuracoes(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="ADVOGA_", extra="ignore")

    pasta_dados: Path = Field(default_factory=pasta_dados_padrao)
    database_url: str | None = None
    host: str = "127.0.0.1"
    porta: int = 8765
    https: bool = True

    # Sessões: expiram por inatividade e também por tempo máximo.
    sessao_inatividade_minutos: int = 240
    sessao_maxima_horas: int = 12

    # Proteção contra tentativas de senha.
    login_max_tentativas: int = 5
    login_bloqueio_minutos: int = 15

    # Serviço de avisos (agenda e financeiro) que roda dentro do servidor.
    servico_avisos: bool = True
    avisos_intervalo_segundos: int = 300

    # Central de Backups: serviço que roda dentro do servidor.
    servico_backups: bool = True
    backups_verificacao_segundos: int = 60
    # Programas do PostgreSQL (pg_dump/pg_restore) e usuário administrador (criar o banco do teste
    # de restauração). Se não forem informados, são lidos de config/servidor.json.
    postgres_bin: Path | None = None
    postgres_admin_url: str | None = None

    @property
    def pasta_config(self) -> Path:
        return self.pasta_dados / "config"

    @property
    def pasta_documentos(self) -> Path:
        return self.pasta_dados / "documentos"

    @property
    def pasta_logs(self) -> Path:
        return self.pasta_dados / "logs"

    @property
    def arquivo_servidor(self) -> Path:
        return self.pasta_config / "servidor.json"

    @property
    def arquivo_codigo_instalacao(self) -> Path:
        return self.pasta_config / "CODIGO_DE_INSTALACAO.txt"

    def url_banco(self) -> str:
        """URL do banco: variável de ambiente ou arquivo de configuração do servidor."""
        if self.database_url:
            return self.database_url
        if self.arquivo_servidor.exists():
            dados = json.loads(self.arquivo_servidor.read_text(encoding="utf-8-sig"))
            url = dados.get("database_url")
            if url:
                return url
        raise RuntimeError(
            "Banco de dados não configurado. Defina ADVOGA_DATABASE_URL ou "
            f"crie {self.arquivo_servidor}."
        )

    def dados_servidor(self) -> dict:
        if self.arquivo_servidor.exists():
            return json.loads(self.arquivo_servidor.read_text(encoding="utf-8-sig"))
        return {}

    def programa_postgres(self, nome: str) -> str:
        """Caminho de pg_dump/pg_restore: configurado, do instalador, no PATH ou instalação padrão."""
        exe = nome + (".exe" if sys.platform == "win32" else "")
        pastas = [self.postgres_bin, self.dados_servidor().get("postgres_bin")]
        for pasta in pastas:
            if pasta and (Path(pasta) / exe).exists():
                return str(Path(pasta) / exe)
        achado = shutil.which(nome)
        if achado:
            return achado
        candidatos = sorted(glob.glob(f"/usr/lib/postgresql/*/bin/{nome}"), reverse=True)
        if sys.platform == "win32":
            candidatos += sorted(glob.glob(rf"C:\Program Files\PostgreSQL\*\bin\{exe}"), reverse=True)
        if candidatos:
            return candidatos[0]
        raise RuntimeError(f"Programa {nome} do PostgreSQL não encontrado neste computador.")

    def url_admin(self) -> str:
        """Usuário que pode criar bancos (teste de restauração). Padrão: o do instalador."""
        if self.postgres_admin_url:
            return self.postgres_admin_url
        d = self.dados_servidor()
        if d.get("postgres_superusuario") and d.get("postgres_superusuario_senha"):
            from urllib.parse import quote

            porta = d.get("postgres_porta", 5433)
            return (f"postgresql+psycopg://{quote(d['postgres_superusuario'])}:"
                    f"{quote(d['postgres_superusuario_senha'])}@127.0.0.1:{porta}/postgres")
        return self.url_banco()

    def garantir_pastas(self) -> None:
        for pasta in (self.pasta_config, self.pasta_documentos, self.pasta_logs):
            pasta.mkdir(parents=True, exist_ok=True)


@lru_cache
def obter_configuracoes() -> Configuracoes:
    return Configuracoes()
