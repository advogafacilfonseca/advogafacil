"""Assistente de migração do servidor (somente a Advogada Master)."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, QTimer, QUrl
from PySide6.QtGui import QColor, QDesktopServices
from PySide6.QtWidgets import (
    QAbstractItemView,
    QFileDialog,
    QFormLayout,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from advoga_shared.esquemas import SITUACOES_MIGRACAO, STATUS_SERVIDOR, EstadoMigracao, Migracao

from ...api_client.cliente import ClienteAPI, ErroAPI
from ..componentes.basicos import cartao, campo, rotulo
from ..componentes.formatos import data_hora_br
from ..tema.tema import CORES

TIPOS = {"exportacao": "Exportação (deste servidor)", "importacao": "Importação (neste servidor)"}


def tabela_conferencia(m: Migracao, pai: QWidget | None = None) -> QTableWidget:
    """Tabela do relatório: registros na origem e no servidor novo, tabela por tabela."""
    importacao = m.tipo == "importacao"
    colunas = ["Dados", "Na origem"] + (["No servidor novo", "Conferência"] if importacao else [])
    t = QTableWidget(len(m.tabelas), len(colunas), pai)
    t.setHorizontalHeaderLabels(colunas)
    t.verticalHeader().setVisible(False)
    t.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
    t.setAlternatingRowColors(True)
    for i, tab in enumerate(m.tabelas):
        valores = [tab.nome, str(tab.origem)]
        if importacao:
            valores += ["—" if tab.destino is None else str(tab.destino), "✓ Idêntico" if tab.conferida else "✗ DIFERENTE"]
        for j, v in enumerate(valores):
            item = QTableWidgetItem(v)
            if j >= 1:
                item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            if j == 3:
                item.setForeground(QColor(CORES["sucesso"] if tab.conferida else CORES["erro"]))
            t.setItem(i, j, item)
    cab = t.horizontalHeader()
    cab.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
    for j in range(1, len(colunas)):
        cab.setSectionResizeMode(j, QHeaderView.ResizeMode.ResizeToContents)
    return t


class TelaMigracao(QWidget):
    def __init__(self, api: ClienteAPI) -> None:
        super().__init__()
        self.api = api
        self.estado: EstadoMigracao | None = None
        # Pontos de confirmação (substituídos nos testes automáticos)
        self.confirmar = lambda titulo, texto: QMessageBox.question(
            self, titulo, texto, QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No) == QMessageBox.StandardButton.Yes
        self.escolher_arquivo = lambda sugestao: QFileDialog.getSaveFileName(
            self, "Salvar relatório da migração", sugestao, "PDF (*.pdf)")[0]
        self.abrir_arquivo = lambda caminho: QDesktopServices.openUrl(QUrl.fromLocalFile(caminho))

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
        lay.addWidget(rotulo("Migração de servidor", "titulo"))
        lay.addWidget(rotulo(
            "Leva o sistema inteiro para um computador servidor novo: usuários e permissões, clientes, processos, "
            "documentos, contratos, parcelas, pagamentos, agenda, pendências, configurações e histórico. "
            "Ninguém precisa recadastrar nada. Durante a migração este servidor fica em modo somente leitura e, "
            "no fim, é desativado para nunca existirem duas bases oficiais.", "subtitulo", True))

        c = cartao()
        lc = QVBoxLayout(c)
        lc.setContentsMargins(14, 10, 14, 10)
        lc.addWidget(rotulo("Este servidor", "rotuloCampo"))
        self.situacao = QLabel("—")
        self.situacao.setWordWrap(True)
        self.situacao.setStyleSheet(f"font-weight:600; color:{CORES['dourado_claro']};")
        lc.addWidget(self.situacao)
        lay.addWidget(c)

        self.andamento = QLabel()
        self.andamento.setWordWrap(True)
        self.andamento.setStyleSheet(f"color:{CORES['aviso']}; border:1px solid {CORES['aviso']}; border-radius:6px;"
                                     "padding:10px; font-weight:600;")
        self.andamento.hide()
        lay.addWidget(self.andamento)

        # ---- 1. Exportar
        self.grupo_exportar = QGroupBox("1. Exportar para o servidor novo")
        fe = QFormLayout(self.grupo_exportar)
        fe.addRow("", rotulo("A pasta é do COMPUTADOR SERVIDOR (ex.: E:\\Migracao num HD externo ou pen drive "
                             "ligado nele). O pacote é criptografado com a senha abaixo.", "rotuloCampo", True))
        self.destino = campo("E:\\Migracao", maximo=400)
        self.btn_verificar = QPushButton("Verificar")
        self.btn_verificar.clicked.connect(self.verificar)
        linha = QHBoxLayout()
        linha.addWidget(self.destino, 1)
        linha.addWidget(self.btn_verificar)
        fe.addRow("Pasta do pacote:", linha)
        self.res_destino = rotulo("", "rotuloCampo", True)
        fe.addRow("", self.res_destino)
        self.senha = campo("Mínimo de 12 caracteres", senha=True, maximo=200)
        self.senha2 = campo("Repita a senha", senha=True, maximo=200)
        l2 = QHBoxLayout()
        l2.addWidget(self.senha, 1)
        l2.addWidget(self.senha2, 1)
        fe.addRow("Senha do pacote:", l2)
        fe.addRow("", rotulo("Anote esta senha: ela será pedida no servidor novo. Ela não fica gravada.",
                             "rotuloCampo", True))
        self.senha_master_exp = campo("Sua senha de login", senha=True, maximo=128)
        fe.addRow("Confirme sua senha:", self.senha_master_exp)
        self.btn_exportar = QPushButton("Exportar para o servidor novo")
        self.btn_exportar.setObjectName("primario")
        self.btn_exportar.clicked.connect(self.exportar)
        fe.addRow("", self.btn_exportar)
        lay.addWidget(self.grupo_exportar)

        # ---- 2. Concluir
        self.grupo_concluir = QGroupBox("2. Concluir a migração")
        fc = QFormLayout(self.grupo_concluir)
        self.info_pacote = rotulo("", "rotuloCampo", True)
        self.info_pacote.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        fc.addRow("", self.info_pacote)
        self.codigo = campo("XXXX-XXXX-XXXX", maximo=20)
        self.codigo.setMaximumWidth(220)
        fc.addRow("Código de confirmação:", self.codigo)
        self.senha_master_conc = campo("Sua senha de login", senha=True, maximo=128)
        fc.addRow("Confirme sua senha:", self.senha_master_conc)
        acoes = QHBoxLayout()
        self.btn_concluir = QPushButton("Concluir e desativar este servidor")
        self.btn_concluir.setObjectName("primario")
        self.btn_concluir.clicked.connect(self.concluir)
        self.btn_cancelar = QPushButton("Cancelar a migração")
        self.btn_cancelar.clicked.connect(self.cancelar)
        acoes.addWidget(self.btn_concluir)
        acoes.addWidget(self.btn_cancelar)
        acoes.addStretch()
        fc.addRow("", acoes)
        lay.addWidget(self.grupo_concluir)

        self.msg = rotulo("", "sucesso", True)
        self.erro = rotulo("", "erro", True)
        lay.addWidget(self.msg)
        lay.addWidget(self.erro)

        # ---- Histórico
        lay.addWidget(rotulo("Histórico de migrações", "rotuloCampo"))
        colunas = ["Início", "Tipo", "Situação", "Por", "Detalhes"]
        self.tabela = QTableWidget(0, len(colunas))
        self.tabela.setHorizontalHeaderLabels(colunas)
        self.tabela.verticalHeader().setVisible(False)
        self.tabela.setAlternatingRowColors(True)
        self.tabela.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.tabela.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.tabela.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.tabela.setMinimumHeight(180)
        cab = self.tabela.horizontalHeader()
        for i in range(len(colunas) - 1):
            cab.setSectionResizeMode(i, QHeaderView.ResizeMode.ResizeToContents)
        cab.setSectionResizeMode(len(colunas) - 1, QHeaderView.ResizeMode.Stretch)
        self.tabela.itemSelectionChanged.connect(self._selecao)
        lay.addWidget(self.tabela)
        lh = QHBoxLayout()
        self.btn_relatorio = QPushButton("Salvar relatório em PDF")
        self.btn_relatorio.setEnabled(False)
        self.btn_relatorio.clicked.connect(self.salvar_relatorio)
        self.btn_atualizar = QPushButton("Atualizar")
        self.btn_atualizar.clicked.connect(self.carregar)
        lh.addWidget(self.btn_relatorio)
        lh.addWidget(self.btn_atualizar)
        lh.addStretch()
        lay.addLayout(lh)
        lay.addStretch()

        self._acompanhar = QTimer(self)
        self._acompanhar.setInterval(2000)
        self._acompanhar.timeout.connect(self.carregar)

    # ----------------------------------------------------------------- dados
    def showEvent(self, evento) -> None:  # noqa: N802
        super().showEvent(evento)
        self.carregar()

    def hideEvent(self, evento) -> None:  # noqa: N802
        self._acompanhar.stop()
        super().hideEvent(evento)

    def carregar(self) -> None:
        try:
            est = self.api.estado_migracao()
        except ErroAPI as exc:
            self.erro.setText(exc.mensagem)
            self._acompanhar.stop()
            return
        self.estado = est
        texto = STATUS_SERVIDOR.get(est.servidor_status, est.servidor_status)
        if est.migrado_de and est.migrado_em:
            texto += f"\nRecebeu os dados de outro servidor em {data_hora_br(est.migrado_em)}."
        self.situacao.setText(texto)
        atual = est.atual
        exportando = atual is not None and atual.situacao == "em_andamento"
        aguardando = atual is not None and atual.situacao == "exportada"
        self.grupo_exportar.setEnabled(est.servidor_status == "ativo" and atual is None)
        self.grupo_concluir.setEnabled(aguardando)
        if exportando:
            self.andamento.setText(f"Exportação em andamento: {atual.etapa or '...'}")
            self.andamento.show()
            if not self._acompanhar.isActive():
                self._acompanhar.start()
        elif aguardando:
            self.andamento.setText("Este servidor está em modo SOMENTE LEITURA até você concluir ou cancelar a "
                                   "migração.")
            self.andamento.show()
            self._acompanhar.stop()
            self.info_pacote.setText(
                f"Pacote: {atual.arquivo}\n{atual.mensagem or ''}\n\nPróximos passos: copie o pacote para o "
                "computador novo, instale o Advoga Fácil Servidor nele e, na primeira abertura do aplicativo, "
                "escolha \"Importar dados de outro servidor\". Depois informe aqui o código de confirmação "
                "mostrado no relatório da importação.")
        else:
            self.andamento.hide()
            self._acompanhar.stop()
            self.info_pacote.setText("Nenhuma exportação aguardando conclusão.")
        self._mostrar_historico(est.historico)

    def _mostrar_historico(self, itens: list[Migracao]) -> None:
        self.tabela.setRowCount(len(itens))
        for i, m in enumerate(itens):
            valores = [data_hora_br(m.iniciado_em), TIPOS.get(m.tipo, m.tipo),
                       SITUACOES_MIGRACAO.get(m.situacao, m.situacao), m.iniciado_por_nome or "—",
                       m.mensagem or m.etapa or ""]
            for j, v in enumerate(valores):
                item = QTableWidgetItem(v)
                item.setToolTip(v)
                if j == 0:
                    item.setData(Qt.ItemDataRole.UserRole, str(m.id))
                if j == 2 and m.situacao == "falhou":
                    item.setForeground(QColor(CORES["erro"]))
                self.tabela.setItem(i, j, item)
        self._selecao()

    def _migracao_selecionada(self) -> Migracao | None:
        linhas = self.tabela.selectionModel().selectedRows() if self.tabela.selectionModel() else []
        if not linhas or self.estado is None:
            return None
        return self.estado.historico[linhas[0].row()]

    def _selecao(self) -> None:
        m = self._migracao_selecionada()
        self.btn_relatorio.setEnabled(m is not None and m.tem_relatorio)

    # ----------------------------------------------------------------- ações
    def _limpar(self) -> None:
        self.msg.clear()
        self.erro.clear()

    def verificar(self) -> None:
        caminho = self.destino.text().strip()
        if not caminho:
            self.res_destino.setText("Informe a pasta.")
            return
        try:
            s = self.api.verificar_destino_migracao(caminho)
        except ErroAPI as exc:
            self.res_destino.setText(exc.mensagem)
            return
        self.res_destino.setText(("✓ " if s.disponivel else "✗ ") + s.mensagem)

    def exportar(self) -> None:
        self._limpar()
        if not self.destino.text().strip():
            self.erro.setText("Informe a pasta do pacote.")
            return
        if self.senha.text() != self.senha2.text():
            self.erro.setText("A confirmação não confere com a senha do pacote.")
            return
        if not self.confirmar("Exportar para o servidor novo",
                              "A partir de agora, ninguém poderá gravar alterações neste servidor (somente consulta) "
                              "até a migração ser concluída ou cancelada.\n\nDeseja continuar?"):
            return
        try:
            self.api.exportar_migracao(self.destino.text().strip(), self.senha.text(), self.senha2.text(),
                                       self.senha_master_exp.text())
        except ErroAPI as exc:
            self.erro.setText(exc.mensagem)
            return
        for c in (self.senha, self.senha2, self.senha_master_exp):
            c.clear()
        self.msg.setText("Exportação iniciada. Acompanhe o andamento acima.")
        self.carregar()
        self._acompanhar.start()

    def concluir(self) -> None:
        self._limpar()
        if not self.codigo.text().strip():
            self.erro.setText("Informe o código de confirmação mostrado no servidor novo.")
            return
        if not self.confirmar("Concluir a migração",
                              "Este servidor será DESATIVADO de forma definitiva: ninguém mais poderá entrar nele. "
                              "Confirme que o servidor novo já está funcionando.\n\nDeseja concluir?"):
            return
        try:
            m = self.api.concluir_migracao(self.codigo.text().strip(), self.senha_master_conc.text())
        except ErroAPI as exc:
            self.erro.setText(exc.mensagem)
            return
        self.senha_master_conc.clear()
        self.msg.setText(m.mensagem or "Migração concluída.")
        self.situacao.setText(STATUS_SERVIDOR["desativado"])
        self.grupo_concluir.setEnabled(False)
        self.grupo_exportar.setEnabled(False)
        self.andamento.hide()

    def cancelar(self) -> None:
        self._limpar()
        if not self.senha_master_conc.text():
            self.erro.setText("Confirme sua senha para cancelar a migração.")
            return
        if not self.confirmar("Cancelar a migração",
                              "Este servidor voltará a ser o servidor oficial e o pacote gerado será apagado.\n\n"
                              "Só cancele se o pacote NÃO foi importado em outro computador. Deseja cancelar?"):
            return
        try:
            m = self.api.cancelar_migracao(self.senha_master_conc.text())
        except ErroAPI as exc:
            self.erro.setText(exc.mensagem)
            return
        self.senha_master_conc.clear()
        self.msg.setText(m.mensagem or "Migração cancelada.")
        self.carregar()

    def salvar_relatorio(self) -> None:
        self._limpar()
        m = self._migracao_selecionada()
        if m is None:
            return
        sugestao = str(Path.home() / f"relatorio_migracao_{m.tipo}_{m.iniciado_em:%Y-%m-%d}.pdf")
        caminho = self.escolher_arquivo(sugestao)
        if not caminho:
            return
        try:
            destino = self.api.baixar_relatorio_migracao(str(m.id), Path(caminho))
        except ErroAPI as exc:
            self.erro.setText(exc.mensagem)
            return
        self.msg.setText(f"Relatório salvo em {destino}.")
        self.abrir_arquivo(str(destino))
