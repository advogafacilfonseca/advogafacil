"""Assistente de configuração inicial — Etapa 1: criar a conta Master."""

from __future__ import annotations

from PySide6.QtWidgets import QDialog, QGridLayout, QHBoxLayout, QPushButton, QVBoxLayout

from ..api_client.cliente import ClienteAPI, ErroAPI
from ..ui.componentes.basicos import ajustar_altura, avisar_sucesso, bloco_campo, campo, logotipo, rotulo
from ..ui.componentes.espera import cursor_espera


class DialogoCriarMaster(QDialog):
    def __init__(self, api: ClienteAPI, parent=None) -> None:
        super().__init__(parent)
        self.api = api
        self.nome_usuario_criado = ""
        self.importado = False
        self.setWindowTitle("Advoga Fácil — Configuração inicial")
        self.setMinimumWidth(640)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(36, 24, 36, 24)
        lay.setSpacing(12)
        lay.addWidget(logotipo(220))
        lay.addWidget(rotulo("Criar a conta da Advogada Master", "titulo"))
        lay.addWidget(rotulo(
            "Esta é a primeira conta do sistema e terá autoridade total. Ela só pode ser criada "
            "uma vez. O código de instalação está no arquivo CODIGO_DE_INSTALACAO.txt, na pasta "
            "de configuração do computador servidor.", "subtitulo", quebra=True))

        self.codigo = campo("XXXX-XXXX-XXXX", maximo=20)
        self.nome = campo("Nome completo", maximo=150)
        self.usuario = campo("ex.: maria.silva", maximo=40)
        self.email = campo("seu@email.com.br", maximo=254)
        self.senha = campo("Mínimo de 10 caracteres, com letras e números", senha=True, maximo=128)
        self.confirmacao = campo("Repita a senha", senha=True, maximo=128)

        grade = QGridLayout()
        grade.setHorizontalSpacing(16)
        grade.setVerticalSpacing(10)
        grade.addWidget(bloco_campo("Código de instalação", self.codigo), 0, 0, 1, 2)
        grade.addWidget(bloco_campo("Nome completo", self.nome), 1, 0, 1, 2)
        grade.addWidget(bloco_campo("Nome de usuário", self.usuario), 2, 0)
        grade.addWidget(bloco_campo("E-mail", self.email), 2, 1)
        grade.addWidget(bloco_campo("Senha", self.senha), 3, 0)
        grade.addWidget(bloco_campo("Confirmação de senha", self.confirmacao), 3, 1)
        lay.addLayout(grade)

        self.erro = rotulo("", "erro", quebra=True)
        lay.addWidget(self.erro)

        botoes = QHBoxLayout()
        cancelar = QPushButton("Cancelar")
        self.btn_criar = QPushButton("Criar conta Master")
        self.btn_criar.setObjectName("primario")
        self.btn_importar = QPushButton("Importar dados de outro servidor")
        self.btn_importar.setToolTip("Para um computador servidor novo que vai substituir o atual (migração)")
        botoes.addWidget(cancelar)
        botoes.addWidget(self.btn_importar)
        botoes.addStretch()
        botoes.addWidget(self.btn_criar)
        lay.addLayout(botoes)

        cancelar.clicked.connect(self.reject)
        self.btn_criar.clicked.connect(self.criar)
        self.btn_importar.clicked.connect(self.importar)

        ajustar_altura(self)
    def importar(self) -> None:
        from .importar_migracao import DialogoImportarMigracao

        dlg = DialogoImportarMigracao(self.api, self)
        if dlg.exec() == QDialog.DialogCode.Accepted and dlg.resultado is not None:
            self.importado = True
            self.accept()

    def _validar_local(self) -> str | None:
        if not all(w.text().strip() for w in (self.codigo, self.nome, self.usuario, self.email)):
            return "Preencha todos os campos."
        if not self.senha.text():
            return "Informe a senha."
        if self.senha.text() != self.confirmacao.text():
            return "A confirmação de senha não confere."
        return None

    def criar(self) -> None:
        erro = self._validar_local()
        if erro:
            self.erro.setText(erro)
            ajustar_altura(self)
            return
        self.erro.setText("")
        dados = {
            "codigo_instalacao": self.codigo.text().strip(),
            "nome_completo": self.nome.text().strip(),
            "nome_usuario": self.usuario.text().strip(),
            "email": self.email.text().strip(),
            "senha": self.senha.text(),
            "senha_confirmacao": self.confirmacao.text(),
        }
        try:
            with cursor_espera():
                usuario = self.api.criar_master(dados)
        except ErroAPI as exc:
            self.erro.setText(exc.mensagem)
            ajustar_altura(self)
            return
        self.nome_usuario_criado = usuario.nome_usuario
        avisar_sucesso(self, "Conta criada",
                       f"A conta Master de {usuario.nome_completo} foi criada. Entre com seu usuário e senha.")
        self.accept()
