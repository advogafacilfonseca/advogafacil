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


def ler_data_hora_br(texto: str) -> datetime | None:
    """Converte 'dd/mm/aaaa hh:mm' (horário deste computador) em data e hora com fuso. Vazio → None."""
    t = " ".join(texto.split())
    if not t:
        return None
    for formato in ("%d/%m/%Y %H:%M", "%d/%m/%Y"):
        try:
            return datetime.strptime(t, formato).astimezone()
        except ValueError:
            continue
    raise ValueError(f"Data e hora inválidas: {t}. Use o formato dd/mm/aaaa hh:mm.")


def tamanho_legivel(n: int) -> str:
    for unidade in ("bytes", "KB", "MB", "GB"):
        if n < 1024 or unidade == "GB":
            return f"{n} {unidade}" if unidade == "bytes" else f"{n:.1f} {unidade}".replace(".", ",")
        n /= 1024
    return str(n)
