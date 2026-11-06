"""Envio de e-mails de notificação pelo endereço oficial do escritório.

O serviço de envio (conta oficial) é configurado pela Master na tela de Notificações. Enquanto
não houver serviço configurado, os avisos continuam aparecendo no aplicativo e o histórico
registra "serviço de envio não configurado".
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from sqlalchemy.orm import Session


class ErroEnvio(Exception):
    """Falha ao enviar. temporaria=True: tentar de novo mais tarde (rede, servidor ocupado)."""

    def __init__(self, mensagem: str, temporaria: bool = True) -> None:
        super().__init__(mensagem)
        self.mensagem = mensagem
        self.temporaria = temporaria


@dataclass
class Mensagem:
    para: str
    assunto: str
    texto: str


class Enviador(Protocol):
    remetente: str

    def enviar(self, msg: Mensagem) -> None: ...


def obter_enviador(db: Session, cfg) -> Enviador | None:
    """Serviço de envio configurado no servidor, ou None se ainda não foi configurado."""
    from .email_google import obter

    return obter(db, cfg)
