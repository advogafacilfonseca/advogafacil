"""Formatos brasileiros (datas, horários, documentos)."""

from __future__ import annotations

from datetime import date, datetime

from advoga_shared.validacoes import formatar_cep, formatar_cpf, formatar_telefone  # noqa: F401 (reexportados)


def data_hora_br(valor: datetime | None) -> str:
    if valor is None:
        return "—"
    return valor.astimezone().strftime("%d/%m/%Y %H:%M")


def data_br(valor: datetime | date | None) -> str:
    if valor is None:
        return "—"
    if isinstance(valor, datetime):
        valor = valor.astimezone()
    return valor.strftime("%d/%m/%Y")


def ler_data_br(texto: str) -> date | None:
    """Converte 'dd/mm/aaaa' em data. Vazio → None. Formato inválido → ValueError."""
    t = texto.strip()
    if not t.replace("/", "").replace("_", "").strip():
        return None
    try:
        return datetime.strptime(t, "%d/%m/%Y").date()
    except ValueError:
        raise ValueError(f"Data inválida: {t}. Use o formato dd/mm/aaaa.") from None
