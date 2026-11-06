from __future__ import annotations

from PySide6.QtWidgets import QDialog, QHBoxLayout, QPushButton, QVBoxLayout

from ...api_client.cliente import ClienteAPI, ErroAPI
from ..componentes.basicos import ajustar_altura, avisar_sucesso, bloco_campo, campo, rotulo
from ..componentes.espera import cursor_espera


class DialogoTrocarSenha(QDialog):
    def __init__(self, api: ClienteAPI, parent=None, obrigatoria: bool = False) -> None:
        super().__init__(parent)
        self.api = api
        self.obrigatoria = obrigatoria
        self.setWindowTitle("Alterar minha senha")
        self.setMinimumWidth(440)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(28, 20, 28, 20)
        lay.addWidget(rotulo("Crie a sua senha" if obrigatoria else "Alterar minha senha", "secao"))
        if obrigatoria:
            lay.addWidget(rotulo("Você entrou com uma senha provisória. Para continuar, crie uma senha "
                                 "pessoal. Ninguém mais deve conhecê-la.", "subtitulo", True))
        self.atual = campo(senha=True, maximo=128)
        self.nova = campo("Mínimo de 10 caracteres, com letras e números", senha=True, maximo=128)
        self.conf = campo(senha=True, maximo=128)
        lay.addWidget(bloco_campo("Senha atual", self.atual))
        lay.addWidget(bloco_campo("Nova senha", self.nova))
        lay.addWidget(bloco_campo("Confirmação da nova senha", self.conf))
        self.erro = rotulo("", "erro", quebra=True)
        lay.addWidget(self.erro)
        b = QHBoxLayout()
        cancelar = QPushButton("Sair" if obrigatoria else "Cancelar")
        salvar = QPushButton("Salvar nova senha" if obrigatoria else "Alterar senha")
        self.btn_salvar = salvar
        salvar.setObjectName("primario")
        b.addWidget(cancelar)
        b.addStretch()
        b.addWidget(salvar)
        lay.addLayout(b)
        cancelar.clicked.connect(self.reject)
        salvar.clicked.connect(self.salvar)

        ajustar_altura(self)
    def salvar(self) -> None:
        try:
            with cursor_espera():
                msg = self.api.trocar_senha(self.atual.text(), self.nova.text(), self.conf.text())
        except ErroAPI as exc:
            self.erro.setText(exc.mensagem)
            ajustar_altura(self)
            return
        if not self.obrigatoria:
            avisar_sucesso(self, "Senha alterada", msg + " As outras sessões abertas foram encerradas.")
        self.accept()
