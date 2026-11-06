"""Janela principal: cabeçalho, menu lateral, área de conteúdo e status do servidor.

O menu mostra somente módulos já implementados e permitidos ao usuário; os demais
entram à medida que cada etapa for concluída (nenhum botão sem função).
"""

from __future__ import annotations

from PySide6.QtCore import QObject, QRunnable, Qt, QThreadPool, QTimer, Signal
from PySide6.QtGui import QIcon, QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QButtonGroup,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMenu,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from ..api_client.cliente import ClienteAPI, ErroAPI, ServidorIndisponivel, SessaoExpirada
from ..recursos_caminho import caminho_recurso
from .componentes.basicos import rotulo
from advoga_shared.permissoes import Permissao

from .telas.auditoria import TelaAuditoria
from .telas.painel import TelaPainel
from .telas.usuarios import TelaUsuarios
from .telas.trocar_senha import DialogoTrocarSenha
from .tema.tema import CORES


class _SinaisSaude(QObject):
    resultado = Signal(bool, str)


class _VerificarSaude(QRunnable):
    def __init__(self, endereco: str, certificado: str, sinais: _SinaisSaude) -> None:
        super().__init__()
        self.endereco = endereco
        self.certificado = certificado
        self.sinais = sinais

    def run(self) -> None:
        try:
            api = ClienteAPI(self.endereco, self.certificado, timeout=5)
        except ErroAPI as exc:
            self.sinais.resultado.emit(False, exc.mensagem)
            return
        try:
            s = api.saude()
            if s.servidor_status == "desativado":
                self.sinais.resultado.emit(False, "Servidor desativado após migração")
            else:
                self.sinais.resultado.emit(True, "Servidor conectado")
        except ServidorIndisponivel:
            self.sinais.resultado.emit(False, "Servidor indisponível — alterações não podem ser gravadas")
        except ErroAPI as exc:
            self.sinais.resultado.emit(False, exc.mensagem)
        finally:
            api.fechar()


class JanelaPrincipal(QMainWindow):
    sessao_encerrada = Signal(str)  # motivo

    def __init__(self, api: ClienteAPI) -> None:
        super().__init__()
        self.api = api
        self.servidor_ok = True
        self._saindo = False
        usuario = api.usuario
        assert usuario is not None
        self.setWindowTitle("Advoga Fácil")
        self.setWindowIcon(QIcon(str(caminho_recurso("icone.png"))))
        self.resize(1280, 800)

        central = QWidget()
        raiz = QVBoxLayout(central)
        raiz.setContentsMargins(0, 0, 0, 0)
        raiz.setSpacing(0)

        # ---- Cabeçalho
        cab = QFrame()
        cab.setObjectName("cabecalho")
        lc = QHBoxLayout(cab)
        lc.setContentsMargins(16, 8, 16, 8)
        logo = QLabel()
        pix = QPixmap(str(caminho_recurso("icone.png")))
        logo.setPixmap(pix.scaledToHeight(40, Qt.TransformationMode.SmoothTransformation))
        nome = QLabel("ADVOGA FÁCIL")
        nome.setStyleSheet(f"color:{CORES['dourado_claro']}; font-size:14pt; font-weight:600; letter-spacing:2px;")
        lc.addWidget(logo)
        lc.addWidget(nome)
        lc.addStretch()
        self.btn_usuario = QPushButton(f"{usuario.nome_exibicao}  ·  {usuario.cargo or ''}".strip(" ·"))
        menu = QMenu(self)
        menu.addAction("Alterar minha senha", self._trocar_senha)
        menu.addSeparator()
        menu.addAction("Sair", self.sair)
        self.btn_usuario.setMenu(menu)
        lc.addWidget(self.btn_usuario)
        raiz.addWidget(cab)

        # ---- Corpo: menu lateral + conteúdo
        corpo = QHBoxLayout()
        corpo.setSpacing(0)
        lateral = QFrame()
        lateral.setObjectName("barraLateral")
        lateral.setFixedWidth(230)
        ll = QVBoxLayout(lateral)
        ll.setContentsMargins(0, 16, 0, 16)
        ll.setSpacing(2)
        self.paginas = QStackedWidget()
        self.grupo = QButtonGroup(self)
        self.grupo.setExclusive(True)

        self._adicionar_secao(ll, "Painel inicial", TelaPainel(api))
        if Permissao.ADMIN_USUARIOS in usuario.permissoes:
            self._adicionar_secao(ll, "Usuários e Permissões", TelaUsuarios(api))
        if usuario.is_master:
            self._adicionar_secao(ll, "Auditoria", TelaAuditoria(api))
        ll.addStretch()
        ll.addWidget(rotulo(f"  Versão {self._versao()}", "rotuloCampo"))

        corpo.addWidget(lateral)
        corpo.addWidget(self.paginas, 1)
        raiz.addLayout(corpo, 1)
        self.setCentralWidget(central)

        # ---- Barra de status com o estado do servidor
        self.status_servidor = QLabel()
        self.statusBar().addPermanentWidget(self.status_servidor)
        self._mostrar_status(True, "Servidor conectado")
        self._sinais = _SinaisSaude()
        self._sinais.resultado.connect(self._mostrar_status)
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._checar_servidor)
        self._timer.start(15_000)

    @staticmethod
    def _versao() -> str:
        from advoga_shared import __version__
        return __version__

    def _adicionar_secao(self, layout: QVBoxLayout, titulo: str, tela: QWidget) -> None:
        botao = QPushButton(titulo)
        botao.setObjectName("itemMenu")
        botao.setCheckable(True)
        botao.setCursor(Qt.CursorShape.PointingHandCursor)
        indice = self.paginas.addWidget(tela)
        botao.clicked.connect(lambda: self.paginas.setCurrentIndex(indice))
        self.grupo.addButton(botao)
        layout.addWidget(botao)
        if indice == 0:
            botao.setChecked(True)

    def _checar_servidor(self) -> None:
        QThreadPool.globalInstance().start(
            _VerificarSaude(self.api.endereco, self.api.certificado_pem, self._sinais))

    def _mostrar_status(self, ok: bool, texto: str) -> None:
        self.servidor_ok = ok
        cor = CORES["sucesso"] if ok else CORES["erro"]
        self.status_servidor.setText(f"<span style='color:{cor}'>●</span> {texto}")

    def _trocar_senha(self) -> None:
        try:
            DialogoTrocarSenha(self.api, self).exec()
        except SessaoExpirada as exc:
            self._saindo = True
            self.sessao_encerrada.emit(exc.mensagem)

    def sair(self) -> None:
        try:
            self.api.logout()
        except ErroAPI:
            pass  # mesmo sem servidor, a sessão local é descartada
        self._timer.stop()
        self._saindo = True
        self.sessao_encerrada.emit("")

    def closeEvent(self, evento) -> None:  # noqa: N802 (nome do Qt)
        if not self._saindo:
            try:
                self.api.logout()
            except ErroAPI:
                pass
            QApplication.quit()
        super().closeEvent(evento)
