"""Assistente de configuração inicial: importar os dados de outro servidor (migração).

Usado no computador servidor NOVO, logo depois da instalação e antes de criar a conta Master.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import QDialog, QGridLayout, QHBoxLayout, QLabel, QPushButton, QVBoxLayout

from advoga_shared.esquemas import AndamentoImportacao

from ..api_client.cliente import ClienteAPI, ErroAPI
from ..ui.componentes.basicos import bloco_campo, campo, logotipo, rotulo
from ..ui.tema.tema import CORES
from ..ui.telas.migracao import tabela_conferencia


class DialogoImportarMigracao(QDialog):
    def __init__(self, api: ClienteAPI, parent=None) -> None:
        super().__init__(parent)
        self.api = api
        self.resultado: AndamentoImportacao | None = None
        self._codigo_usado = ""
        self.setWindowTitle("Advoga Fácil — Importar dados de outro servidor")
        self.setMinimumWidth(760)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(32, 20, 32, 20)
        lay.setSpacing(10)
        lay.addWidget(logotipo(180))
        lay.addWidget(rotulo("Importar dados de outro servidor", "titulo"))
        lay.addWidget(rotulo(
            "Use esta opção no computador servidor NOVO, com o pacote de migração (.afmig) gerado no servidor "
            "antigo em \"Migração de servidor\". Todos os usuários, senhas, permissões e dados do escritório vêm "
            "juntos: não crie a conta Master de novo.", "subtitulo", quebra=True))

        self.codigo = campo("XXXX-XXXX-XXXX", maximo=20)
        self.pacote = campo("E:\\Migracao\\AdvogaFacil_Migracao_2026-11-06_120000.afmig", maximo=500)
        self.senha = campo("Senha definida na exportação", senha=True, maximo=200)
        self.grade = QGridLayout()
        self.grade.setHorizontalSpacing(16)
        self.grade.setVerticalSpacing(10)
        self.grade.addWidget(bloco_campo("Código de instalação (arquivo CODIGO_DE_INSTALACAO.txt do servidor novo)",
                                         self.codigo), 0, 0)
        self.grade.addWidget(bloco_campo("Caminho do pacote no computador servidor novo", self.pacote), 1, 0)
        self.grade.addWidget(bloco_campo("Senha do pacote", self.senha), 2, 0)
        lay.addLayout(self.grade)

        self.andamento = rotulo("", "rotuloCampo", True)
        self.erro = rotulo("", "erro", True)
        lay.addWidget(self.andamento)
        lay.addWidget(self.erro)

        # Resultado (aparece no fim)
        self.titulo_resultado = rotulo("", "titulo", True)
        self.titulo_resultado.hide()
        lay.addWidget(self.titulo_resultado)
        self.codigo_confirmacao = QLabel()
        self.codigo_confirmacao.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.codigo_confirmacao.setStyleSheet(f"color:{CORES['dourado_claro']}; font-size:20pt; font-weight:700;"
                                              "letter-spacing:3px;")
        self.codigo_confirmacao.hide()
        lay.addWidget(self.codigo_confirmacao)
        self.pendencias = rotulo("", "rotuloCampo", True)
        self.pendencias.hide()
        lay.addWidget(self.pendencias)
        self.area_tabela = QVBoxLayout()
        lay.addLayout(self.area_tabela)

        botoes = QHBoxLayout()
        self.btn_voltar = QPushButton("Voltar")
        self.btn_importar = QPushButton("Importar")
        self.btn_importar.setObjectName("primario")
        self.btn_concluir = QPushButton("Ir para o login")
        self.btn_concluir.setObjectName("primario")
        self.btn_concluir.hide()
        botoes.addWidget(self.btn_voltar)
        botoes.addStretch()
        botoes.addWidget(self.btn_importar)
        botoes.addWidget(self.btn_concluir)
        lay.addLayout(botoes)
        self.btn_voltar.clicked.connect(self.reject)
        self.btn_importar.clicked.connect(self.importar)
        self.btn_concluir.clicked.connect(self.accept)

        self._timer = QTimer(self)
        self._timer.setInterval(1500)
        self._timer.timeout.connect(self.acompanhar)

    def importar(self) -> None:
        self.erro.clear()
        if not all(c.text().strip() for c in (self.codigo, self.pacote)) or not self.senha.text():
            self.erro.setText("Preencha o código de instalação, o caminho do pacote e a senha.")
            return
        self._codigo_usado = self.codigo.text().strip()
        try:
            self.api.importar_migracao(self._codigo_usado, self.pacote.text().strip(), self.senha.text())
        except ErroAPI as exc:
            self.erro.setText(exc.mensagem)
            return
        self._bloquear(True)
        self.andamento.setText("Importação iniciada...")
        self._timer.start()

    def _bloquear(self, sim: bool) -> None:
        for w in (self.codigo, self.pacote, self.senha, self.btn_importar, self.btn_voltar):
            w.setEnabled(not sim)

    def acompanhar(self) -> None:
        try:
            a = self.api.andamento_importacao(self._codigo_usado)
        except ErroAPI as exc:
            self.andamento.setText(f"Aguardando o servidor... ({exc.mensagem})")
            return
        if a.situacao == "em_andamento":
            self.andamento.setText(f"Importando: {a.etapa or '...'}")
            return
        self._timer.stop()
        if a.situacao == "falhou":
            self._bloquear(False)
            self.andamento.clear()
            self.erro.setText(f"A importação não foi feita. {a.mensagem or ''}")
            return
        self.resultado = a
        self._mostrar_resultado(a)

    def _mostrar_resultado(self, a: AndamentoImportacao) -> None:
        for w in (self.codigo, self.pacote, self.senha):
            w.parentWidget().hide()
        self.btn_importar.hide()
        self.btn_voltar.hide()
        self.andamento.setText(a.mensagem or "")
        self.titulo_resultado.setText("Importação concluída e conferida. Código de confirmação:")
        self.titulo_resultado.show()
        self.codigo_confirmacao.setText(a.codigo_confirmacao or "")
        self.codigo_confirmacao.show()
        rel = a.relatorio
        if rel is not None:
            itens = "\n".join(f"• {p}" for p in rel.pendencias)
            self.pendencias.setText("Anote o código acima e informe-o no servidor antigo, em \"Migração de "
                                    "servidor\", para desativá-lo. O relatório também foi gravado na pasta "
                                    f"\"migracoes\" dos dados do servidor.\n\nO que falta fazer:\n{itens}")
            self.pendencias.show()
            t = tabela_conferencia(rel, self)
            t.setMinimumHeight(260)
            self.area_tabela.addWidget(t)
        self.btn_concluir.show()
        self.adjustSize()
