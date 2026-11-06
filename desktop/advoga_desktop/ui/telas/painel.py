"""Painel inicial: indicadores reais vindos do servidor.

Cada bloco só aparece para quem tem acesso à área (o servidor nem envia os outros).
Valores financeiros só aparecem para quem tem a permissão Financeiro.
"""

from __future__ import annotations

from datetime import datetime

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from advoga_shared.esquemas import TIPOS_COMPROMISSO, CompromissoPainel, Painel
from advoga_shared.permissoes import ROTULOS_PERMISSAO

from ...api_client.cliente import ClienteAPI, ErroAPI
from ..componentes.basicos import cartao, rotulo
from ..componentes.formatos import dinheiro_br
from ..tema.tema import CORES

_DIAS = ["segunda-feira", "terça-feira", "quarta-feira", "quinta-feira", "sexta-feira", "sábado", "domingo"]
_MESES = ["janeiro", "fevereiro", "março", "abril", "maio", "junho", "julho", "agosto",
          "setembro", "outubro", "novembro", "dezembro"]


def data_por_extenso(d: datetime) -> str:
    return f"{_DIAS[d.weekday()]}, {d.day} de {_MESES[d.month - 1]} de {d.year}"


def saudacao(d: datetime) -> str:
    if d.hour < 12:
        return "Bom dia"
    if d.hour < 18:
        return "Boa tarde"
    return "Boa noite"


def _indicador(titulo: str) -> tuple[QFrame, QLabel]:
    f = cartao()
    lay = QVBoxLayout(f)
    lay.setContentsMargins(16, 12, 16, 12)
    lay.addWidget(rotulo(titulo, "rotuloCampo"))
    valor = QLabel("—")
    valor.setStyleSheet(f"font-size:18pt; font-weight:600; color:{CORES['dourado_claro']};")
    lay.addWidget(valor)
    return f, valor


def _texto_item(c: CompromissoPainel, mostrar_dia: bool) -> str:
    inicio = c.inicio.astimezone()
    if c.dia_inteiro:
        quando = inicio.strftime("%d/%m") if mostrar_dia else "Dia todo"
    else:
        quando = inicio.strftime("%d/%m %H:%M") if mostrar_dia else inicio.strftime("%H:%M")
    partes = [quando, TIPOS_COMPROMISSO.get(c.tipo, c.tipo), c.titulo]
    if c.cliente_nome:
        partes.append(c.cliente_nome)
    if c.responsavel_nome:
        partes.append(f"Resp.: {c.responsavel_nome}")
    return "  ·  ".join(partes)


class _Lista(QFrame):
    def __init__(self, titulo: str, vazio: str, mostrar_dia: bool, ao_abrir) -> None:
        super().__init__()
        self.setObjectName("cartao")
        self.vazio = vazio
        self.mostrar_dia = mostrar_dia
        lay = QVBoxLayout(self)
        lay.setContentsMargins(16, 12, 16, 12)
        self.titulo = rotulo(titulo, "secao")
        lay.addWidget(self.titulo)
        self.lista = QListWidget()
        self.lista.setMinimumHeight(150)
        self.lista.itemDoubleClicked.connect(lambda item: item.data(Qt.ItemDataRole.UserRole)
                                             and ao_abrir(item.data(Qt.ItemDataRole.UserRole)))
        lay.addWidget(self.lista)

    def preencher(self, itens: list[CompromissoPainel], total: int | None = None) -> None:
        self.lista.clear()
        for c in itens:
            item = QListWidgetItem(_texto_item(c, self.mostrar_dia))
            item.setData(Qt.ItemDataRole.UserRole, str(c.id))
            item.setToolTip("Dois cliques para abrir")
            if c.atrasado:
                item.setForeground(QColor(CORES.get("erro", "#E06C6C")))
            self.lista.addItem(item)
        if total is not None and total > len(itens):
            extra = QListWidgetItem(f"... e mais {total - len(itens)} (veja a Central de Pendências)")
            extra.setFlags(Qt.ItemFlag.NoItemFlags)
            self.lista.addItem(extra)
        if not itens:
            vazio = QListWidgetItem(self.vazio)
            vazio.setFlags(Qt.ItemFlag.NoItemFlags)
            self.lista.addItem(vazio)


class TelaPainel(QWidget):
    def __init__(self, api: ClienteAPI) -> None:
        super().__init__()
        self.api = api
        self.dados: Painel | None = None
        u = api.usuario
        assert u is not None
        externo = QVBoxLayout(self)
        externo.setContentsMargins(0, 0, 0, 0)
        rolagem = QScrollArea()
        rolagem.setWidgetResizable(True)
        rolagem.setFrameShape(QFrame.Shape.NoFrame)
        externo.addWidget(rolagem)
        conteudo = QWidget()
        rolagem.setWidget(conteudo)
        lay = QVBoxLayout(conteudo)
        lay.setContentsMargins(32, 28, 32, 28)
        lay.setSpacing(16)

        agora = datetime.now()
        topo = QHBoxLayout()
        textos = QVBoxLayout()
        self.ola = rotulo(f"{saudacao(agora)}, {u.nome_exibicao}", "titulo")
        self.data = rotulo(data_por_extenso(agora).capitalize(), "subtitulo")
        textos.addWidget(self.ola)
        textos.addWidget(self.data)
        topo.addLayout(textos, 1)
        self.btn_atualizar = QPushButton("Atualizar")
        self.btn_atualizar.clicked.connect(self.carregar)
        topo.addWidget(self.btn_atualizar, 0, Qt.AlignmentFlag.AlignTop)
        lay.addLayout(topo)
        self.erro = rotulo("", "erro", True)
        self.erro.hide()
        lay.addWidget(self.erro)

        # Indicadores gerais
        self.grade = QGridLayout()
        self.grade.setSpacing(12)
        self.ind: dict[str, tuple[QFrame, QLabel]] = {}
        for i, (chave, titulo) in enumerate([("clientes", "Clientes ativos"), ("processos", "Processos em andamento"),
                                            ("hoje", "Compromissos de hoje"), ("atrasados", "Atrasados")]):
            self.ind[chave] = _indicador(titulo)
            self.grade.addWidget(self.ind[chave][0], 0, i)
            self.ind[chave][0].hide()
        lay.addLayout(self.grade)

        # Financeiro (somente com permissão)
        self.caixa_fin = QWidget()
        lf = QVBoxLayout(self.caixa_fin)
        lf.setContentsMargins(0, 0, 0, 0)
        lf.addWidget(rotulo("Financeiro do mês", "secao"))
        gf = QGridLayout()
        gf.setSpacing(12)
        self.fin: dict[str, QLabel] = {}
        for i, (chave, titulo) in enumerate([("recebido", "Recebido no mês"), ("despesas", "Despesas no mês"),
                                            ("saldo", "Saldo do mês"), ("a_receber", "Total a receber"),
                                            ("vencido", "Em atraso"), ("vencem", "Vencem em 7 dias")]):
            quadro, valor = _indicador(titulo)
            self.fin[chave] = valor
            gf.addWidget(quadro, i // 3, i % 3)
        lf.addLayout(gf)
        self.caixa_fin.hide()
        lay.addWidget(self.caixa_fin)

        # Agenda
        self.caixa_agenda = QWidget()
        ga = QGridLayout(self.caixa_agenda)
        ga.setContentsMargins(0, 0, 0, 0)
        ga.setSpacing(12)
        self.lista_hoje = _Lista("Hoje", "Nenhum compromisso para hoje.", False, self.abrir_compromisso)
        self.lista_atrasados = _Lista("Atrasados", "Nada atrasado.", True, self.abrir_compromisso)
        self.lista_audiencias = _Lista("Próximas audiências (7 dias)", "Nenhuma audiência nos próximos 7 dias.",
                                       True, self.abrir_compromisso)
        self.lista_prazos = _Lista("Próximos prazos (7 dias)", "Nenhum prazo nos próximos 7 dias.", True,
                                   self.abrir_compromisso)
        ga.addWidget(self.lista_hoje, 0, 0)
        ga.addWidget(self.lista_atrasados, 0, 1)
        ga.addWidget(self.lista_audiencias, 1, 0)
        ga.addWidget(self.lista_prazos, 1, 1)
        self.caixa_agenda.hide()
        lay.addWidget(self.caixa_agenda)

        # Minha conta e acessos
        c2 = cartao()
        l2 = QVBoxLayout(c2)
        l2.setContentsMargins(20, 16, 20, 16)
        l2.addWidget(rotulo("Minha conta", "secao"))
        l2.addWidget(QLabel(f"{u.nome_completo}  ·  Usuário: {u.nome_usuario}  ·  Cargo: {u.cargo or '—'}"))
        if u.is_master:
            l2.addWidget(rotulo("Advogada Master: acesso total e administração do sistema.", "rotuloCampo"))
        if u.permissoes:
            l2.addWidget(rotulo("Acessos: " + ", ".join(ROTULOS_PERMISSAO[p] for p in u.permissoes), "rotuloCampo",
                                True))
        else:
            l2.addWidget(rotulo("Nenhum acesso liberado ainda. Fale com a Advogada Master.", "rotuloCampo", True))
        lay.addWidget(c2)
        lay.addStretch()

    def showEvent(self, evento) -> None:  # noqa: N802
        super().showEvent(evento)
        self.carregar()

    def carregar(self) -> None:
        agora = datetime.now()
        u = self.api.usuario
        if u is not None:
            self.ola.setText(f"{saudacao(agora)}, {u.nome_exibicao}")
        self.data.setText(data_por_extenso(agora).capitalize())
        try:
            p = self.api.painel()
        except ErroAPI as exc:
            self.erro.setText(f"Não foi possível atualizar o painel: {exc.mensagem}")
            self.erro.show()
            return
        self.erro.hide()
        self.dados = p
        self._valor("clientes", p.clientes_ativos)
        self._valor("processos", p.processos_em_andamento)
        self._valor("hoje", None if p.compromissos_hoje is None else len(p.compromissos_hoje))
        self._valor("atrasados", p.total_atrasados)
        if p.compromissos_hoje is not None:
            self.caixa_agenda.show()
            self.lista_hoje.preencher(p.compromissos_hoje)
            self.lista_atrasados.preencher(p.atrasados or [], p.total_atrasados)
            self.lista_audiencias.preencher(p.proximas_audiencias or [])
            self.lista_prazos.preencher(p.proximos_prazos or [])
        else:
            self.caixa_agenda.hide()
        f = p.financeiro
        self.caixa_fin.setVisible(f is not None)
        if f is not None:
            self.fin["recebido"].setText(dinheiro_br(f.recebido_no_mes))
            self.fin["despesas"].setText(dinheiro_br(f.despesas_no_mes))
            self.fin["saldo"].setText(dinheiro_br(f.saldo_do_mes))
            self.fin["a_receber"].setText(dinheiro_br(f.total_a_receber))
            self.fin["vencido"].setText(f"{dinheiro_br(f.total_vencido)} ({f.parcelas_vencidas})")
            self.fin["vencem"].setText(str(f.vencem_em_7_dias))

    def _valor(self, chave: str, valor: int | None) -> None:
        quadro, rot = self.ind[chave]
        quadro.setVisible(valor is not None)
        rot.setText(str(valor) if valor is not None else "—")

    def abrir_compromisso(self, compromisso_id: str) -> None:
        from .agenda import abrir_compromisso

        abrir_compromisso(self.api, compromisso_id, self, self.carregar)
