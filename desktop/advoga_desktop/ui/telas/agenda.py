"""Agenda (dia, semana e mês) e Central de Pendências."""

from __future__ import annotations

from datetime import date, datetime, time, timedelta
from typing import Any

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor, QFont
from PySide6.QtWidgets import (
    QAbstractItemView,
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QDialog,
    QFormLayout,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QStackedWidget,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from advoga_shared.esquemas import (
    PRIORIDADES,
    SITUACOES_COMPROMISSO,
    TIPOS_COMPROMISSO,
    Compromisso,
    ItemPendencia,
)
from advoga_shared.permissoes import Permissao

from ...api_client.cliente import ClienteAPI, ErroAPI
from ..componentes.basicos import ajustar_altura, bloco_campo, campo, limpar_formulario, rotulo
from ..componentes.espera import cursor_espera
from ..componentes.formatos import data_br, data_hora_br, dinheiro_br, ler_data_br
from ..componentes.seletores import SeletorCliente
from ..tema.tema import CORES
from .financeiro import _botoes, _combo_processos, _combo_usuarios, _preencher, _recarregar_processos, _tabela

DIAS_SEMANA = ["Segunda", "Terça", "Quarta", "Quinta", "Sexta", "Sábado", "Domingo"]
MESES = ["janeiro", "fevereiro", "março", "abril", "maio", "junho", "julho", "agosto", "setembro", "outubro",
         "novembro", "dezembro"]
DURACOES = [("Sem duração definida", None), ("15 minutos", 15), ("30 minutos", 30), ("1 hora", 60),
            ("1 hora e 30", 90), ("2 horas", 120), ("3 horas", 180), ("4 horas", 240), ("Meio período", 300)]
ACOES = {
    "compromisso.criado": "Compromisso cadastrado", "compromisso.editado": "Dados alterados",
    "compromisso.reagendado": "Reagendado", "compromisso.concluido": "Concluído",
    "compromisso.cancelado": "Cancelado", "compromisso.atribuido": "Responsável alterado",
}
CAMPOS = {"titulo": "título", "tipo": "tipo", "local": "local", "inicio": "data/horário", "prioridade": "prioridade",
          "responsavel_id": "responsável", "cliente_id": "cliente", "processo_id": "processo",
          "observacoes": "observações", "duracao_minutos": "duração", "dia_inteiro": "dia inteiro"}


def pode(api: ClienteAPI, p: Permissao) -> bool:
    return bool(api.usuario and p in api.usuario.permissoes)


def hora_ou_dia(c: Compromisso) -> str:
    return "Dia todo" if c.dia_inteiro else c.inicio.astimezone().strftime("%H:%M")


def quando_texto(c: Compromisso) -> str:
    local = c.inicio.astimezone()
    return local.strftime("%d/%m/%Y") + ("" if c.dia_inteiro else local.strftime(" %H:%M"))


def cor_compromisso(c: Compromisso) -> str | None:
    if c.situacao == "cancelado" or c.situacao == "concluido":
        return CORES["texto_suave"]
    if c.atrasado:
        return CORES["erro"]
    if c.prioridade == "urgente":
        return CORES["aviso"]
    return None


def situacao_texto(c: Compromisso) -> str:
    if c.situacao == "agendado" and c.atrasado:
        return "Atrasado"
    return SITUACOES_COMPROMISSO.get(c.situacao, c.situacao)


def _data_hora(data_txt: str, hora_txt: str, dia_inteiro: bool) -> datetime:
    d = ler_data_br(data_txt)
    if d is None:
        raise ValueError("Informe a data.")
    if dia_inteiro:
        return datetime.combine(d, time.min).astimezone()
    h = hora_txt.strip()
    try:
        t = datetime.strptime(h, "%H:%M").time()
    except ValueError as exc:
        raise ValueError("Horário inválido. Use o formato hh:mm (ex.: 14:30).") from exc
    return datetime.combine(d, t).astimezone()


def descrever_historico(acao: str, d: dict[str, Any]) -> str:
    texto = ACOES.get(acao, acao)
    extra = []
    if d.get("origem") == "processo":
        extra.append("pelo cadastro do processo")
    if acao == "compromisso.reagendado" and isinstance(d.get("inicio"), dict):
        ini = d["inicio"]
        try:
            extra.append(f"de {data_hora_br(datetime.fromisoformat(ini['antes']))} para "
                         f"{data_hora_br(datetime.fromisoformat(ini['depois']))}")
        except (TypeError, ValueError, KeyError):
            pass
    if acao == "compromisso.editado":
        nomes = [CAMPOS.get(k, k) for k in d if k not in ("origem",)]
        if nomes:
            extra.append("alterou " + ", ".join(nomes))
    if d.get("motivo"):
        extra.append(f"motivo: {d['motivo']}")
    if d.get("observacao"):
        extra.append(d["observacao"])
    if acao == "compromisso.atribuido":
        extra.append(f"para {d.get('responsavel') or 'ninguém'}")
    return texto + (". " + "; ".join(extra) if extra else "")


# ============================================================================ diálogos
class DialogoCompromisso(QDialog):
    def __init__(self, api: ClienteAPI, compromisso: Compromisso | None = None, dia: date | None = None,
                 cliente: tuple[str, str] | None = None, parent=None) -> None:
        super().__init__(parent)
        self.api = api
        self.original = compromisso
        self.resultado: Compromisso | None = None
        self.setWindowTitle("Editar compromisso" if compromisso else "Novo compromisso")
        self.setMinimumWidth(720)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(24, 18, 24, 18)
        lay.addWidget(rotulo("Editar compromisso" if compromisso else "Novo compromisso", "secao"))
        self.titulo = campo("Ex.: Audiência de instrução, Ligar para o perito", maximo=300)
        self.tipo = QComboBox()
        self.tipo.setMinimumHeight(36)
        for k, v in TIPOS_COMPROMISSO.items():
            self.tipo.addItem(v, k)
        self.cliente = SeletorCliente(api)
        self.processo = _combo_processos(api, None)
        self.responsavel = _combo_usuarios(api, str(api.usuario.id) if api.usuario and not compromisso else None,
                                           "Sem responsável")
        self.data = campo("dd/mm/aaaa", maximo=10)
        self.hora = campo("hh:mm", maximo=5)
        self.dia_inteiro = QCheckBox("Dia todo (sem horário)")
        self.duracao = QComboBox()
        self.duracao.setMinimumHeight(36)
        for t, v in DURACOES:
            self.duracao.addItem(t, v)
        self.local = campo("Ex.: Fórum de Campinas, sala 3", maximo=300)
        self.prioridade = QComboBox()
        self.prioridade.setMinimumHeight(36)
        for k, v in PRIORIDADES.items():
            self.prioridade.addItem(v, k)
        self.prioridade.setCurrentIndex(self.prioridade.findData("normal"))
        self.obs = QPlainTextEdit()
        self.obs.setMinimumHeight(70)
        g = QGridLayout()
        g.setHorizontalSpacing(14)
        g.addWidget(bloco_campo("Título *", self.titulo), 0, 0, 1, 2)
        g.addWidget(bloco_campo("Tipo *", self.tipo), 0, 2)
        g.addWidget(bloco_campo("Cliente", self.cliente), 1, 0, 1, 2)
        g.addWidget(bloco_campo("Processo", self.processo), 1, 2)
        g.addWidget(bloco_campo("Data *", self.data), 2, 0)
        g.addWidget(bloco_campo("Horário *", self.hora), 2, 1)
        g.addWidget(self.dia_inteiro, 2, 2, Qt.AlignmentFlag.AlignBottom)
        g.addWidget(bloco_campo("Duração", self.duracao), 3, 0)
        g.addWidget(bloco_campo("Responsável", self.responsavel), 3, 1)
        g.addWidget(bloco_campo("Prioridade", self.prioridade), 3, 2)
        g.addWidget(bloco_campo("Local", self.local), 4, 0, 1, 3)
        lay.addLayout(g)
        lay.addWidget(bloco_campo("Observações", self.obs))
        self.aviso_processo = rotulo("Este compromisso vem da \"próxima audiência ou prazo\" do processo: tipo e "
                                     "processo são alterados na ficha do processo.", "rotuloCampo", True)
        self.aviso_processo.setVisible(bool(compromisso and compromisso.do_processo))
        lay.addWidget(self.aviso_processo)
        self.erro = rotulo("", "erro", True)
        lay.addWidget(self.erro)
        b, self.btn_salvar = _botoes(self, "Salvar" if compromisso else "Agendar")
        lay.addLayout(b)
        self.btn_salvar.clicked.connect(self.salvar)
        self.dia_inteiro.toggled.connect(lambda v: self.hora.setEnabled(not v))
        self.cliente.alterado.connect(lambda cid: _recarregar_processos(api, self.processo, cid))
        d = dia or date.today()
        self.data.setText(d.strftime("%d/%m/%Y"))
        self.hora.setText("09:00")
        if cliente:
            self.cliente.definir(*cliente)
        if compromisso:
            self._preencher(compromisso)
        ajustar_altura(self)

    def _preencher(self, c: Compromisso) -> None:
        self.titulo.setText(c.titulo)
        self.tipo.setCurrentIndex(self.tipo.findData(c.tipo))
        if c.cliente_id:
            self.cliente.definir(str(c.cliente_id), c.cliente_nome or "")
            self.processo.setCurrentIndex(max(self.processo.findData(str(c.processo_id) if c.processo_id else None), 0))
        local = c.inicio.astimezone()
        self.data.setText(local.strftime("%d/%m/%Y"))
        self.hora.setText(local.strftime("%H:%M"))
        self.dia_inteiro.setChecked(c.dia_inteiro)
        self.duracao.setCurrentIndex(max(self.duracao.findData(c.duracao_minutos), 0))
        self.responsavel.setCurrentIndex(max(self.responsavel.findData(
            str(c.responsavel_id) if c.responsavel_id else None), 0))
        self.prioridade.setCurrentIndex(self.prioridade.findData(c.prioridade))
        self.local.setText(c.local or "")
        self.obs.setPlainText(c.observacoes or "")
        if c.do_processo:
            self.tipo.setEnabled(False)
            self.processo.setEnabled(False)
            self.cliente.btn.setEnabled(False)

    def _dados(self) -> dict[str, Any]:
        if not self.titulo.text().strip():
            raise ValueError("Informe o título.")
        inicio = _data_hora(self.data.text(), self.hora.text(), self.dia_inteiro.isChecked())
        return {"titulo": self.titulo.text().strip(), "tipo": self.tipo.currentData(),
                "cliente_id": self.cliente.cliente_id, "processo_id": self.processo.currentData(),
                "responsavel_id": self.responsavel.currentData(), "inicio": inicio.isoformat(),
                "dia_inteiro": self.dia_inteiro.isChecked(), "duracao_minutos": self.duracao.currentData(),
                "local": self.local.text().strip() or None, "prioridade": self.prioridade.currentData(),
                "observacoes": self.obs.toPlainText().strip() or None}

    def salvar(self) -> None:
        try:
            dados = self._dados()
        except ValueError as exc:
            self.erro.setText(str(exc))
            ajustar_altura(self)
            return
        try:
            with cursor_espera():
                if self.original is None:
                    self.resultado = self.api.criar_compromisso(dados)
                else:
                    if self.original.do_processo:
                        dados.pop("tipo")
                        dados.pop("processo_id")
                        dados.pop("cliente_id")
                    self.resultado = self.api.atualizar_compromisso(str(self.original.id),
                                                                    dados | {"versao": self.original.versao})
        except ErroAPI as exc:
            self.erro.setText(exc.mensagem)
            ajustar_altura(self)
            return
        self.accept()


class DialogoReagendar(QDialog):
    def __init__(self, api: ClienteAPI, c: Compromisso, parent=None) -> None:
        super().__init__(parent)
        self.api = api
        self.compromisso = c
        self.resultado: Compromisso | None = None
        self.setWindowTitle("Reagendar")
        self.setMinimumWidth(480)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(24, 18, 24, 18)
        lay.addWidget(rotulo("Reagendar compromisso", "secao"))
        lay.addWidget(rotulo(f"{c.titulo}\nAtual: {quando_texto(c)}", quebra=True))
        local = c.inicio.astimezone()
        self.data = campo("dd/mm/aaaa", maximo=10)
        self.data.setText(local.strftime("%d/%m/%Y"))
        self.hora = campo("hh:mm", maximo=5)
        self.hora.setText(local.strftime("%H:%M"))
        self.dia_inteiro = QCheckBox("Dia todo (sem horário)")
        self.dia_inteiro.setChecked(c.dia_inteiro)
        self.hora.setEnabled(not c.dia_inteiro)
        self.motivo = campo("Ex.: Audiência redesignada pelo juízo", maximo=500)
        g = QGridLayout()
        g.addWidget(bloco_campo("Nova data *", self.data), 0, 0)
        g.addWidget(bloco_campo("Novo horário *", self.hora), 0, 1)
        g.addWidget(self.dia_inteiro, 1, 0, 1, 2)
        lay.addLayout(g)
        lay.addWidget(bloco_campo("Motivo", self.motivo))
        self.erro = rotulo("", "erro", True)
        lay.addWidget(self.erro)
        b, self.btn_salvar = _botoes(self, "Reagendar")
        lay.addLayout(b)
        self.dia_inteiro.toggled.connect(lambda v: self.hora.setEnabled(not v))
        self.btn_salvar.clicked.connect(self.salvar)
        ajustar_altura(self)

    def salvar(self) -> None:
        try:
            inicio = _data_hora(self.data.text(), self.hora.text(), self.dia_inteiro.isChecked())
        except ValueError as exc:
            self.erro.setText(str(exc))
            return
        try:
            with cursor_espera():
                self.resultado = self.api.reagendar_compromisso(
                    str(self.compromisso.id), inicio, self.compromisso.versao, self.dia_inteiro.isChecked(),
                    self.motivo.text().strip() or None)
        except ErroAPI as exc:
            self.erro.setText(exc.mensagem)
            return
        self.accept()


class DialogoAtribuir(QDialog):
    def __init__(self, api: ClienteAPI, c: Compromisso, parent=None) -> None:
        super().__init__(parent)
        self.api = api
        self.compromisso = c
        self.resultado: Compromisso | None = None
        self.setWindowTitle("Atribuir responsável")
        self.setMinimumWidth(440)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(24, 18, 24, 18)
        lay.addWidget(rotulo(f"Quem cuida de \"{c.titulo}\"?", "secao", True))
        self.responsavel = _combo_usuarios(api, str(c.responsavel_id) if c.responsavel_id else None,
                                           "Sem responsável")
        lay.addWidget(bloco_campo("Responsável", self.responsavel))
        self.erro = rotulo("", "erro", True)
        lay.addWidget(self.erro)
        b, self.btn_salvar = _botoes(self, "Atribuir")
        lay.addLayout(b)
        self.btn_salvar.clicked.connect(self.salvar)
        ajustar_altura(self)

    def salvar(self) -> None:
        try:
            with cursor_espera():
                self.resultado = self.api.atribuir_compromisso(str(self.compromisso.id),
                                                               self.responsavel.currentData(), self.compromisso.versao)
        except ErroAPI as exc:
            self.erro.setText(exc.mensagem)
            return
        self.accept()


class AcoesCompromisso:
    """Concluir, reagendar, atribuir e cancelar, com as mesmas mensagens em todas as telas."""

    def __init__(self, api: ClienteAPI, pai: QWidget) -> None:
        self.api = api
        self.pai = pai

    def concluir(self, c: Compromisso) -> bool:
        obs, ok = QInputDialog.getText(self.pai, "Concluir", f"Concluir \"{c.titulo}\"?\n"
                                                             "Observação (opcional):")
        if not ok:
            return False
        return self._executar("Concluir", lambda: self.api.concluir_compromisso(str(c.id), c.versao,
                                                                                obs.strip() or None))

    def reagendar(self, c: Compromisso) -> bool:
        return bool(DialogoReagendar(self.api, c, self.pai).exec())

    def atribuir(self, c: Compromisso) -> bool:
        return bool(DialogoAtribuir(self.api, c, self.pai).exec())

    def cancelar(self, c: Compromisso) -> bool:
        motivo, ok = QInputDialog.getText(self.pai, "Cancelar compromisso",
                                          f"Cancelar \"{c.titulo}\"?\nO registro continua no histórico. "
                                          "Informe o motivo:")
        if not ok:
            return False
        return self._executar("Cancelar", lambda: self.api.cancelar_compromisso(str(c.id), motivo.strip(), c.versao))

    def _executar(self, titulo: str, acao) -> bool:
        try:
            with cursor_espera():
                acao()
        except ErroAPI as exc:
            QMessageBox.warning(self.pai, titulo, exc.mensagem)
            return False
        return True


class FichaCompromisso(QDialog):
    alterado = Signal()

    def __init__(self, api: ClienteAPI, compromisso_id: str, parent=None) -> None:
        super().__init__(parent)
        self.api = api
        self.compromisso_id = compromisso_id
        self.compromisso: Compromisso | None = None
        self.acoes = AcoesCompromisso(api, self)
        self.setWindowTitle("Compromisso")
        self.setMinimumSize(760, 560)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(24, 18, 24, 18)
        self.titulo = rotulo("", "titulo", True)
        self.subtitulo = rotulo("", "subtitulo", True)
        lay.addWidget(self.titulo)
        lay.addWidget(self.subtitulo)
        botoes = QHBoxLayout()
        self.btn_editar = QPushButton("Editar")
        self.btn_reagendar = QPushButton("Reagendar")
        self.btn_atribuir = QPushButton("Atribuir")
        self.btn_cancelar = QPushButton("Cancelar compromisso")
        self.btn_concluir = QPushButton("Concluir")
        self.btn_concluir.setObjectName("primario")
        agenda = pode(api, Permissao.AGENDA)
        self.btn_editar.setVisible(agenda)
        self.btn_cancelar.setVisible(agenda)
        for b in (self.btn_editar, self.btn_reagendar, self.btn_atribuir, self.btn_cancelar):
            botoes.addWidget(b)
        botoes.addStretch()
        botoes.addWidget(self.btn_concluir)
        lay.addLayout(botoes)
        self.abas = QTabWidget()
        rol = QScrollArea()
        rol.setWidgetResizable(True)
        dados = QWidget()
        self.form = QFormLayout(dados)
        self.form.setContentsMargins(20, 16, 20, 16)
        self.form.setVerticalSpacing(8)
        rol.setWidget(dados)
        self.abas.addTab(rol, "Dados")
        self.tabela_hist = _tabela(["Data e hora", "Usuário", "O que aconteceu"], 2)
        self.abas.addTab(self.tabela_hist, "Histórico")
        lay.addWidget(self.abas, 1)
        fechar = QPushButton("Fechar")
        fechar.clicked.connect(self.accept)
        lay.addWidget(fechar, 0, Qt.AlignmentFlag.AlignRight)
        self.btn_editar.clicked.connect(self.editar)
        self.btn_reagendar.clicked.connect(lambda: self._apos(self.acoes.reagendar(self.compromisso)))
        self.btn_atribuir.clicked.connect(lambda: self._apos(self.acoes.atribuir(self.compromisso)))
        self.btn_cancelar.clicked.connect(lambda: self._apos(self.acoes.cancelar(self.compromisso)))
        self.btn_concluir.clicked.connect(lambda: self._apos(self.acoes.concluir(self.compromisso)))
        self.abas.currentChanged.connect(lambda _i: self.carregar_historico()
                                         if self.abas.currentWidget() is self.tabela_hist else None)
        self.carregar()

    def carregar(self) -> None:
        with cursor_espera():
            c = self.compromisso = self.api.obter_compromisso(self.compromisso_id)
        self.titulo.setText(c.titulo)
        self.subtitulo.setText(f"{TIPOS_COMPROMISSO.get(c.tipo, c.tipo)}  ·  {quando_texto(c)}  ·  {situacao_texto(c)}")
        aberto = c.situacao == "agendado"
        for b in (self.btn_editar, self.btn_reagendar, self.btn_atribuir, self.btn_cancelar, self.btn_concluir):
            b.setEnabled(aberto)
        limpar_formulario(self.form)
        duracao = next((t for t, v in DURACOES if v == c.duracao_minutos and v), None)
        linhas = [("Tipo", TIPOS_COMPROMISSO.get(c.tipo)), ("Data e horário", quando_texto(c)),
                  ("Duração", duracao), ("Situação", situacao_texto(c)), ("Prioridade", PRIORIDADES.get(c.prioridade)),
                  ("Cliente", c.cliente_nome), ("Processo", c.processo_rotulo), ("Responsável", c.responsavel_nome),
                  ("Local", c.local), ("Observações", c.observacoes),
                  ("Reagendado", f"{c.reagendamentos} vez(es)" if c.reagendamentos else None),
                  ("Origem", "Próxima audiência ou prazo do processo" if c.do_processo else None),
                  ("Concluído", f"{data_hora_br(c.concluido_em)} por {c.concluido_por_nome or '—'}"
                   if c.concluido_em else None),
                  ("Observação da conclusão", c.observacao_conclusao),
                  ("Cancelado", f"{data_hora_br(c.cancelado_em)}: {c.motivo_cancelamento}" if c.cancelado_em else None),
                  ("Cadastrado", f"{data_hora_br(c.criado_em)} por {c.criado_por_nome or '—'}")]
        for rot, valor in linhas:
            if valor is None and rot not in ("Cliente", "Responsável", "Local"):
                continue
            v = rotulo(valor or "—", quebra=True)
            v.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            if rot == "Situação" and c.atrasado:
                v.setStyleSheet(f"color:{CORES['erro']}; font-weight:600;")
            self.form.addRow(rotulo(rot, "rotuloCampo"), v)

    def carregar_historico(self) -> None:
        try:
            itens = self.api.historico_compromisso(self.compromisso_id)
        except ErroAPI as exc:
            QMessageBox.warning(self, "Histórico", exc.mensagem)
            return
        _preencher(self.tabela_hist, [[data_hora_br(a.ocorrido_em), a.usuario_nome or "Sistema",
                                       descrever_historico(a.acao, a.detalhes or {})] for a in itens])

    def _apos(self, mudou: bool) -> None:
        if not mudou:
            return
        self.carregar()
        if self.abas.currentWidget() is self.tabela_hist:
            self.carregar_historico()
        self.alterado.emit()

    def editar(self) -> None:
        self._apos(bool(DialogoCompromisso(self.api, self.compromisso, parent=self).exec()))


def abrir_compromisso(api: ClienteAPI, compromisso_id: str, pai: QWidget, ao_alterar) -> None:
    try:
        ficha = FichaCompromisso(api, compromisso_id, pai)
    except ErroAPI as exc:
        QMessageBox.warning(pai, "Compromisso", exc.mensagem)
        return
    ficha.alterado.connect(ao_alterar)
    ficha.exec()


# ============================================================================== agenda
class _Dia(QFrame):
    """Um dia na semana ou no mês: cabeçalho e lista de compromissos."""

    abrir = Signal(str)
    escolher_dia = Signal(object)

    def __init__(self, compacto: bool) -> None:
        super().__init__()
        self.setObjectName("cartao")
        self.dia: date | None = None
        lay = QVBoxLayout(self)
        lay.setContentsMargins(6, 4, 6, 6)
        lay.setSpacing(2)
        self.cabecalho = QPushButton("")
        self.cabecalho.setFlat(True)
        self.cabecalho.setCursor(Qt.CursorShape.PointingHandCursor)
        self.cabecalho.setStyleSheet("text-align:left; padding:2px 4px; border:none; background:transparent;")
        self.lista = QListWidget()
        self.lista.setFrameShape(QFrame.Shape.NoFrame)
        self.lista.setStyleSheet("background:transparent; font-size:9pt;" if compacto else "background:transparent;")
        self.lista.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.lista.setWordWrap(not compacto)
        lay.addWidget(self.cabecalho)
        lay.addWidget(self.lista, 1)
        self.lista.itemDoubleClicked.connect(lambda i: self.abrir.emit(i.data(Qt.ItemDataRole.UserRole)))
        self.cabecalho.clicked.connect(lambda: self.escolher_dia.emit(self.dia))

    def mostrar(self, dia: date, titulo: str, itens: list[Compromisso], fora_do_mes: bool = False) -> None:
        self.dia = dia
        self.cabecalho.setText(titulo)
        hoje = dia == date.today()
        cor = CORES["dourado_claro"] if hoje else (CORES["texto_suave"] if fora_do_mes else CORES["texto"])
        self.cabecalho.setStyleSheet(f"text-align:left; padding:2px 4px; border:none; background:transparent; "
                                     f"color:{cor}; font-weight:{'700' if hoje else '500'};")
        self.lista.clear()
        for c in itens:
            item = QListWidgetItem(f"{hora_ou_dia(c)}  {c.titulo}")
            item.setData(Qt.ItemDataRole.UserRole, str(c.id))
            item.setToolTip(f"{TIPOS_COMPROMISSO.get(c.tipo)} · {situacao_texto(c)}\n{c.titulo}"
                            + (f"\nCliente: {c.cliente_nome}" if c.cliente_nome else "")
                            + (f"\nResponsável: {c.responsavel_nome}" if c.responsavel_nome else "")
                            + (f"\nLocal: {c.local}" if c.local else ""))
            cor_item = cor_compromisso(c)
            if cor_item:
                item.setForeground(QColor(cor_item))
            if c.situacao == "cancelado":
                f = QFont(item.font())
                f.setStrikeOut(True)
                item.setFont(f)
            self.lista.addItem(item)


class TelaAgenda(QWidget):
    VISOES = ("dia", "semana", "mes")

    def __init__(self, api: ClienteAPI) -> None:
        super().__init__()
        self.api = api
        self.acoes = AcoesCompromisso(api, self)
        self.referencia = date.today()
        self.visao = "semana"
        self.compromissos: list[Compromisso] = []
        lay = QVBoxLayout(self)
        lay.setContentsMargins(28, 24, 28, 20)
        topo = QHBoxLayout()
        topo.addWidget(rotulo("Agenda", "titulo"))
        topo.addSpacing(20)
        self.btn_anterior = QPushButton("◀")
        self.btn_hoje = QPushButton("Hoje")
        self.btn_proximo = QPushButton("▶")
        for b in (self.btn_anterior, self.btn_hoje, self.btn_proximo):
            topo.addWidget(b)
        self.periodo = rotulo("", "secao")
        topo.addSpacing(12)
        topo.addWidget(self.periodo)
        topo.addStretch()
        self.grupo_visao = QButtonGroup(self)
        for i, (nome, chave) in enumerate((("Dia", "dia"), ("Semana", "semana"), ("Mês", "mes"))):
            b = QPushButton(nome)
            b.setCheckable(True)
            b.setChecked(chave == self.visao)
            self.grupo_visao.addButton(b, i)
            topo.addWidget(b)
        self.btn_novo = QPushButton("Novo compromisso")
        self.btn_novo.setObjectName("primario")
        self.btn_novo.setVisible(pode(api, Permissao.AGENDA))
        topo.addSpacing(12)
        topo.addWidget(self.btn_novo)
        lay.addLayout(topo)

        filtros = QHBoxLayout()
        self.responsavel = _combo_usuarios(api, None, "Todos os responsáveis")
        self.tipo = QComboBox()
        self.tipo.setMinimumHeight(36)
        self.tipo.addItem("Todos os tipos", None)
        for k, v in TIPOS_COMPROMISSO.items():
            self.tipo.addItem(v, k)
        self.chk_cancelados = QCheckBox("Mostrar cancelados")
        filtros.addWidget(self.responsavel)
        filtros.addWidget(self.tipo)
        filtros.addWidget(self.chk_cancelados)
        filtros.addStretch()
        self.info = rotulo("", "rotuloCampo")
        filtros.addWidget(self.info)
        lay.addLayout(filtros)

        self.avisos = QListWidget()
        self.avisos.setFixedHeight(104)
        self.avisos.setObjectName("avisos")
        lay.addWidget(self.avisos)

        self.paginas = QStackedWidget()
        # Dia: tabela detalhada
        pagina_dia = QWidget()
        ld = QVBoxLayout(pagina_dia)
        ld.setContentsMargins(0, 0, 0, 0)
        self.tabela_dia = _tabela(["Horário", "Título", "Tipo", "Cliente", "Responsável", "Local", "Prioridade",
                                   "Situação"], 1)
        ld.addWidget(self.tabela_dia, 1)
        acoes = QHBoxLayout()
        acoes.addStretch()
        self.btn_reagendar = QPushButton("Reagendar")
        self.btn_atribuir = QPushButton("Atribuir")
        self.btn_concluir = QPushButton("Concluir")
        self.btn_concluir.setObjectName("primario")
        for b in (self.btn_reagendar, self.btn_atribuir, self.btn_concluir):
            acoes.addWidget(b)
        ld.addLayout(acoes)
        self.paginas.addWidget(pagina_dia)
        # Semana: 7 colunas
        pagina_semana = QWidget()
        ls = QHBoxLayout(pagina_semana)
        ls.setContentsMargins(0, 0, 0, 0)
        ls.setSpacing(6)
        self.dias_semana = [_Dia(False) for _ in range(7)]
        for d in self.dias_semana:
            ls.addWidget(d, 1)
        self.paginas.addWidget(pagina_semana)
        # Mês: 6 x 7
        pagina_mes = QWidget()
        lm = QGridLayout(pagina_mes)
        lm.setContentsMargins(0, 0, 0, 0)
        lm.setSpacing(4)
        for j, nome in enumerate(DIAS_SEMANA):
            lm.addWidget(rotulo(nome, "rotuloCampo"), 0, j, Qt.AlignmentFlag.AlignCenter)
        self.dias_mes = [_Dia(True) for _ in range(42)]
        for i, d in enumerate(self.dias_mes):
            lm.addWidget(d, 1 + i // 7, i % 7)
        for r in range(1, 7):
            lm.setRowStretch(r, 1)
        self.paginas.addWidget(pagina_mes)
        lay.addWidget(self.paginas, 1)

        for d in self.dias_semana + self.dias_mes:
            d.abrir.connect(self.abrir)
            d.escolher_dia.connect(self.ir_para_dia)
        self.btn_anterior.clicked.connect(lambda: self.mover(-1))
        self.btn_proximo.clicked.connect(lambda: self.mover(1))
        self.btn_hoje.clicked.connect(self.ir_hoje)
        self.grupo_visao.idClicked.connect(lambda i: self.mudar_visao(self.VISOES[i]))
        self.btn_novo.clicked.connect(self.novo)
        self.responsavel.currentIndexChanged.connect(lambda _i: self.carregar())
        self.tipo.currentIndexChanged.connect(lambda _i: self.carregar())
        self.chk_cancelados.toggled.connect(lambda _v: self.carregar())
        self.tabela_dia.cellDoubleClicked.connect(lambda linha, _c: self._abrir_linha(linha))
        self.avisos.itemDoubleClicked.connect(lambda i: self.abrir(i.data(Qt.ItemDataRole.UserRole)))
        self.btn_concluir.clicked.connect(lambda: self._acao_dia(self.acoes.concluir))
        self.btn_reagendar.clicked.connect(lambda: self._acao_dia(self.acoes.reagendar))
        self.btn_atribuir.clicked.connect(lambda: self._acao_dia(self.acoes.atribuir))
        self._carregado = False

    def showEvent(self, evento) -> None:  # noqa: N802
        super().showEvent(evento)
        if not self._carregado:
            self._carregado = True
            self.carregar()

    # ---------------------------------------------------------------- navegação
    def intervalo(self) -> tuple[date, date]:
        r = self.referencia
        if self.visao == "dia":
            return r, r + timedelta(days=1)
        if self.visao == "semana":
            ini = r - timedelta(days=r.weekday())
            return ini, ini + timedelta(days=7)
        primeiro = r.replace(day=1)
        ini = primeiro - timedelta(days=primeiro.weekday())
        return ini, ini + timedelta(days=42)

    def mover(self, sentido: int) -> None:
        r = self.referencia
        if self.visao == "dia":
            self.referencia = r + timedelta(days=sentido)
        elif self.visao == "semana":
            self.referencia = r + timedelta(days=7 * sentido)
        else:
            mes = r.month - 1 + sentido
            self.referencia = date(r.year + mes // 12, mes % 12 + 1, 1)
        self.carregar()

    def ir_hoje(self) -> None:
        self.referencia = date.today()
        self.carregar()

    def ir_para_dia(self, dia: date) -> None:
        self.referencia = dia
        self.mudar_visao("dia")

    def mudar_visao(self, visao: str) -> None:
        self.visao = visao
        self.grupo_visao.button(self.VISOES.index(visao)).setChecked(True)
        self.carregar()

    # ------------------------------------------------------------------ dados
    def carregar(self) -> None:
        ini, fim = self.intervalo()
        try:
            with cursor_espera():
                r = self.api.listar_compromissos(datetime.combine(ini, time.min).astimezone(),
                                                 datetime.combine(fim, time.min).astimezone(),
                                                 responsavel_id=self.responsavel.currentData(),
                                                 tipo=self.tipo.currentData(), por_pagina=1000)
                avisos = self.api.avisos_agenda()
        except ErroAPI as exc:
            self.info.setText(exc.mensagem)
            return
        self.compromissos = [c for c in r.itens if self.chk_cancelados.isChecked() or c.situacao != "cancelado"]
        pend = sum(1 for c in self.compromissos if c.situacao == "agendado")
        self.info.setText(f"{len(self.compromissos)} compromisso(s) · {pend} em aberto")
        self._mostrar_avisos(avisos)
        self._mostrar_periodo(ini)
        if self.visao == "dia":
            self._mostrar_dia()
        elif self.visao == "semana":
            self._mostrar_semana(ini)
        else:
            self._mostrar_mes(ini)
        self.paginas.setCurrentIndex(self.VISOES.index(self.visao))

    def _mostrar_avisos(self, avisos) -> None:
        self.avisos.clear()
        cores = {"atrasado": CORES["erro"], "hoje": CORES["aviso"], "pendente": CORES["aviso"],
                 "amanha": CORES["dourado_claro"]}
        for a in avisos:
            c = a.compromisso
            item = QListWidgetItem(f"{a.titulo}  ·  {c.titulo}  ·  {quando_texto(c)}"
                                   + (f"  ·  {c.responsavel_nome}" if c.responsavel_nome else ""))
            item.setData(Qt.ItemDataRole.UserRole, str(c.id))
            item.setForeground(QColor(cores.get(a.tipo, CORES["texto"])))
            self.avisos.addItem(item)
        if not avisos:
            self.avisos.addItem(QListWidgetItem("Nenhum aviso para hoje e amanhã."))

    def _mostrar_periodo(self, ini: date) -> None:
        r = self.referencia
        if self.visao == "dia":
            texto = f"{DIAS_SEMANA[r.weekday()]}, {r.day} de {MESES[r.month - 1]} de {r.year}"
        elif self.visao == "semana":
            fim = ini + timedelta(days=6)
            texto = f"{data_br(ini)} a {data_br(fim)}"
        else:
            texto = f"{MESES[r.month - 1].capitalize()} de {r.year}"
        self.periodo.setText(texto)

    def _do_dia(self, dia: date) -> list[Compromisso]:
        return [c for c in self.compromissos if c.inicio.astimezone().date() == dia]

    def _mostrar_dia(self) -> None:
        itens = self._do_dia(self.referencia)
        self.itens_dia = itens
        _preencher(self.tabela_dia, [[hora_ou_dia(c), c.titulo, TIPOS_COMPROMISSO.get(c.tipo, c.tipo),
                                      c.cliente_nome or "", c.responsavel_nome or "", c.local or "",
                                      PRIORIDADES.get(c.prioridade, ""), situacao_texto(c)] for c in itens],
                   [cor_compromisso(c) for c in itens])

    def _mostrar_semana(self, ini: date) -> None:
        for i, w in enumerate(self.dias_semana):
            d = ini + timedelta(days=i)
            w.mostrar(d, f"{DIAS_SEMANA[i]} {d.day:02d}/{d.month:02d}", self._do_dia(d))

    def _mostrar_mes(self, ini: date) -> None:
        for i, w in enumerate(self.dias_mes):
            d = ini + timedelta(days=i)
            w.mostrar(d, str(d.day), self._do_dia(d), fora_do_mes=d.month != self.referencia.month)

    # ----------------------------------------------------------------- ações
    def _abrir_linha(self, linha: int) -> None:
        if 0 <= linha < len(getattr(self, "itens_dia", [])):
            self.abrir(str(self.itens_dia[linha].id))

    def _selecionado(self) -> Compromisso | None:
        linha = self.tabela_dia.currentRow()
        itens = getattr(self, "itens_dia", [])
        return itens[linha] if 0 <= linha < len(itens) and self.tabela_dia.selectedItems() else None

    def _acao_dia(self, acao) -> None:
        c = self._selecionado()
        if c is None or c.situacao != "agendado":
            QMessageBox.information(self, "Agenda", "Escolha um compromisso em aberto na lista.")
            return
        if acao(c):
            self.carregar()

    def abrir(self, compromisso_id: str | None) -> None:
        if compromisso_id:
            abrir_compromisso(self.api, compromisso_id, self, self.carregar)

    def novo(self) -> None:
        dia = self.referencia if self.visao == "dia" else date.today()
        if DialogoCompromisso(self.api, dia=dia, parent=self).exec():
            self.carregar()


# ================================================================= central de pendências
class TelaPendencias(QWidget):
    GRUPOS = [("atrasado", "Atrasados"), ("hoje", "Hoje"), ("amanha", "Amanhã"), ("proximos", "Próximos dias")]
    NOMES_GRUPO = {"atrasado": "Atrasado", "hoje": "Hoje", "amanha": "Amanhã", "proximos": "Próximos",
                   "concluido": "Concluído", "cancelado": "Cancelado"}

    def __init__(self, api: ClienteAPI) -> None:
        super().__init__()
        self.api = api
        self.fin = pode(api, Permissao.FINANCEIRO)
        self.acoes = AcoesCompromisso(api, self)
        self.itens: list[ItemPendencia] = []
        lay = QVBoxLayout(self)
        lay.setContentsMargins(28, 24, 28, 20)
        lay.addWidget(rotulo("Central de Pendências", "titulo"))
        lay.addWidget(rotulo("Audiências, prazos, ligações, retornos, reuniões, entregas e tarefas que ainda "
                             "precisam de atenção, de todo o escritório.", "rotuloCampo", True))
        cartoes = QHBoxLayout()
        self.cartoes: dict[str, QLabel] = {}
        grupos = self.GRUPOS + ([("financeiro", "Parcelas a receber")] if self.fin else [])
        for chave, titulo in grupos:
            f = QFrame()
            f.setObjectName("cartao")
            lf = QVBoxLayout(f)
            lf.setContentsMargins(14, 10, 14, 10)
            lf.addWidget(rotulo(titulo, "rotuloCampo"))
            v = QLabel("0")
            v.setStyleSheet(f"font-size:16pt; font-weight:600; color:"
                            f"{CORES['erro'] if chave == 'atrasado' else CORES['dourado_claro']};")
            lf.addWidget(v)
            self.cartoes[chave] = v
            cartoes.addWidget(f)
        lay.addLayout(cartoes)

        filtros = QGridLayout()
        filtros.setHorizontalSpacing(10)
        self.responsavel = _combo_usuarios(api, None, "Todos os responsáveis")
        self.responsavel.insertItem(1, "Sem responsável", "__sem__")
        self.cliente = SeletorCliente(api)
        self.btn_limpar_cliente = QPushButton("Limpar")
        self.processo = _combo_processos(api, None)
        self.processo.setItemText(0, "Todos os processos")
        self.tipo = QComboBox()
        self.tipo.setMinimumHeight(36)
        self.tipo.addItem("Todos os tipos", None)
        for k, v in TIPOS_COMPROMISSO.items():
            self.tipo.addItem(v, k)
        if self.fin:
            self.tipo.addItem("Parcelas (financeiro)", "financeiro")
        self.prioridade = QComboBox()
        self.prioridade.setMinimumHeight(36)
        self.prioridade.addItem("Todas as prioridades", None)
        for k, v in PRIORIDADES.items():
            self.prioridade.addItem(v, k)
        self.situacao = QComboBox()
        self.situacao.setMinimumHeight(36)
        for t, k in (("Pendentes", "pendente"), ("Somente atrasados", "atrasado"), ("Concluídos", "concluido"),
                     ("Cancelados", "cancelado")):
            self.situacao.addItem(t, k)
        self.desde = campo("dd/mm/aaaa", maximo=10)
        self.ate = campo("dd/mm/aaaa", maximo=10)
        self.ate.setText((date.today() + timedelta(days=14)).strftime("%d/%m/%Y"))
        self.btn_filtrar = QPushButton("Filtrar")
        self.btn_filtrar.setObjectName("primario")
        cli_box = QWidget()
        cli_box.setObjectName("bloco")
        lc = QHBoxLayout(cli_box)
        lc.setContentsMargins(0, 0, 0, 0)
        lc.addWidget(self.cliente, 1)
        lc.addWidget(self.btn_limpar_cliente)
        filtros.addWidget(bloco_campo("Responsável", self.responsavel), 0, 0)
        filtros.addWidget(bloco_campo("Cliente", cli_box), 0, 1, 1, 2)
        filtros.addWidget(bloco_campo("Processo", self.processo), 0, 3)
        filtros.addWidget(bloco_campo("Tipo", self.tipo), 1, 0)
        filtros.addWidget(bloco_campo("Prioridade", self.prioridade), 1, 1)
        filtros.addWidget(bloco_campo("Situação", self.situacao), 1, 2)
        per = QWidget()
        per.setObjectName("bloco")
        lp = QHBoxLayout(per)
        lp.setContentsMargins(0, 0, 0, 0)
        lp.addWidget(self.desde)
        lp.addWidget(rotulo("a", "rotuloCampo"))
        lp.addWidget(self.ate)
        filtros.addWidget(bloco_campo("Período (desde · até)", per), 1, 3)
        filtros.addWidget(self.btn_filtrar, 1, 4, Qt.AlignmentFlag.AlignBottom)
        lay.addLayout(filtros)

        self.tabela = _tabela(["Quando", "Situação", "Tipo", "Título", "Cliente", "Processo", "Responsável",
                               "Prioridade"], 3)
        lay.addWidget(self.tabela, 1)
        barra = QHBoxLayout()
        self.info = rotulo("", "rotuloCampo")
        barra.addWidget(self.info)
        barra.addStretch()
        self.btn_abrir = QPushButton("Abrir")
        self.btn_atribuir = QPushButton("Atribuir")
        self.btn_reagendar = QPushButton("Reagendar")
        self.btn_concluir = QPushButton("Concluir")
        self.btn_concluir.setObjectName("primario")
        self.btn_receber = QPushButton("Registrar recebimento")
        self.btn_receber.setVisible(self.fin)
        for b in (self.btn_abrir, self.btn_atribuir, self.btn_reagendar, self.btn_receber, self.btn_concluir):
            barra.addWidget(b)
        lay.addLayout(barra)

        self.btn_filtrar.clicked.connect(self.carregar)
        for combo in (self.responsavel, self.processo, self.tipo, self.prioridade, self.situacao):
            combo.currentIndexChanged.connect(lambda _i: self.carregar())
        self.cliente.alterado.connect(self._cliente_mudou)
        self.btn_limpar_cliente.clicked.connect(lambda: self._cliente_mudou(None, limpar=True))
        self.tabela.cellDoubleClicked.connect(lambda _l, _c: self.abrir())
        self.btn_abrir.clicked.connect(self.abrir)
        self.btn_concluir.clicked.connect(lambda: self._acao(self.acoes.concluir))
        self.btn_reagendar.clicked.connect(lambda: self._acao(self.acoes.reagendar))
        self.btn_atribuir.clicked.connect(lambda: self._acao(self.acoes.atribuir))
        self.btn_receber.clicked.connect(self.receber)
        self._carregado = False
        self._silenciar = False

    def showEvent(self, evento) -> None:  # noqa: N802
        super().showEvent(evento)
        if not self._carregado:
            self._carregado = True
            self.carregar()

    def _cliente_mudou(self, cliente_id: str | None, limpar: bool = False) -> None:
        if limpar:
            self.cliente.limpar()
        self._silenciar = True
        _recarregar_processos(self.api, self.processo, self.cliente.cliente_id)
        self.processo.setItemText(0, "Todos os processos")
        self._silenciar = False
        self.carregar()

    def filtros(self) -> dict[str, Any]:
        resp = self.responsavel.currentData()
        return {"responsavel_id": None if resp == "__sem__" else resp, "sem_responsavel": resp == "__sem__",
                "cliente_id": self.cliente.cliente_id, "processo_id": self.processo.currentData(),
                "tipo": self.tipo.currentData(), "prioridade": self.prioridade.currentData(),
                "situacao": self.situacao.currentData(), "desde": ler_data_br(self.desde.text()),
                "ate": ler_data_br(self.ate.text())}

    def carregar(self) -> None:
        if self._silenciar:
            return
        try:
            filtros = self.filtros()
        except ValueError as exc:
            self.info.setText(str(exc))
            return
        try:
            with cursor_espera():
                r = self.api.pendencias(**filtros)
        except ErroAPI as exc:
            self.info.setText(exc.mensagem)
            return
        self.itens = r.itens
        for chave, lbl in self.cartoes.items():
            if chave == "financeiro":
                lbl.setText(str(sum(1 for i in r.itens if i.origem == "parcela")))
            else:
                lbl.setText(str(sum(1 for i in r.itens if i.grupo == chave and i.origem == "compromisso")))
        linhas, cores = [], []
        for i in r.itens:
            if i.origem == "parcela" and i.parcela:
                p = i.parcela
                linhas.append([data_br(p.vencimento), self.NOMES_GRUPO.get(i.grupo, i.grupo), "Parcela a receber",
                               f"{i.titulo} · restante {dinheiro_br(p.valor_restante)}", i.cliente_nome or "", "", "", ""])
                cores.append(CORES["erro"] if i.grupo == "atrasado" else CORES["dourado_claro"])
            else:
                c = i.compromisso
                linhas.append([quando_texto(c), self.NOMES_GRUPO.get(i.grupo, i.grupo),
                               TIPOS_COMPROMISSO.get(c.tipo, c.tipo), c.titulo, c.cliente_nome or "",
                               c.processo_rotulo or "", c.responsavel_nome or "Sem responsável",
                               PRIORIDADES.get(c.prioridade, "")])
                cores.append(cor_compromisso(c))
        _preencher(self.tabela, linhas, cores)
        self.info.setText(f"{len(r.itens)} pendência(s)" if r.itens else "Nenhuma pendência com estes filtros.")

    def _item(self) -> ItemPendencia | None:
        linha = self.tabela.currentRow()
        return self.itens[linha] if 0 <= linha < len(self.itens) and self.tabela.selectedItems() else None

    def abrir(self) -> None:
        i = self._item()
        if i is None:
            return
        if i.origem == "parcela":
            from .financeiro import FichaContrato

            ficha = FichaContrato(self.api, str(i.parcela.contrato_id), self)
            ficha.alterado.connect(self.carregar)
            ficha.exec()
        else:
            abrir_compromisso(self.api, str(i.compromisso.id), self, self.carregar)

    def _acao(self, acao) -> None:
        i = self._item()
        if i is None or i.origem != "compromisso" or i.compromisso.situacao != "agendado":
            QMessageBox.information(self, "Central de Pendências", "Escolha um compromisso em aberto na lista.")
            return
        if acao(i.compromisso):
            self.carregar()

    def receber(self) -> None:
        i = self._item()
        if i is None or i.origem != "parcela":
            QMessageBox.information(self, "Registrar recebimento", "Escolha uma parcela na lista.")
            return
        from .financeiro import DialogoRecebimento

        if DialogoRecebimento(self.api, i.parcela, i.cliente_nome or "", self).exec():
            self.carregar()
