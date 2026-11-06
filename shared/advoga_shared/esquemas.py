"""Contratos de dados (entrada e saída) usados pela API e pelo aplicativo."""

from __future__ import annotations

import re
import uuid
from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator, model_validator

from .permissoes import Permissao
from .validacoes import UFS, cpf_valido, somente_digitos

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
    deve_trocar_senha: bool = False


class SessaoCriada(BaseModel):
    token: str
    expira_em: datetime
    usuario: UsuarioPublico


class Mensagem(BaseModel):
    mensagem: str


# ----------------------------------------------------------------- usuários


def _limpar(v: str | None) -> str | None:
    if v is None:
        return None
    v = " ".join(v.split())
    return v or None


class UsuarioCriar(BaseModel):
    nome_completo: str = Field(min_length=3, max_length=150)
    nome_exibicao: str | None = Field(default=None, max_length=80)
    cargo: str | None = Field(default=None, max_length=80)
    nome_usuario: str
    email: EmailStr
    senha_provisoria: str
    permissoes: list[Permissao] = Field(default_factory=list)

    _nomes = field_validator("nome_completo", "nome_exibicao", "cargo")(classmethod(lambda cls, v: _limpar(v)))

    @field_validator("nome_usuario")
    @classmethod
    def _usuario(cls, v: str) -> str:
        return normalizar_nome_usuario(v)

    @field_validator("senha_provisoria")
    @classmethod
    def _senha(cls, v: str) -> str:
        return validar_forca_senha(v)


class UsuarioAtualizar(BaseModel):
    nome_completo: str | None = Field(default=None, min_length=3, max_length=150)
    nome_exibicao: str | None = Field(default=None, min_length=1, max_length=80)
    cargo: str | None = Field(default=None, max_length=80)
    email: EmailStr | None = None

    _nomes = field_validator("nome_completo", "nome_exibicao", "cargo")(classmethod(lambda cls, v: _limpar(v)))


class PermissoesDefinir(BaseModel):
    permissoes: list[Permissao]


class RedefinirSenha(BaseModel):
    senha_provisoria: str

    @field_validator("senha_provisoria")
    @classmethod
    def _senha(cls, v: str) -> str:
        return validar_forca_senha(v)


class UsuarioDetalhe(UsuarioPublico):
    deve_trocar_senha: bool
    criado_em: datetime
    ultimo_login_em: datetime | None
    desativado_em: datetime | None
    sessoes_ativas: int


# ---------------------------------------------------------------- auditoria


class ItemAuditoria(BaseModel):
    id: int
    ocorrido_em: datetime
    usuario_id: uuid.UUID | None
    usuario_nome: str | None
    acao: str
    entidade: str | None
    entidade_id: str | None
    detalhes: dict | None
    ip: str | None


class PaginaAuditoria(BaseModel):
    itens: list[ItemAuditoria]
    total: int
    pagina: int
    por_pagina: int


# ----------------------------------------------------------------- clientes

class _ClienteBase(BaseModel):
    nome_completo: str | None = Field(default=None, max_length=150)
    cpf: str | None = Field(default=None, max_length=20)
    rg: str | None = Field(default=None, max_length=30)
    data_nascimento: date | None = None
    telefone_principal: str | None = Field(default=None, max_length=20)
    telefone_secundario: str | None = Field(default=None, max_length=20)
    email: EmailStr | None = None
    cep: str | None = Field(default=None, max_length=10)
    logradouro: str | None = Field(default=None, max_length=200)
    numero: str | None = Field(default=None, max_length=20)
    complemento: str | None = Field(default=None, max_length=100)
    bairro: str | None = Field(default=None, max_length=100)
    cidade: str | None = Field(default=None, max_length=100)
    uf: str | None = Field(default=None, max_length=2)
    observacoes: str | None = Field(default=None, max_length=5000)
    data_inicio_atendimento: date | None = None
    advogado_responsavel_id: uuid.UUID | None = None

    @field_validator("nome_completo", "rg", "logradouro", "numero", "complemento", "bairro", "cidade")
    @classmethod
    def _texto(cls, v: str | None) -> str | None:
        return _limpar(v)

    @field_validator("observacoes")
    @classmethod
    def _obs(cls, v: str | None) -> str | None:
        v = (v or "").strip()
        return v or None

    @field_validator("cpf")
    @classmethod
    def _cpf(cls, v: str | None) -> str | None:
        d = somente_digitos(v)
        if not d:
            return None
        if not cpf_valido(d):
            raise ValueError("CPF inválido. Confira os números digitados.")
        return d

    @field_validator("telefone_principal", "telefone_secundario")
    @classmethod
    def _tel(cls, v: str | None) -> str | None:
        d = somente_digitos(v)
        if not d:
            return None
        if len(d) not in (10, 11):
            raise ValueError("Telefone inválido. Informe DDD e número (10 ou 11 dígitos).")
        return d

    @field_validator("cep")
    @classmethod
    def _cep(cls, v: str | None) -> str | None:
        d = somente_digitos(v)
        if not d:
            return None
        if len(d) != 8:
            raise ValueError("CEP inválido. Informe 8 dígitos.")
        return d

    @field_validator("uf")
    @classmethod
    def _uf(cls, v: str | None) -> str | None:
        v = (v or "").strip().upper()
        if not v:
            return None
        if v not in UFS:
            raise ValueError("UF inválida.")
        return v

    @field_validator("data_nascimento")
    @classmethod
    def _nasc(cls, v: date | None) -> date | None:
        if v and (v > date.today() or v.year < 1900):
            raise ValueError("Data de nascimento inválida.")
        return v


class ClienteCriar(_ClienteBase):
    nome_completo: str = Field(min_length=3, max_length=150)
    # Quando já existe cliente com o mesmo nome e nascimento (sem CPF), o servidor pede confirmação.
    confirmar_possivel_duplicidade: bool = False


class ClienteAtualizar(_ClienteBase):
    versao: int


class ClienteEncerrar(BaseModel):
    motivo: str = Field(min_length=3, max_length=500)
    versao: int


class Cliente(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    nome_completo: str
    cpf: str | None
    rg: str | None
    data_nascimento: date | None
    telefone_principal: str | None
    telefone_secundario: str | None
    email: str | None
    cep: str | None
    logradouro: str | None
    numero: str | None
    complemento: str | None
    bairro: str | None
    cidade: str | None
    uf: str | None
    observacoes: str | None
    data_inicio_atendimento: date | None
    advogado_responsavel_id: uuid.UUID | None
    advogado_responsavel_nome: str | None = None
    situacao: str
    encerrado_em: datetime | None
    motivo_encerramento: str | None
    criado_em: datetime
    atualizado_em: datetime
    versao: int


class ClienteResumo(BaseModel):
    id: uuid.UUID
    nome_completo: str
    cpf: str | None
    telefone_principal: str | None
    cidade: str | None
    uf: str | None
    situacao: str
    advogado_responsavel_nome: str | None = None


class PaginaClientes(BaseModel):
    itens: list[ClienteResumo]
    total: int
    pagina: int
    por_pagina: int


class ResultadoPesquisa(BaseModel):
    tipo: str  # "cliente" (processos e outros registros entram nas próximas etapas)
    id: uuid.UUID
    titulo: str
    resumo: str


class PaginaPesquisa(BaseModel):
    termo: str
    itens: list[ResultadoPesquisa]
    total: int
    pagina: int
    por_pagina: int


class OpcaoUsuario(BaseModel):
    id: uuid.UUID
    nome: str
