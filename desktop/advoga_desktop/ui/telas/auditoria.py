"""Consulta da auditoria (somente a Master)."""

from __future__ import annotations

import json
import math

from PySide6.QtCore import QDate
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QDateEdit,
    QHBoxLayout,
    QHeaderView,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ...api_client.cliente import ClienteAPI, ErroAPI
from ..componentes.basicos import bloco_campo, rotulo
from ..componentes.espera import cursor_espera
from ..componentes.formatos import data_hora_br

ACOES = {
    "login.sucesso": "Entrada no sistema",
    "login.falha": "Tentativa de entrada recusada",
    "logout": "Saída do sistema",
    "acesso.negado": "Acesso negado",
    "setup.master_criada": "Conta Master criada",
    "setup.codigo_invalido": "Código de instalação inválido",
    "usuario.criado": "Usuário cadastrado",
    "usuario.editado": "Dados de usuário alterados",
    "usuario.permissoes_alteradas": "Permissões alteradas",
    "usuario.desativado": "Usuário desativado",
    "usuario.reativado": "Usuário reativado",
    "usuario.senha_redefinida": "Senha redefinida pela administração",
    "usuario.senha_alterada": "Senha alterada pelo próprio usuário",
}

FILTROS_ACAO = [("Todas as ações", ""), ("Entradas e saídas", "log"), ("Acessos negados", "acesso."),
                ("Usuários e permissões", "usuario."), ("Configuração inicial", "setup.")]


def resumo_detalhes(detalhes: dict | None) -> str:
    if not detalhes:
        return ""
    texto = json.dumps(detalhes, ensure_ascii=False)
    return texto if len(texto) <= 160 else texto[:157] + "..."


class TelaAuditoria(QWidget):
    POR_PAGINA = 50

    def __init__(self, api: ClienteAPI) -> None:
        super().__init__()
        self.api = api
        self.pagina = 1
        self.total = 0
        self._carregado = False
        lay = QVBoxLayout(self)
        lay.setContentsMargins(28, 24, 28, 24)
        lay.addWidget(rotulo("Auditoria", "titulo"))
        lay.addWidget(rotulo("Registro permanente das atividades. Os registros não podem ser alterados "
                             "nem apagados.", "subtitulo", True))

        filtros = QHBoxLayout()
        self.inicio = QDateEdit(QDate.currentDate().addDays(-30))
        self.fim = QDateEdit(QDate.currentDate())
        for d in (self.inicio, self.fim):
            d.setCalendarPopup(True)
            d.setDisplayFormat("dd/MM/yyyy")
        self.usuario = QComboBox()
        self.acao = QComboBox()
        for texto, valor in FILTROS_ACAO:
            self.acao.addItem(texto, valor)
        self.btn_buscar = QPushButton("Buscar")
        self.btn_buscar.setObjectName("primario")
        filtros.addWidget(bloco_campo("De", self.inicio))
        filtros.addWidget(bloco_campo("Até", self.fim))
        filtros.addWidget(bloco_campo("Usuário", self.usuario), 1)
        filtros.addWidget(bloco_campo("Ação", self.acao), 1)
        filtros.addWidget(self.btn_buscar)
        lay.addLayout(filtros)

        self.tabela = QTableWidget(0, 5)
        self.tabela.setHorizontalHeaderLabels(["Data e hora", "Usuário", "Ação", "Detalhes", "Endereço"])
        self.tabela.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.tabela.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.tabela.verticalHeader().setVisible(False)
        self.tabela.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        lay.addWidget(self.tabela, 1)

        pag = QHBoxLayout()
        self.lbl_pagina = rotulo("", "rotuloCampo")
        self.btn_ant = QPushButton("Anterior")
        self.btn_prox = QPushButton("Próxima")
        pag.addWidget(self.lbl_pagina)
        pag.addStretch()
        pag.addWidget(self.btn_ant)
        pag.addWidget(self.btn_prox)
        lay.addLayout(pag)

        self.btn_buscar.clicked.connect(lambda: self.buscar(1))
        self.btn_ant.clicked.connect(lambda: self.buscar(self.pagina - 1))
        self.btn_prox.clicked.connect(lambda: self.buscar(self.pagina + 1))

    def showEvent(self, evento) -> None:  # noqa: N802
        super().showEvent(evento)
        if not self._carregado:
            self._carregado = True
            self._carregar_usuarios()
            self.buscar(1)

    def _carregar_usuarios(self) -> None:
        self.usuario.clear()
        self.usuario.addItem("Todos os usuários", "")
        try:
            for u in self.api.listar_usuarios():
                self.usuario.addItem(u.nome_completo, str(u.id))
        except ErroAPI:
            pass  # o filtro por usuário fica só com "Todos"; a busca continua funcionando

    def buscar(self, pagina: int) -> None:
        if self.inicio.date() > self.fim.date():
            QMessageBox.warning(self, "Auditoria", "A data inicial é posterior à data final.")
            return
        try:
            with cursor_espera():
                r = self.api.auditoria(
                    inicio=self.inicio.date().toString("yyyy-MM-dd"),
                    fim=self.fim.date().toString("yyyy-MM-dd"),
                    usuario_id=self.usuario.currentData(), acao=self.acao.currentData(),
                    pagina=pagina, por_pagina=self.POR_PAGINA)
        except ErroAPI as exc:
            QMessageBox.warning(self, "Auditoria", exc.mensagem)
            return
        self.pagina, self.total = r.pagina, r.total
        self.tabela.setRowCount(len(r.itens))
        for i, a in enumerate(r.itens):
            valores = [data_hora_br(a.ocorrido_em), a.usuario_nome or "—", ACOES.get(a.acao, a.acao),
                       resumo_detalhes(a.detalhes), a.ip or ""]
            for j, v in enumerate(valores):
                self.tabela.setItem(i, j, QTableWidgetItem(v))
        self.tabela.resizeColumnsToContents()
        self.tabela.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        paginas = max(1, math.ceil(self.total / self.POR_PAGINA))
        self.lbl_pagina.setText(f"{self.total} registro(s)  ·  Página {self.pagina} de {paginas}")
        self.btn_ant.setEnabled(self.pagina > 1)
        self.btn_prox.setEnabled(self.pagina < paginas)
