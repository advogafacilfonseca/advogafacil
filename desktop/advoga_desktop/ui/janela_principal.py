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
    QLineEdit,
    QMessageBox,
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
from .telas.clientes import FichaCliente, TelaClientes, TelaResultadosPesquisa
from .telas.notificacoes import PainelAvisos, TelaNotificacoes
from .telas.agenda import TelaAgenda, TelaPendencias
from .telas.financeiro import TelaContratos, TelaFinanceiro
from .telas.documentos import TelaDocumentos, abrir_documento, limpar_visualizacao
from .telas.processos import FichaProcesso, TelaProcessos
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
        limpar_visualizacao()
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
        # Pesquisa global: a partir de 3 caracteres, sem diferenciar acentos e maiúsculas.
        self.pesquisa = QLineEdit()
        self.pesquisa.setObjectName("pesquisaGlobal")
        self.pesquisa.setPlaceholderText("Pesquisar clientes, processos ou documentos...")
        self.pesquisa.setClearButtonEnabled(True)
        self.pesquisa.setMinimumWidth(420)
        self.pesquisa.setMinimumHeight(36)
        self.pesquisa.setMaxLength(100)
        lc.addWidget(self.pesquisa)
        lc.addSpacing(16)
        self.btn_avisos = QPushButton("Avisos")
        self.btn_avisos.setObjectName("botaoAvisos")
        self.btn_avisos.setToolTip("Meus avisos de agenda e financeiro")
        self.btn_avisos.clicked.connect(self.abrir_avisos)
        lc.addWidget(self.btn_avisos)
        lc.addSpacing(8)
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
        self.tela_clientes: TelaClientes | None = None
        if Permissao.CLIENTES in usuario.permissoes:
            self.tela_clientes = TelaClientes(api)
            self._adicionar_secao(ll, "Clientes", self.tela_clientes)
        if Permissao.PROCESSOS in usuario.permissoes:
            self._adicionar_secao(ll, "Processos", TelaProcessos(api))
        if Permissao.AGENDA in usuario.permissoes:
            self._adicionar_secao(ll, "Agenda", TelaAgenda(api))
        if Permissao.PENDENCIAS in usuario.permissoes:
            self._adicionar_secao(ll, "Central de Pendências", TelaPendencias(api))
        if Permissao.CONTRATOS in usuario.permissoes or Permissao.FINANCEIRO in usuario.permissoes:
            self._adicionar_secao(ll, "Contratos", TelaContratos(api))
        if Permissao.FINANCEIRO in usuario.permissoes:
            self._adicionar_secao(ll, "Financeiro", TelaFinanceiro(api))
        if Permissao.DOCUMENTOS in usuario.permissoes:
            self._adicionar_secao(ll, "Documentos", TelaDocumentos(api))
        if Permissao.ADMIN_USUARIOS in usuario.permissoes:
            self._adicionar_secao(ll, "Usuários e Permissões", TelaUsuarios(api))
        if usuario.is_master:
            self._adicionar_secao(ll, "Notificações", TelaNotificacoes(api))
            self._adicionar_secao(ll, "Auditoria", TelaAuditoria(api))
        ll.addStretch()
        ll.addWidget(rotulo(f"  Versão {self._versao()}", "rotuloCampo"))

        # Resultados da pesquisa global (página fora do menu)
        self.tela_resultados = TelaResultadosPesquisa(api)
        self.indice_resultados = self.paginas.addWidget(self.tela_resultados)
        self.tela_resultados.abrir.connect(self.abrir_registro)
        self._atraso_pesquisa = QTimer(self)
        self._atraso_pesquisa.setSingleShot(True)
        self._atraso_pesquisa.setInterval(400)
        self._atraso_pesquisa.timeout.connect(self._pesquisar)
        self.pesquisa.textChanged.connect(self._ao_digitar_pesquisa)
        self.pesquisa.returnPressed.connect(self._pesquisar)

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
        self._timer_avisos = QTimer(self)
        self._timer_avisos.timeout.connect(self.atualizar_avisos)
        self._timer_avisos.start(60_000)
        self.atualizar_avisos()

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

    def _ao_digitar_pesquisa(self, texto: str) -> None:
        if len(texto.strip()) >= 3:
            self._atraso_pesquisa.start()
        else:
            self._atraso_pesquisa.stop()

    def _pesquisar(self) -> None:
        termo = " ".join(self.pesquisa.text().split())
        if len(termo) < 3:
            self.statusBar().showMessage("Digite pelo menos 3 caracteres para pesquisar.", 4000)
            return
        self._atraso_pesquisa.stop()
        self.tela_resultados.pesquisar(termo)
        botao = self.grupo.checkedButton()
        if botao:  # nenhum item do menu fica marcado enquanto os resultados estão na tela
            self.grupo.setExclusive(False)
            botao.setChecked(False)
            self.grupo.setExclusive(True)
        self.paginas.setCurrentIndex(self.indice_resultados)

    def abrir_registro(self, tipo: str, ident: str) -> None:
        try:
            if tipo == "documento":
                abrir_documento(self.api, self.api.obter_documento(ident), self)
                return
            ficha = FichaCliente(self.api, ident, self) if tipo == "cliente" else FichaProcesso(self.api, ident, self)
        except SessaoExpirada as exc:
            self._saindo = True
            self.sessao_encerrada.emit(exc.mensagem)
            return
        except ErroAPI as exc:
            QMessageBox.warning(self, "Abrir", exc.mensagem)
            return
        if tipo == "cliente" and self.tela_clientes:
            ficha.alterado.connect(lambda: self.tela_clientes.carregar(self.tela_clientes.pagina))
        ficha.alterado.connect(lambda: self.tela_resultados.pesquisar(
            self.tela_resultados.termo, self.tela_resultados.pagina))
        ficha.exec()

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
        self._timer_avisos.stop()
        limpar_visualizacao()
        self._saindo = True
        self.sessao_encerrada.emit("")

    def atualizar_avisos(self) -> None:
        """Número de avisos não lidos no botão do cabeçalho (consulta leve, a cada minuto)."""
        if not self.servidor_ok or self._saindo:
            return
        try:
            n = self.api.minhas_notificacoes(somente_nao_lidas=True, limite=1).nao_lidas
        except SessaoExpirada as exc:
            self._timer_avisos.stop()
            self._saindo = True
            self.sessao_encerrada.emit(exc.mensagem)
            return
        except ErroAPI:
            return
        self.btn_avisos.setText(f"Avisos ({n})" if n else "Avisos")
        self.btn_avisos.setProperty("pendente", bool(n))
        self.btn_avisos.style().unpolish(self.btn_avisos)
        self.btn_avisos.style().polish(self.btn_avisos)

    def abrir_avisos(self) -> None:
        painel = PainelAvisos(self.api, self)
        painel.alterado.connect(self.atualizar_avisos)
        painel.exec()
        self.atualizar_avisos()

    def closeEvent(self, evento) -> None:  # noqa: N802 (nome do Qt)
        self._timer_avisos.stop()
        if not self._saindo:
            try:
                self.api.logout()
            except Exception:  # noqa: BLE001 - fechar a janela nunca pode falhar
                pass
            limpar_visualizacao()
            QApplication.quit()
        super().closeEvent(evento)
