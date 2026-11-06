"""Validações brasileiras (CPF, telefone, CEP, UF)."""

from __future__ import annotations

import re

UFS = {"AC", "AL", "AP", "AM", "BA", "CE", "DF", "ES", "GO", "MA", "MT", "MS", "MG", "PA", "PB",
       "PR", "PE", "PI", "RJ", "RN", "RS", "RO", "RR", "SC", "SP", "SE", "TO"}


def somente_digitos(valor: str | None) -> str:
    return re.sub(r"\D", "", valor or "")


def cpf_valido(cpf: str) -> bool:
    d = somente_digitos(cpf)
    if len(d) != 11 or d == d[0] * 11:
        return False
    for n in (9, 10):
        soma = sum(int(d[i]) * (n + 1 - i) for i in range(n))
        dig = (soma * 10) % 11 % 10
        if dig != int(d[n]):
            return False
    return True


def formatar_cpf(cpf: str | None) -> str:
    d = somente_digitos(cpf)
    return f"{d[:3]}.{d[3:6]}.{d[6:9]}-{d[9:]}" if len(d) == 11 else (cpf or "")


def formatar_telefone(tel: str | None) -> str:
    d = somente_digitos(tel)
    if len(d) == 11:
        return f"({d[:2]}) {d[2:7]}-{d[7:]}"
    if len(d) == 10:
        return f"({d[:2]}) {d[2:6]}-{d[6:]}"
    return tel or ""


def formatar_cep(cep: str | None) -> str:
    d = somente_digitos(cep)
    return f"{d[:5]}-{d[5:]}" if len(d) == 8 else (cep or "")


def cnj_valido(numero: str | None) -> bool:
    """Número único CNJ (NNNNNNN-DD.AAAA.J.TR.OOOO), dígito verificador módulo 97 (Res. CNJ 65/2008)."""
    d = somente_digitos(numero)
    if len(d) != 20:
        return False
    base = d[:7] + d[9:] + "00"
    return int(d[7:9]) == 98 - (int(base) % 97)


def formatar_cnj(numero: str | None) -> str:
    d = somente_digitos(numero)
    if len(d) != 20:
        return numero or ""
    return f"{d[:7]}-{d[7:9]}.{d[9:13]}.{d[13]}.{d[14:16]}.{d[16:]}"


def digito_cnj(sequencial: str, ano: str, segmento: str, tribunal: str, origem: str) -> str:
    """Calcula o dígito verificador (usado para conferência e testes)."""
    return f"{98 - int(sequencial + ano + segmento + tribunal + origem + '00') % 97:02d}"
