"""Recuperação da senha da conta Master, feita só no próprio computador servidor.

Não existe recuperação pela rede nem por e-mail: quem consegue rodar este comando já
tem acesso de administrador ao servidor (a configuração do banco só abre como
administrador). Gera uma senha provisória, que a Master troca no próximo acesso;
desbloqueia a conta, encerra as sessões abertas e registra na Auditoria e nos avisos.
"""

from __future__ import annotations

import getpass
import secrets
import socket
import string
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from advoga_shared.esquemas import CATEGORIA_BACKUP

from ..core.seguranca import gerar_hash_senha
from ..models import Notificacao, Usuario
from . import auditoria
from .autenticacao import encerrar_sessoes_do_usuario

# Sem letras e números que se confundem (0/O, 1/l/I).
_LETRAS = "".join(c for c in string.ascii_letters if c not in "OlI")
_NUMEROS = "23456789"


def senha_provisoria(tamanho: int = 12) -> str:
    while True:
        s = "".join(secrets.choice(_LETRAS + _NUMEROS) for _ in range(tamanho))
        if any(c.isalpha() for c in s) and any(c.isdigit() for c in s):
            return s


def recuperar_senha_master(db: Session) -> tuple[Usuario, str]:
    master = db.scalar(select(Usuario).where(Usuario.is_master).with_for_update())
    if master is None:
        raise LookupError("Ainda não existe conta Master. Crie a conta com o código de instalação.")
    senha = senha_provisoria()
    master.senha_hash = gerar_hash_senha(senha)
    master.deve_trocar_senha = True
    master.tentativas_falhas = 0
    master.bloqueado_ate = None
    encerrar_sessoes_do_usuario(db, master.id, "senha_redefinida")
    try:
        conta_windows = getpass.getuser()
    except Exception:  # noqa: BLE001
        conta_windows = None
    detalhes = {"computador": socket.gethostname(), "conta_windows": conta_windows}
    auditoria.registrar(db, "usuario.senha_master_recuperada", entidade="usuario", entidade_id=master.id,
                        detalhes=detalhes)
    agora = datetime.now(UTC)
    db.add(Notificacao(chave=f"senha_master:{master.id}:{agora.isoformat()}", categoria=CATEGORIA_BACKUP,
                       usuario_id=master.id, titulo="A senha da conta Master foi redefinida",
                       mensagem=(f"A senha da Master foi redefinida no próprio servidor ({detalhes['computador']}) "
                                 f"em {agora.astimezone():%d/%m/%Y %H:%M}. Se não foi você, troque a senha "
                                 "imediatamente e confira a Auditoria."),
                       entidade="usuario", email_destino=None))
    db.flush()
    return master, senha
