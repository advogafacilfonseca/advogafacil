"""Ponto de entrada do aplicativo Advoga Fácil."""

from __future__ import annotations

import logging
import sys
import traceback

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QIcon, QPixmap
from PySide6.QtWidgets import QApplication, QDialog, QMessageBox, QSplashScreen

from .api_client.cliente import ClienteAPI, ErroAPI
from .assistente.conexao import DialogoConexao
from .assistente.criar_master import DialogoCriarMaster
from .config_local import ConfigLocal, pasta_config_local
from .recursos_caminho import caminho_recurso
from .ui.janela_principal import JanelaPrincipal
from .ui.telas.login import TROCAR_SERVIDOR, DialogoLogin
from .ui.telas.trocar_senha import DialogoTrocarSenha
from .ui.tema.tema import aplicar_tema

log = logging.getLogger("advoga_desktop")


def _configurar_log() -> None:
    pasta = pasta_config_local() / "logs"
    pasta.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        filename=pasta / "advoga_facil.log",
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        encoding="utf-8",
    )


def _erro_inesperado(tipo, valor, tb) -> None:
    log.error("Erro inesperado:\n%s", "".join(traceback.format_exception(tipo, valor, tb)))
    QMessageBox.critical(None, "Advoga Fácil",
                         "Ocorreu um erro inesperado. Nenhuma informação foi perdida no servidor.\n"
                         "Detalhes foram gravados no arquivo de log do aplicativo.")


class Aplicativo:
    def __init__(self, app: QApplication) -> None:
        self.app = app
        self.config = ConfigLocal.carregar()
        self.api: ClienteAPI | None = None
        self.janela: JanelaPrincipal | None = None

    def iniciar(self) -> None:
        if not self._garantir_servidor():
            self.app.quit()
            return
        self._entrar()

    def _garantir_servidor(self) -> bool:
        while True:
            if not self.config.endereco_servidor:
                if DialogoConexao(self.config).exec() != QDialog.DialogCode.Accepted:
                    return False
            try:
                self.api = ClienteAPI(self.config.endereco_servidor, self.config.certificado_pem)
                configurado = self.api.sistema_configurado()
            except ErroAPI as exc:
                escolha = QMessageBox.warning(
                    None, "Servidor indisponível",
                    f"{exc.mensagem}\n\nServidor: {self.config.endereco_servidor}",
                    QMessageBox.StandardButton.Retry | QMessageBox.StandardButton.Open
                    | QMessageBox.StandardButton.Close,
                )
                if escolha == QMessageBox.StandardButton.Retry:
                    continue
                if escolha == QMessageBox.StandardButton.Open:
                    self.config.endereco_servidor = ""
                    continue
                return False
            if not configurado:
                dlg = DialogoCriarMaster(self.api)
                if dlg.exec() != QDialog.DialogCode.Accepted:
                    return False
                self.config.ultimo_usuario = dlg.nome_usuario_criado
                self.config.salvar()
            return True

    def _entrar(self, aviso: str = "") -> None:
        assert self.api is not None
        if aviso:
            QMessageBox.information(None, "Advoga Fácil", aviso)
        dlg = DialogoLogin(self.api, self.config)
        resultado = dlg.exec()
        if resultado == TROCAR_SERVIDOR:
            self.config.endereco_servidor = ""
            self.iniciar()
            return
        if resultado != QDialog.DialogCode.Accepted:
            self.app.quit()
            return
        if self.api.usuario and self.api.usuario.deve_trocar_senha:
            troca = DialogoTrocarSenha(self.api, obrigatoria=True)
            if troca.exec() != QDialog.DialogCode.Accepted:
                try:
                    self.api.logout()
                except ErroAPI:
                    pass
                QTimer.singleShot(0, self._entrar)
                return
            self.api.eu()
        self.janela = JanelaPrincipal(self.api)
        self.janela.sessao_encerrada.connect(self._sessao_encerrada)
        self.janela.showMaximized()

    def _sessao_encerrada(self, motivo: str) -> None:
        if self.janela is not None:
            self.janela.close()
            self.janela.deleteLater()
            self.janela = None
        QTimer.singleShot(0, lambda: self._entrar(motivo))


def main() -> int:
    _configurar_log()
    sys.excepthook = _erro_inesperado
    QApplication.setHighDpiScaleFactorRoundingPolicy(Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
    app = QApplication(sys.argv)
    app.setApplicationName("Advoga Fácil")
    app.setOrganizationName("Advoga Fácil")
    app.setWindowIcon(QIcon(str(caminho_recurso("icone.png"))))
    app.setQuitOnLastWindowClosed(False)
    aplicar_tema(app)

    pix = QPixmap(str(caminho_recurso("logo.png")))
    splash = QSplashScreen(pix.scaledToWidth(560, Qt.TransformationMode.SmoothTransformation))
    splash.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
    splash.show()
    app.processEvents()

    controle = Aplicativo(app)

    def _depois_da_abertura() -> None:
        splash.close()
        controle.iniciar()

    QTimer.singleShot(1500, _depois_da_abertura)
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
