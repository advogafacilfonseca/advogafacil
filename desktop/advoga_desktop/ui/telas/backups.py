"""Central de Backups (somente a Advogada Master)."""

from __future__ import annotations

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QFormLayout,
    QFrame,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from advoga_shared.esquemas import SITUACOES_BACKUP, TIPOS_BACKUP, EstadoBackups, ExecucaoBackup

from ...api_client.cliente import ClienteAPI, ErroAPI
from ..componentes.basicos import cartao, campo, rotulo
from ..componentes.formatos import data_hora_br, tamanho_legivel
from ..tema.tema import CORES


def _resumo_execucao(e: ExecucaoBackup | None, vazio: str) -> str:
    if e is None:
        return vazio
    quando = data_hora_br(e.concluido_em or e.iniciado_em)
    return f"{quando}\n{SITUACOES_BACKUP.get(e.situacao, e.situacao)}"


def _duracao(e: ExecucaoBackup) -> str:
    if not e.concluido_em:
        return "—"
    s = int((e.concluido_em - e.iniciado_em).total_seconds())
    return f"{s // 60} min {s % 60:02d} s" if s >= 60 else f"{s} s"


class TelaBackups(QWidget):
    def __init__(self, api: ClienteAPI) -> None:
        super().__init__()
        self.api = api
        self.estado: EstadoBackups | None = None
        externo = QVBoxLayout(self)
        externo.setContentsMargins(0, 0, 0, 0)
        rolagem = QScrollArea()
        rolagem.setWidgetResizable(True)
        rolagem.setFrameShape(QFrame.Shape.NoFrame)
        externo.addWidget(rolagem)
        conteudo = QWidget()
        rolagem.setWidget(conteudo)
        lay = QVBoxLayout(conteudo)
        lay.setContentsMargins(28, 24, 28, 20)
        lay.setSpacing(12)
        lay.addWidget(rotulo("Central de Backups", "titulo"))
        lay.addWidget(rotulo("Cópias do banco de dados e dos documentos no HD externo, conferidas e testadas. "
                             "Sincronização de pastas não substitui backup.", "subtitulo", True))

        self.alertas = QLabel()
        self.alertas.setWordWrap(True)
        self.alertas.setStyleSheet(f"color:{CORES['aviso']}; border:1px solid {CORES['aviso']}; border-radius:6px;"
                                   "padding:10px; font-weight:600;")
        self.alertas.hide()
        lay.addWidget(self.alertas)

        grade = QGridLayout()
        grade.setSpacing(12)
        self.cartoes: dict[str, QLabel] = {}
        for i, (chave, titulo) in enumerate([("ultimo", "Último backup"), ("completo", "Último backup completo"),
                                            ("teste", "Último teste de restauração"), ("hd", "HD de backup")]):
            c = cartao()
            lc = QVBoxLayout(c)
            lc.setContentsMargins(14, 10, 14, 10)
            lc.addWidget(rotulo(titulo, "rotuloCampo"))
            v = QLabel("—")
            v.setWordWrap(True)
            v.setStyleSheet(f"font-weight:600; color:{CORES['dourado_claro']};")
            lc.addWidget(v)
            self.cartoes[chave] = v
            grade.addWidget(c, 0, i)
        lay.addLayout(grade)

        acoes = QHBoxLayout()
        self.btn_completo = QPushButton("Fazer backup completo agora")
        self.btn_completo.setObjectName("primario")
        self.btn_rapido = QPushButton("Backup rápido agora")
        self.btn_teste = QPushButton("Testar restauração agora")
        self.btn_atualizar = QPushButton("Atualizar")
        self.btn_completo.clicked.connect(lambda: self.executar("completo"))
        self.btn_rapido.clicked.connect(lambda: self.executar("rapido"))
        self.btn_teste.clicked.connect(self.testar)
        self.btn_atualizar.clicked.connect(self.carregar)
        for b in (self.btn_completo, self.btn_rapido, self.btn_teste, self.btn_atualizar):
            acoes.addWidget(b)
        acoes.addStretch()
        lay.addLayout(acoes)
        self.msg = rotulo("", "sucesso", True)
        self.erro = rotulo("", "erro", True)
        lay.addWidget(self.msg)
        lay.addWidget(self.erro)

        self.abas = QTabWidget()
        self.abas.addTab(self._aba_config(), "Configuração")
        self.abas.addTab(self._aba_historico(), "Histórico")
        lay.addWidget(self.abas, 1)

        self._acompanhar = QTimer(self)
        self._acompanhar.setInterval(3000)
        self._acompanhar.timeout.connect(self._atualizar_andamento)

    # ------------------------------------------------------------------- abas
    def _aba_config(self) -> QWidget:
        aba = QWidget()
        lay = QVBoxLayout(aba)
        lay.setContentsMargins(14, 14, 14, 14)
        lay.addWidget(rotulo("As pastas são do COMPUTADOR SERVIDOR (ex.: E:\\Backups no HD externo ligado nele). "
                             "Use \"Verificar\" para conferir se o servidor encontra a pasta.", "rotuloCampo", True))
        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        self.ativo = QCheckBox("Fazer backups automáticos")
        form.addRow("", self.ativo)
        self.destino = campo("E:\\Backups", maximo=400)
        self.btn_verificar = QPushButton("Verificar")
        self.btn_verificar.clicked.connect(lambda: self.verificar(self.destino, self.res_destino))
        self.res_destino = rotulo("", "rotuloCampo", True)
        linha = QHBoxLayout()
        linha.addWidget(self.destino, 1)
        linha.addWidget(self.btn_verificar)
        form.addRow("Pasta no HD externo:", linha)
        form.addRow("", self.res_destino)
        self.hora = campo("23:00", maximo=5)
        self.hora.setMaximumWidth(90)
        form.addRow("Backup completo diário às:", self.hora)
        self.intervalo = QSpinBox()
        self.intervalo.setRange(0, 24)
        self.intervalo.setSuffix(" h")
        self.intervalo.setSpecialValueText("Desligado")
        form.addRow("Backup rápido a cada:", self.intervalo)
        self.reter = QSpinBox()
        self.reter.setRange(7, 3650)
        self.reter.setSuffix(" dias")
        form.addRow("Guardar versões por:", self.reter)
        self.teste_dias = QSpinBox()
        self.teste_dias.setRange(0, 90)
        self.teste_dias.setSuffix(" dias")
        self.teste_dias.setSpecialValueText("Desligado")
        for caixa in (self.intervalo, self.reter, self.teste_dias):
            caixa.setMaximumWidth(160)
        form.addRow("Testar a restauração a cada:", self.teste_dias)
        lay.addLayout(form)

        grupo = QGroupBox("Cópia criptografada em outro local (ex.: segundo HD ou pasta de rede)")
        fg = QFormLayout(grupo)
        self.sec_ativa = QCheckBox("Gravar uma cópia criptografada a cada backup completo")
        fg.addRow("", self.sec_ativa)
        self.destino_sec = campo("F:\\CopiaAdvogaFacil", maximo=400)
        self.btn_verificar_sec = QPushButton("Verificar")
        self.btn_verificar_sec.clicked.connect(lambda: self.verificar(self.destino_sec, self.res_sec))
        self.res_sec = rotulo("", "rotuloCampo", True)
        l2 = QHBoxLayout()
        l2.addWidget(self.destino_sec, 1)
        l2.addWidget(self.btn_verificar_sec)
        fg.addRow("Pasta:", l2)
        fg.addRow("", self.res_sec)
        self.reter_sec = QSpinBox()
        self.reter_sec.setRange(1, 365)
        self.reter_sec.setSuffix(" cópias")
        self.reter_sec.setMaximumWidth(160)
        fg.addRow("Guardar as últimas:", self.reter_sec)
        self.situacao_senha = rotulo("", "rotuloCampo", True)
        fg.addRow("Senha da cópia:", self.situacao_senha)
        self.senha = campo("Mínimo de 12 caracteres", senha=True, maximo=200)
        self.senha2 = campo("Repita a senha", senha=True, maximo=200)
        self.btn_senha = QPushButton("Definir senha")
        self.btn_senha.clicked.connect(self.definir_senha)
        l3 = QHBoxLayout()
        l3.addWidget(self.senha, 1)
        l3.addWidget(self.senha2, 1)
        l3.addWidget(self.btn_senha)
        fg.addRow("Nova senha:", l3)
        fg.addRow("", rotulo("Guarde esta senha fora do computador (ex.: papel no cofre). Sem ela, a cópia "
                             "criptografada não pode ser aberta. A senha não fica gravada no sistema.",
                             "rotuloCampo", True))
        lay.addWidget(grupo)
        self.btn_salvar = QPushButton("Salvar configuração")
        self.btn_salvar.setObjectName("primario")
        self.btn_salvar.clicked.connect(self.salvar)
        self.erro_cfg = rotulo("", "erro", True)
        lb = QHBoxLayout()
        lb.addWidget(self.btn_salvar)
        lb.addWidget(self.erro_cfg, 1)
        lay.addLayout(lb)
        lay.addStretch()
        return aba

    def _aba_historico(self) -> QWidget:
        aba = QWidget()
        lay = QVBoxLayout(aba)
        lay.setContentsMargins(12, 12, 12, 12)
        colunas = ["Início", "Tipo", "Origem", "Situação", "Duração", "Tamanho", "Arquivos", "Detalhes"]
        self.tabela = QTableWidget(0, len(colunas))
        self.tabela.setHorizontalHeaderLabels(colunas)
        self.tabela.verticalHeader().setVisible(False)
        self.tabela.setAlternatingRowColors(True)
        self.tabela.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.tabela.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.tabela.setMinimumHeight(300)
        cab = self.tabela.horizontalHeader()
        for i in range(len(colunas) - 1):
            cab.setSectionResizeMode(i, QHeaderView.ResizeMode.ResizeToContents)
        cab.setSectionResizeMode(len(colunas) - 1, QHeaderView.ResizeMode.Stretch)
        lay.addWidget(self.tabela)
        return aba

    # ----------------------------------------------------------------- dados
    def showEvent(self, evento) -> None:  # noqa: N802
        super().showEvent(evento)
        self.carregar()

    def hideEvent(self, evento) -> None:  # noqa: N802
        self._acompanhar.stop()
        super().hideEvent(evento)

    def carregar(self) -> None:
        try:
            est = self.api.estado_backups()
            hist = self.api.historico_backups()
        except ErroAPI as exc:
            self.erro.setText(exc.mensagem)
            return
        self.estado = est
        self._mostrar_estado(est)
        self._mostrar_config(est)
        self._mostrar_historico(hist)

    def _mostrar_estado(self, est: EstadoBackups) -> None:
        if est.alertas:
            self.alertas.setText("\n".join(f"⚠  {a}" for a in est.alertas))
            self.alertas.show()
        else:
            self.alertas.hide()
        self.cartoes["ultimo"].setText(_resumo_execucao(est.ultimo_sucesso, "Nenhum ainda"))
        self.cartoes["completo"].setText(_resumo_execucao(est.ultimo_completo, "Nenhum ainda"))
        self.cartoes["teste"].setText(_resumo_execucao(est.ultimo_teste, "Nenhum ainda"))
        self.cartoes["hd"].setText(est.destino.mensagem)
        andamento = est.em_andamento is not None
        for b in (self.btn_completo, self.btn_rapido, self.btn_teste):
            b.setEnabled(not andamento and bool(est.configuracao.destino))
        if andamento:
            self.msg.setText(f"{TIPOS_BACKUP.get(est.em_andamento.tipo, '')} em andamento desde "
                             f"{data_hora_br(est.em_andamento.iniciado_em)}...")
            if self.isVisible():
                self._acompanhar.start()
        else:
            self._acompanhar.stop()

    def _mostrar_config(self, est: EstadoBackups) -> None:
        c = est.configuracao
        self.ativo.setChecked(c.ativo)
        self.destino.setText(c.destino or "")
        self.hora.setText(c.hora_completo)
        self.intervalo.setValue(c.intervalo_horas)
        self.reter.setValue(c.reter_dias)
        self.teste_dias.setValue(c.teste_restauracao_dias)
        self.sec_ativa.setChecked(c.copia_secundaria_ativa)
        self.destino_sec.setText(c.destino_secundario or "")
        self.reter_sec.setValue(c.reter_copias_secundarias)
        self.situacao_senha.setText("Definida." if c.senha_copia_definida else "Ainda não definida.")

    def _mostrar_historico(self, itens: list[ExecucaoBackup]) -> None:
        self.tabela.setRowCount(len(itens))
        for i, e in enumerate(itens):
            arquivos = "" if e.arquivos_total is None else (
                f"{e.arquivos_novos} novos / {e.arquivos_total}" if e.arquivos_novos is not None else str(e.arquivos_total))
            detalhe = e.mensagem or ""
            if e.copia_secundaria:
                detalhe += f"  Cópia criptografada: {e.copia_secundaria}"
            valores = [data_hora_br(e.iniciado_em), TIPOS_BACKUP.get(e.tipo, e.tipo),
                       "Automático" if e.origem == "automatico" else f"Manual ({e.iniciado_por_nome or '—'})",
                       SITUACOES_BACKUP.get(e.situacao, e.situacao), _duracao(e),
                       tamanho_legivel(e.tamanho_bytes) if e.tamanho_bytes else "", arquivos, detalhe]
            for j, v in enumerate(valores):
                item = QTableWidgetItem(v)
                item.setToolTip(v)
                if j == 3 and e.situacao == "falhou":
                    from PySide6.QtGui import QColor

                    item.setForeground(QColor(CORES["erro"]))
                self.tabela.setItem(i, j, item)

    def _atualizar_andamento(self) -> None:
        try:
            est = self.api.estado_backups()
        except ErroAPI:
            return
        if est.em_andamento is None:
            self.carregar()
            ultimo = self.tabela.item(0, 3).text() if self.tabela.rowCount() else ""
            self.msg.setText(f"Terminou: {ultimo}. Veja os detalhes no histórico.")
        else:
            self._mostrar_estado(est)

    # ----------------------------------------------------------------- ações
    def verificar(self, caixa, resultado: QLabel) -> None:
        caminho = caixa.text().strip()
        if not caminho:
            resultado.setText("Informe a pasta.")
            return
        try:
            s = self.api.verificar_destino_backup(caminho)
        except ErroAPI as exc:
            resultado.setText(exc.mensagem)
            return
        resultado.setText(("✓ " if s.disponivel else "✗ ") + s.mensagem)

    def salvar(self) -> None:
        self.erro_cfg.clear()
        dados = {"ativo": self.ativo.isChecked(), "destino": self.destino.text().strip() or None,
                 "hora_completo": self.hora.text().strip(), "intervalo_horas": self.intervalo.value(),
                 "reter_dias": self.reter.value(), "teste_restauracao_dias": self.teste_dias.value(),
                 "copia_secundaria_ativa": self.sec_ativa.isChecked(),
                 "destino_secundario": self.destino_sec.text().strip() or None,
                 "reter_copias_secundarias": self.reter_sec.value()}
        try:
            self.api.salvar_configuracao_backups(dados)
        except ErroAPI as exc:
            self.erro_cfg.setText(exc.mensagem)
            return
        self.msg.setText("Configuração dos backups salva.")
        self.carregar()

    def definir_senha(self) -> None:
        self.erro_cfg.clear()
        try:
            mensagem = self.api.definir_senha_copia_backup(self.senha.text(), self.senha2.text())
        except ErroAPI as exc:
            self.erro_cfg.setText(exc.mensagem)
            return
        self.senha.clear()
        self.senha2.clear()
        self.msg.setText(mensagem)
        self.carregar()

    def executar(self, tipo: str) -> None:
        self.erro.clear()
        try:
            self.msg.setText(self.api.executar_backup(tipo))
        except ErroAPI as exc:
            self.erro.setText(exc.mensagem)
            return
        self.carregar()
        self._acompanhar.start()

    def testar(self) -> None:
        self.erro.clear()
        try:
            self.msg.setText(self.api.testar_restauracao_backup())
        except ErroAPI as exc:
            self.erro.setText(exc.mensagem)
            return
        self.carregar()
        self._acompanhar.start()
