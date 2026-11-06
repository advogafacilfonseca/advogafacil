"""Identidade visual: preto e grafite com detalhes dourados."""

from __future__ import annotations

from PySide6.QtGui import QColor, QFont, QPalette
from PySide6.QtWidgets import QApplication

CORES = {
    "fundo": "#0E0E10",
    "superficie": "#17171A",
    "grafite": "#222226",
    "grafite_claro": "#2E2E33",
    "borda": "#3A3A40",
    "dourado": "#C9A24A",
    "dourado_claro": "#E2C275",
    "dourado_escuro": "#9C7A2F",
    "texto": "#EDEDED",
    "texto_suave": "#A3A3AB",
    "erro": "#E5484D",
    "sucesso": "#3FB950",
    "aviso": "#E3A008",
}

QSS = """
* {{ font-family: "Segoe UI", "Inter", "Helvetica Neue", Arial, sans-serif; font-size: 10.5pt; }}
QWidget {{ background: {fundo}; color: {texto}; }}
QDialog, QMainWindow {{ background: {fundo}; }}
QLabel {{ background: transparent; }}
QWidget#bloco {{ background: transparent; }}
QLabel#titulo {{ font-size: 18pt; font-weight: 600; color: {dourado_claro}; }}
QLabel#subtitulo {{ font-size: 11pt; color: {texto_suave}; }}
QLabel#rotuloCampo {{ color: {texto_suave}; font-size: 9.5pt; }}
QLabel#erro {{ color: {erro}; }}
QLabel#sucesso {{ color: {sucesso}; }}
QLabel#secao {{ font-size: 13pt; font-weight: 600; color: {dourado}; }}
QFrame#cartao {{ background: {superficie}; border: 1px solid {borda}; border-radius: 10px; }}
QFrame#cartao QLabel {{ background: transparent; }}
QWidget#bloco {{ background: transparent; }}
QFrame#barraLateral {{ background: {superficie}; border-right: 1px solid {borda}; }}
QFrame#cabecalho {{ background: {superficie}; border-bottom: 1px solid {dourado_escuro}; }}
QLineEdit, QComboBox, QSpinBox, QDateEdit, QTextEdit, QPlainTextEdit {{
    background: {grafite}; border: 1px solid {borda}; border-radius: 6px;
    padding: 7px 9px; selection-background-color: {dourado_escuro}; color: {texto};
    min-height: 20px;
}}
QLineEdit:focus, QComboBox:focus, QTextEdit:focus, QPlainTextEdit:focus {{ border: 1px solid {dourado}; }}
QLineEdit[invalido="true"] {{ border: 1px solid {erro}; }}
QPushButton {{
    background: {grafite_claro}; border: 1px solid {borda}; border-radius: 6px;
    padding: 8px 16px; color: {texto};
}}
QPushButton:hover {{ border-color: {dourado}; }}
QPushButton:disabled {{ color: {texto_suave}; background: {grafite}; }}
QPushButton#botaoAvisos[pendente="true"] {{ color: {fundo}; background: {dourado}; border-color: {dourado}; font-weight: 600; }}
QPushButton:checked {{ color: {dourado_claro}; border-color: {dourado}; }}
QPushButton#primario {{
    background: {dourado}; color: #111; border: 1px solid {dourado_claro}; font-weight: 600;
}}
QPushButton#primario:hover {{ background: {dourado_claro}; }}
QPushButton#primario:disabled {{ background: {dourado_escuro}; color: #333; }}
QPushButton#link {{ background: transparent; border: none; color: {dourado}; padding: 2px; }}
QPushButton#link:hover {{ color: {dourado_claro}; text-decoration: underline; }}
QPushButton#itemMenu {{
    background: transparent; border: none; border-left: 3px solid transparent;
    border-radius: 0; text-align: left; padding: 11px 18px; color: {texto_suave};
}}
QPushButton#itemMenu:hover {{ color: {texto}; background: {grafite}; }}
QPushButton#itemMenu:checked {{ color: {dourado_claro}; border-left: 3px solid {dourado}; background: {grafite}; }}
QStatusBar {{ background: {superficie}; color: {texto_suave}; border-top: 1px solid {borda}; }}
QStatusBar QLabel {{ background: transparent; padding: 0 8px; }}
QStatusBar::item {{ border: none; }}
QMessageBox {{ background: {superficie}; }}
QToolTip {{ background: {grafite_claro}; color: {texto}; border: 1px solid {dourado}; }}
QScrollBar:vertical {{ background: {fundo}; width: 10px; }}
QScrollBar::handle:vertical {{ background: {borda}; border-radius: 5px; min-height: 30px; }}
QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; }}
QTableWidget {{ background: {superficie}; alternate-background-color: {grafite}; gridline-color: {borda};
    border: 1px solid {borda}; border-radius: 6px; selection-background-color: {dourado_escuro}; }}
QHeaderView::section {{ background: {grafite}; color: {dourado}; border: none;
    border-bottom: 1px solid {borda}; padding: 6px 8px; font-weight: 600; }}
QCheckBox {{ background: transparent; spacing: 8px; padding: 3px 0; }}
QCheckBox::indicator {{ width: 16px; height: 16px; border: 1px solid {borda}; border-radius: 3px; background: {grafite}; }}
QCheckBox::indicator:checked {{ background: {dourado}; border-color: {dourado_claro}; }}
QCheckBox:disabled {{ color: {texto_suave}; }}
QCheckBox::indicator:disabled {{ background: {fundo}; border: 1px dashed {grafite_claro}; }}
QScrollArea {{ border: none; }}
QSplitter::handle {{ background: {fundo}; width: 12px; }}
QTabWidget::pane {{ border: 1px solid {borda}; border-radius: 6px; top: -1px; background: {superficie}; }}
QTabBar::tab {{ background: {grafite}; color: {texto_suave}; padding: 8px 18px; border: 1px solid {borda};
    border-bottom: none; border-top-left-radius: 6px; border-top-right-radius: 6px; margin-right: 2px; }}
QTabBar::tab:selected {{ background: {superficie}; color: {dourado_claro}; }}
QLineEdit#pesquisaGlobal {{ border: 1px solid {dourado_escuro}; border-radius: 18px; padding: 6px 14px; }}
QLabel#etiquetaEncerrado {{ color: {aviso}; font-weight: 600; }}
QMenu {{ background: {superficie}; border: 1px solid {borda}; }}
QMenu::item {{ padding: 7px 22px; }}
QMenu::item:selected {{ background: {grafite_claro}; color: {dourado_claro}; }}
""".format(**CORES)


def aplicar_tema(app: QApplication) -> None:
    app.setStyle("Fusion")
    paleta = QPalette()
    paleta.setColor(QPalette.ColorRole.Window, QColor(CORES["fundo"]))
    paleta.setColor(QPalette.ColorRole.WindowText, QColor(CORES["texto"]))
    paleta.setColor(QPalette.ColorRole.Base, QColor(CORES["grafite"]))
    paleta.setColor(QPalette.ColorRole.Text, QColor(CORES["texto"]))
    paleta.setColor(QPalette.ColorRole.Button, QColor(CORES["grafite_claro"]))
    paleta.setColor(QPalette.ColorRole.ButtonText, QColor(CORES["texto"]))
    paleta.setColor(QPalette.ColorRole.Highlight, QColor(CORES["dourado_escuro"]))
    paleta.setColor(QPalette.ColorRole.HighlightedText, QColor("#FFFFFF"))
    app.setPalette(paleta)
    app.setFont(QFont("Segoe UI", 10))
    app.setStyleSheet(QSS)
