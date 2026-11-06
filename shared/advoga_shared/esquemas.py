"""Contratos de dados (entrada e saída) usados pela API e pelo aplicativo."""

from __future__ import annotations

import re
import uuid
from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator, model_validator

from .permissoes import Permissao
from .validacoes import UFS, cnj_valido, cpf_valido, somente_digitos

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


class OpcaoCliente(BaseModel):
    id: uuid.UUID
    nome: str
    situacao: str


# ------------------------------------------------------------------ processos
SITUACOES_PROCESSO = {
    "em_andamento": "Em andamento",
    "suspenso": "Suspenso",
    "arquivado": "Arquivado",
    "encerrado": "Encerrado",
}
TIPOS_PROXIMO_EVENTO = {"audiencia": "Audiência", "prazo": "Prazo"}


class _ProcessoBase(BaseModel):
    numero_cnj: str | None = Field(default=None, max_length=30)
    cliente_id: uuid.UUID | None = None
    tipo_acao: str | None = Field(default=None, max_length=150)
    area_juridica: str | None = Field(default=None, max_length=80)
    tribunal: str | None = Field(default=None, max_length=120)
    comarca: str | None = Field(default=None, max_length=120)
    vara: str | None = Field(default=None, max_length=150)
    parte_contraria: str | None = Field(default=None, max_length=300)
    advogado_responsavel_id: uuid.UUID | None = None
    data_distribuicao: date | None = None
    situacao: str | None = None
    fase_processual: str | None = Field(default=None, max_length=120)
    proximo_evento_tipo: str | None = None
    proximo_evento_em: datetime | None = None
    proximo_evento_descricao: str | None = Field(default=None, max_length=300)
    descricao: str | None = Field(default=None, max_length=10000)
    observacoes: str | None = Field(default=None, max_length=10000)

    @field_validator("tipo_acao", "area_juridica", "tribunal", "comarca", "vara", "parte_contraria",
                     "fase_processual", "proximo_evento_descricao")
    @classmethod
    def _texto(cls, v: str | None) -> str | None:
        return _limpar(v)

    @field_validator("descricao", "observacoes")
    @classmethod
    def _longo(cls, v: str | None) -> str | None:
        v = (v or "").strip()
        return v or None

    @field_validator("numero_cnj")
    @classmethod
    def _cnj(cls, v: str | None) -> str | None:
        d = somente_digitos(v)
        if not d:
            return None
        if len(d) != 20:
            raise ValueError("Número CNJ inválido. Use o formato 0000000-00.0000.0.00.0000 (20 dígitos).")
        if not cnj_valido(d):
            raise ValueError("Número CNJ inválido: o dígito verificador não confere. Confira os números.")
        return d

    @field_validator("situacao")
    @classmethod
    def _situacao(cls, v: str | None) -> str | None:
        if v is not None and v not in SITUACOES_PROCESSO:
            raise ValueError("Situação inválida.")
        return v

    @field_validator("proximo_evento_tipo")
    @classmethod
    def _evento(cls, v: str | None) -> str | None:
        if v in (None, ""):
            return None
        if v not in TIPOS_PROXIMO_EVENTO:
            raise ValueError("Tipo inválido: escolha audiência ou prazo.")
        return v

    @field_validator("data_distribuicao")
    @classmethod
    def _distribuicao(cls, v: date | None) -> date | None:
        if v and (v > date.today() or v.year < 1900):
            raise ValueError("Data de distribuição inválida.")
        return v

    @field_validator("proximo_evento_em")
    @classmethod
    def _evento_em(cls, v: datetime | None) -> datetime | None:
        if v is not None and v.tzinfo is None:
            raise ValueError("Data e hora sem fuso horário.")
        return v


class ProcessoCriar(_ProcessoBase):
    cliente_id: uuid.UUID
    situacao: str = "em_andamento"


class ProcessoAtualizar(_ProcessoBase):
    versao: int


class Processo(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    numero_cnj: str | None
    cliente_id: uuid.UUID
    cliente_nome: str | None = None
    tipo_acao: str | None
    area_juridica: str | None
    tribunal: str | None
    comarca: str | None
    vara: str | None
    parte_contraria: str | None
    advogado_responsavel_id: uuid.UUID | None
    advogado_responsavel_nome: str | None = None
    data_distribuicao: date | None
    situacao: str
    fase_processual: str | None
    proximo_evento_tipo: str | None
    proximo_evento_em: datetime | None
    proximo_evento_descricao: str | None
    descricao: str | None
    observacoes: str | None
    criado_em: datetime
    atualizado_em: datetime
    versao: int


class ProcessoResumo(BaseModel):
    id: uuid.UUID
    numero_cnj: str | None
    cliente_id: uuid.UUID
    cliente_nome: str
    tipo_acao: str | None
    parte_contraria: str | None
    situacao: str
    fase_processual: str | None
    proximo_evento_tipo: str | None
    proximo_evento_em: datetime | None
    advogado_responsavel_nome: str | None = None


class PaginaProcessos(BaseModel):
    itens: list[ProcessoResumo]
    total: int
    pagina: int
    por_pagina: int


class OpcaoProcesso(BaseModel):
    id: uuid.UUID
    rotulo: str


class MovimentacaoCriar(BaseModel):
    data_movimentacao: date
    descricao: str = Field(min_length=3, max_length=5000)

    @field_validator("descricao")
    @classmethod
    def _desc(cls, v: str) -> str:
        v = v.strip()
        if len(v) < 3:
            raise ValueError("Descreva a movimentação.")
        return v

    @field_validator("data_movimentacao")
    @classmethod
    def _data(cls, v: date) -> date:
        if v.year < 1900 or v > date.today().replace(year=date.today().year + 5):
            raise ValueError("Data da movimentação inválida.")
        return v


class Movimentacao(BaseModel):
    id: int
    processo_id: uuid.UUID
    data_movimentacao: date
    descricao: str
    registrado_por_nome: str | None
    registrado_em: datetime


# ----------------------------------------------------------------- documentos
class Documento(BaseModel):
    id: uuid.UUID
    cliente_id: uuid.UUID
    cliente_nome: str | None = None
    processo_id: uuid.UUID | None
    processo_rotulo: str | None = None
    nome_arquivo: str
    descricao: str | None
    tipo_conteudo: str | None
    tamanho: int
    sha256: str
    enviado_por_nome: str | None = None
    criado_em: datetime
    removido_em: datetime | None = None
    removido_por_nome: str | None = None
    motivo_remocao: str | None = None
    versao: int


class DocumentoAtualizar(BaseModel):
    versao: int
    nome_arquivo: str | None = Field(default=None, min_length=1, max_length=255)
    descricao: str | None = Field(default=None, max_length=500)
    processo_id: uuid.UUID | None = None

    @field_validator("nome_arquivo")
    @classmethod
    def _nome(cls, v: str | None) -> str | None:
        return _limpar(v)


class DocumentoRemover(BaseModel):
    versao: int
    motivo: str = Field(min_length=3, max_length=500)


class PaginaDocumentos(BaseModel):
    itens: list[Documento]
    total: int
    pagina: int
    por_pagina: int


# ------------------------------------------------------------------ contratos e financeiro
# Valores em reais com 2 casas decimais (Decimal: nunca ponto flutuante para dinheiro).

SITUACOES_CONTRATO = {"ativo": "Ativo", "quitado": "Quitado", "cancelado": "Cancelado"}
SITUACOES_PARCELA = {"aberta": "Em aberto", "paga": "Paga", "cancelada": "Cancelada", "renegociada": "Renegociada"}
FORMAS_PAGAMENTO = {
    "pix": "Pix", "dinheiro": "Dinheiro", "transferencia": "Transferência", "boleto": "Boleto",
    "cartao_credito": "Cartão de crédito", "cartao_debito": "Cartão de débito", "cheque": "Cheque", "outro": "Outro",
}
CATEGORIAS_DESPESA = {
    "combustivel": "Combustível", "estacionamento": "Estacionamento", "alimentacao": "Alimentação",
    "transporte": "Transporte", "materiais": "Materiais", "administrativas": "Despesas administrativas",
    "custas": "Custas e taxas", "outras": "Outras",
}


class ParcelaPlano(BaseModel):
    """Parcela informada manualmente (vencimentos e valores personalizados)."""
    valor: Decimal = Field(gt=0, max_digits=14, decimal_places=2)
    vencimento: date


class ContratoCriar(BaseModel):
    cliente_id: uuid.UUID
    processo_id: uuid.UUID | None = None
    servico_contratado: str = Field(min_length=3, max_length=300)
    advogado_responsavel_id: uuid.UUID | None = None
    data_inicio: date
    valor_total: Decimal = Field(gt=0, max_digits=14, decimal_places=2)
    valor_entrada: Decimal = Field(default=Decimal("0"), ge=0, max_digits=14, decimal_places=2)
    vencimento_entrada: date | None = None
    quantidade_parcelas: int | None = Field(default=None, ge=0, le=360)
    valor_parcela: Decimal | None = Field(default=None, gt=0, max_digits=14, decimal_places=2)
    primeiro_vencimento: date | None = None
    dia_vencimento: int | None = Field(default=None, ge=1, le=31)
    parcelas_personalizadas: list[ParcelaPlano] | None = Field(default=None, max_length=360)
    observacoes: str | None = Field(default=None, max_length=5000)

    @field_validator("servico_contratado")
    @classmethod
    def _servico(cls, v: str) -> str:
        v = _limpar(v) or ""
        if len(v) < 3:
            raise ValueError("Informe o serviço contratado.")
        return v

    @field_validator("observacoes")
    @classmethod
    def _obs(cls, v: str | None) -> str | None:
        return (v or "").strip() or None


class ContratoAtualizar(BaseModel):
    """Somente dados não financeiros. Valores mudam por renegociação ou cancelamento (registrados)."""
    versao: int
    servico_contratado: str | None = Field(default=None, min_length=3, max_length=300)
    advogado_responsavel_id: uuid.UUID | None = None
    processo_id: uuid.UUID | None = None
    data_inicio: date | None = None
    observacoes: str | None = Field(default=None, max_length=5000)


class Parcela(BaseModel):
    id: uuid.UUID
    contrato_id: uuid.UUID
    numero: int
    tipo: str  # entrada | parcela
    valor: Decimal
    vencimento: date
    situacao: str
    valor_pago: Decimal
    valor_restante: Decimal
    valor_baixado: Decimal  # cancelado ou transferido na renegociação
    atrasada: bool
    cliente_id: uuid.UUID | None = None
    cliente_nome: str | None = None
    servico_contratado: str | None = None
    versao: int


class TotaisContrato(BaseModel):
    contratado: Decimal
    recebido: Decimal
    a_receber: Decimal
    vencido: Decimal
    cancelado: Decimal


class Contrato(BaseModel):
    id: uuid.UUID
    cliente_id: uuid.UUID
    cliente_nome: str | None = None
    processo_id: uuid.UUID | None
    processo_rotulo: str | None = None
    servico_contratado: str
    advogado_responsavel_id: uuid.UUID | None
    advogado_responsavel_nome: str | None = None
    data_inicio: date
    observacoes: str | None
    situacao: str
    motivo_cancelamento: str | None
    criado_em: datetime
    versao: int
    # Somente para quem tem a permissão "Financeiro" (os demais recebem vazio):
    financeiro_visivel: bool = False
    totais: TotaisContrato | None = None
    parcelas: list[Parcela] | None = None


class PaginaContratos(BaseModel):
    itens: list[Contrato]
    total: int
    pagina: int
    por_pagina: int


class ContratoCancelar(BaseModel):
    versao: int
    motivo: str = Field(min_length=3, max_length=500)


class ParcelaCancelar(BaseModel):
    versao: int
    motivo: str = Field(min_length=3, max_length=500)


class Renegociar(BaseModel):
    versao: int  # versão do contrato
    parcelas_ids: list[uuid.UUID] = Field(min_length=1)
    novo_valor: Decimal = Field(gt=0, max_digits=14, decimal_places=2)
    quantidade_parcelas: int | None = Field(default=None, ge=1, le=360)
    primeiro_vencimento: date | None = None
    dia_vencimento: int | None = Field(default=None, ge=1, le=31)
    parcelas_personalizadas: list[ParcelaPlano] | None = Field(default=None, max_length=360)
    motivo: str = Field(min_length=3, max_length=500)


class PagamentoCriar(BaseModel):
    parcela_id: uuid.UUID
    valor: Decimal = Field(gt=0, max_digits=14, decimal_places=2)
    data_recebimento: date
    forma_pagamento: str
    observacoes: str | None = Field(default=None, max_length=2000)
    comprovante_id: uuid.UUID | None = None

    @field_validator("forma_pagamento")
    @classmethod
    def _forma(cls, v: str) -> str:
        if v not in FORMAS_PAGAMENTO:
            raise ValueError("Forma de pagamento inválida.")
        return v

    @field_validator("data_recebimento")
    @classmethod
    def _data(cls, v: date) -> date:
        if v > date.today() or v.year < 2000:
            raise ValueError("Data de recebimento inválida (não pode ser futura).")
        return v


class Pagamento(BaseModel):
    id: uuid.UUID
    parcela_id: uuid.UUID
    parcela_numero: int
    contrato_id: uuid.UUID
    cliente_id: uuid.UUID
    cliente_nome: str | None = None
    valor: Decimal
    data_recebimento: date
    forma_pagamento: str
    observacoes: str | None
    comprovante_id: uuid.UUID | None
    comprovante_nome: str | None = None
    registrado_por_nome: str | None
    registrado_em: datetime
    estornado_em: datetime | None
    estornado_por_nome: str | None = None
    motivo_estorno: str | None


class PagamentoEstornar(BaseModel):
    motivo: str = Field(min_length=3, max_length=500)


class DespesaCriar(BaseModel):
    descricao: str = Field(min_length=3, max_length=300)
    categoria: str
    valor: Decimal = Field(gt=0, max_digits=14, decimal_places=2)
    data: date
    responsavel_id: uuid.UUID | None = None
    cliente_id: uuid.UUID | None = None
    processo_id: uuid.UUID | None = None
    comprovante_id: uuid.UUID | None = None
    observacoes: str | None = Field(default=None, max_length=2000)

    @field_validator("categoria")
    @classmethod
    def _cat(cls, v: str) -> str:
        if v not in CATEGORIAS_DESPESA:
            raise ValueError("Categoria inválida.")
        return v

    @field_validator("descricao")
    @classmethod
    def _desc(cls, v: str) -> str:
        v = _limpar(v) or ""
        if len(v) < 3:
            raise ValueError("Descreva a despesa.")
        return v


class DespesaAtualizar(BaseModel):
    versao: int
    descricao: str | None = Field(default=None, min_length=3, max_length=300)
    categoria: str | None = None
    valor: Decimal | None = Field(default=None, gt=0, max_digits=14, decimal_places=2)
    data: date | None = None
    responsavel_id: uuid.UUID | None = None
    cliente_id: uuid.UUID | None = None
    processo_id: uuid.UUID | None = None
    comprovante_id: uuid.UUID | None = None
    observacoes: str | None = Field(default=None, max_length=2000)

    @field_validator("categoria")
    @classmethod
    def _cat(cls, v: str | None) -> str | None:
        if v is not None and v not in CATEGORIAS_DESPESA:
            raise ValueError("Categoria inválida.")
        return v


class Despesa(BaseModel):
    id: uuid.UUID
    descricao: str
    categoria: str
    valor: Decimal
    data: date
    responsavel_id: uuid.UUID | None
    responsavel_nome: str | None = None
    cliente_id: uuid.UUID | None
    cliente_nome: str | None = None
    processo_id: uuid.UUID | None
    processo_rotulo: str | None = None
    comprovante_id: uuid.UUID | None
    comprovante_nome: str | None = None
    observacoes: str | None
    cancelada_em: datetime | None
    motivo_cancelamento: str | None
    registrado_por_nome: str | None = None
    criado_em: datetime
    versao: int


class DespesaCancelar(BaseModel):
    versao: int
    motivo: str = Field(min_length=3, max_length=500)


class Comprovante(BaseModel):
    id: uuid.UUID
    nome_arquivo: str
    tamanho: int
    sha256: str


class AvisoFinanceiro(BaseModel):
    tipo: str  # amanha | hoje | atrasada
    titulo: str
    parcela: Parcela


class ResumoFinanceiro(BaseModel):
    inicio: date
    fim: date
    total_contratado: Decimal          # contratos vigentes (ativos e quitados)
    total_recebido: Decimal            # tudo que já entrou
    total_a_receber: Decimal           # parcelas em aberto (inclui atrasadas)
    total_vencido: Decimal             # parte do "a receber" já vencida
    parcelas_vencidas: int
    parcelas_a_vencer: int
    recebido_no_periodo: Decimal
    previsto_no_periodo: Decimal       # parcelas com vencimento no período (restante a receber)
    despesas_no_periodo: Decimal
    saldo_liquido_periodo: Decimal     # recebido no período − despesas no período
    despesas_por_categoria: dict[str, Decimal]
    avisos: list[AvisoFinanceiro]
