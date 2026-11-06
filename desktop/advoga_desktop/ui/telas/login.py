"""Tela de login."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDialog, QHBoxLayout, QPushButton, QVBoxLayout

from ...api_client.cliente import ClienteAPI, ErroAPI
from ...config_local import ConfigLocal
from ..componentes.basicos import ajustar_altura, bloco_campo, campo, logotipo, rotulo
from ..componentes.espera import cursor_espera

TROCAR_SERVIDOR = 2


class DialogoLogin(QDialog):
    def __init__(self, api: ClienteAPI, config: ConfigLocal, parent=None) -> None:
        super().__init__(parent)
        self.api = api
        self.config = config
        self.setWindowTitle("Advoga Fácil — Entrar")
        self.setMinimumWidth(460)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(40, 28, 40, 24)
        lay.setSpacing(12)
        lay.addWidget(logotipo(340))

        self.usuario = campo("Nome de usuário", maximo=40)
        self.usuario.setText(config.ultimo_usuario)
        self.senha = campo("Senha", senha=True, maximo=128)
        lay.addWidget(bloco_campo("Usuário", self.usuario))
        lay.addWidget(bloco_campo("Senha", self.senha))

        self.erro = rotulo("", "erro", quebra=True)
        lay.addWidget(self.erro)

        self.btn_entrar = QPushButton("Entrar")
        self.btn_entrar.setObjectName("primario")
        lay.addWidget(self.btn_entrar)

        rodape = QHBoxLayout()
        servidor = rotulo(f"Servidor: {api.endereco}", "rotuloCampo")
        trocar = QPushButton("Alterar servidor")
        trocar.setObjectName("link")
        trocar.setCursor(Qt.CursorShape.PointingHandCursor)
        rodape.addWidget(servidor)
        rodape.addStretch()
        rodape.addWidget(trocar)
        lay.addLayout(rodape)

        self.btn_entrar.clicked.connect(self.entrar)
        self.senha.returnPressed.connect(self.entrar)
        self.usuario.returnPressed.connect(self.senha.setFocus)
        trocar.clicked.connect(lambda: self.done(TROCAR_SERVIDOR))
        (self.senha if config.ultimo_usuario else self.usuario).setFocus()

        ajustar_altura(self)
    def entrar(self) -> None:
        if not self.usuario.text().strip() or not self.senha.text():
            self.erro.setText("Informe usuário e senha.")
            ajustar_altura(self)
            return
        try:
            with cursor_espera():
                self.api.login(self.usuario.text().strip(), self.senha.text())
        except ErroAPI as exc:
            self.erro.setText(exc.mensagem)
            ajustar_altura(self)
            self.senha.clear()
            self.senha.setFocus()
            return
        self.config.ultimo_usuario = self.usuario.text().strip().lower()
        self.config.salvar()
        self.accept()
