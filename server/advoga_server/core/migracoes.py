"""Aplica as migrações do banco (Alembic) a partir do próprio pacote."""

from __future__ import annotations

from pathlib import Path

from alembic import command
from alembic.config import Config

_INI = Path(__file__).resolve().parent.parent / "alembic.ini"


def config_alembic(url: str) -> Config:
    cfg = Config(str(_INI))
    cfg.set_main_option("script_location", str(_INI.parent / "alembic"))
    cfg.attributes["url"] = url
    return cfg


def atualizar_banco(url: str) -> None:
    command.upgrade(config_alembic(url), "head")
