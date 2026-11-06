"""Formatos brasileiros (datas, horários)."""

from __future__ import annotations

from datetime import datetime


def data_hora_br(valor: datetime | None) -> str:
    if valor is None:
        return "—"
    return valor.astimezone().strftime("%d/%m/%Y %H:%M")


def data_br(valor: datetime | None) -> str:
    if valor is None:
        return "—"
    return valor.astimezone().strftime("%d/%m/%Y")
