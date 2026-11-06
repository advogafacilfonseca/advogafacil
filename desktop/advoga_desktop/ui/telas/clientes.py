"""Clientes: procura, cadastro, ficha (dados pessoais e histórico), encerramento.

Todas as regras (validação, duplicidade, permissão, edição simultânea) são do servidor;
a tela mostra as mensagens que ele devolve.
"""

from __future__ import annotations

import json
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
    QInputDialog,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from advoga_shared.esquemas import Cliente
from advoga_shared.permissoes import Permissao
from advoga_shared.validacoes import UFS

from ...api_client.cliente import ClienteAPI, ErroAPI
from ..componentes.basicos import ajustar_altura, bloco_campo, campo, limpar_formulario, rotulo
from ..componentes.espera import cursor_espera
from ..componentes.formatos import data_br, data_hora_br, formatar_cep, formatar_cpf, formatar_telefone, ler_data_br

SITUACOES = {"ativo": "Ativo", "encerrado": "Atendimento encerrado"}

ACOES_CLIENTE = {
    "cliente.criado": "Cliente cadastrado",
    "cliente.editado": "Dados alterados",
    "cliente.encerrado": "Atendimento encerrado",
    "cliente.reativado": "Cliente reativado",
}

ROTULOS_CAMPOS = {
    "nome_completo": "Nome completo", "cpf": "CPF", "rg": "RG", "data_nascimento": "Data de nascimento",
    "telefone_principal": "Telefone principal", "telefone_secundario": "Telefone secundário",
    "email": "E-mail", "cep": "CEP", "logradouro": "Endereço", "numero": "Número",
    "complemento": "Complemento", "bairro": "Bairro", "cidade": "Cidade", "uf": "UF",
    "observacoes": "Observações", "data_inicio_atendimento": "Início do atendimento",
    "advogado_responsavel_id": "Advogado responsável", "motivo": "Motivo",
}


def _txt(valor: Any) -> str:
    return "—" if valor in (None, "") else str(valor)


def descrever_alteracoes(acao: str, detalhes: dict | None) -> str:
    if not detalhes or acao in ("cliente.criado", "cliente.reativado"):
        return ""
    if acao == "cliente.editado":
        partes = []
        for chave, mudanca in detalhes.items():
            if isinstance(mudanca, dict) and "depois" in mudanca:
                nome = ROTULOS_CAMPOS.get(chave, chave)
                if chave == "advogado_responsavel_id":
                    partes.append(f"{nome} alterado")
                else:
                    partes.append(f"{nome}: {_txt(mudanca.get('antes'))} → {_txt(mudanca.get('depois'))}")
        return "; ".join(partes)
    if "motivo" in detalhes:
        return f"Motivo: {detalhes['motivo']}"
    texto = json.dumps(detalhes, ensure_ascii=False)
    return texto if len(texto) <= 160 else texto[:157] + "..."


# =========================================================================== formulário
class DialogoCliente(QDialog):
    """Cadastro de novo cliente ou edição dos dados de um cliente existente."""

    def __init__(self, api: ClienteAPI, cliente: Cliente | None = None, parent=None) -> None:
        super().__init__(parent)
        self.api = api
        self.original = cliente
        self.resultado: Cliente | None = None
        self.setWindowTitle("Editar cliente" if cliente else "Cadastrar cliente")
        self.setMinimumWidth(760)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(28, 20, 28, 20)
        lay.addWidget(rotulo("Editar dados do cliente" if cliente else "Cadastrar cliente", "secao"))
        lay.addWidget(rotulo("Somente o nome é obrigatório. O CPF, quando informado, é conferido e não "
                             "pode se repetir entre clientes.", "rotuloCampo", True))

        self.nome = campo("Nome completo do cliente", maximo=150)
        self.cpf = campo("000.000.000-00", maximo=14)
        self.rg = campo(maximo=30)
        self.nascimento = campo("dd/mm/aaaa", maximo=10)
        self.tel1 = campo("(00) 00000-0000", maximo=20)
        self.tel2 = campo("(00) 00000-0000", maximo=20)
        self.email = campo("email@exemplo.com", maximo=254)
        self.cep = campo("00000-000", maximo=9)
        self.logradouro = campo("Rua, avenida...", maximo=200)
        self.numero = campo(maximo=20)
        self.complemento = campo(maximo=100)
        self.bairro = campo(maximo=100)
        self.cidade = campo(maximo=100)
        self.uf = QComboBox()
        self.uf.addItem("—", None)
        for uf in sorted(UFS):
            self.uf.addItem(uf, uf)
        self.inicio = campo("dd/mm/aaaa", maximo=10)
        self.responsavel = QComboBox()
        self.responsavel.addItem("Não definido", None)
        try:
            for u in api.usuarios_ativos():
                self.responsavel.addItem(u.nome, str(u.id))
        except ErroAPI:
            pass  # sem a lista, o campo fica "Não definido"; o servidor valida de qualquer forma
        self.obs = QPlainTextEdit()
        self.obs.setPlaceholderText("Observações gerais sobre o cliente")
        self.obs.setMinimumHeight(80)

        g = QGridLayout()
        g.setHorizontalSpacing(14)
        g.addWidget(bloco_campo("Nome completo *", self.nome), 0, 0, 1, 4)
        g.addWidget(bloco_campo("CPF", self.cpf), 1, 0)
        g.addWidget(bloco_campo("RG", self.rg), 1, 1)
        g.addWidget(bloco_campo("Data de nascimento", self.nascimento), 1, 2)
        g.addWidget(bloco_campo("Início do atendimento", self.inicio), 1, 3)
        g.addWidget(bloco_campo("Telefone principal", self.tel1), 2, 0)
        g.addWidget(bloco_campo("Telefone secundário", self.tel2), 2, 1)
        g.addWidget(bloco_campo("E-mail", self.email), 2, 2, 1, 2)
        g.addWidget(bloco_campo("CEP", self.cep), 3, 0)
        g.addWidget(bloco_campo("Endereço", self.logradouro), 3, 1, 1, 2)
        g.addWidget(bloco_campo("Número", self.numero), 3, 3)
        g.addWidget(bloco_campo("Complemento", self.complemento), 4, 0)
        g.addWidget(bloco_campo("Bairro", self.bairro), 4, 1)
        g.addWidget(bloco_campo("Cidade", self.cidade), 4, 2)
        g.addWidget(bloco_campo("UF", self.uf), 4, 3)
        g.addWidget(bloco_campo("Advogado responsável", self.responsavel), 5, 0, 1, 2)
        lay.addLayout(g)
        lay.addWidget(bloco_campo("Observações", self.obs))

        self.erro = rotulo("", "erro", True)
        lay.addWidget(self.erro)
        b = QHBoxLayout()
        cancelar = QPushButton("Cancelar")
        self.btn_salvar = QPushButton("Salvar alterações" if cliente else "Cadastrar")
        self.btn_salvar.setObjectName("primario")
        b.addWidget(cancelar)
        b.addStretch()
        b.addWidget(self.btn_salvar)
        lay.addLayout(b)
        cancelar.clicked.connect(self.reject)
        self.btn_salvar.clicked.connect(self.salvar)
        if cliente:
            self._preencher(cliente)
        ajustar_altura(self)

    def _preencher(self, c: Cliente) -> None:
        self.nome.setText(c.nome_completo)
        self.cpf.setText(formatar_cpf(c.cpf))
        self.rg.setText(c.rg or "")
        self.nascimento.setText(c.data_nascimento.strftime("%d/%m/%Y") if c.data_nascimento else "")
        self.inicio.setText(c.data_inicio_atendimento.strftime("%d/%m/%Y") if c.data_inicio_atendimento else "")
        self.tel1.setText(formatar_telefone(c.telefone_principal))
        self.tel2.setText(formatar_telefone(c.telefone_secundario))
        self.email.setText(c.email or "")
        self.cep.setText(formatar_cep(c.cep))
        self.logradouro.setText(c.logradouro or "")
        self.numero.setText(c.numero or "")
        self.complemento.setText(c.complemento or "")
        self.bairro.setText(c.bairro or "")
        self.cidade.setText(c.cidade or "")
        i = self.uf.findData(c.uf)
        self.uf.setCurrentIndex(max(i, 0))
        if c.advogado_responsavel_id:
            i = self.responsavel.findData(str(c.advogado_responsavel_id))
            if i < 0:  # responsável desativado: mantém o vínculo existente visível
                self.responsavel.addItem(c.advogado_responsavel_nome or "Usuário inativo",
                                         str(c.advogado_responsavel_id))
                i = self.responsavel.count() - 1
            self.responsavel.setCurrentIndex(i)
        self.obs.setPlainText(c.observacoes or "")

    def _dados(self) -> dict[str, Any]:
        def t(w: QLineEdit) -> str | None:
            return w.text().strip() or None
        nasc = ler_data_br(self.nascimento.text())
        ini = ler_data_br(self.inicio.text())
        return {
            "nome_completo": t(self.nome), "cpf": t(self.cpf), "rg": t(self.rg),
            "data_nascimento": nasc.isoformat() if nasc else None,
            "data_inicio_atendimento": ini.isoformat() if ini else None,
            "telefone_principal": t(self.tel1), "telefone_secundario": t(self.tel2),
            "email": (t(self.email) or "").lower() or None, "cep": t(self.cep),
            "logradouro": t(self.logradouro), "numero": t(self.numero), "complemento": t(self.complemento),
            "bairro": t(self.bairro), "cidade": t(self.cidade), "uf": self.uf.currentData(),
            "advogado_responsavel_id": self.responsavel.currentData(),
            "observacoes": self.obs.toPlainText().strip() or None,
        }

    def _mostrar_erro(self, texto: str) -> None:
        self.erro.setText(texto)
        ajustar_altura(self)

    def salvar(self) -> None:
        try:
            dados = self._dados()
        except ValueError as exc:
            self._mostrar_erro(str(exc))
            return
        if not dados["nome_completo"] or len(dados["nome_completo"]) < 3:
            self._mostrar_erro("Informe o nome completo do cliente.")
            return
        try:
            with cursor_espera():
                if self.original is None:
                    self.resultado = self._cadastrar(dados)
                    if self.resultado is None:
                        return
                else:
                    dados["versao"] = self.original.versao
                    self.resultado = self.api.atualizar_cliente(str(self.original.id), dados)
        except ErroAPI as exc:
            self._mostrar_erro(exc.mensagem)
            return
        self.accept()

    def _cadastrar(self, dados: dict[str, Any]) -> Cliente | None:
        try:
            return self.api.criar_cliente(dados)
        except ErroAPI as exc:
            if exc.status != 428:
                raise
            # Possível cadastro repetido (mesmo nome, sem CPF para diferenciar): a pessoa decide.
            r = QMessageBox.question(self, "Possível cadastro repetido",
                                     f"{exc.mensagem}\n\nDeseja cadastrar mesmo assim como um novo cliente?",
                                     QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                                     QMessageBox.StandardButton.No)
            if r != QMessageBox.StandardButton.Yes:
                return None
            return self.api.criar_cliente(dados | {"confirmar_possivel_duplicidade": True})


# =============================================================================== ficha
class FichaCliente(QDialog):
    """Ficha do cliente: dados pessoais e histórico. Processos, contratos, financeiro, agenda e
    documentos aparecem como abas conforme as permissões de quem está usando; contratos,
    financeiro e agenda entram nas etapas em que cada módulo for construído."""

    alterado = Signal()

    def __init__(self, api: ClienteAPI, cliente_id: str, parent=None) -> None:
        super().__init__(parent)
        self.api = api
        self.cliente_id = cliente_id
        self.cliente: Cliente | None = None
        self.setWindowTitle("Ficha do cliente")
        self.setMinimumSize(860, 600)
        self.resize(1040, 700)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(24, 18, 24, 18)
        topo = QHBoxLayout()
        caixa_nome = QVBoxLayout()
        self.titulo = rotulo("", "titulo", True)
        self.situacao = rotulo("", "etiquetaEncerrado", True)
        caixa_nome.addWidget(self.titulo)
        caixa_nome.addWidget(self.situacao)
        topo.addLayout(caixa_nome, 1)
        self.btn_editar = QPushButton("Editar dados")
        self.btn_encerrar = QPushButton("Encerrar atendimento")
        self.btn_reativar = QPushButton("Reativar cliente")
        for btn in (self.btn_editar, self.btn_encerrar, self.btn_reativar):
            topo.addWidget(btn, 0, Qt.AlignmentFlag.AlignTop)
        self.btn_editar.setObjectName("primario")
        lay.addLayout(topo)

        self.abas = QTabWidget()
        self.aba_dados = QWidget()
        self.form = QFormLayout(self.aba_dados)
        self.form.setContentsMargins(20, 16, 20, 16)
        self.form.setHorizontalSpacing(24)
        self.form.setVerticalSpacing(8)
        self.abas.addTab(self.aba_dados, "Dados pessoais")
        self.tabela_hist = QTableWidget(0, 3)
        self.tabela_hist.setHorizontalHeaderLabels(["Data e hora", "Usuário", "O que aconteceu"])
        self.tabela_hist.verticalHeader().setVisible(False)
        self.tabela_hist.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.tabela_hist.setWordWrap(True)
        cab = self.tabela_hist.horizontalHeader()
        cab.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        cab.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        cab.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        self.painel_processos = None
        self.painel_docs = None
        self.painel_contratos = None
        permissoes = api.usuario.permissoes if api.usuario else []
        if Permissao.PROCESSOS in permissoes:
            from .processos import PainelProcessos
            self.painel_processos = PainelProcessos(api, cliente=(cliente_id, ""))
            self.abas.addTab(self.painel_processos, "Processos")
        if Permissao.DOCUMENTOS in permissoes:
            from .documentos import PainelDocumentos
            self.painel_docs = PainelDocumentos(api, cliente=(cliente_id, ""))
            self.abas.addTab(self.painel_docs, "Documentos")
        if Permissao.CONTRATOS in permissoes or Permissao.FINANCEIRO in permissoes:
            from .financeiro import PainelContratos
            self.painel_contratos = PainelContratos(api, cliente=(cliente_id, ""))
            self.abas.addTab(self.painel_contratos, "Contratos e financeiro"
                             if Permissao.FINANCEIRO in permissoes else "Contratos")
        self.abas.addTab(self.tabela_hist, "Histórico")
        lay.addWidget(self.abas, 1)

        fechar = QPushButton("Fechar")
        fechar.clicked.connect(self.accept)
        lay.addWidget(fechar, 0, Qt.AlignmentFlag.AlignRight)
        self.btn_editar.clicked.connect(self.editar)
        self.btn_encerrar.clicked.connect(self.encerrar)
        self.btn_reativar.clicked.connect(self.reativar)
        self.abas.currentChanged.connect(self._ao_trocar_aba)
        self.carregar()

    def _ao_trocar_aba(self, _i: int) -> None:
        w = self.abas.currentWidget()
        if w is self.tabela_hist:
            self.carregar_historico()
        elif w is not None and w in (self.painel_processos, self.painel_docs, self.painel_contratos):
            w.carregar(1)

    def carregar(self) -> None:
        with cursor_espera():
            self.cliente = self.api.obter_cliente(self.cliente_id)
        for painel in (self.painel_processos, self.painel_docs, self.painel_contratos):
            if painel is not None:
                painel.cliente = (self.cliente_id, self.cliente.nome_completo)
        self._mostrar(self.cliente)
        if self.abas.currentWidget() is self.tabela_hist:
            self.carregar_historico()

    def _mostrar(self, c: Cliente) -> None:
        self.titulo.setText(c.nome_completo)
        self.setWindowTitle(f"Ficha do cliente — {c.nome_completo}")
        if c.situacao == "encerrado":
            self.situacao.setText(f"Atendimento encerrado em {data_br(c.encerrado_em)}"
                                  f"{' · ' + c.motivo_encerramento if c.motivo_encerramento else ''}")
        else:
            self.situacao.setText("")
        self.btn_encerrar.setVisible(c.situacao == "ativo")
        self.btn_reativar.setVisible(c.situacao == "encerrado")
        limpar_formulario(self.form)
        endereco = ", ".join(p for p in [c.logradouro, c.numero, c.complemento] if p)
        local = " / ".join(p for p in [c.bairro, f"{c.cidade}/{c.uf}" if c.cidade and c.uf else (c.cidade or c.uf)] if p)
        linhas = [
            ("CPF", formatar_cpf(c.cpf)), ("RG", c.rg), ("Data de nascimento", data_br(c.data_nascimento)
                                                     if c.data_nascimento else None),
            ("Telefone principal", formatar_telefone(c.telefone_principal)),
            ("Telefone secundário", formatar_telefone(c.telefone_secundario)), ("E-mail", c.email),
            ("Endereço", endereco), ("Bairro / Cidade", local), ("CEP", formatar_cep(c.cep)),
            ("Advogado responsável", c.advogado_responsavel_nome),
            ("Início do atendimento", data_br(c.data_inicio_atendimento) if c.data_inicio_atendimento else None),
            ("Observações", c.observacoes),
            ("Cadastrado em", data_hora_br(c.criado_em)), ("Última alteração", data_hora_br(c.atualizado_em)),
        ]
        for rot, valor in linhas:
            v = rotulo(_txt(valor), quebra=True)
            v.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            self.form.addRow(rotulo(rot, "rotuloCampo"), v)

    def carregar_historico(self) -> None:
        try:
            with cursor_espera():
                itens = self.api.historico_cliente(self.cliente_id)
        except ErroAPI as exc:
            QMessageBox.warning(self, "Histórico", exc.mensagem)
            return
        self.tabela_hist.setRowCount(len(itens))
        for i, a in enumerate(itens):
            acao = ACOES_CLIENTE.get(a.acao, a.acao)
            desc = descrever_alteracoes(a.acao, a.detalhes)
            valores = [data_hora_br(a.ocorrido_em), a.usuario_nome or "—", f"{acao}. {desc}" if desc else acao]
            for j, v in enumerate(valores):
                self.tabela_hist.setItem(i, j, QTableWidgetItem(v))
        self.tabela_hist.resizeRowsToContents()

    def _apos_gravar(self, c: Cliente) -> None:
        self.cliente = c
        self._mostrar(c)
        if self.abas.currentWidget() is self.tabela_hist:
            self.carregar_historico()
        self.alterado.emit()

    def _tratar_erro(self, exc: ErroAPI) -> None:
        QMessageBox.warning(self, "Não foi possível concluir", exc.mensagem)
        if exc.status == 409:
            self.carregar()  # mostra a versão atual gravada por outra pessoa

    def editar(self) -> None:
        if not self.cliente:
            return
        d = DialogoCliente(self.api, self.cliente, self)
        if d.exec() and d.resultado:
            self._apos_gravar(d.resultado)
        elif d.erro.text() and "alterado por outra pessoa" in d.erro.text():
            self.carregar()

    def encerrar(self) -> None:
        if not self.cliente:
            return
        motivo, ok = QInputDialog.getText(
            self, "Encerrar atendimento",
            "O cadastro e todo o histórico continuam guardados.\nInforme o motivo do encerramento:")
        if not ok:
            return
        try:
            with cursor_espera():
                self._apos_gravar(self.api.encerrar_cliente(self.cliente_id, motivo.strip(), self.cliente.versao))
        except ErroAPI as exc:
            self._tratar_erro(exc)

    def reativar(self) -> None:
        if not self.cliente:
            return
        if QMessageBox.question(self, "Reativar cliente", f"Reativar {self.cliente.nome_completo}?") != \
                QMessageBox.StandardButton.Yes:
            return
        try:
            with cursor_espera():
                self._apos_gravar(self.api.reativar_cliente(self.cliente_id, self.cliente.versao))
        except ErroAPI as exc:
            self._tratar_erro(exc)


# ============================================================================ listagem
class TelaClientes(QWidget):
    POR_PAGINA = 50

    def __init__(self, api: ClienteAPI) -> None:
        super().__init__()
        self.api = api
        self.pagina = 1
        self.total = 0
        lay = QVBoxLayout(self)
        lay.setContentsMargins(28, 24, 28, 20)
        topo = QHBoxLayout()
        topo.addWidget(rotulo("Clientes", "titulo"))
        topo.addStretch()
        self.btn_novo = QPushButton("Cadastrar cliente")
        self.btn_novo.setObjectName("primario")
        topo.addWidget(self.btn_novo)
        lay.addLayout(topo)

        filtros = QHBoxLayout()
        self.busca = campo("Procurar por nome, CPF ou telefone (mínimo 3 caracteres)", maximo=100)
        self.situacao = QComboBox()
        self.situacao.addItem("Ativos", "ativo")
        self.situacao.addItem("Atendimento encerrado", "encerrado")
        self.situacao.addItem("Todos", None)
        self.situacao.setMinimumHeight(36)
        filtros.addWidget(self.busca, 1)
        filtros.addWidget(self.situacao)
        lay.addLayout(filtros)

        self.tabela = QTableWidget(0, 5)
        self.tabela.setHorizontalHeaderLabels(["Nome", "CPF", "Telefone", "Cidade/UF", "Situação"])
        self.tabela.verticalHeader().setVisible(False)
        self.tabela.setAlternatingRowColors(True)
        self.tabela.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.tabela.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.tabela.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        cab = self.tabela.horizontalHeader()
        cab.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        for i in range(1, 5):
            cab.setSectionResizeMode(i, QHeaderView.ResizeMode.ResizeToContents)
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
        self._carregado = False

    def showEvent(self, evento) -> None:  # noqa: N802
        super().showEvent(evento)
        if not self._carregado:
            self._carregado = True
            self.carregar(1)

    def _ao_digitar(self, texto: str) -> None:
        t = texto.strip()
        if len(t) == 0 or len(t) >= 3:
            self._atraso.start()
        else:
            self.info.setText("Digite pelo menos 3 caracteres para pesquisar.")

    def carregar(self, pagina: int) -> None:
        termo = self.busca.text().strip()
        if 0 < len(termo) < 3:
            return
        try:
            with cursor_espera():
                r = self.api.listar_clientes(termo, self.situacao.currentData(), pagina, self.POR_PAGINA)
        except ErroAPI as exc:
            self.info.setText(exc.mensagem)
            return
        self.pagina, self.total = r.pagina, r.total
        self.tabela.setRowCount(len(r.itens))
        for i, c in enumerate(r.itens):
            local = f"{c.cidade}/{c.uf}" if c.cidade and c.uf else (c.cidade or c.uf or "")
            valores = [c.nome_completo, formatar_cpf(c.cpf), formatar_telefone(c.telefone_principal), local,
                       SITUACOES.get(c.situacao, c.situacao)]
            for j, v in enumerate(valores):
                item = QTableWidgetItem(v)
                if j == 0:
                    item.setData(Qt.ItemDataRole.UserRole, str(c.id))
                self.tabela.setItem(i, j, item)
        paginas = max(1, -(-r.total // self.POR_PAGINA))
        if r.total == 0:
            self.info.setText("Nenhum cliente encontrado." if termo else "Nenhum cliente nesta lista.")
        else:
            self.info.setText(f"{r.total} cliente(s) · página {r.pagina} de {paginas} · "
                              "dê dois cliques para abrir a ficha")
        self.btn_ant.setEnabled(r.pagina > 1)
        self.btn_prox.setEnabled(r.pagina < paginas)

    def abrir_linha(self, linha: int) -> None:
        item = self.tabela.item(linha, 0)
        if item:
            self.abrir_ficha(item.data(Qt.ItemDataRole.UserRole))

    def abrir_ficha(self, cliente_id: str) -> None:
        try:
            ficha = FichaCliente(self.api, cliente_id, self)
        except ErroAPI as exc:
            QMessageBox.warning(self, "Ficha do cliente", exc.mensagem)
            return
        ficha.alterado.connect(lambda: self.carregar(self.pagina))
        ficha.exec()

    def cadastrar(self) -> None:
        d = DialogoCliente(self.api, None, self)
        if d.exec() and d.resultado:
            self.carregar(self.pagina)
            self.abrir_ficha(str(d.resultado.id))


# ===================================================================== pesquisa global
class TelaResultadosPesquisa(QWidget):
    """Resultados da barra de pesquisa do cabeçalho. Cada tipo de registro aparece só para
    quem tem a permissão correspondente (a filtragem é feita no servidor)."""

    abrir = Signal(str, str)  # tipo, id
    POR_PAGINA = 20

    def __init__(self, api: ClienteAPI) -> None:
        super().__init__()
        self.api = api
        self.termo = ""
        self.pagina = 1
        lay = QVBoxLayout(self)
        lay.setContentsMargins(28, 24, 28, 20)
        self.titulo = rotulo("Resultados da pesquisa", "titulo")
        lay.addWidget(self.titulo)
        self.tabela = QTableWidget(0, 3)
        self.tabela.setHorizontalHeaderLabels(["Tipo", "Encontrado", "Detalhes"])
        self.tabela.verticalHeader().setVisible(False)
        self.tabela.setAlternatingRowColors(True)
        self.tabela.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.tabela.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        cab = self.tabela.horizontalHeader()
        cab.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        cab.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        cab.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
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
        self.btn_ant.clicked.connect(lambda: self.pesquisar(self.termo, self.pagina - 1))
        self.btn_prox.clicked.connect(lambda: self.pesquisar(self.termo, self.pagina + 1))
        self.tabela.cellDoubleClicked.connect(self._abrir)
        self.tabela.cellActivated.connect(self._abrir)

    def pesquisar(self, termo: str, pagina: int = 1) -> None:
        self.termo = termo
        try:
            r = self.api.pesquisar(termo, pagina, self.POR_PAGINA)
        except ErroAPI as exc:
            self.info.setText(exc.mensagem)
            self.tabela.setRowCount(0)
            return
        self.pagina = r.pagina
        self.titulo.setText(f"Resultados para “{r.termo}”")
        self.tabela.setRowCount(len(r.itens))
        for i, item in enumerate(r.itens):
            tipo = {"cliente": "Cliente", "processo": "Processo", "documento": "Documento"}.get(item.tipo, item.tipo)
            celulas = [tipo, item.titulo, item.resumo]
            for j, v in enumerate(celulas):
                cel = QTableWidgetItem(v)
                if j == 0:
                    cel.setData(Qt.ItemDataRole.UserRole, (item.tipo, str(item.id)))
                self.tabela.setItem(i, j, cel)
        paginas = max(1, -(-r.total // self.POR_PAGINA))
        self.info.setText("Nada encontrado." if r.total == 0 else
                          f"{r.total} resultado(s) · página {r.pagina} de {paginas} · dê dois cliques para abrir")
        self.btn_ant.setEnabled(r.pagina > 1)
        self.btn_prox.setEnabled(r.pagina < paginas)

    def _abrir(self, linha: int, _coluna: int = 0) -> None:
        cel = self.tabela.item(linha, 0)
        if cel:
            tipo, ident = cel.data(Qt.ItemDataRole.UserRole)
            self.abrir.emit(tipo, ident)
