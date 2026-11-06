"""Configuração local de cada computador (somente o endereço do servidor).

Nenhum dado do escritório fica neste arquivo. No Windows: %APPDATA%\\AdvogaFacil\\cliente.json
"""

from __future__ import annotations

import json
import os
import sys
from dataclasses import asdict, dataclass
from pathlib import Path


# Testes apontam para uma pasta temporária sem alterar variáveis de ambiente do processo
# (alterar o ambiente com o servidor rodando em outras threads não é seguro).
PASTA_OVERRIDE: Path | None = None


def pasta_config_local() -> Path:
    if PASTA_OVERRIDE is not None:
        return PASTA_OVERRIDE
    if sys.platform == "win32":
        return Path(os.environ.get("APPDATA", Path.home())) / "AdvogaFacil"
    return Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "advogafacil"


@dataclass
class ConfigLocal:
    endereco_servidor: str = ""
    certificado_pem: str = ""  # certificado do servidor registrado na primeira conexão
    ultimo_usuario: str = ""

    @classmethod
    def carregar(cls) -> "ConfigLocal":
        arq = pasta_config_local() / "cliente.json"
        if not arq.exists():
            return cls()
        try:
            dados = json.loads(arq.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return cls()
        return cls(**{k: v for k, v in dados.items() if k in cls.__dataclass_fields__})

    def salvar(self) -> None:
        pasta = pasta_config_local()
        pasta.mkdir(parents=True, exist_ok=True)
        (pasta / "cliente.json").write_text(json.dumps(asdict(self), ensure_ascii=False, indent=2),
                                            encoding="utf-8")


def normalizar_endereco(texto: str) -> str:
    """Aceita 'servidor', 'servidor:8765' ou 'http(s)://servidor:8765'. Padrão: HTTPS."""
    t = (texto or "").strip().rstrip("/")
    if not t:
        return ""
    if "://" not in t:
        t = "https://" + t
    esquema, resto = t.split("://", 1)
    if ":" not in resto.split("/")[0]:
        resto = resto.split("/")[0] + ":8765"
    return f"{esquema}://{resto.split('/')[0]}"
