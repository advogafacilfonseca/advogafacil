"""Contratos de dados (entrada e saída) usados pela API e pelo aplicativo."""

from __future__ import annotations

import re
import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator, model_validator

from .permissoes import Permissao

PADRAO_NOME_USUARIO = re.compile(r"^[a-z0-9._-]{3,40}$")
SENHA_MINIMO = 10


def validar_forca_senha(senha: str) -> str:
    if len(senha) < SENHA_MINIMO:
        raise ValueError(f"A senha deve ter pelo menos {SENHA_MINIMO} caracteres.")
    if len(senha) > 128:
        raise ValueError("A senha deve ter no máximo 128 caracteres.")
    if not re.search(r"[A-Za-zÀ-ÿ]", senha) or not re.search(r"\d", senha):
        raise ValueError("A senha deve conter letras e números.")
    return senha


def normalizar_nome_usuario(valor: str) -> str:
    valor = (valor or "").strip().lower()
    if not PADRAO_NOME_USUARIO.fullmatch(valor):
        raise ValueError(
            "O nome de usuário deve ter de 3 a 40 caracteres: letras minúsculas sem acento, "
            "números, ponto, hífen ou sublinhado."
        )
    return valor


class Saude(BaseModel):
    status: str
    versao: str
    banco: str
    servidor_id: uuid.UUID | None = None
    servidor_status: str | None = None
    configurado: bool


class SetupStatus(BaseModel):
    configurado: bool


class CriarMaster(BaseModel):
    codigo_instalacao: str = Field(min_length=1, max_length=64)
    nome_completo: str = Field(min_length=3, max_length=150)
    nome_usuario: str
    email: EmailStr
    senha: str
    senha_confirmacao: str

    @field_validator("nome_completo")
    @classmethod
    def _nome(cls, v: str) -> str:
        v = " ".join(v.split())
        if len(v) < 3:
            raise ValueError("Informe o nome completo.")
        return v

    @field_validator("nome_usuario")
    @classmethod
    def _usuario(cls, v: str) -> str:
        return normalizar_nome_usuario(v)

    @field_validator("senha")
    @classmethod
    def _senha(cls, v: str) -> str:
        return validar_forca_senha(v)

    @model_validator(mode="after")
    def _confere(self) -> "CriarMaster":
        if self.senha != self.senha_confirmacao:
            raise ValueError("A confirmação de senha não confere.")
        return self


class Login(BaseModel):
    nome_usuario: str = Field(min_length=1, max_length=40)
    senha: str = Field(min_length=1, max_length=128)
    dispositivo: str | None = Field(default=None, max_length=120)


class TrocarSenha(BaseModel):
    senha_atual: str = Field(min_length=1, max_length=128)
    nova_senha: str
    nova_senha_confirmacao: str

    @field_validator("nova_senha")
    @classmethod
    def _senha(cls, v: str) -> str:
        return validar_forca_senha(v)

    @model_validator(mode="after")
    def _confere(self) -> "TrocarSenha":
        if self.nova_senha != self.nova_senha_confirmacao:
            raise ValueError("A confirmação da nova senha não confere.")
        return self


class UsuarioPublico(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    nome_completo: str
    nome_exibicao: str
    nome_usuario: str
    email: str
    cargo: str | None
    is_master: bool
    ativo: bool
    permissoes: list[Permissao]


class SessaoCriada(BaseModel):
    token: str
    expira_em: datetime
    usuario: UsuarioPublico


class Mensagem(BaseModel):
    mensagem: str
