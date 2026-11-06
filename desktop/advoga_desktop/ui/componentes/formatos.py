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


def dinheiro_br(valor) -> str:
    """Decimal → 'R$ 1.234,56'."""
    from decimal import Decimal

    v = Decimal(valor or 0)
    texto = f"{abs(v):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return f"{'-' if v < 0 else ''}R$ {texto}"


def ler_dinheiro_br(texto: str):
    """'1.234,56', 'R$ 1234,5' ou '1234.56' → Decimal com 2 casas. Vazio → None."""
    import re
    from decimal import Decimal, InvalidOperation

    t = (texto or "").replace("R$", "").replace(" ", "").strip()
    if not t:
        return None
    if "," in t:
        t = t.replace(".", "").replace(",", ".")
    elif re.fullmatch(r"\d{1,3}(\.\d{3})+", t):
        t = t.replace(".", "")
    try:
        v = Decimal(t)
    except InvalidOperation:
        raise ValueError(f"Valor inválido: {texto}. Use o formato 1.234,56.") from None
    if v != v.quantize(Decimal("0.01")):
        raise ValueError(f"Valor inválido: {texto}. Use no máximo 2 casas decimais.")
    return v.quantize(Decimal("0.01"))
