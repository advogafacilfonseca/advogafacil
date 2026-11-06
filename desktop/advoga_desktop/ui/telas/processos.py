"""Processos: lista, cadastro, ficha (dados, movimentações, documentos, histórico)."""

from __future__ import annotations

from datetime import date
from typing import Any

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QDialog,
    QFormLayout,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from advoga_shared.esquemas import SITUACOES_PROCESSO, TIPOS_PROXIMO_EVENTO, Processo
from advoga_shared.permissoes import Permissao
from advoga_shared.validacoes import formatar_cnj

from ...api_client.cliente import ClienteAPI, ErroAPI
from ..componentes.basicos import ajustar_altura, bloco_campo, campo, rotulo
from ..componentes.espera import cursor_espera
from ..componentes.formatos import data_br, data_hora_br, ler_data_br, ler_data_hora_br
from ..componentes.seletores import SeletorCliente
from .clientes import ROTULOS_CAMPOS as ROTULOS_CLIENTE

AREAS = ["Penal", "Processo Penal", "Execução Penal", "Juizado Especial Criminal", "Cível", "Família",
         "Trabalhista", "Previdenciário", "Administrativo", "Outra"]
FASES = ["Inquérito policial", "Denúncia / queixa", "Resposta à acusação", "Instrução", "Alegações finais",
         "Sentença", "Recurso", "Tribunais superiores", "Execução penal", "Trânsito em julgado"]

ROTULOS_CAMPOS = ROTULOS_CLIENTE | {
    "numero_cnj": "Número CNJ", "cliente_id": "Cliente", "tipo_acao": "Tipo de ação",
    "area_juridica": "Área jurídica", "tribunal": "Tribunal", "comarca": "Comarca", "vara": "Vara",
    "parte_contraria": "Parte contrária", "data_distribuicao": "Data de distribuição", "situacao": "Situação",
    "fase_processual": "Fase processual", "proximo_evento_tipo": "Próxima audiência/prazo (tipo)",
    "proximo_evento_em": "Próxima audiência/prazo (data)", "proximo_evento_descricao": "Próxima audiência/prazo",
    "descricao": "Descrição",
}
ACOES_PROCESSO = {
    "processo.criado": "Processo cadastrado",
    "processo.editado": "Dados alterados",
    "processo.movimentacao": "Movimentação registrada",
}


def _txt(v: Any) -> str:
    return "—" if v in (None, "") else str(v)


def numero(p) -> str:
    return formatar_cnj(p.numero_cnj) if p.numero_cnj else "Sem número"


def proximo_evento(p) -> str:
    if not p.proximo_evento_em:
        return ""
    return f"{TIPOS_PROXIMO_EVENTO.get(p.proximo_evento_tipo, '')} {data_hora_br(p.proximo_evento_em)}".strip()


def _combo_editavel(opcoes: list[str]) -> QComboBox:
    c = QComboBox()
    c.setEditable(True)
    c.addItem("")
    c.addItems(opcoes)
    c.setMinimumHeight(36)
    return c


# =========================================================================== formulário
class DialogoProcesso(QDialog):
    def __init__(self, api: ClienteAPI, processo: Processo | None = None,
                 cliente: tuple[str, str] | None = None, parent=None) -> None:
        super().__init__(parent)
        self.api = api
        self.original = processo
        self.resultado: Processo | None = None
        self.setWindowTitle("Editar processo" if processo else "Cadastrar processo")
        self.setMinimumSize(820, 660)
        externo = QVBoxLayout(self)
        externo.setContentsMargins(0, 0, 0, 0)
        rolagem = QScrollArea()
        rolagem.setWidgetResizable(True)
        conteudo = QWidget()
        lay = QVBoxLayout(conteudo)
        lay.setContentsMargins(28, 20, 28, 12)
        lay.addWidget(rotulo("Editar processo" if processo else "Cadastrar processo", "secao"))

        self.cliente = SeletorCliente(api)
        self.numero = campo("0000000-00.0000.0.00.0000", maximo=30)
        self.tipo = campo("Ex.: Ação Penal, Habeas Corpus, Revisão Criminal", maximo=150)
        self.area = _combo_editavel(AREAS)
        self.tribunal = campo("Ex.: TJSP, TRF3, STJ", maximo=120)
        self.comarca = campo(maximo=120)
        self.vara = campo(maximo=150)
        self.parte = campo("Ex.: Ministério Público do Estado", maximo=300)
        self.responsavel = QComboBox()
        self.responsavel.setMinimumHeight(36)
        self.responsavel.addItem("Não definido", None)
        try:
            for u in api.usuarios_ativos():
                self.responsavel.addItem(u.nome, str(u.id))
        except ErroAPI:
            pass
        self.distribuicao = campo("dd/mm/aaaa", maximo=10)
        self.situacao = QComboBox()
        self.situacao.setMinimumHeight(36)
        for chave, nome in SITUACOES_PROCESSO.items():
            self.situacao.addItem(nome, chave)
        self.fase = _combo_editavel(FASES)
        self.evento_tipo = QComboBox()
        self.evento_tipo.setMinimumHeight(36)
        self.evento_tipo.addItem("Nenhum", None)
        for chave, nome in TIPOS_PROXIMO_EVENTO.items():
            self.evento_tipo.addItem(nome, chave)
        self.evento_em = campo("dd/mm/aaaa hh:mm", maximo=16)
        self.evento_desc = campo("Ex.: Audiência de instrução e julgamento", maximo=300)
        self.descricao = QPlainTextEdit()
        self.descricao.setMinimumHeight(70)
        self.obs = QPlainTextEdit()
        self.obs.setMinimumHeight(70)

        g = QGridLayout()
        g.setHorizontalSpacing(14)
        g.addWidget(bloco_campo("Cliente vinculado *", self.cliente), 0, 0, 1, 2)
        g.addWidget(bloco_campo("Número CNJ", self.numero), 0, 2, 1, 2)
        g.addWidget(bloco_campo("Tipo de ação", self.tipo), 1, 0, 1, 2)
        g.addWidget(bloco_campo("Área jurídica", self.area), 1, 2)
        g.addWidget(bloco_campo("Data de distribuição", self.distribuicao), 1, 3)
        g.addWidget(bloco_campo("Tribunal", self.tribunal), 2, 0)
        g.addWidget(bloco_campo("Comarca", self.comarca), 2, 1)
        g.addWidget(bloco_campo("Vara", self.vara), 2, 2, 1, 2)
        g.addWidget(bloco_campo("Parte contrária", self.parte), 3, 0, 1, 2)
        g.addWidget(bloco_campo("Advogado responsável", self.responsavel), 3, 2, 1, 2)
        g.addWidget(bloco_campo("Situação", self.situacao), 4, 0)
        g.addWidget(bloco_campo("Fase processual", self.fase), 4, 1)
        g.addWidget(bloco_campo("Próxima audiência ou prazo", self.evento_tipo), 5, 0)
        g.addWidget(bloco_campo("Data e hora", self.evento_em), 5, 1)
        g.addWidget(bloco_campo("Descrição da audiência ou prazo", self.evento_desc), 5, 2, 1, 2)
        lay.addLayout(g)
        lay.addWidget(bloco_campo("Descrição do caso", self.descricao))
        lay.addWidget(bloco_campo("Observações", self.obs))
        rolagem.setWidget(conteudo)
        externo.addWidget(rolagem, 1)

        rodape = QVBoxLayout()
        rodape.setContentsMargins(28, 0, 28, 18)
        self.erro = rotulo("", "erro", True)
        rodape.addWidget(self.erro)
        b = QHBoxLayout()
        cancelar = QPushButton("Cancelar")
        self.btn_salvar = QPushButton("Salvar alterações" if processo else "Cadastrar")
        self.btn_salvar.setObjectName("primario")
        b.addWidget(cancelar)
        b.addStretch()
        b.addWidget(self.btn_salvar)
        rodape.addLayout(b)
        externo.addLayout(rodape)
        cancelar.clicked.connect(self.reject)
        self.btn_salvar.clicked.connect(self.salvar)
        if cliente:
            self.cliente.definir(*cliente)
        if processo:
            self._preencher(processo)
        self.resize(880, 760)

    def _preencher(self, p: Processo) -> None:
        self.cliente.definir(str(p.cliente_id), p.cliente_nome or "")
        self.numero.setText(formatar_cnj(p.numero_cnj) if p.numero_cnj else "")
        self.tipo.setText(p.tipo_acao or "")
        self.area.setCurrentText(p.area_juridica or "")
        self.tribunal.setText(p.tribunal or "")
        self.comarca.setText(p.comarca or "")
        self.vara.setText(p.vara or "")
        self.parte.setText(p.parte_contraria or "")
        if p.advogado_responsavel_id:
            i = self.responsavel.findData(str(p.advogado_responsavel_id))
            if i < 0:
                self.responsavel.addItem(p.advogado_responsavel_nome or "Usuário inativo", str(p.advogado_responsavel_id))
                i = self.responsavel.count() - 1
            self.responsavel.setCurrentIndex(i)
        self.distribuicao.setText(p.data_distribuicao.strftime("%d/%m/%Y") if p.data_distribuicao else "")
        self.situacao.setCurrentIndex(max(self.situacao.findData(p.situacao), 0))
        self.fase.setCurrentText(p.fase_processual or "")
        self.evento_tipo.setCurrentIndex(max(self.evento_tipo.findData(p.proximo_evento_tipo), 0))
        self.evento_em.setText(p.proximo_evento_em.astimezone().strftime("%d/%m/%Y %H:%M")
                               if p.proximo_evento_em else "")
        self.evento_desc.setText(p.proximo_evento_descricao or "")
        self.descricao.setPlainText(p.descricao or "")
        self.obs.setPlainText(p.observacoes or "")

    def _dados(self) -> dict[str, Any]:
        dist = ler_data_br(self.distribuicao.text())
        quando = ler_data_hora_br(self.evento_em.text())
        tipo = self.evento_tipo.currentData()
        if (tipo is None) != (quando is None):
            raise ValueError("Próxima audiência ou prazo: escolha o tipo e informe a data e hora.")
        return {
            "cliente_id": self.cliente.cliente_id,
            "numero_cnj": self.numero.text().strip() or None,
            "tipo_acao": self.tipo.text().strip() or None,
            "area_juridica": self.area.currentText().strip() or None,
            "tribunal": self.tribunal.text().strip() or None,
            "comarca": self.comarca.text().strip() or None,
            "vara": self.vara.text().strip() or None,
            "parte_contraria": self.parte.text().strip() or None,
            "advogado_responsavel_id": self.responsavel.currentData(),
            "data_distribuicao": dist.isoformat() if dist else None,
            "situacao": self.situacao.currentData(),
            "fase_processual": self.fase.currentText().strip() or None,
            "proximo_evento_tipo": tipo,
            "proximo_evento_em": quando.isoformat() if quando else None,
            "proximo_evento_descricao": self.evento_desc.text().strip() or None,
            "descricao": self.descricao.toPlainText().strip() or None,
            "observacoes": self.obs.toPlainText().strip() or None,
        }

    def salvar(self) -> None:
        try:
            dados = self._dados()
        except ValueError as exc:
            self.erro.setText(str(exc))
            return
        if not dados["cliente_id"]:
            self.erro.setText("Escolha o cliente vinculado ao processo.")
            return
        try:
            with cursor_espera():
                if self.original is None:
                    self.resultado = self.api.criar_processo(dados)
                else:
                    dados["versao"] = self.original.versao
                    self.resultado = self.api.atualizar_processo(str(self.original.id), dados)
        except ErroAPI as exc:
            self.erro.setText(exc.mensagem)
            return
        self.accept()


class DialogoMovimentacao(QDialog):
    def __init__(self, api: ClienteAPI, processo_id: str, parent=None) -> None:
        super().__init__(parent)
        self.api = api
        self.processo_id = processo_id
        self.resultado = None
        self.setWindowTitle("Registrar movimentação")
        self.setMinimumWidth(560)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(24, 18, 24, 18)
        lay.addWidget(rotulo("Registrar movimentação", "secao"))
        lay.addWidget(rotulo("Movimentações não podem ser alteradas depois de registradas. Para corrigir, "
                             "registre uma nova movimentação explicando a correção.", "rotuloCampo", True))
        self.data = campo("dd/mm/aaaa", maximo=10)
        self.data.setText(date.today().strftime("%d/%m/%Y"))
        self.descricao = QPlainTextEdit()
        self.descricao.setMinimumHeight(110)
        lay.addWidget(bloco_campo("Data", self.data))
        lay.addWidget(bloco_campo("Descrição *", self.descricao))
        self.erro = rotulo("", "erro", True)
        lay.addWidget(self.erro)
        b = QHBoxLayout()
        cancelar = QPushButton("Cancelar")
        self.btn_salvar = QPushButton("Registrar")
        self.btn_salvar.setObjectName("primario")
        b.addWidget(cancelar)
        b.addStretch()
        b.addWidget(self.btn_salvar)
        lay.addLayout(b)
        cancelar.clicked.connect(self.reject)
        self.btn_salvar.clicked.connect(self.salvar)
        ajustar_altura(self)

    def salvar(self) -> None:
        try:
            d = ler_data_br(self.data.text())
        except ValueError as exc:
            self.erro.setText(str(exc))
            return
        texto = self.descricao.toPlainText().strip()
        if d is None or len(texto) < 3:
            self.erro.setText("Informe a data e descreva a movimentação.")
            return
        try:
            with cursor_espera():
                self.resultado = self.api.nova_movimentacao(self.processo_id, d.isoformat(), texto)
        except ErroAPI as exc:
            self.erro.setText(exc.mensagem)
            return
        self.accept()


def _tabela(colunas: list[str], esticar: int) -> QTableWidget:
    t = QTableWidget(0, len(colunas))
    t.setHorizontalHeaderLabels(colunas)
    t.verticalHeader().setVisible(False)
    t.setAlternatingRowColors(True)
    t.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
    t.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
    t.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
    t.setWordWrap(True)
    cab = t.horizontalHeader()
    for i in range(len(colunas)):
        cab.setSectionResizeMode(i, QHeaderView.ResizeMode.ResizeToContents)
    cab.setSectionResizeMode(esticar, QHeaderView.ResizeMode.Stretch)
    return t


# =============================================================================== ficha
class FichaProcesso(QDialog):
    alterado = Signal()

    def __init__(self, api: ClienteAPI, processo_id: str, parent=None) -> None:
        super().__init__(parent)
        self.api = api
        self.processo_id = processo_id
        self.processo: Processo | None = None
        self.setWindowTitle("Processo")
        self.setMinimumSize(900, 640)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(24, 18, 24, 18)
        topo = QHBoxLayout()
        caixa = QVBoxLayout()
        self.titulo = rotulo("", "titulo", True)
        self.subtitulo = rotulo("", "subtitulo", True)
        caixa.addWidget(self.titulo)
        caixa.addWidget(self.subtitulo)
        topo.addLayout(caixa, 1)
        self.btn_editar = QPushButton("Editar dados")
        self.btn_editar.setObjectName("primario")
        topo.addWidget(self.btn_editar, 0, Qt.AlignmentFlag.AlignTop)
        lay.addLayout(topo)

        self.abas = QTabWidget()
        rolagem = QScrollArea()
        rolagem.setWidgetResizable(True)
        self.aba_dados = QWidget()
        self.form = QFormLayout(self.aba_dados)
        self.form.setContentsMargins(20, 16, 20, 16)
        self.form.setHorizontalSpacing(24)
        self.form.setVerticalSpacing(8)
        rolagem.setWidget(self.aba_dados)
        self.abas.addTab(rolagem, "Dados do processo")

        aba_mov = QWidget()
        lm = QVBoxLayout(aba_mov)
        lm.setContentsMargins(12, 12, 12, 12)
        bm = QHBoxLayout()
        bm.addStretch()
        self.btn_movimentacao = QPushButton("Registrar movimentação")
        self.btn_movimentacao.setObjectName("primario")
        bm.addWidget(self.btn_movimentacao)
        lm.addLayout(bm)
        self.tabela_mov = _tabela(["Data", "Movimentação", "Registrado por", "Em"], 1)
        lm.addWidget(self.tabela_mov, 1)
        self.abas.addTab(aba_mov, "Movimentações")

        self.painel_docs = None
        if api.usuario and Permissao.DOCUMENTOS in api.usuario.permissoes:
            from .documentos import PainelDocumentos
            self.painel_docs = PainelDocumentos(api, processo_id=processo_id)
            self.abas.addTab(self.painel_docs, "Documentos")

        self.tabela_hist = _tabela(["Data e hora", "Usuário", "O que aconteceu"], 2)
        self.abas.addTab(self.tabela_hist, "Histórico")
        lay.addWidget(self.abas, 1)
        fechar = QPushButton("Fechar")
        fechar.clicked.connect(self.accept)
        lay.addWidget(fechar, 0, Qt.AlignmentFlag.AlignRight)

        self.btn_editar.clicked.connect(self.editar)
        self.btn_movimentacao.clicked.connect(self.registrar_movimentacao)
        self.abas.currentChanged.connect(self._ao_trocar_aba)
        self.carregar()
        self.carregar_movimentacoes()

    def _ao_trocar_aba(self, i: int) -> None:
        w = self.abas.widget(i)
        if w is self.tabela_hist:
            self.carregar_historico()
        elif self.painel_docs is not None and w is self.painel_docs:
            self.painel_docs.carregar(1)

    def carregar(self) -> None:
        with cursor_espera():
            self.processo = self.api.obter_processo(self.processo_id)
        p = self.processo
        if self.painel_docs is not None:
            self.painel_docs.cliente = (str(p.cliente_id), p.cliente_nome or "")
        self.titulo.setText(numero(p) + (f" · {p.tipo_acao}" if p.tipo_acao else ""))
        self.subtitulo.setText(f"Cliente: {p.cliente_nome}  ·  {SITUACOES_PROCESSO.get(p.situacao, p.situacao)}"
                               + (f"  ·  {proximo_evento(p)}" if p.proximo_evento_em else ""))
        self.setWindowTitle(f"Processo {numero(p)}")
        while self.form.rowCount():
            self.form.removeRow(0)
        linhas = [
            ("Cliente", p.cliente_nome), ("Número CNJ", numero(p)), ("Tipo de ação", p.tipo_acao),
            ("Área jurídica", p.area_juridica), ("Tribunal", p.tribunal), ("Comarca", p.comarca), ("Vara", p.vara),
            ("Parte contrária", p.parte_contraria), ("Advogado responsável", p.advogado_responsavel_nome),
            ("Data de distribuição", data_br(p.data_distribuicao) if p.data_distribuicao else None),
            ("Situação", SITUACOES_PROCESSO.get(p.situacao)), ("Fase processual", p.fase_processual),
            ("Próxima audiência ou prazo", " — ".join(x for x in [proximo_evento(p), p.proximo_evento_descricao] if x)),
            ("Descrição", p.descricao), ("Observações", p.observacoes),
            ("Cadastrado em", data_hora_br(p.criado_em)), ("Última alteração", data_hora_br(p.atualizado_em)),
        ]
        for rot, valor in linhas:
            v = rotulo(_txt(valor), quebra=True)
            v.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            self.form.addRow(rotulo(rot, "rotuloCampo"), v)

    def carregar_movimentacoes(self) -> None:
        try:
            movs = self.api.movimentacoes(self.processo_id)
        except ErroAPI as exc:
            QMessageBox.warning(self, "Movimentações", exc.mensagem)
            return
        self.tabela_mov.setRowCount(len(movs))
        for i, m in enumerate(movs):
            for j, v in enumerate([data_br(m.data_movimentacao), m.descricao, m.registrado_por_nome or "—",
                                   data_hora_br(m.registrado_em)]):
                self.tabela_mov.setItem(i, j, QTableWidgetItem(v))
        self.tabela_mov.resizeRowsToContents()
        self.abas.setTabText(1, f"Movimentações ({len(movs)})")

    def carregar_historico(self) -> None:
        try:
            itens = self.api.historico_processo(self.processo_id)
        except ErroAPI as exc:
            QMessageBox.warning(self, "Histórico", exc.mensagem)
            return
        self.tabela_hist.setRowCount(len(itens))
        for i, a in enumerate(itens):
            acao = ACOES_PROCESSO.get(a.acao, a.acao)
            det = ""
            if a.acao == "processo.editado" and a.detalhes:
                det = "; ".join(f"{ROTULOS_CAMPOS.get(k, k)}: {_txt(v.get('antes'))} → {_txt(v.get('depois'))}"
                                for k, v in a.detalhes.items()
                                if isinstance(v, dict) and k not in ("advogado_responsavel_id", "cliente_id"))
            elif a.acao == "processo.movimentacao" and a.detalhes:
                det = a.detalhes.get("descricao", "")
            for j, v in enumerate([data_hora_br(a.ocorrido_em), a.usuario_nome or "—",
                                   f"{acao}. {det}" if det else acao]):
                self.tabela_hist.setItem(i, j, QTableWidgetItem(v))
        self.tabela_hist.resizeRowsToContents()

    def editar(self) -> None:
        if not self.processo:
            return
        d = DialogoProcesso(self.api, self.processo, parent=self)
        if d.exec() and d.resultado:
            self.carregar()
            self.alterado.emit()
        elif "alterado por outra pessoa" in d.erro.text():
            self.carregar()

    def registrar_movimentacao(self) -> None:
        d = DialogoMovimentacao(self.api, self.processo_id, self)
        if d.exec():
            self.carregar_movimentacoes()
            self.alterado.emit()


# ============================================================================ listagem
class PainelProcessos(QWidget):
    """Lista de processos (de todos os clientes ou de um cliente)."""

    COLUNAS = ["Número", "Cliente", "Tipo de ação", "Parte contrária", "Fase", "Situação", "Próxima audiência/prazo"]
    POR_PAGINA = 50

    def __init__(self, api: ClienteAPI, cliente: tuple[str, str] | None = None) -> None:
        super().__init__()
        self.api = api
        self.cliente = cliente
        self.pagina = 1
        self.total = 0
        lay = QVBoxLayout(self)
        lay.setContentsMargins(12, 12, 12, 12)
        filtros = QHBoxLayout()
        self.busca = campo("Procurar por número, parte contrária ou tipo de ação (mínimo 3 caracteres)", maximo=100)
        self.situacao = QComboBox()
        self.situacao.setMinimumHeight(36)
        self.situacao.addItem("Todas as situações", None)
        for chave, nome in SITUACOES_PROCESSO.items():
            self.situacao.addItem(nome, chave)
        self.btn_novo = QPushButton("Cadastrar processo")
        self.btn_novo.setObjectName("primario")
        filtros.addWidget(self.busca, 1)
        filtros.addWidget(self.situacao)
        filtros.addWidget(self.btn_novo)
        lay.addLayout(filtros)
        self.tabela = _tabela(self.COLUNAS, 3)
        self.tabela.setColumnHidden(1, cliente is not None)
        lay.addWidget(self.tabela, 1)
        rodape = QHBoxLayout()
        self.info = rotulo("", "rotuloCampo")
        self.btn_ant = QPushButton("‹ Anterior")
        self.btn_prox = QPushButton("Próxima ›")
        rodape.addWidget(self.info)
        rodape.addStretch()
        rodape.addWidget(self.btn_ant)
        rodape.addWidget(self.btn_prox)
        lay.addLayout(rodape)
        self._atraso = QTimer(self)
        self._atraso.setSingleShot(True)
        self._atraso.setInterval(350)
        self._atraso.timeout.connect(lambda: self.carregar(1))
        self.busca.textChanged.connect(self._ao_digitar)
        self.situacao.currentIndexChanged.connect(lambda: self.carregar(1))
        self.btn_novo.clicked.connect(self.cadastrar)
        self.btn_ant.clicked.connect(lambda: self.carregar(self.pagina - 1))
        self.btn_prox.clicked.connect(lambda: self.carregar(self.pagina + 1))
        self.tabela.cellDoubleClicked.connect(lambda linha, _c: self.abrir_linha(linha))
        self.ids: list[str] = []

    def _ao_digitar(self, texto: str) -> None:
        t = texto.strip()
        if len(t) == 0 or len(t) >= 3:
            self._atraso.start()
        else:
            self.info.setText("Digite pelo menos 3 caracteres para pesquisar.")

    def carregar(self, pagina: int = 1) -> None:
        termo = self.busca.text().strip()
        if 0 < len(termo) < 3:
            return
        try:
            with cursor_espera():
                r = self.api.listar_processos(termo, self.cliente[0] if self.cliente else None,
                                              self.situacao.currentData(), pagina, self.POR_PAGINA)
        except ErroAPI as exc:
            self.info.setText(exc.mensagem)
            return
        self.pagina, self.total = r.pagina, r.total
        self.ids = [str(p.id) for p in r.itens]
        self.tabela.setRowCount(len(r.itens))
        for i, p in enumerate(r.itens):
            valores = [numero(p), p.cliente_nome, p.tipo_acao or "", p.parte_contraria or "", p.fase_processual or "",
                       SITUACOES_PROCESSO.get(p.situacao, p.situacao), proximo_evento(p)]
            for j, v in enumerate(valores):
                self.tabela.setItem(i, j, QTableWidgetItem(v))
        paginas = max(1, -(-r.total // self.POR_PAGINA))
        self.info.setText("Nenhum processo encontrado." if r.total == 0 else
                          f"{r.total} processo(s) · página {r.pagina} de {paginas} · dê dois cliques para abrir")
        self.btn_ant.setEnabled(r.pagina > 1)
        self.btn_prox.setEnabled(r.pagina < paginas)

    def abrir_linha(self, linha: int) -> None:
        if 0 <= linha < len(self.ids):
            self.abrir(self.ids[linha])

    def abrir(self, processo_id: str) -> None:
        try:
            ficha = FichaProcesso(self.api, processo_id, self)
        except ErroAPI as exc:
            QMessageBox.warning(self, "Processo", exc.mensagem)
            return
        ficha.alterado.connect(lambda: self.carregar(self.pagina))
        ficha.exec()

    def cadastrar(self) -> None:
        d = DialogoProcesso(self.api, cliente=self.cliente, parent=self)
        if self.cliente:
            d.cliente.btn.setEnabled(False)
        if d.exec() and d.resultado:
            self.carregar(1)
            self.abrir(str(d.resultado.id))


class TelaProcessos(QWidget):
    def __init__(self, api: ClienteAPI) -> None:
        super().__init__()
        lay = QVBoxLayout(self)
        lay.setContentsMargins(28, 24, 28, 20)
        lay.addWidget(rotulo("Processos", "titulo"))
        self.painel = PainelProcessos(api)
        self.painel.layout().setContentsMargins(0, 8, 0, 0)
        lay.addWidget(self.painel, 1)
        self._carregado = False

    def showEvent(self, evento) -> None:  # noqa: N802
        super().showEvent(evento)
        if not self._carregado:
            self._carregado = True
            self.painel.carregar(1)
