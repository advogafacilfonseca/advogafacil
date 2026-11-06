"""Localiza arquivos de recursos tanto no código-fonte quanto no executável empacotado."""

from __future__ import annotations

import sys
from pathlib import Path


def caminho_recurso(nome: str) -> Path:
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent))
    candidato = base / "advoga_desktop" / "recursos" / nome
    if candidato.exists():
        return candidato
    return Path(__file__).resolve().parent / "recursos" / nome
