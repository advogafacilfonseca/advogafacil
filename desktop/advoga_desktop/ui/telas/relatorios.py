"""Relatórios: escolher, filtrar, ver na tela e exportar em PDF ou Excel.

O servidor monta o relatório e o arquivo conforme as permissões de quem pede. Esta tela só
lista os relatórios liberados para a pessoa.
"""

from __future__ import annotations

import calendar
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QDesktopServices
from PySide6.QtCore import QUrl
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QComboBox,
    QFileDialog,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from advoga_shared.esquemas import SITUACOES_RELATORIO, Relatorio

from ...api_client.cliente import ClienteAPI, ErroAPI
from ..componentes.basicos import bloco_campo, campo, rotulo
from ..componentes.formatos import data_br, data_hora_br, dinheiro_br, ler_data_br
from ..componentes.seletores import SeletorCliente

# Período padrão de cada relatório: "mes" (mês atual) ou vazio (todos os registros).
PERIODO_PADRAO = {"audiencias": "mes", "prazos": "mes", "parcelas": "mes", "recebimentos": "mes", "despesas": "mes",
                  "resultado_financeiro": "mes"}
SEM_FILTROS_EXTRAS = {"resultado_financeiro"}


def texto_celula(valor, tipo: str) -> str:
    if valor is None or valor == "":
        return ""
    if tipo == "valor":
        return dinheiro_br(Decimal(str(valor)))
    if tipo in ("data", "data_hora") and isinstance(valor, str):
        try:
            if "T" in valor:
                return data_hora_br(datetime.fromisoformat(valor))
            return data_br(date.fromisoformat(valor))
        except ValueError:
            return valor
    return str(valor)


class TelaRelatorios(QWidget):
    def __init__(self, api: ClienteAPI) -> None:
        super().__init__()
        self.api = api
        self.relatorio: Relatorio | None = None
        lay = QVBoxLayout(self)
        lay.setContentsMargins(28, 24, 28, 20)
        lay.setSpacing(12)
        lay.addWidget(rotulo("Relatórios", "titulo"))
        lay.addWidget(rotulo("Escolha o relatório e os filtros. Você pode ver na tela e exportar em PDF ou Excel.",
                             "subtitulo", True))

        grade = QGridLayout()
        grade.setHorizontalSpacing(12)
        self.tipo = QComboBox()
        self.tipo.setMinimumHeight(36)
        try:
            for chave, nome in api.relatorios_disponiveis().items():
                self.tipo.addItem(nome, chave)
        except ErroAPI:
            pass
        self.inicio = campo("dd/mm/aaaa", maximo=10)
        self.fim = campo("dd/mm/aaaa", maximo=10)
        self.responsavel = QComboBox()
        self.responsavel.setMinimumHeight(36)
        self.responsavel.addItem("Todos", None)
        try:
            for u in api.usuarios_ativos():
                self.responsavel.addItem(u.nome, str(u.id))
        except ErroAPI:
            pass
        self.cliente = SeletorCliente(api)
        self.btn_limpar_cliente = QPushButton("Todos")
        self.btn_limpar_cliente.setToolTip("Remover o filtro de cliente")
        self.btn_limpar_cliente.clicked.connect(self.cliente.limpar)
        caixa_cliente = QWidget()
        caixa_cliente.setObjectName("bloco")
        lc = QHBoxLayout(caixa_cliente)
        lc.setContentsMargins(0, 0, 0, 0)
        lc.addWidget(self.cliente, 1)
        lc.addWidget(self.btn_limpar_cliente)
        self.situacao = QComboBox()
        self.situacao.setMinimumHeight(36)
        grade.addWidget(bloco_campo("Relatório", self.tipo), 0, 0)
        grade.addWidget(bloco_campo("De", self.inicio), 0, 1)
        grade.addWidget(bloco_campo("Até", self.fim), 0, 2)
        grade.addWidget(bloco_campo("Situação", self.situacao), 0, 3)
        self.bloco_resp = bloco_campo("Responsável", self.responsavel)
        self.bloco_cliente = bloco_campo("Cliente", caixa_cliente)
        grade.addWidget(self.bloco_resp, 1, 0)
        grade.addWidget(self.bloco_cliente, 1, 1, 1, 3)
        grade.setColumnStretch(0, 2)
        grade.setColumnStretch(3, 2)
        lay.addLayout(grade)

        botoes = QHBoxLayout()
        self.btn_gerar = QPushButton("Gerar relatório")
        self.btn_gerar.setObjectName("primario")
        self.btn_gerar.clicked.connect(self.gerar)
        self.btn_pdf = QPushButton("Exportar PDF")
        self.btn_pdf.clicked.connect(lambda: self.exportar("pdf"))
        self.btn_excel = QPushButton("Exportar Excel")
        self.btn_excel.clicked.connect(lambda: self.exportar("xlsx"))
        botoes.addWidget(self.btn_gerar)
        botoes.addWidget(self.btn_pdf)
        botoes.addWidget(self.btn_excel)
        botoes.addStretch()
        lay.addLayout(botoes)
        self.erro = rotulo("", "erro", True)
        self.msg = rotulo("", "sucesso", True)
        lay.addWidget(self.erro)
        lay.addWidget(self.msg)
        self.info = rotulo("", "rotuloCampo", True)
        lay.addWidget(self.info)

        self.tabela = QTableWidget(0, 0)
        self.tabela.verticalHeader().setVisible(False)
        self.tabela.setAlternatingRowColors(True)
        self.tabela.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.tabela.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        lay.addWidget(self.tabela, 1)
        self.totais = rotulo("", None, True)
        self.totais.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        lay.addWidget(self.totais)

        self.tipo.currentIndexChanged.connect(self._ao_trocar_tipo)
        self.sem_relatorios = self.tipo.count() == 0
        if self.sem_relatorios:
            self.erro.setText("Nenhum relatório liberado para você. Fale com a Advogada Master.")
            for b in (self.btn_gerar, self.btn_pdf, self.btn_excel):
                b.setEnabled(False)
        else:
            self._ao_trocar_tipo()

    # ------------------------------------------------------------------ filtros
    def _ao_trocar_tipo(self) -> None:
        tipo = self.tipo.currentData()
        self.situacao.clear()
        self.situacao.addItem("Todas", None)
        for chave, nome in SITUACOES_RELATORIO.get(tipo, {}).items():
            self.situacao.addItem(nome, chave)
        self.situacao.setEnabled(self.situacao.count() > 1)
        extras = tipo not in SEM_FILTROS_EXTRAS
        self.bloco_resp.setEnabled(extras)
        self.bloco_cliente.setEnabled(extras)
        if not extras:
            self.responsavel.setCurrentIndex(0)
            self.cliente.limpar()
        hoje = date.today()
        if PERIODO_PADRAO.get(tipo) == "mes":
            self.inicio.setText(hoje.replace(day=1).strftime("%d/%m/%Y"))
            self.fim.setText(hoje.replace(day=calendar.monthrange(hoje.year, hoje.month)[1]).strftime("%d/%m/%Y"))
        else:
            self.inicio.clear()
            self.fim.clear()
        self.relatorio = None
        self.tabela.setRowCount(0)
        self.tabela.setColumnCount(0)
        self.totais.clear()
        self.info.clear()
        self.erro.clear()
        self.msg.clear()

    def filtros(self) -> dict:
        inicio, fim = ler_data_br(self.inicio.text()), ler_data_br(self.fim.text())
        if inicio and fim and fim < inicio:
            raise ValueError("A data final do período não pode ser anterior à data inicial.")
        return {"inicio": inicio.isoformat() if inicio else None, "fim": fim.isoformat() if fim else None,
                "situacao": self.situacao.currentData(), "responsavel_id": self.responsavel.currentData(),
                "cliente_id": self.cliente.cliente_id}

    # ------------------------------------------------------------------- ações
    def gerar(self) -> None:
        self.erro.clear()
        self.msg.clear()
        try:
            filtros = self.filtros()
        except ValueError as exc:
            self.erro.setText(str(exc))
            return
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            rel = self.api.relatorio(self.tipo.currentData(), **filtros)
        except ErroAPI as exc:
            self.erro.setText(exc.mensagem)
            return
        finally:
            QApplication.restoreOverrideCursor()
        self.relatorio = rel
        self._mostrar(rel)

    def _mostrar(self, rel: Relatorio) -> None:
        t = self.tabela
        t.clear()
        t.setColumnCount(len(rel.colunas))
        t.setHorizontalHeaderLabels([c.titulo for c in rel.colunas])
        t.setRowCount(len(rel.linhas))
        direita = Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        for i, linha in enumerate(rel.linhas):
            for j, (v, c) in enumerate(zip(linha, rel.colunas)):
                texto = texto_celula(v, c.tipo)
                item = QTableWidgetItem(texto)
                item.setToolTip(texto)
                if c.tipo in ("valor", "numero"):
                    item.setTextAlignment(direita)
                t.setItem(i, j, item)
        cab = t.horizontalHeader()
        for j in range(len(rel.colunas)):
            cab.setSectionResizeMode(j, QHeaderView.ResizeMode.ResizeToContents)
        if rel.colunas:
            maior = max(range(len(rel.colunas)), key=lambda j: rel.colunas[j].largura)
            cab.setSectionResizeMode(maior, QHeaderView.ResizeMode.Stretch)
        partes = ["  ·  ".join(rel.filtros)]
        if rel.observacao:
            partes.append(rel.observacao)
        if rel.confidencial:
            partes.append("Confidencial: contém informações financeiras.")
        if not rel.linhas:
            partes.append("Nenhum registro encontrado com estes filtros.")
        self.info.setText("\n".join(partes))
        self.totais.setText("&nbsp;&nbsp;&nbsp;·&nbsp;&nbsp;&nbsp;".join(
            f"{x.rotulo}: <b>{x.valor}</b>" for x in rel.totais))

    def exportar(self, formato: str) -> None:
        self.erro.clear()
        self.msg.clear()
        try:
            filtros = self.filtros()
        except ValueError as exc:
            self.erro.setText(str(exc))
            return
        tipo = self.tipo.currentData()
        ext, filtro = ("pdf", "PDF (*.pdf)") if formato == "pdf" else ("xlsx", "Planilha do Excel (*.xlsx)")
        sugestao = Path.home() / "Documents" / f"{self.tipo.currentText()} {date.today():%d-%m-%Y}.{ext}"
        if not sugestao.parent.exists():
            sugestao = Path.home() / sugestao.name
        caminho, _ = QFileDialog.getSaveFileName(self, "Salvar relatório", str(sugestao), filtro)
        if not caminho:
            return
        destino = Path(caminho)
        if destino.suffix.lower() != f".{ext}":
            destino = destino.with_name(destino.name + f".{ext}")
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            self.api.exportar_relatorio(tipo, formato, destino, **filtros)
        except ErroAPI as exc:
            self.erro.setText(exc.mensagem)
            return
        finally:
            QApplication.restoreOverrideCursor()
        self.ultimo_arquivo = destino
        self.msg.setText(f"Relatório salvo em {destino}.")
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(destino)))
