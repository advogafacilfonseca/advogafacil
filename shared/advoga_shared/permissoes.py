"""Lista oficial de permissões do Advoga Fácil.

A permissão é sempre verificada no servidor. O nome ou o cargo exibido de um
usuário nunca concede permissão alguma.
"""

from enum import StrEnum


class Permissao(StrEnum):
    CLIENTES = "clientes"
    PROCESSOS = "processos"
    CONTRATOS = "contratos"
    FINANCEIRO = "financeiro"
    AGENDA = "agenda"
    DOCUMENTOS = "documentos"
    PENDENCIAS = "pendencias"
    NOTIFICACOES = "notificacoes"
    ADMIN_USUARIOS = "admin_usuarios"
    CONFIGURACOES = "configuracoes"


ROTULOS_PERMISSAO: dict[Permissao, str] = {
    Permissao.CLIENTES: "Acesso aos clientes",
    Permissao.PROCESSOS: "Acesso aos processos",
    Permissao.CONTRATOS: "Acesso aos contratos",
    Permissao.FINANCEIRO: "Acesso ao financeiro",
    Permissao.AGENDA: "Acesso à agenda",
    Permissao.DOCUMENTOS: "Acesso aos documentos",
    Permissao.PENDENCIAS: "Acesso às pendências",
    Permissao.NOTIFICACOES: "Recebimento de notificações",
    Permissao.ADMIN_USUARIOS: "Administração de usuários",
    Permissao.CONFIGURACOES: "Configurações do sistema",
}

TODAS_AS_PERMISSOES: frozenset[Permissao] = frozenset(Permissao)
