"""Configuração local de cada computador (somente o endereço do servidor).

Nenhum dado do escritório fica neste arquivo. No Windows: %APPDATA%\\AdvogaFacil\\cliente.json
"""

from __future__ import annotations

import json
import os
import sys
from dataclasses import asdict, dataclass, field
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
    servidor_id: str = ""  # identidade do servidor oficial conhecido por este computador
    servidores_substituidos: list[str] = field(default_factory=list)  # servidores antigos (migração)

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


MSG_SUBSTITUIDO = ("Este servidor foi substituído por um servidor novo numa migração e não é mais a base "
                   "oficial do escritório. Para não gravar dados no lugar errado, o aplicativo não se conecta a ele. "
                   "Informe o endereço do servidor novo.")


def conferir_servidor(config: ConfigLocal, servidor_id, status: str | None, migrado_de) -> str | None:
    """Impede o uso de um servidor antigo depois de uma migração. Retorna a mensagem de recusa, ou None.

    Quando o servidor informa que substituiu outro (migrado_de), o antigo entra na lista de servidores
    substituídos deste computador e passa a ser recusado, mesmo que alguém o ligue de novo."""
    sid = str(servidor_id) if servidor_id else ""
    if status == "desativado" or (sid and sid in config.servidores_substituidos):
        return MSG_SUBSTITUIDO
    alterado = False
    if migrado_de and str(migrado_de) not in config.servidores_substituidos:
        config.servidores_substituidos.append(str(migrado_de))
        alterado = True
    if sid and config.servidor_id != sid:
        config.servidor_id = sid
        alterado = True
    if alterado:
        config.salvar()
    return None


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
