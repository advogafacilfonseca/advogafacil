"""Componentes reutilizáveis da interface."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import QFrame, QLabel, QLineEdit, QMessageBox, QVBoxLayout, QWidget

from ...recursos_caminho import caminho_recurso


def rotulo(texto: str, nome_objeto: str | None = None, quebra: bool = False) -> QLabel:
    lbl = QLabel(texto)
    if nome_objeto:
        lbl.setObjectName(nome_objeto)
    lbl.setWordWrap(quebra)
    return lbl


def campo(placeholder: str = "", senha: bool = False, maximo: int | None = None) -> QLineEdit:
    c = QLineEdit()
    c.setMinimumHeight(36)
    c.setPlaceholderText(placeholder)
    if senha:
        c.setEchoMode(QLineEdit.EchoMode.Password)
    if maximo:
        c.setMaxLength(maximo)
    return c


def bloco_campo(titulo: str, widget: QWidget) -> QWidget:
    w = QWidget()
    w.setObjectName("bloco")
    widget.setMinimumHeight(max(36, widget.minimumHeight()))
    lay = QVBoxLayout(w)
    lay.setContentsMargins(0, 0, 0, 0)
    lay.setSpacing(4)
    lay.addWidget(rotulo(titulo, "rotuloCampo"))
    lay.addWidget(widget)
    w.setMinimumHeight(widget.minimumHeight() + 30)
    return w


def cartao() -> QFrame:
    f = QFrame()
    f.setObjectName("cartao")
    return f


def logotipo(largura: int) -> QLabel:
    lbl = QLabel()
    pix = QPixmap(str(caminho_recurso("logo.png")))
    if not pix.isNull():
        lbl.setPixmap(pix.scaledToWidth(largura, Qt.TransformationMode.SmoothTransformation))
    lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
    return lbl


def avisar_erro(pai: QWidget | None, titulo: str, mensagem: str) -> None:
    QMessageBox.critical(pai, titulo, mensagem)


def avisar_sucesso(pai: QWidget | None, titulo: str, mensagem: str) -> None:
    QMessageBox.information(pai, titulo, mensagem)


def ajustar_altura(janela: QWidget) -> None:
    """Garante altura suficiente para textos com quebra de linha (evita campos espremidos)."""
    lay = janela.layout()
    if lay is None:
        return
    largura = max(janela.width(), janela.minimumWidth())
    altura = lay.totalHeightForWidth(largura) if lay.hasHeightForWidth() else lay.sizeHint().height()
    janela.setMinimumHeight(altura)
    if janela.height() < altura:
        janela.resize(largura, altura)
