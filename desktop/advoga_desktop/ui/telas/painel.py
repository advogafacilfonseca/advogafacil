"""Painel inicial.

Nesta etapa mostra apenas informações reais já disponíveis (usuário, permissões e
estado do servidor). Os indicadores de clientes, processos, agenda, prazos e
financeiro são adicionados conforme cada módulo é implementado.
"""

from __future__ import annotations

from datetime import datetime

from PySide6.QtWidgets import QGridLayout, QLabel, QVBoxLayout, QWidget

from advoga_shared.permissoes import ROTULOS_PERMISSAO

from ...api_client.cliente import ClienteAPI
from ..componentes.basicos import cartao, rotulo

_DIAS = ["segunda-feira", "terça-feira", "quarta-feira", "quinta-feira", "sexta-feira", "sábado", "domingo"]
_MESES = ["janeiro", "fevereiro", "março", "abril", "maio", "junho", "julho", "agosto",
          "setembro", "outubro", "novembro", "dezembro"]


def data_por_extenso(d: datetime) -> str:
    return f"{_DIAS[d.weekday()]}, {d.day} de {_MESES[d.month - 1]} de {d.year}"


def saudacao(d: datetime) -> str:
    if d.hour < 12:
        return "Bom dia"
    if d.hour < 18:
        return "Boa tarde"
    return "Boa noite"


class TelaPainel(QWidget):
    def __init__(self, api: ClienteAPI) -> None:
        super().__init__()
        u = api.usuario
        assert u is not None
        agora = datetime.now()
        lay = QVBoxLayout(self)
        lay.setContentsMargins(32, 28, 32, 28)
        lay.setSpacing(16)
        lay.addWidget(rotulo(f"{saudacao(agora)}, {u.nome_exibicao}", "titulo"))
        lay.addWidget(rotulo(data_por_extenso(agora).capitalize(), "subtitulo"))

        grade = QGridLayout()
        grade.setSpacing(16)

        c1 = cartao()
        l1 = QVBoxLayout(c1)
        l1.setContentsMargins(20, 16, 20, 16)
        l1.addWidget(rotulo("Minha conta", "secao"))
        l1.addWidget(QLabel(u.nome_completo))
        l1.addWidget(rotulo(f"Usuário: {u.nome_usuario}  ·  Cargo: {u.cargo or '—'}", "rotuloCampo"))
        if u.is_master:
            l1.addWidget(rotulo("Advogada Master: acesso total e administração do sistema.", "rotuloCampo"))
        l1.addStretch()
        grade.addWidget(c1, 0, 0)

        c2 = cartao()
        l2 = QVBoxLayout(c2)
        l2.setContentsMargins(20, 16, 20, 16)
        l2.addWidget(rotulo("Meus acessos", "secao"))
        if u.permissoes:
            for p in u.permissoes:
                l2.addWidget(rotulo(f"✓  {ROTULOS_PERMISSAO[p]}", "rotuloCampo"))
        else:
            l2.addWidget(rotulo("Nenhum acesso liberado ainda. Fale com a Advogada Master.", "rotuloCampo", True))
        l2.addStretch()
        grade.addWidget(c2, 0, 1)

        lay.addLayout(grade)
        lay.addStretch()
