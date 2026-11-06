"""Configuração do servidor.

Os dados (banco, documentos, configurações e backups) ficam sempre fora da pasta
do código e do programa instalado. No Windows: C:\\ProgramData\\AdvogaFacil.
"""

from __future__ import annotations

import json
import os
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

    # Sessões: expiram por inatividade e também por tempo máximo.
    sessao_inatividade_minutos: int = 240
    sessao_maxima_horas: int = 12

    # Proteção contra tentativas de senha.
    login_max_tentativas: int = 5
    login_bloqueio_minutos: int = 15

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
            dados = json.loads(self.arquivo_servidor.read_text(encoding="utf-8"))
            url = dados.get("database_url")
            if url:
                return url
        raise RuntimeError(
            "Banco de dados não configurado. Defina ADVOGA_DATABASE_URL ou "
            f"crie {self.arquivo_servidor}."
        )

    def garantir_pastas(self) -> None:
        for pasta in (self.pasta_config, self.pasta_documentos, self.pasta_logs):
            pasta.mkdir(parents=True, exist_ok=True)


@lru_cache
def obter_configuracoes() -> Configuracoes:
    return Configuracoes()
