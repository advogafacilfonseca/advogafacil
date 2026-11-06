from __future__ import annotations

from advoga_shared.esquemas import UsuarioPublico

from ..models import Usuario
from ..services.autenticacao import permissoes_efetivas


def usuario_publico(usuario: Usuario) -> UsuarioPublico:
    return UsuarioPublico(
        id=usuario.id,
        nome_completo=usuario.nome_completo,
        nome_exibicao=usuario.nome_exibicao,
        nome_usuario=usuario.nome_usuario,
        email=usuario.email,
        cargo=usuario.cargo,
        is_master=usuario.is_master,
        ativo=usuario.ativo,
        permissoes=sorted(permissoes_efetivas(usuario), key=lambda p: p.value),
    )
