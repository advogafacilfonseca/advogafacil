"""Avisos do usuário (botão no cabeçalho) e tela de Notificações da Master: quem recebe cada
categoria, opções de envio e histórico de envios."""

from __future__ import annotations

from datetime import datetime, time, timedelta

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QHBoxLayout,
    QHeaderView,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from advoga_shared.esquemas import CATEGORIAS_NOTIFICACAO, SITUACOES_EMAIL, ConfiguracaoNotificacoes, Notificacao
from advoga_shared.permissoes import Permissao

from ...api_client.cliente import ClienteAPI, ErroAPI
from ..componentes.basicos import bloco_campo, campo, rotulo
from ..componentes.espera import cursor_espera
from ..componentes.formatos import data_hora_br, ler_data_br
from ..tema.tema import CORES
from .financeiro import _preencher, _tabela

CORES_SITUACAO = {"enviado": "sucesso", "falhou": "erro", "rejeitado": "erro", "pendente": "aviso"}


# ======================================================================= avisos do usuário
class PainelAvisos(QDialog):
    """Lista de avisos do próprio usuário. Dois cliques abre o compromisso ou o contrato."""

    alterado = Signal()

    def __init__(self, api: ClienteAPI, parent=None) -> None:
        super().__init__(parent)
        self.api = api
        self.itens: list[Notificacao] = []
        self.setWindowTitle("Meus avisos")
        self.setMinimumSize(680, 520)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(20, 16, 20, 16)
        topo = QHBoxLayout()
        topo.addWidget(rotulo("Meus avisos", "secao"))
        topo.addStretch()
        self.chk_nao_lidos = QCheckBox("Somente não lidos")
        self.btn_todos = QPushButton("Marcar todos como lidos")
        topo.addWidget(self.chk_nao_lidos)
        topo.addWidget(self.btn_todos)
        lay.addLayout(topo)
        self.lista = QListWidget()
        self.lista.setWordWrap(True)
        self.lista.setSpacing(4)
        lay.addWidget(self.lista, 1)
        self.info = rotulo("Dois cliques abrem o compromisso ou o contrato relacionado.", "rotuloCampo")
        lay.addWidget(self.info)
        fechar = QPushButton("Fechar")
        fechar.clicked.connect(self.accept)
        lay.addWidget(fechar, 0, Qt.AlignmentFlag.AlignRight)
        self.chk_nao_lidos.toggled.connect(lambda _v: self.carregar())
        self.btn_todos.clicked.connect(self.marcar_todos)
        self.lista.itemDoubleClicked.connect(self.abrir)
        self.carregar()

    def carregar(self) -> None:
        try:
            r = self.api.minhas_notificacoes(self.chk_nao_lidos.isChecked(), limite=200)
        except ErroAPI as exc:
            self.info.setText(exc.mensagem)
            return
        self.itens = r.itens
        self.lista.clear()
        for n in r.itens:
            item = QListWidgetItem(f"{n.titulo}   ·   {data_hora_br(n.criada_em)}\n{n.mensagem}")
            item.setData(Qt.ItemDataRole.UserRole, str(n.id))
            if n.lida_em is None:
                f = QFont(item.font())
                f.setBold(True)
                item.setFont(f)
                item.setForeground(QColor(CORES["dourado_claro"]))
            self.lista.addItem(item)
        if not r.itens:
            self.lista.addItem(QListWidgetItem("Nenhum aviso."))
        self.btn_todos.setEnabled(r.nao_lidas > 0)

    def marcar_todos(self) -> None:
        try:
            self.api.marcar_notificacoes_lidas(None)
        except ErroAPI as exc:
            QMessageBox.warning(self, "Avisos", exc.mensagem)
        self.carregar()
        self.alterado.emit()

    def abrir(self, item: QListWidgetItem) -> None:
        ident = item.data(Qt.ItemDataRole.UserRole)
        n = next((x for x in self.itens if str(x.id) == ident), None)
        if n is None:
            return
        try:
            if n.lida_em is None:
                self.api.marcar_notificacoes_lidas([ident])
        except ErroAPI:
            pass
        if n.entidade == "compromisso" and n.entidade_id:
            from .agenda import abrir_compromisso

            abrir_compromisso(self.api, n.entidade_id, self, lambda: None)
        elif n.entidade == "parcela" and n.entidade_id and Permissao.FINANCEIRO in self.api.usuario.permissoes:
            from .financeiro import FichaContrato

            try:
                p = self.api.obter_parcela(n.entidade_id)
                FichaContrato(self.api, str(p.contrato_id), self).exec()
            except ErroAPI as exc:
                QMessageBox.warning(self, "Avisos", exc.mensagem)
        self.carregar()
        self.alterado.emit()


# ===================================================================== tela da Master
class TelaNotificacoes(QWidget):
    def __init__(self, api: ClienteAPI) -> None:
        super().__init__()
        self.api = api
        self.config: ConfiguracaoNotificacoes | None = None
        self.historico_itens: list[Notificacao] = []
        lay = QVBoxLayout(self)
        lay.setContentsMargins(28, 24, 28, 20)
        topo = QHBoxLayout()
        topo.addWidget(rotulo("Notificações", "titulo"))
        topo.addStretch()
        self.btn_verificar = QPushButton("Verificar avisos agora")
        topo.addWidget(self.btn_verificar)
        lay.addLayout(topo)
        lay.addWidget(rotulo("Os avisos são gerados pelo servidor, mesmo com os aplicativos fechados, e aparecem no "
                             "botão \"Avisos\" de cada pessoa. Quem estiver marcado também recebe por e-mail.",
                             "rotuloCampo", True))
        self.abas = QTabWidget()
        lay.addWidget(self.abas, 1)

        # -------- Quem recebe
        aba = QWidget()
        la = QVBoxLayout(aba)
        la.setContentsMargins(12, 12, 12, 12)
        la.addWidget(rotulo("Marque quem recebe cada tipo de aviso. Só aparecem habilitadas as pessoas com a "
                            "permissão \"Recebimento de notificações\" e acesso à área do aviso (agenda ou "
                            "pendências; avisos financeiros exigem a permissão Financeiro).", "rotuloCampo", True))
        self.grade = QTableWidget(0, 0)
        self.grade.verticalHeader().setDefaultSectionSize(40)
        la.addWidget(self.grade, 1)
        opcoes = QHBoxLayout()
        self.chk_email = QCheckBox("Enviar os avisos também por e-mail")
        self.hora = campo("hh:mm", maximo=5)
        self.hora.setMaximumWidth(90)
        opcoes.addWidget(self.chk_email)
        opcoes.addSpacing(24)
        opcoes.addWidget(rotulo("Avisos do dia começam às", "rotuloCampo"))
        opcoes.addWidget(self.hora)
        opcoes.addStretch()
        self.btn_salvar = QPushButton("Salvar")
        self.btn_salvar.setObjectName("primario")
        opcoes.addWidget(self.btn_salvar)
        la.addLayout(opcoes)
        self.envio = rotulo("", "rotuloCampo", True)
        la.addWidget(self.envio)
        self.erro = rotulo("", "erro", True)
        la.addWidget(self.erro)
        self.abas.addTab(aba, "Quem recebe")

        # -------- Conta de envio
        aba = QWidget()
        lc = QVBoxLayout(aba)
        lc.setContentsMargins(16, 14, 16, 14)
        lc.addWidget(rotulo("Conta oficial de envio", "secao"))
        self.estado_email = rotulo("", quebra=True)
        lc.addWidget(self.estado_email)
        lc.addWidget(rotulo(
            "Os avisos saem de um único endereço do escritório (Gmail ou Google Workspace). A autorização é feita "
            "na tela do próprio Google: o Advoga Fácil nunca vê a senha da conta e só recebe permissão para ENVIAR "
            "e-mails (não lê a caixa de entrada). Antes, crie o identificador do aplicativo no Google Cloud, seguindo "
            "o manual \"Configurar o envio pelo Google\" (docs/manuais/configurar-envio-google.md).",
            "rotuloCampo", True))
        self.client_id = campo("Ex.: 1234567890-abc123.apps.googleusercontent.com", maximo=300)
        self.client_secret = campo("Chave secreta do cliente", senha=True, maximo=300)
        lc.addWidget(bloco_campo("ID do cliente OAuth (Google Cloud)", self.client_id))
        lc.addWidget(bloco_campo("Chave secreta do cliente", self.client_secret))
        bc = QHBoxLayout()
        self.btn_conectar = QPushButton("Conectar conta Google")
        self.btn_conectar.setObjectName("primario")
        self.btn_testar = QPushButton("Enviar e-mail de teste")
        self.btn_desconectar = QPushButton("Desconectar")
        bc.addWidget(self.btn_conectar)
        bc.addWidget(self.btn_testar)
        bc.addStretch()
        bc.addWidget(self.btn_desconectar)
        lc.addLayout(bc)
        self.msg_email = rotulo("", "rotuloCampo", True)
        lc.addWidget(self.msg_email)
        lc.addStretch()
        self.abas.addTab(aba, "Conta de envio")

        # -------- Histórico
        aba = QWidget()
        lh = QVBoxLayout(aba)
        lh.setContentsMargins(12, 12, 12, 12)
        filtros = QHBoxLayout()
        self.f_categoria = QComboBox()
        self.f_categoria.setMinimumHeight(36)
        self.f_categoria.addItem("Todas as categorias", None)
        for k, v in CATEGORIAS_NOTIFICACAO.items():
            if k != "financeiro" or Permissao.FINANCEIRO in api.usuario.permissoes:
                self.f_categoria.addItem(v, k)
        self.f_categoria.addItem("Backups (falhas e alertas)", "backups")
        self.f_situacao = QComboBox()
        self.f_situacao.setMinimumHeight(36)
        self.f_situacao.addItem("Todas as situações", None)
        for k, v in SITUACOES_EMAIL.items():
            self.f_situacao.addItem(v, k)
        self.f_desde = campo("dd/mm/aaaa", maximo=10)
        self.f_desde.setMaximumWidth(130)
        self.f_desde.setText((datetime.now() - timedelta(days=30)).strftime("%d/%m/%Y"))
        self.btn_filtrar = QPushButton("Filtrar")
        for w in (self.f_categoria, self.f_situacao):
            filtros.addWidget(w)
        filtros.addWidget(rotulo("desde", "rotuloCampo"))
        filtros.addWidget(self.f_desde)
        filtros.addWidget(self.btn_filtrar)
        filtros.addStretch()
        self.btn_reenviar = QPushButton("Reenviar e-mail")
        filtros.addWidget(self.btn_reenviar)
        lh.addLayout(filtros)
        self.tabela_hist = _tabela(["Gerado em", "Para", "Aviso", "E-mail", "Tentativas", "Enviado em", "Detalhe"], 6)
        lh.addWidget(self.tabela_hist, 1)
        self.info_hist = rotulo("", "rotuloCampo")
        lh.addWidget(self.info_hist)
        self.abas.addTab(aba, "Histórico de envios")

        self.btn_salvar.clicked.connect(self.salvar)
        self.btn_verificar.clicked.connect(self.verificar)
        self.btn_filtrar.clicked.connect(self.carregar_historico)
        self.f_categoria.currentIndexChanged.connect(lambda _i: self.carregar_historico())
        self.f_situacao.currentIndexChanged.connect(lambda _i: self.carregar_historico())
        self.btn_reenviar.clicked.connect(self.reenviar)
        self.btn_conectar.clicked.connect(self.conectar_google)
        self.btn_testar.clicked.connect(self.testar_email)
        self.btn_desconectar.clicked.connect(self.desconectar_email)
        self.abas.currentChanged.connect(lambda i: self.carregar_historico() if i == 2 else None)
        self._receptor = None
        self._autorizacao = None
        self._espera = QTimer(self)
        self._espera.setInterval(300)
        self._espera.timeout.connect(self._verificar_retorno)
        self._carregado = False

    def showEvent(self, evento) -> None:  # noqa: N802
        super().showEvent(evento)
        if not self._carregado:
            self._carregado = True
            self.carregar()

    # ------------------------------------------------------------- configuração
    def carregar(self) -> None:
        try:
            with cursor_espera():
                self.config = c = self.api.configuracao_notificacoes()
        except ErroAPI as exc:
            self.erro.setText(exc.mensagem)
            return
        usuarios = c.usuarios
        self.grade.clear()
        self.grade.setRowCount(len(c.categorias))
        self.grade.setColumnCount(len(usuarios) + 1)
        self.grade.setHorizontalHeaderLabels([self._quebrar(u.nome) for u in usuarios] + ["Avisar também\no responsável"])
        self.grade.horizontalHeader().setMinimumHeight(52)
        self.grade.setVerticalHeaderLabels([cat.rotulo for cat in c.categorias])
        self.caixas: dict[tuple[str, str], QCheckBox] = {}
        self.caixas_resp: dict[str, QCheckBox] = {}
        for i, cat in enumerate(c.categorias):
            marcados = {str(x) for x in cat.usuarios_ids}
            for j, u in enumerate(usuarios):
                chk = QCheckBox()
                pode = u.recebe_notificacoes and (u.acessa_financeiro if cat.restrita_financeiro else u.acessa_agenda)
                chk.setEnabled(pode)
                chk.setChecked(str(u.id) in marcados)
                if not u.recebe_notificacoes:
                    chk.setToolTip(f"{u.nome} não tem a permissão \"Recebimento de notificações\".")
                elif not pode:
                    chk.setToolTip(f"{u.nome} não tem acesso a esta área"
                                   + (" (permissão Financeiro)." if cat.restrita_financeiro else "."))
                else:
                    chk.setToolTip(f"Aviso enviado para {u.email}")
                self.grade.setCellWidget(i, j, self._centralizar(chk))
                self.caixas[(cat.categoria, str(u.id))] = chk
            if cat.incluir_responsavel is None:
                item = QTableWidgetItem("—")
                item.setFlags(Qt.ItemFlag.ItemIsEnabled)
                item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                self.grade.setItem(i, len(usuarios), item)
            else:
                chk = QCheckBox()
                chk.setChecked(cat.incluir_responsavel)
                chk.setToolTip("O responsável pelo compromisso também recebe (se tiver as permissões necessárias).")
                self.grade.setCellWidget(i, len(usuarios), self._centralizar(chk))
                self.caixas_resp[cat.categoria] = chk
        cab = self.grade.horizontalHeader()
        cab.setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.grade.verticalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Fixed)
        self.grade.verticalHeader().setMinimumWidth(300)
        self.chk_email.setChecked(c.email_ativo)
        self.hora.setText(c.hora_inicio)
        self.erro.setText("")
        self.carregar_estado_email()

    # ------------------------------------------------------------- conta de envio
    def carregar_estado_email(self) -> None:
        try:
            e = self.api.estado_email()
        except ErroAPI as exc:
            self.estado_email.setText(exc.mensagem)
            return
        cor = CORES["sucesso"] if e.configurado and not e.precisa_reconectar else CORES["aviso"]
        texto = e.mensagem
        if e.configurado and e.conectado_em:
            texto += f"\nConectada em {data_hora_br(e.conectado_em)}" + (
                f" por {e.conectado_por_nome}." if e.conectado_por_nome else ".")
        self.estado_email.setText(texto)
        self.estado_email.setStyleSheet(f"color:{cor};")
        ok = e.configurado and not e.precisa_reconectar
        self.btn_testar.setEnabled(ok)
        self.btn_desconectar.setEnabled(e.configurado)
        self.btn_conectar.setText("Conectar de novo" if e.configurado else "Conectar conta Google")
        self.envio.setText(f"Conta de envio: {e.remetente}" if ok else
                           "Conta oficial de envio: não conectada (aba \"Conta de envio\"). Enquanto isso, os avisos "
                           "aparecem no aplicativo e o histórico registra \"serviço de envio não configurado\".")

    def conectar_google(self) -> None:
        from PySide6.QtCore import QUrl
        from PySide6.QtGui import QDesktopServices

        from ..componentes.oauth_local import ReceptorOAuth

        cid, segredo = self.client_id.text().strip(), self.client_secret.text().strip()
        if not cid or not segredo:
            self.msg_email.setText("Informe o ID do cliente e a chave secreta criados no Google Cloud.")
            return
        self._cancelar_espera()
        self._receptor = ReceptorOAuth()
        try:
            self._autorizacao = self.api.email_google_iniciar(cid, segredo, self._receptor.endereco)
        except ErroAPI as exc:
            self._cancelar_espera()
            self.msg_email.setText(exc.mensagem)
            return
        self._receptor.iniciar()
        self._prazo = 300 * 1000 // self._espera.interval()  # até 5 minutos
        self._espera.start()
        self.btn_conectar.setEnabled(False)
        self.msg_email.setText("Abrimos a página do Google no navegador. Entre com a conta oficial do escritório e "
                               "autorize o envio de e-mails. Esta tela atualiza sozinha ao terminar.")
        QDesktopServices.openUrl(QUrl(self._autorizacao.url))

    def _verificar_retorno(self) -> None:
        self._prazo -= 1
        r = self._receptor.resultado if self._receptor else None
        if r is None and self._prazo > 0:
            return
        auth = self._autorizacao
        self._cancelar_espera()
        if r is None:
            self.msg_email.setText("Tempo esgotado. Clique em \"Conectar conta Google\" para tentar de novo.")
            return
        if "error" in r or r.get("state") != auth.state:
            self.msg_email.setText("A autorização foi cancelada ou não confere. Tente de novo.")
            return
        try:
            with cursor_espera():
                e = self.api.email_google_concluir(auth.state, r["code"])
        except ErroAPI as exc:
            self.msg_email.setText(exc.mensagem)
            return
        self.client_secret.clear()
        self.msg_email.setText(f"Conta {e.remetente} conectada. Use \"Enviar e-mail de teste\" para confirmar.")
        self.carregar_estado_email()

    def _cancelar_espera(self) -> None:
        self._espera.stop()
        if self._receptor is not None:
            self._receptor.encerrar()
            self._receptor = None
        self.btn_conectar.setEnabled(True)

    def testar_email(self) -> None:
        try:
            with cursor_espera():
                destino = self.api.testar_email()
        except ErroAPI as exc:
            self.msg_email.setText(exc.mensagem)
            return
        self.msg_email.setText(f"E-mail de teste enviado para {destino}. Confira a caixa de entrada (e o spam).")

    def desconectar_email(self) -> None:
        from PySide6.QtWidgets import QMessageBox as Caixa

        if Caixa.question(self, "Desconectar", "Os avisos deixarão de ser enviados por e-mail até uma conta ser "
                                               "conectada de novo. Desconectar?") != Caixa.StandardButton.Yes:
            return
        try:
            self.api.desconectar_email()
        except ErroAPI as exc:
            self.msg_email.setText(exc.mensagem)
            return
        self.msg_email.setText("Conta desconectada.")
        self.carregar_estado_email()

    def hideEvent(self, evento) -> None:  # noqa: N802
        self._cancelar_espera()
        super().hideEvent(evento)

    @staticmethod
    def _quebrar(nome: str) -> str:
        """Nome em duas linhas no cabeçalho, para caber na coluna."""
        partes = nome.split()
        if len(partes) < 2:
            return nome
        meio = (len(partes) + 1) // 2
        return " ".join(partes[:meio]) + "\n" + " ".join(partes[meio:])

    @staticmethod
    def _centralizar(w: QWidget) -> QWidget:
        caixa = QWidget()
        caixa.setObjectName("bloco")
        lay = QHBoxLayout(caixa)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(w, 0, Qt.AlignmentFlag.AlignCenter)
        return caixa

    def dados(self) -> dict:
        assert self.config is not None
        categorias = []
        for cat in self.config.categorias:
            ids = [str(u.id) for u in self.config.usuarios if self.caixas[(cat.categoria, str(u.id))].isChecked()]
            categorias.append({"categoria": cat.categoria, "usuarios_ids": ids,
                               "incluir_responsavel": bool(self.caixas_resp.get(cat.categoria)
                                                           and self.caixas_resp[cat.categoria].isChecked())})
        return {"categorias": categorias, "email_ativo": self.chk_email.isChecked(), "hora_inicio": self.hora.text().strip()}

    def salvar(self) -> None:
        try:
            time.fromisoformat(self.hora.text().strip())
        except ValueError:
            self.erro.setText("Horário inválido. Use o formato hh:mm (ex.: 07:00).")
            return
        try:
            with cursor_espera():
                self.api.salvar_configuracao_notificacoes(self.dados())
        except ErroAPI as exc:
            self.erro.setText(exc.mensagem)
            return
        self.carregar()
        self.erro.setText("")
        QMessageBox.information(self, "Notificações", "Configuração salva.")

    def verificar(self) -> None:
        try:
            with cursor_espera():
                r = self.api.verificar_avisos_agora()
        except ErroAPI as exc:
            QMessageBox.warning(self, "Notificações", exc.mensagem)
            return
        QMessageBox.information(self, "Notificações",
                                f"Verificação concluída: {r.geradas} aviso(s) novo(s), {r.enviadas} e-mail(s) "
                                f"enviado(s), {r.falhas} falha(s), {r.nao_enviadas} não enviado(s).")
        if self.abas.currentIndex() == 2:
            self.carregar_historico()

    # ---------------------------------------------------------------- histórico
    def carregar_historico(self) -> None:
        try:
            d = ler_data_br(self.f_desde.text())
        except ValueError as exc:
            self.info_hist.setText(str(exc))
            return
        try:
            r = self.api.historico_notificacoes(categoria=self.f_categoria.currentData(),
                                                situacao=self.f_situacao.currentData(),
                                                desde=datetime.combine(d, time.min).astimezone() if d else None,
                                                por_pagina=500)
        except ErroAPI as exc:
            self.info_hist.setText(exc.mensagem)
            return
        self.historico_itens = r.itens
        _preencher(self.tabela_hist, [[data_hora_br(n.criada_em), n.usuario_nome or "", n.titulo,
                                       SITUACOES_EMAIL.get(n.email_situacao, n.email_situacao),
                                       str(n.email_tentativas) if n.email_tentativas else "",
                                       data_hora_br(n.email_enviado_em) if n.email_enviado_em else "",
                                       n.email_erro or n.mensagem.split("\n")[0]] for n in r.itens],
                   [CORES.get(CORES_SITUACAO.get(n.email_situacao, ""), None) for n in r.itens])
        problemas = sum(1 for n in r.itens if n.email_situacao in ("falhou", "rejeitado"))
        self.info_hist.setText(f"{r.total} aviso(s)" + (f" · {problemas} com falha no envio" if problemas else ""))

    def reenviar(self) -> None:
        linha = self.tabela_hist.currentRow()
        if not (0 <= linha < len(self.historico_itens)) or not self.tabela_hist.selectedItems():
            QMessageBox.information(self, "Reenviar", "Escolha um aviso na lista.")
            return
        n = self.historico_itens[linha]
        try:
            self.api.reenviar_notificacao(str(n.id))
        except ErroAPI as exc:
            QMessageBox.warning(self, "Reenviar", exc.mensagem)
            return
        self.carregar_historico()
