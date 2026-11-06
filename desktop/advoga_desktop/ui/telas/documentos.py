"""Documentos: anexar, abrir, salvar cópia, renomear, vincular a processo e remover (com motivo).
A Master também vê os documentos removidos e pode restaurá-los."""

from __future__ import annotations

import os
import shutil
import uuid
from pathlib import Path

from PySide6.QtCore import Qt, QTimer, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QHeaderView,
    QInputDialog,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from advoga_shared.esquemas import Documento

from ...api_client.cliente import ClienteAPI, ErroAPI
from ..componentes.basicos import ajustar_altura, bloco_campo, campo, rotulo
from ..componentes.espera import cursor_espera
from ..componentes.formatos import data_hora_br, tamanho_legivel
from ..componentes.seletores import SeletorCliente


PASTA_OVERRIDE: Path | None = None  # testes: pasta temporária, sem alterar o ambiente do processo


def pasta_visualizacao() -> Path:
    """Cópias abertas para leitura neste computador. São apagadas ao entrar e ao sair do sistema;
    o documento original permanece somente no servidor."""
    if PASTA_OVERRIDE is not None:
        return PASTA_OVERRIDE / "AdvogaFacil" / "abertos"
    base = os.environ.get("LOCALAPPDATA") or os.environ.get("XDG_CACHE_HOME") or str(Path.home() / ".cache")
    return Path(base) / "AdvogaFacil" / "abertos"


def limpar_visualizacao() -> None:
    shutil.rmtree(pasta_visualizacao(), ignore_errors=True)


def abrir_documento(api: ClienteAPI, d: Documento, pai: QWidget | None = None) -> Path | None:
    """Baixa uma cópia para leitura (conferida pela impressão SHA-256) e abre no programa padrão."""
    destino = pasta_visualizacao() / uuid.uuid4().hex[:8] / d.nome_arquivo
    try:
        with cursor_espera():
            api.baixar_documento(str(d.id), destino)
    except ErroAPI as exc:
        QMessageBox.warning(pai, "Abrir documento", exc.mensagem)
        return None
    QDesktopServices.openUrl(QUrl.fromLocalFile(str(destino)))
    return destino


class DialogoAnexar(QDialog):
    """Anexa um ou mais arquivos a um cliente (e, se quiser, a um processo dele)."""

    def __init__(self, api: ClienteAPI, arquivos: list[str], cliente: tuple[str, str] | None = None,
                 processo_id: str | None = None, parent=None) -> None:
        super().__init__(parent)
        self.api = api
        self.arquivos = [Path(a) for a in arquivos]
        self.anexados: list[Documento] = []
        self.setWindowTitle("Anexar documentos")
        self.setMinimumWidth(620)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(24, 18, 24, 18)
        lay.addWidget(rotulo("Anexar documentos", "secao"))
        nomes = "\n".join(f"• {a.name} ({tamanho_legivel(a.stat().st_size)})" for a in self.arquivos)
        lay.addWidget(rotulo(nomes, quebra=True))
        self.cliente = SeletorCliente(api)
        self.processo = QComboBox()
        self.processo.setMinimumHeight(36)
        self.processo.addItem("Documento geral do cliente (sem processo)", None)
        self.descricao = campo("Ex.: Procuração assinada, laudo pericial...", maximo=500)
        lay.addWidget(bloco_campo("Cliente *", self.cliente))
        lay.addWidget(bloco_campo("Processo", self.processo))
        lay.addWidget(bloco_campo("Descrição (opcional)", self.descricao))
        self.erro = rotulo("", "erro", True)
        lay.addWidget(self.erro)
        b = QHBoxLayout()
        cancelar = QPushButton("Cancelar")
        self.btn_enviar = QPushButton("Anexar")
        self.btn_enviar.setObjectName("primario")
        b.addWidget(cancelar)
        b.addStretch()
        b.addWidget(self.btn_enviar)
        lay.addLayout(b)
        cancelar.clicked.connect(self.reject)
        self.btn_enviar.clicked.connect(self.enviar)
        self.cliente.alterado.connect(self._carregar_processos)
        if cliente:
            self.cliente.definir(*cliente)
            self.cliente.btn.setEnabled(False)
        if processo_id:
            i = self.processo.findData(processo_id)
            if i >= 0:
                self.processo.setCurrentIndex(i)
        ajustar_altura(self)

    def _carregar_processos(self, cliente_id: str) -> None:
        self.processo.clear()
        self.processo.addItem("Documento geral do cliente (sem processo)", None)
        try:
            for p in self.api.processos_opcoes(cliente_id):
                self.processo.addItem(p.rotulo, str(p.id))
        except ErroAPI as exc:
            self.erro.setText(exc.mensagem)

    def enviar(self) -> None:
        if not self.cliente.cliente_id:
            self.erro.setText("Escolha o cliente.")
            ajustar_altura(self)
            return
        for arquivo in self.arquivos:
            try:
                with cursor_espera():
                    self.anexados.append(self.api.anexar_documento(
                        arquivo, self.cliente.cliente_id, self.processo.currentData(),
                        self.descricao.text().strip() or None))
            except ErroAPI as exc:
                enviados = f"{len(self.anexados)} arquivo(s) já foram anexados. " if self.anexados else ""
                self.erro.setText(f"{arquivo.name}: {exc.mensagem} {enviados}")
                self.arquivos = self.arquivos[self.arquivos.index(arquivo):]  # reenviar só o que faltou
                ajustar_altura(self)
                return
        self.accept()


class DialogoEditarDocumento(QDialog):
    def __init__(self, api: ClienteAPI, doc: Documento, parent=None) -> None:
        super().__init__(parent)
        self.api = api
        self.doc = doc
        self.resultado: Documento | None = None
        self.setWindowTitle("Editar documento")
        self.setMinimumWidth(560)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(24, 18, 24, 18)
        lay.addWidget(rotulo("Editar documento", "secao"))
        self.nome = campo(maximo=255)
        self.nome.setText(doc.nome_arquivo)
        self.descricao = campo(maximo=500)
        self.descricao.setText(doc.descricao or "")
        self.processo = QComboBox()
        self.processo.setMinimumHeight(36)
        self.processo.addItem("Documento geral do cliente (sem processo)", None)
        try:
            for p in api.processos_opcoes(str(doc.cliente_id)):
                self.processo.addItem(p.rotulo, str(p.id))
        except ErroAPI:
            pass
        i = self.processo.findData(str(doc.processo_id) if doc.processo_id else None)
        self.processo.setCurrentIndex(max(i, 0))
        lay.addWidget(bloco_campo("Nome do arquivo", self.nome))
        lay.addWidget(bloco_campo("Descrição", self.descricao))
        lay.addWidget(bloco_campo("Processo", self.processo))
        self.erro = rotulo("", "erro", True)
        lay.addWidget(self.erro)
        b = QHBoxLayout()
        cancelar = QPushButton("Cancelar")
        self.btn_salvar = QPushButton("Salvar")
        self.btn_salvar.setObjectName("primario")
        b.addWidget(cancelar)
        b.addStretch()
        b.addWidget(self.btn_salvar)
        lay.addLayout(b)
        cancelar.clicked.connect(self.reject)
        self.btn_salvar.clicked.connect(self.salvar)
        ajustar_altura(self)

    def salvar(self) -> None:
        dados = {"versao": self.doc.versao, "nome_arquivo": self.nome.text().strip(),
                 "descricao": self.descricao.text().strip() or None, "processo_id": self.processo.currentData()}
        try:
            with cursor_espera():
                self.resultado = self.api.atualizar_documento(str(self.doc.id), dados)
        except ErroAPI as exc:
            self.erro.setText(exc.mensagem)
            ajustar_altura(self)
            return
        self.accept()


class PainelDocumentos(QWidget):
    """Lista de documentos com as ações. Usado na ficha do cliente, na ficha do processo e na
    seção Documentos (todos os clientes)."""

    COLUNAS = ["Arquivo", "Cliente", "Processo", "Descrição", "Tamanho", "Anexado por", "Data"]

    def __init__(self, api: ClienteAPI, cliente: tuple[str, str] | None = None, processo_id: str | None = None,
                 mostrar_busca: bool = False) -> None:
        super().__init__()
        self.api = api
        self.cliente = cliente
        self.processo_id = processo_id
        self.pagina = 1
        self.docs: list[Documento] = []
        lay = QVBoxLayout(self)
        lay.setContentsMargins(12, 12, 12, 12)
        barra = QHBoxLayout()
        self.busca = campo("Procurar documento pelo nome ou descrição", maximo=100)
        self.busca.setVisible(mostrar_busca)
        barra.addWidget(self.busca, 1)
        self.chk_removidos = QCheckBox("Mostrar removidos")
        self.chk_removidos.setVisible(bool(api.usuario and api.usuario.is_master))
        barra.addWidget(self.chk_removidos)
        if not mostrar_busca:
            barra.addStretch()
        self.btn_anexar = QPushButton("Anexar arquivos...")
        self.btn_anexar.setObjectName("primario")
        barra.addWidget(self.btn_anexar)
        lay.addLayout(barra)

        self.tabela = QTableWidget(0, len(self.COLUNAS))
        self.tabela.setHorizontalHeaderLabels(self.COLUNAS)
        self.tabela.verticalHeader().setVisible(False)
        self.tabela.setAlternatingRowColors(True)
        self.tabela.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.tabela.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.tabela.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        cab = self.tabela.horizontalHeader()
        for i in range(len(self.COLUNAS)):
            cab.setSectionResizeMode(i, QHeaderView.ResizeMode.ResizeToContents)
        for col, largura in ((0, 230), (1, 200), (2, 210)):
            cab.setSectionResizeMode(col, QHeaderView.ResizeMode.Interactive)
            self.tabela.setColumnWidth(col, largura)
        cab.setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        cab.setMinimumSectionSize(90)
        self.tabela.setColumnHidden(1, cliente is not None)
        self.tabela.setColumnHidden(2, processo_id is not None)
        lay.addWidget(self.tabela, 1)

        acoes = QHBoxLayout()
        self.info = rotulo("", "rotuloCampo")
        acoes.addWidget(self.info)
        acoes.addStretch()
        self.btn_abrir = QPushButton("Abrir")
        self.btn_salvar = QPushButton("Salvar cópia...")
        self.btn_editar = QPushButton("Editar")
        self.btn_remover = QPushButton("Remover")
        self.btn_restaurar = QPushButton("Restaurar")
        self.btn_ant = QPushButton("‹")
        self.btn_prox = QPushButton("›")
        for b in (self.btn_abrir, self.btn_salvar, self.btn_editar, self.btn_remover, self.btn_restaurar,
                  self.btn_ant, self.btn_prox):
            acoes.addWidget(b)
        lay.addLayout(acoes)

        self._atraso = QTimer(self)
        self._atraso.setSingleShot(True)
        self._atraso.setInterval(350)
        self._atraso.timeout.connect(lambda: self.carregar(1))
        self.busca.textChanged.connect(
            lambda t: self._atraso.start() if len(t.strip()) == 0 or len(t.strip()) >= 3 else None)
        self.chk_removidos.toggled.connect(lambda _v: self.carregar(1))
        self.btn_anexar.clicked.connect(self.anexar)
        self.btn_abrir.clicked.connect(self.abrir)
        self.btn_salvar.clicked.connect(self.salvar_copia)
        self.btn_editar.clicked.connect(self.editar)
        self.btn_remover.clicked.connect(self.remover)
        self.btn_restaurar.clicked.connect(self.restaurar)
        self.btn_ant.clicked.connect(lambda: self.carregar(self.pagina - 1))
        self.btn_prox.clicked.connect(lambda: self.carregar(self.pagina + 1))
        self.tabela.cellDoubleClicked.connect(lambda _l, _c: self.abrir())
        self.tabela.itemSelectionChanged.connect(self._atualizar_botoes)
        self._atualizar_botoes()

    # --------------------------------------------------------------- dados
    def carregar(self, pagina: int = 1) -> None:
        removidos = self.chk_removidos.isChecked()
        try:
            with cursor_espera():
                r = self.api.listar_documentos(
                    self.busca.text(),
                    cliente_id=self.cliente[0] if self.cliente else None, processo_id=self.processo_id,
                    removidos=removidos, pagina=pagina)
        except ErroAPI as exc:
            self.info.setText(exc.mensagem)
            return
        self.pagina = r.pagina
        self.docs = r.itens
        self.tabela.setRowCount(len(r.itens))
        for i, d in enumerate(r.itens):
            descricao = d.descricao or ""
            if removidos:
                descricao = f"Removido em {data_hora_br(d.removido_em)} por {d.removido_por_nome}: {d.motivo_remocao}"
            valores = [d.nome_arquivo, d.cliente_nome or "", d.processo_rotulo or "Geral", descricao,
                       tamanho_legivel(d.tamanho), d.enviado_por_nome or "—", data_hora_br(d.criado_em)]
            for j, v in enumerate(valores):
                item = QTableWidgetItem(v)
                item.setToolTip(v)
                self.tabela.setItem(i, j, item)
        paginas = max(1, -(-r.total // r.por_pagina))
        self.info.setText("Nenhum documento." if r.total == 0 else f"{r.total} documento(s) · página {r.pagina} de {paginas}")
        self.btn_ant.setEnabled(r.pagina > 1)
        self.btn_prox.setEnabled(r.pagina < paginas)
        self._atualizar_botoes()

    def selecionado(self) -> Documento | None:
        linha = self.tabela.currentRow()
        return self.docs[linha] if 0 <= linha < len(self.docs) and self.tabela.selectedItems() else None

    def _atualizar_botoes(self) -> None:
        d = self.selecionado()
        removidos = self.chk_removidos.isChecked()
        for b in (self.btn_abrir, self.btn_salvar):
            b.setEnabled(d is not None)
        self.btn_editar.setEnabled(d is not None and not removidos)
        self.btn_remover.setEnabled(d is not None and not removidos)
        self.btn_remover.setVisible(not removidos)
        self.btn_editar.setVisible(not removidos)
        self.btn_anexar.setVisible(not removidos)
        self.btn_restaurar.setVisible(removidos)
        self.btn_restaurar.setEnabled(d is not None)

    # --------------------------------------------------------------- ações
    def anexar(self) -> None:
        arquivos, _ = QFileDialog.getOpenFileNames(self, "Escolher arquivos para anexar")
        if arquivos:
            self.anexar_arquivos(arquivos)

    def anexar_arquivos(self, arquivos: list[str]) -> DialogoAnexar:
        d = DialogoAnexar(self.api, arquivos, self.cliente, self.processo_id, self)
        if self.processo_id:
            d.processo.setEnabled(False)
        if d.exec():
            self.carregar(1)
        return d

    def abrir(self) -> Path | None:
        d = self.selecionado()
        return abrir_documento(self.api, d, self) if d else None

    def salvar_copia(self) -> Path | None:
        d = self.selecionado()
        if d is None:
            return None
        destino, _ = QFileDialog.getSaveFileName(self, "Salvar cópia do documento",
                                                 str(Path.home() / d.nome_arquivo))
        if not destino:
            return None
        try:
            with cursor_espera():
                return self.api.baixar_documento(str(d.id), Path(destino))
        except ErroAPI as exc:
            QMessageBox.warning(self, "Salvar cópia", exc.mensagem)
            return None

    def editar(self) -> None:
        d = self.selecionado()
        if d is None:
            return
        dlg = DialogoEditarDocumento(self.api, d, self)
        if dlg.exec():
            self.carregar(self.pagina)

    def remover(self) -> None:
        d = self.selecionado()
        if d is None:
            return
        motivo, ok = QInputDialog.getText(
            self, "Remover documento",
            f"Remover \"{d.nome_arquivo}\"?\n\nO arquivo continua guardado no servidor e a remoção fica "
            "registrada. Somente a Advogada Master pode restaurá-lo.\n\nInforme o motivo:")
        if not ok:
            return
        try:
            with cursor_espera():
                self.api.remover_documento(str(d.id), motivo.strip(), d.versao)
        except ErroAPI as exc:
            QMessageBox.warning(self, "Remover documento", exc.mensagem)
            return
        self.carregar(self.pagina)

    def restaurar(self) -> None:
        d = self.selecionado()
        if d is None:
            return
        try:
            with cursor_espera():
                self.api.restaurar_documento(str(d.id), d.versao)
        except ErroAPI as exc:
            QMessageBox.warning(self, "Restaurar documento", exc.mensagem)
            return
        self.carregar(self.pagina)


class TelaDocumentos(QWidget):
    """Seção Documentos: todos os documentos que o usuário pode ver, com pesquisa."""

    def __init__(self, api: ClienteAPI) -> None:
        super().__init__()
        lay = QVBoxLayout(self)
        lay.setContentsMargins(28, 24, 28, 20)
        lay.addWidget(rotulo("Documentos", "titulo"))
        lay.addWidget(rotulo("Arquivos organizados por cliente e processo. Para anexar, escolha os arquivos "
                             "e depois o cliente.", "rotuloCampo", True))
        self.painel = PainelDocumentos(api, mostrar_busca=True)
        self.painel.layout().setContentsMargins(0, 8, 0, 0)
        lay.addWidget(self.painel, 1)
        self._carregado = False

    def showEvent(self, evento) -> None:  # noqa: N802
        super().showEvent(evento)
        if not self._carregado:
            self._carregado = True
            self.painel.carregar(1)
