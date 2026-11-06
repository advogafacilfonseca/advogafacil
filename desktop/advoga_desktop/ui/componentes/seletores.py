"""Escolha de cliente (por nome, CPF ou telefone) sem expor outros dados do cadastro."""

from __future__ import annotations

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ...api_client.cliente import ClienteAPI, ErroAPI
from .basicos import campo, rotulo


class DialogoEscolherCliente(QDialog):
    def __init__(self, api: ClienteAPI, parent=None) -> None:
        super().__init__(parent)
        self.api = api
        self.escolhido: tuple[str, str] | None = None
        self.setWindowTitle("Escolher cliente")
        self.setMinimumSize(520, 420)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(24, 18, 24, 18)
        lay.addWidget(rotulo("Escolher cliente", "secao"))
        self.busca = campo("Digite pelo menos 3 letras do nome, CPF ou telefone", maximo=100)
        lay.addWidget(self.busca)
        self.lista = QListWidget()
        lay.addWidget(self.lista, 1)
        self.info = rotulo("", "rotuloCampo", True)
        lay.addWidget(self.info)
        b = QHBoxLayout()
        cancelar = QPushButton("Cancelar")
        self.btn_escolher = QPushButton("Escolher")
        self.btn_escolher.setObjectName("primario")
        b.addWidget(cancelar)
        b.addStretch()
        b.addWidget(self.btn_escolher)
        lay.addLayout(b)
        self._atraso = QTimer(self)
        self._atraso.setSingleShot(True)
        self._atraso.setInterval(350)
        self._atraso.timeout.connect(self.procurar)
        self.busca.textChanged.connect(lambda t: self._atraso.start() if len(t.strip()) >= 3 else None)
        cancelar.clicked.connect(self.reject)
        self.btn_escolher.clicked.connect(self._confirmar)
        self.lista.itemDoubleClicked.connect(lambda _i: self._confirmar())

    def procurar(self) -> None:
        self._atraso.stop()
        termo = self.busca.text().strip()
        if len(termo) < 3:
            return
        try:
            opcoes = self.api.clientes_opcoes(termo)
        except ErroAPI as exc:
            self.info.setText(exc.mensagem)
            return
        self.lista.clear()
        for o in opcoes:
            texto = o.nome + ("  (atendimento encerrado)" if o.situacao == "encerrado" else "")
            item = QListWidgetItem(texto)
            item.setData(Qt.ItemDataRole.UserRole, (str(o.id), o.nome))
            self.lista.addItem(item)
        self.info.setText("Nenhum cliente encontrado." if not opcoes else
                          "Mostrando até 30 clientes. Refine a busca se não encontrar." if len(opcoes) == 30 else "")
        if opcoes:
            self.lista.setCurrentRow(0)

    def _confirmar(self) -> None:
        item = self.lista.currentItem()
        if item is None:
            self.info.setText("Escolha um cliente da lista.")
            return
        self.escolhido = item.data(Qt.ItemDataRole.UserRole)
        self.accept()


class SeletorCliente(QWidget):
    alterado = Signal(str)  # id do cliente

    def __init__(self, api: ClienteAPI, parent=None) -> None:
        super().__init__(parent)
        self.api = api
        self.cliente_id: str | None = None
        self.setObjectName("bloco")
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        self.nome = campo("Nenhum cliente escolhido")
        self.nome.setReadOnly(True)
        self.btn = QPushButton("Escolher...")
        lay.addWidget(self.nome, 1)
        lay.addWidget(self.btn)
        self.setMinimumHeight(36)
        self.btn.clicked.connect(self.escolher)

    def definir(self, cliente_id: str, nome: str) -> None:
        self.cliente_id = cliente_id
        self.nome.setText(nome)
        self.alterado.emit(cliente_id)

    def escolher(self) -> None:
        d = DialogoEscolherCliente(self.api, self)
        if d.exec() and d.escolhido:
            self.definir(*d.escolhido)
