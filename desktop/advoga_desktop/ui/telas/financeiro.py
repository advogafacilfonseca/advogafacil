"""Contratos e financeiro.

Valores só aparecem para quem tem a permissão "Financeiro" (o servidor nem envia os valores
aos demais). Com "Contratos", a pessoa vê e edita os dados do serviço contratado.
"""

from __future__ import annotations

import calendar
import uuid
from datetime import date, timedelta
from decimal import ROUND_DOWN, Decimal
from pathlib import Path
from typing import Any

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QDialog,
    QFileDialog,
    QFormLayout,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QInputDialog,
    QLabel,
    QListWidget,
    QListWidgetItem,
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

from advoga_shared.esquemas import (
    CATEGORIAS_DESPESA,
    FORMAS_PAGAMENTO,
    SITUACOES_CONTRATO,
    SITUACOES_PARCELA,
    Contrato,
    Despesa,
    Parcela,
)
from advoga_shared.permissoes import Permissao

from ...api_client.cliente import ClienteAPI, ErroAPI
from ..componentes.basicos import ajustar_altura, bloco_campo, campo, limpar_formulario, rotulo
from ..componentes.espera import cursor_espera
from ..componentes.formatos import data_br, data_hora_br, dinheiro_br, ler_data_br, ler_dinheiro_br
from ..componentes.seletores import SeletorCliente
from ..tema.tema import CORES

CENTAVO = Decimal("0.01")
ACOES_CONTRATO = {
    "contrato.criado": "Contrato cadastrado",
    "contrato.editado": "Dados do contrato alterados",
    "contrato.cancelado": "Contrato cancelado",
    "contrato.renegociado": "Parcelas renegociadas",
    "financeiro.recebimento": "Recebimento registrado",
    "financeiro.estorno": "Recebimento estornado",
    "financeiro.parcela_cancelada": "Parcela cancelada",
}


def pode_financeiro(api: ClienteAPI) -> bool:
    return bool(api.usuario and Permissao.FINANCEIRO in api.usuario.permissoes)


def pode_contratos(api: ClienteAPI) -> bool:
    return bool(api.usuario and Permissao.CONTRATOS in api.usuario.permissoes)


def situacao_parcela(p: Parcela) -> str:
    if p.situacao == "aberta":
        if p.atrasada:
            return "Atrasada"
        if p.valor_pago > 0:
            return "Paga em parte"
        return "A vencer"
    return SITUACOES_PARCELA.get(p.situacao, p.situacao)


def rotulo_parcela(p: Parcela) -> str:
    return "Entrada" if p.tipo == "entrada" else f"Parcela {p.numero}"


def _tabela(colunas: list[str], esticar: int | None = None) -> QTableWidget:
    t = QTableWidget(0, len(colunas))
    t.setHorizontalHeaderLabels(colunas)
    t.verticalHeader().setVisible(False)
    t.setAlternatingRowColors(True)
    t.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
    t.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
    t.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
    cab = t.horizontalHeader()
    for i in range(len(colunas)):
        cab.setSectionResizeMode(i, QHeaderView.ResizeMode.ResizeToContents)
    if esticar is not None:
        cab.setSectionResizeMode(esticar, QHeaderView.ResizeMode.Stretch)
    return t


def _preencher(t: QTableWidget, linhas: list[list[str]], cores: list[str | None] | None = None,
               alinhar_direita: tuple[int, ...] = ()) -> None:
    from PySide6.QtGui import QColor

    t.setRowCount(len(linhas))
    for i, valores in enumerate(linhas):
        for j, v in enumerate(valores):
            item = QTableWidgetItem(v)
            item.setToolTip(v)
            if j in alinhar_direita:
                item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            if cores and cores[i]:
                item.setForeground(QColor(cores[i]))
            t.setItem(i, j, item)


def _cartao_valor(titulo: str) -> tuple[QFrame, QLabel]:
    f = QFrame()
    f.setObjectName("cartao")
    lay = QVBoxLayout(f)
    lay.setContentsMargins(14, 10, 14, 10)
    lay.addWidget(rotulo(titulo, "rotuloCampo"))
    valor = QLabel("—")
    valor.setStyleSheet(f"font-size:14pt; font-weight:600; color:{CORES['dourado_claro']};")
    lay.addWidget(valor)
    return f, valor


def _somar_meses(d: date, meses: int, dia: int) -> date:
    mes = d.month - 1 + meses
    ano = d.year + mes // 12
    mes = mes % 12 + 1
    return date(ano, mes, min(dia, calendar.monthrange(ano, mes)[1]))


def plano_local(saldo: Decimal, n: int, valor_parcela: Decimal | None, primeiro: date | None,
                dia: int | None) -> list[tuple[Decimal, date]]:
    """Mesma regra do servidor, só para mostrar a prévia antes de salvar."""
    if saldo <= 0 or n <= 0 or primeiro is None:
        return []
    if valor_parcela:
        valores = [valor_parcela] * n
    else:
        base = (saldo / n).quantize(CENTAVO, rounding=ROUND_DOWN)
        valores = [base] * n
        valores[-1] = saldo - base * (n - 1)
    dia = dia or primeiro.day
    return [(v, primeiro if i == 0 else _somar_meses(primeiro, i, dia)) for i, v in enumerate(valores)]


def _combo_processos(api: ClienteAPI, cliente_id: str | None, atual: str | None = None) -> QComboBox:
    c = QComboBox()
    c.setMinimumHeight(36)
    _recarregar_processos(api, c, cliente_id, atual)
    return c


def _recarregar_processos(api: ClienteAPI, c: QComboBox, cliente_id: str | None, atual: str | None = None) -> None:
    c.clear()
    c.addItem("Nenhum", None)
    if cliente_id:
        try:
            for p in api.processos_opcoes(cliente_id):
                c.addItem(p.rotulo, str(p.id))
        except ErroAPI:
            pass
    c.setCurrentIndex(max(c.findData(atual), 0))


def _combo_usuarios(api: ClienteAPI, atual: str | None, vazio: str = "Não definido") -> QComboBox:
    c = QComboBox()
    c.setMinimumHeight(36)
    c.addItem(vazio, None)
    try:
        for u in api.usuarios_ativos():
            c.addItem(u.nome, str(u.id))
    except ErroAPI:
        pass
    c.setCurrentIndex(max(c.findData(atual), 0))
    return c


def _botoes(dialogo: QDialog, texto: str) -> tuple[QHBoxLayout, QPushButton]:
    b = QHBoxLayout()
    cancelar = QPushButton("Cancelar")
    salvar = QPushButton(texto)
    salvar.setObjectName("primario")
    b.addWidget(cancelar)
    b.addStretch()
    b.addWidget(salvar)
    cancelar.clicked.connect(dialogo.reject)
    return b, salvar


# ============================================================================== contrato
class DialogoContrato(QDialog):
    """Cadastro do contrato: gera automaticamente a entrada e as parcelas (a receber)."""

    def __init__(self, api: ClienteAPI, cliente: tuple[str, str] | None = None, parent=None) -> None:
        super().__init__(parent)
        self.api = api
        self.resultado: Contrato | None = None
        self.setWindowTitle("Novo contrato")
        self.setMinimumSize(860, 700)
        externo = QVBoxLayout(self)
        externo.setContentsMargins(0, 0, 0, 0)
        rolagem = QScrollArea()
        rolagem.setWidgetResizable(True)
        conteudo = QWidget()
        lay = QVBoxLayout(conteudo)
        lay.setContentsMargins(28, 20, 28, 12)
        lay.addWidget(rotulo("Novo contrato", "secao"))
        lay.addWidget(rotulo("As parcelas são geradas automaticamente como valores a receber. O dinheiro só conta "
                             "como recebido quando cada pagamento for registrado.", "rotuloCampo", True))
        self.cliente = SeletorCliente(api)
        self.processo = _combo_processos(api, None)
        self.servico = campo("Ex.: Defesa criminal em ação penal, Habeas corpus", maximo=300)
        self.responsavel = _combo_usuarios(api, None)
        self.inicio = campo("dd/mm/aaaa", maximo=10)
        self.inicio.setText(date.today().strftime("%d/%m/%Y"))
        self.total = campo("0,00", maximo=20)
        self.entrada = campo("0,00", maximo=20)
        self.venc_entrada = campo("dd/mm/aaaa (padrão: início)", maximo=10)
        self.qtd = campo("0", maximo=3)
        self.valor_parcela = campo("Automático", maximo=20)
        self.primeiro = campo("dd/mm/aaaa", maximo=10)
        self.dia = campo("Mesmo dia do 1º vencimento", maximo=2)
        self.personalizar = QCheckBox("Personalizar valores e vencimentos das parcelas")
        self.obs = QPlainTextEdit()
        self.obs.setMinimumHeight(60)
        g = QGridLayout()
        g.setHorizontalSpacing(14)
        g.addWidget(bloco_campo("Cliente *", self.cliente), 0, 0, 1, 2)
        g.addWidget(bloco_campo("Processo (opcional)", self.processo), 0, 2, 1, 2)
        g.addWidget(bloco_campo("Serviço contratado *", self.servico), 1, 0, 1, 2)
        g.addWidget(bloco_campo("Advogado responsável", self.responsavel), 1, 2)
        g.addWidget(bloco_campo("Início do atendimento *", self.inicio), 1, 3)
        g.addWidget(bloco_campo("Valor total do contrato *", self.total), 2, 0)
        g.addWidget(bloco_campo("Valor da entrada", self.entrada), 2, 1)
        g.addWidget(bloco_campo("Vencimento da entrada", self.venc_entrada), 2, 2)
        g.addWidget(bloco_campo("Quantidade de parcelas", self.qtd), 3, 0)
        g.addWidget(bloco_campo("Valor de cada parcela", self.valor_parcela), 3, 1)
        g.addWidget(bloco_campo("Primeiro vencimento", self.primeiro), 3, 2)
        g.addWidget(bloco_campo("Dia dos vencimentos seguintes", self.dia), 3, 3)
        lay.addLayout(g)
        lay.addWidget(self.personalizar)
        self.previa = QTableWidget(0, 3)
        self.previa.setHorizontalHeaderLabels(["Parcela", "Vencimento (dd/mm/aaaa)", "Valor"])
        self.previa.verticalHeader().setVisible(False)
        self.previa.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.previa.setMinimumHeight(170)
        self.previa.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        lay.addWidget(self.previa)
        self.resumo = rotulo("", "rotuloCampo", True)
        lay.addWidget(self.resumo)
        lay.addWidget(bloco_campo("Observações contratuais", self.obs))
        rolagem.setWidget(conteudo)
        externo.addWidget(rolagem, 1)
        rodape = QVBoxLayout()
        rodape.setContentsMargins(28, 0, 28, 18)
        self.erro = rotulo("", "erro", True)
        rodape.addWidget(self.erro)
        b, self.btn_salvar = _botoes(self, "Cadastrar contrato")
        rodape.addLayout(b)
        externo.addLayout(rodape)
        self.btn_salvar.clicked.connect(self.salvar)
        self.cliente.alterado.connect(lambda cid: _recarregar_processos(api, self.processo, cid))
        for w in (self.total, self.entrada, self.qtd, self.valor_parcela, self.primeiro, self.dia):
            w.textChanged.connect(self.atualizar_previa)
        self.personalizar.toggled.connect(self._alternar_personalizacao)
        if cliente:
            self.cliente.definir(*cliente)
            self.cliente.btn.setEnabled(False)
        self.resize(900, 780)

    def _numeros(self) -> tuple[Decimal, Decimal, int, Decimal | None, date | None, int | None]:
        total = ler_dinheiro_br(self.total.text()) or Decimal("0")
        entrada = ler_dinheiro_br(self.entrada.text()) or Decimal("0")
        qtd = int(self.qtd.text()) if self.qtd.text().strip().isdigit() else 0
        vp = ler_dinheiro_br(self.valor_parcela.text())
        primeiro = ler_data_br(self.primeiro.text())
        dia = int(self.dia.text()) if self.dia.text().strip().isdigit() else None
        return total, entrada, qtd, vp, primeiro, dia

    def atualizar_previa(self) -> None:
        if self.personalizar.isChecked():
            self._atualizar_resumo()
            return
        try:
            total, entrada, qtd, vp, primeiro, dia = self._numeros()
        except ValueError:
            return
        plano = plano_local(total - entrada, qtd, vp, primeiro, dia)
        self.previa.setRowCount(len(plano))
        for i, (v, d) in enumerate(plano):
            for j, txt in enumerate([f"Parcela {i + 1}", d.strftime("%d/%m/%Y"), dinheiro_br(v)]):
                self.previa.setItem(i, j, QTableWidgetItem(txt))
        self._atualizar_resumo()

    def _parcelas_da_tabela(self) -> list[tuple[Decimal, date]]:
        saida = []
        for i in range(self.previa.rowCount()):
            d = ler_data_br(self.previa.item(i, 1).text() if self.previa.item(i, 1) else "")
            v = ler_dinheiro_br(self.previa.item(i, 2).text() if self.previa.item(i, 2) else "")
            if d is None or v is None:
                raise ValueError(f"Parcela {i + 1}: informe vencimento e valor.")
            saida.append((v, d))
        return saida

    def _atualizar_resumo(self) -> None:
        try:
            total, entrada, *_ = self._numeros()
            soma = sum((v for v, _d in self._parcelas_da_tabela()), Decimal("0"))
        except ValueError:
            self.resumo.setText("")
            return
        texto = f"Entrada {dinheiro_br(entrada)} + parcelas {dinheiro_br(soma)} = {dinheiro_br(entrada + soma)}"
        if total and entrada + soma != total:
            texto += f"  ·  diferença de {dinheiro_br(total - entrada - soma)} para o valor total"
        self.resumo.setText(texto)

    def _alternar_personalizacao(self, ligado: bool) -> None:
        self.previa.setEditTriggers(QAbstractItemView.EditTrigger.AllEditTriggers if ligado
                                    else QAbstractItemView.EditTrigger.NoEditTriggers)
        for w in (self.valor_parcela, self.primeiro, self.dia):
            w.setEnabled(not ligado)
        if ligado:
            self.previa.itemChanged.connect(self._atualizar_resumo)
            if self.previa.rowCount() == 0:
                _t, _e, qtd, *_ = self._numeros()
                self.previa.setRowCount(max(qtd, 1))
                for i in range(self.previa.rowCount()):
                    self.previa.setItem(i, 0, QTableWidgetItem(f"Parcela {i + 1}"))
        else:
            self.previa.itemChanged.disconnect(self._atualizar_resumo)
            self.atualizar_previa()

    def _dados(self) -> dict[str, Any]:
        total, entrada, qtd, vp, primeiro, dia = self._numeros()
        ini = ler_data_br(self.inicio.text())
        if not self.cliente.cliente_id:
            raise ValueError("Escolha o cliente.")
        if ini is None:
            raise ValueError("Informe a data de início do atendimento.")
        if total <= 0:
            raise ValueError("Informe o valor total do contrato.")
        dados: dict[str, Any] = {
            "cliente_id": self.cliente.cliente_id, "processo_id": self.processo.currentData(),
            "servico_contratado": self.servico.text().strip(), "advogado_responsavel_id": self.responsavel.currentData(),
            "data_inicio": ini.isoformat(), "valor_total": str(total), "valor_entrada": str(entrada),
            "observacoes": self.obs.toPlainText().strip() or None,
        }
        ve = ler_data_br(self.venc_entrada.text())
        if ve:
            dados["vencimento_entrada"] = ve.isoformat()
        if self.personalizar.isChecked():
            dados["parcelas_personalizadas"] = [{"valor": str(v), "vencimento": d.isoformat()}
                                                for v, d in self._parcelas_da_tabela()]
        elif total - entrada > 0:
            dados.update({"quantidade_parcelas": qtd, "valor_parcela": str(vp) if vp else None,
                          "primeiro_vencimento": primeiro.isoformat() if primeiro else None, "dia_vencimento": dia})
        return dados

    def salvar(self) -> None:
        try:
            dados = self._dados()
        except ValueError as exc:
            self.erro.setText(str(exc))
            return
        try:
            with cursor_espera():
                self.resultado = self.api.criar_contrato(dados)
        except ErroAPI as exc:
            self.erro.setText(exc.mensagem)
            return
        self.accept()


class DialogoEditarContrato(QDialog):
    def __init__(self, api: ClienteAPI, c: Contrato, parent=None) -> None:
        super().__init__(parent)
        self.api = api
        self.contrato = c
        self.resultado: Contrato | None = None
        self.setWindowTitle("Editar contrato")
        self.setMinimumWidth(620)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(24, 18, 24, 18)
        lay.addWidget(rotulo("Editar dados do contrato", "secao"))
        lay.addWidget(rotulo("Valores mudam somente por renegociação ou cancelamento, que ficam registrados.",
                             "rotuloCampo", True))
        self.servico = campo(maximo=300)
        self.servico.setText(c.servico_contratado)
        self.processo = _combo_processos(api, str(c.cliente_id), str(c.processo_id) if c.processo_id else None)
        self.responsavel = _combo_usuarios(api, str(c.advogado_responsavel_id) if c.advogado_responsavel_id else None)
        self.inicio = campo("dd/mm/aaaa", maximo=10)
        self.inicio.setText(c.data_inicio.strftime("%d/%m/%Y"))
        self.obs = QPlainTextEdit()
        self.obs.setPlainText(c.observacoes or "")
        self.obs.setMinimumHeight(80)
        for titulo, w in (("Serviço contratado", self.servico), ("Processo", self.processo),
                          ("Advogado responsável", self.responsavel), ("Início do atendimento", self.inicio),
                          ("Observações contratuais", self.obs)):
            lay.addWidget(bloco_campo(titulo, w))
        self.erro = rotulo("", "erro", True)
        lay.addWidget(self.erro)
        b, self.btn_salvar = _botoes(self, "Salvar")
        lay.addLayout(b)
        self.btn_salvar.clicked.connect(self.salvar)
        ajustar_altura(self)

    def salvar(self) -> None:
        try:
            ini = ler_data_br(self.inicio.text())
        except ValueError as exc:
            self.erro.setText(str(exc))
            return
        dados = {"versao": self.contrato.versao, "servico_contratado": self.servico.text().strip(),
                 "processo_id": self.processo.currentData(), "advogado_responsavel_id": self.responsavel.currentData(),
                 "observacoes": self.obs.toPlainText().strip() or None}
        if ini:
            dados["data_inicio"] = ini.isoformat()
        try:
            with cursor_espera():
                self.resultado = self.api.atualizar_contrato(str(self.contrato.id), dados)
        except ErroAPI as exc:
            self.erro.setText(exc.mensagem)
            return
        self.accept()


# ========================================================================== recebimento
class DialogoRecebimento(QDialog):
    def __init__(self, api: ClienteAPI, parcela: Parcela, cliente_nome: str = "", parent=None) -> None:
        super().__init__(parent)
        self.api = api
        self.parcela = parcela
        self.resultado = None
        self.arquivo: Path | None = None
        self.setWindowTitle("Registrar recebimento")
        self.setMinimumWidth(560)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(24, 18, 24, 18)
        lay.addWidget(rotulo("Registrar recebimento", "secao"))
        info = (f"{cliente_nome + ' · ' if cliente_nome else ''}{rotulo_parcela(parcela)} · vencimento "
                f"{data_br(parcela.vencimento)}\nValor {dinheiro_br(parcela.valor)} · já recebido "
                f"{dinheiro_br(parcela.valor_pago)} · restante {dinheiro_br(parcela.valor_restante)}")
        lay.addWidget(rotulo(info, quebra=True))
        self.valor = campo(maximo=20)
        self.valor.setText(dinheiro_br(parcela.valor_restante).replace("R$ ", ""))
        self.data = campo("dd/mm/aaaa", maximo=10)
        self.data.setText(date.today().strftime("%d/%m/%Y"))
        self.forma = QComboBox()
        self.forma.setMinimumHeight(36)
        for k, v in FORMAS_PAGAMENTO.items():
            self.forma.addItem(v, k)
        self.obs = campo(maximo=2000)
        linha_comp = QHBoxLayout()
        self.comp_nome = campo("Nenhum arquivo")
        self.comp_nome.setReadOnly(True)
        escolher = QPushButton("Escolher...")
        linha_comp.addWidget(self.comp_nome, 1)
        linha_comp.addWidget(escolher)
        comp = QWidget()
        comp.setObjectName("bloco")
        comp.setLayout(linha_comp)
        linha_comp.setContentsMargins(0, 0, 0, 0)
        g = QGridLayout()
        g.addWidget(bloco_campo("Valor recebido *", self.valor), 0, 0)
        g.addWidget(bloco_campo("Data do recebimento *", self.data), 0, 1)
        g.addWidget(bloco_campo("Forma de pagamento *", self.forma), 1, 0)
        g.addWidget(bloco_campo("Observações", self.obs), 1, 1)
        lay.addLayout(g)
        lay.addWidget(bloco_campo("Comprovante (opcional)", comp))
        lay.addWidget(rotulo("Para receber só uma parte, altere o valor: a parcela continua em aberto com o "
                             "restante.", "rotuloCampo", True))
        self.erro = rotulo("", "erro", True)
        lay.addWidget(self.erro)
        b, self.btn_salvar = _botoes(self, "Registrar")
        lay.addLayout(b)
        self.btn_salvar.clicked.connect(self.salvar)
        escolher.clicked.connect(self._escolher)
        ajustar_altura(self)

    def _escolher(self) -> None:
        arquivo, _ = QFileDialog.getOpenFileName(self, "Escolher comprovante")
        if arquivo:
            self.definir_comprovante(Path(arquivo))

    def definir_comprovante(self, arquivo: Path) -> None:
        self.arquivo = arquivo
        self.comp_nome.setText(arquivo.name)

    def salvar(self) -> None:
        try:
            valor = ler_dinheiro_br(self.valor.text())
            data = ler_data_br(self.data.text())
        except ValueError as exc:
            self.erro.setText(str(exc))
            ajustar_altura(self)
            return
        if not valor or valor <= 0 or data is None:
            self.erro.setText("Informe o valor recebido e a data.")
            ajustar_altura(self)
            return
        try:
            with cursor_espera():
                comprovante_id = str(self.api.enviar_comprovante(self.arquivo).id) if self.arquivo else None
                self.resultado = self.api.registrar_pagamento({
                    "parcela_id": str(self.parcela.id), "valor": str(valor), "data_recebimento": data.isoformat(),
                    "forma_pagamento": self.forma.currentData(), "observacoes": self.obs.text().strip() or None,
                    "comprovante_id": comprovante_id})
        except ErroAPI as exc:
            self.erro.setText(exc.mensagem)
            ajustar_altura(self)
            return
        self.accept()


class DialogoRenegociar(QDialog):
    def __init__(self, api: ClienteAPI, c: Contrato, parent=None) -> None:
        super().__init__(parent)
        self.api = api
        self.contrato = c
        self.resultado: Contrato | None = None
        self.setWindowTitle("Renegociar parcelas")
        self.setMinimumWidth(620)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(24, 18, 24, 18)
        lay.addWidget(rotulo("Renegociar parcelas", "secao"))
        lay.addWidget(rotulo("Escolha as parcelas em aberto. O restante delas é substituído pelas novas parcelas; "
                             "o histórico guarda tudo.", "rotuloCampo", True))
        self.lista = QListWidget()
        self.lista.setMinimumHeight(150)
        for p in c.parcelas or []:
            if p.situacao == "aberta":
                item = QListWidgetItem(f"{rotulo_parcela(p)} · venc. {data_br(p.vencimento)} · restante "
                                       f"{dinheiro_br(p.valor_restante)}{' · ATRASADA' if p.atrasada else ''}")
                item.setData(Qt.ItemDataRole.UserRole, (str(p.id), p.valor_restante))
                item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
                item.setCheckState(Qt.CheckState.Checked if p.atrasada else Qt.CheckState.Unchecked)
                self.lista.addItem(item)
        lay.addWidget(self.lista)
        self.saldo = rotulo("", quebra=True)
        lay.addWidget(self.saldo)
        self.novo = campo(maximo=20)
        self.qtd = campo("1", maximo=3)
        self.qtd.setText("1")
        self.primeiro = campo("dd/mm/aaaa", maximo=10)
        self.primeiro.setText((date.today() + timedelta(days=30)).strftime("%d/%m/%Y"))
        self.dia = campo("Mesmo dia do 1º vencimento", maximo=2)
        self.motivo = campo("Ex.: Acordo com o cliente em 10/11", maximo=500)
        g = QGridLayout()
        g.addWidget(bloco_campo("Novo valor total renegociado *", self.novo), 0, 0)
        g.addWidget(bloco_campo("Quantidade de novas parcelas *", self.qtd), 0, 1)
        g.addWidget(bloco_campo("Primeiro vencimento *", self.primeiro), 1, 0)
        g.addWidget(bloco_campo("Dia dos vencimentos seguintes", self.dia), 1, 1)
        lay.addLayout(g)
        lay.addWidget(bloco_campo("Motivo *", self.motivo))
        self.erro = rotulo("", "erro", True)
        lay.addWidget(self.erro)
        b, self.btn_salvar = _botoes(self, "Renegociar")
        lay.addLayout(b)
        self.btn_salvar.clicked.connect(self.salvar)
        self.lista.itemChanged.connect(lambda _i: self._atualizar_saldo())
        self._atualizar_saldo()
        ajustar_altura(self)

    def selecionadas(self) -> list[tuple[str, Decimal]]:
        return [self.lista.item(i).data(Qt.ItemDataRole.UserRole) for i in range(self.lista.count())
                if self.lista.item(i).checkState() == Qt.CheckState.Checked]

    def _atualizar_saldo(self) -> None:
        saldo = sum((v for _i, v in self.selecionadas()), Decimal("0"))
        self.saldo.setText(f"Saldo das parcelas escolhidas: {dinheiro_br(saldo)}")
        self.novo.setText(dinheiro_br(saldo).replace("R$ ", ""))

    def salvar(self) -> None:
        sel = self.selecionadas()
        if not sel:
            self.erro.setText("Escolha pelo menos uma parcela.")
            return
        try:
            novo = ler_dinheiro_br(self.novo.text())
            primeiro = ler_data_br(self.primeiro.text())
        except ValueError as exc:
            self.erro.setText(str(exc))
            return
        dados = {"versao": self.contrato.versao, "parcelas_ids": [i for i, _v in sel],
                 "novo_valor": str(novo) if novo else None,
                 "quantidade_parcelas": int(self.qtd.text()) if self.qtd.text().isdigit() else None,
                 "primeiro_vencimento": primeiro.isoformat() if primeiro else None,
                 "dia_vencimento": int(self.dia.text()) if self.dia.text().isdigit() else None,
                 "motivo": self.motivo.text().strip()}
        try:
            with cursor_espera():
                self.resultado = self.api.renegociar(str(self.contrato.id), dados)
        except ErroAPI as exc:
            self.erro.setText(exc.mensagem)
            return
        self.accept()


# ========================================================================= ficha contrato
class FichaContrato(QDialog):
    alterado = Signal()

    def __init__(self, api: ClienteAPI, contrato_id: str, parent=None) -> None:
        super().__init__(parent)
        self.api = api
        self.contrato_id = contrato_id
        self.contrato: Contrato | None = None
        self.fin = pode_financeiro(api)
        self.setWindowTitle("Contrato")
        self.setMinimumSize(980, 680)
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
        self.btn_renegociar = QPushButton("Renegociar")
        self.btn_cancelar = QPushButton("Cancelar contrato")
        for b in (self.btn_editar, self.btn_renegociar, self.btn_cancelar):
            topo.addWidget(b, 0, Qt.AlignmentFlag.AlignTop)
        self.btn_editar.setVisible(pode_contratos(api))
        self.btn_renegociar.setVisible(self.fin)
        self.btn_cancelar.setVisible(self.fin and pode_contratos(api))
        lay.addLayout(topo)

        self.cartoes: dict[str, QLabel] = {}
        if self.fin:
            linha = QHBoxLayout()
            for chave, titulo in (("contratado", "Valor contratado"), ("recebido", "Recebido"),
                                  ("a_receber", "A receber"), ("vencido", "Em atraso"), ("cancelado", "Cancelado")):
                f, v = _cartao_valor(titulo)
                self.cartoes[chave] = v
                linha.addWidget(f)
            lay.addLayout(linha)

        self.abas = QTabWidget()
        rol = QScrollArea()
        rol.setWidgetResizable(True)
        self.aba_dados = QWidget()
        self.form = QFormLayout(self.aba_dados)
        self.form.setContentsMargins(20, 16, 20, 16)
        self.form.setVerticalSpacing(8)
        rol.setWidget(self.aba_dados)
        self.abas.addTab(rol, "Dados do contrato")
        if self.fin:
            aba_p = QWidget()
            lp = QVBoxLayout(aba_p)
            lp.setContentsMargins(12, 12, 12, 12)
            self.tabela_parcelas = _tabela(["Parcela", "Vencimento", "Valor", "Recebido", "Restante",
                                            "Situação"], 5)
            lp.addWidget(self.tabela_parcelas, 1)
            bp = QHBoxLayout()
            bp.addStretch()
            self.btn_receber = QPushButton("Registrar recebimento")
            self.btn_receber.setObjectName("primario")
            self.btn_cancelar_parcela = QPushButton("Cancelar parcela")
            bp.addWidget(self.btn_cancelar_parcela)
            bp.addWidget(self.btn_receber)
            lp.addLayout(bp)
            self.abas.addTab(aba_p, "Parcelas")
            aba_r = QWidget()
            lr = QVBoxLayout(aba_r)
            lr.setContentsMargins(12, 12, 12, 12)
            self.tabela_receb = _tabela(["Data", "Parcela", "Valor", "Forma", "Registrado por", "Comprovante",
                                         "Observações"], 6)
            lr.addWidget(self.tabela_receb, 1)
            br = QHBoxLayout()
            br.addStretch()
            self.btn_comprovante = QPushButton("Abrir comprovante")
            self.btn_estornar = QPushButton("Estornar recebimento")
            br.addWidget(self.btn_comprovante)
            br.addWidget(self.btn_estornar)
            lr.addLayout(br)
            self.abas.addTab(aba_r, "Recebimentos")
            self.btn_receber.clicked.connect(self.receber)
            self.btn_cancelar_parcela.clicked.connect(self.cancelar_parcela)
            self.btn_estornar.clicked.connect(self.estornar)
            self.btn_comprovante.clicked.connect(self.abrir_comprovante)
            self.tabela_parcelas.cellDoubleClicked.connect(lambda _l, _c: self.receber())
        self.tabela_hist = _tabela(["Data e hora", "Usuário", "O que aconteceu"], 2)
        self.abas.addTab(self.tabela_hist, "Histórico")
        lay.addWidget(self.abas, 1)
        fechar = QPushButton("Fechar")
        fechar.clicked.connect(self.accept)
        lay.addWidget(fechar, 0, Qt.AlignmentFlag.AlignRight)
        self.btn_editar.clicked.connect(self.editar)
        self.btn_renegociar.clicked.connect(self.renegociar)
        self.btn_cancelar.clicked.connect(self.cancelar_contrato)
        self.abas.currentChanged.connect(lambda _i: self.carregar_historico()
                                         if self.abas.currentWidget() is self.tabela_hist else None)
        self.pagamentos = []
        self.carregar()

    def carregar(self) -> None:
        with cursor_espera():
            c = self.contrato = self.api.obter_contrato(self.contrato_id)
        self.titulo.setText(c.servico_contratado)
        self.subtitulo.setText(f"Cliente: {c.cliente_nome}  ·  {SITUACOES_CONTRATO.get(c.situacao, c.situacao)}"
                               f"  ·  início {data_br(c.data_inicio)}")
        self.btn_renegociar.setEnabled(c.situacao == "ativo")
        self.btn_cancelar.setEnabled(c.situacao != "cancelado")
        limpar_formulario(self.form)
        for rot, valor in (("Cliente", c.cliente_nome), ("Serviço contratado", c.servico_contratado),
                           ("Processo", c.processo_rotulo), ("Advogado responsável", c.advogado_responsavel_nome),
                           ("Início do atendimento", data_br(c.data_inicio)),
                           ("Situação", SITUACOES_CONTRATO.get(c.situacao)),
                           ("Motivo do cancelamento", c.motivo_cancelamento),
                           ("Observações contratuais", c.observacoes), ("Cadastrado em", data_hora_br(c.criado_em))):
            if rot == "Motivo do cancelamento" and not valor:
                continue
            v = rotulo(valor or "—", quebra=True)
            v.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            self.form.addRow(rotulo(rot, "rotuloCampo"), v)
        if not self.fin:
            self.form.addRow(rotulo("Valores", "rotuloCampo"),
                             rotulo("Visíveis somente para quem tem a permissão Financeiro.", "rotuloCampo"))
            return
        for chave, lbl in self.cartoes.items():
            lbl.setText(dinheiro_br(getattr(c.totais, chave)))
        self.cartoes["vencido"].setStyleSheet(
            f"font-size:14pt; font-weight:600; color:{CORES['erro'] if c.totais.vencido > 0 else CORES['dourado_claro']};")
        ps = c.parcelas or []
        cores = [CORES["erro"] if p.atrasada else (CORES["texto_suave"] if p.situacao in ("cancelada", "renegociada")
                                                   else None) for p in ps]
        _preencher(self.tabela_parcelas, [[rotulo_parcela(p), data_br(p.vencimento), dinheiro_br(p.valor),
                                           dinheiro_br(p.valor_pago), dinheiro_br(p.valor_restante),
                                           situacao_parcela(p)] for p in ps], cores, (2, 3, 4))
        self.pagamentos, _ = self.api.listar_pagamentos(contrato_id=self.contrato_id)
        _preencher(self.tabela_receb, [[data_br(pg.data_recebimento), "Entrada" if pg.parcela_numero == 0 else
                                        f"Parcela {pg.parcela_numero}", dinheiro_br(pg.valor),
                                        FORMAS_PAGAMENTO.get(pg.forma_pagamento, pg.forma_pagamento),
                                        pg.registrado_por_nome or "—", pg.comprovante_nome or "",
                                        (f"ESTORNADO: {pg.motivo_estorno}" if pg.estornado_em else (pg.observacoes or ""))]
                                       for pg in self.pagamentos],
                   [CORES["texto_suave"] if pg.estornado_em else None for pg in self.pagamentos], (2,))
        self.abas.setTabText(2, f"Recebimentos ({sum(1 for p in self.pagamentos if not p.estornado_em)})")

    def carregar_historico(self) -> None:
        try:
            itens = self.api.historico_contrato(self.contrato_id)
        except ErroAPI as exc:
            QMessageBox.warning(self, "Histórico", exc.mensagem)
            return
        linhas = []
        for a in itens:
            d = a.detalhes or {}
            extra = ""
            if a.acao == "financeiro.recebimento":
                extra = f"{'Entrada' if d.get('parcela') == 0 else 'Parcela ' + str(d.get('parcela'))}: " \
                        f"{dinheiro_br(d.get('valor', 0))} ({FORMAS_PAGAMENTO.get(d.get('forma'), '')})"
            elif a.acao in ("financeiro.estorno", "financeiro.parcela_cancelada", "contrato.cancelado",
                            "contrato.renegociado"):
                extra = d.get("motivo", "")
            linhas.append([data_hora_br(a.ocorrido_em), a.usuario_nome or "—",
                           ACOES_CONTRATO.get(a.acao, a.acao) + (f". {extra}" if extra else "")])
        _preencher(self.tabela_hist, linhas)

    def _parcela_selecionada(self) -> Parcela | None:
        linha = self.tabela_parcelas.currentRow()
        ps = (self.contrato.parcelas or []) if self.contrato else []
        return ps[linha] if 0 <= linha < len(ps) and self.tabela_parcelas.selectedItems() else None

    def _apos(self) -> None:
        self.carregar()
        if self.abas.currentWidget() is self.tabela_hist:
            self.carregar_historico()
        self.alterado.emit()

    def receber(self) -> None:
        p = self._parcela_selecionada()
        if p is None:
            QMessageBox.information(self, "Registrar recebimento", "Escolha a parcela na lista.")
            return
        if p.situacao != "aberta":
            QMessageBox.information(self, "Registrar recebimento", "Esta parcela não está em aberto.")
            return
        d = DialogoRecebimento(self.api, p, self.contrato.cliente_nome or "", self)
        if d.exec():
            self._apos()

    def cancelar_parcela(self) -> None:
        p = self._parcela_selecionada()
        if p is None or p.situacao != "aberta":
            QMessageBox.information(self, "Cancelar parcela", "Escolha uma parcela em aberto.")
            return
        motivo, ok = QInputDialog.getText(self, "Cancelar parcela",
                                          f"Cancelar o restante de {rotulo_parcela(p)} "
                                          f"({dinheiro_br(p.valor_restante)})?\nInforme o motivo:")
        if not ok:
            return
        try:
            with cursor_espera():
                self.api.cancelar_parcela(str(p.id), motivo.strip(), p.versao)
        except ErroAPI as exc:
            QMessageBox.warning(self, "Cancelar parcela", exc.mensagem)
        self._apos()

    def _pagamento_selecionado(self):
        linha = self.tabela_receb.currentRow()
        return self.pagamentos[linha] if 0 <= linha < len(self.pagamentos) and self.tabela_receb.selectedItems() else None

    def estornar(self) -> None:
        pg = self._pagamento_selecionado()
        if pg is None or pg.estornado_em:
            QMessageBox.information(self, "Estornar", "Escolha um recebimento não estornado.")
            return
        motivo, ok = QInputDialog.getText(self, "Estornar recebimento",
                                          f"Estornar {dinheiro_br(pg.valor)} de {data_br(pg.data_recebimento)}?\n"
                                          "O registro continua no histórico. Informe o motivo:")
        if not ok:
            return
        try:
            with cursor_espera():
                self.api.estornar_pagamento(str(pg.id), motivo.strip())
        except ErroAPI as exc:
            QMessageBox.warning(self, "Estornar", exc.mensagem)
        self._apos()

    def abrir_comprovante(self) -> Path | None:
        pg = self._pagamento_selecionado()
        if pg is None or not pg.comprovante_id:
            QMessageBox.information(self, "Comprovante", "Este recebimento não tem comprovante.")
            return None
        return abrir_comprovante(self.api, str(pg.comprovante_id), pg.comprovante_nome or "comprovante", self)

    def editar(self) -> None:
        d = DialogoEditarContrato(self.api, self.contrato, self)
        if d.exec():
            self._apos()

    def renegociar(self) -> None:
        d = DialogoRenegociar(self.api, self.contrato, self)
        if d.exec():
            self._apos()

    def cancelar_contrato(self) -> None:
        motivo, ok = QInputDialog.getText(self, "Cancelar contrato",
                                          "As parcelas em aberto serão canceladas. Recebimentos já registrados "
                                          "continuam valendo.\nInforme o motivo:")
        if not ok:
            return
        try:
            with cursor_espera():
                self.api.cancelar_contrato(self.contrato_id, motivo.strip(), self.contrato.versao)
        except ErroAPI as exc:
            QMessageBox.warning(self, "Cancelar contrato", exc.mensagem)
        self._apos()


def abrir_comprovante(api: ClienteAPI, comprovante_id: str, nome: str, pai: QWidget | None = None) -> Path | None:
    from PySide6.QtCore import QUrl
    from PySide6.QtGui import QDesktopServices

    from .documentos import pasta_visualizacao

    destino = pasta_visualizacao() / uuid.uuid4().hex[:8] / nome
    try:
        with cursor_espera():
            api.baixar_comprovante(comprovante_id, destino)
    except ErroAPI as exc:
        QMessageBox.warning(pai, "Comprovante", exc.mensagem)
        return None
    QDesktopServices.openUrl(QUrl.fromLocalFile(str(destino)))
    return destino


# ============================================================================= listagem
class PainelContratos(QWidget):
    def __init__(self, api: ClienteAPI, cliente: tuple[str, str] | None = None) -> None:
        super().__init__()
        self.api = api
        self.cliente = cliente
        self.fin = pode_financeiro(api)
        self.contratos: list[Contrato] = []
        lay = QVBoxLayout(self)
        lay.setContentsMargins(12, 12, 12, 12)
        barra = QHBoxLayout()
        self.situacao = QComboBox()
        self.situacao.setMinimumHeight(36)
        self.situacao.addItem("Todas as situações", None)
        for k, v in SITUACOES_CONTRATO.items():
            self.situacao.addItem(v, k)
        barra.addWidget(self.situacao)
        barra.addStretch()
        self.btn_novo = QPushButton("Novo contrato")
        self.btn_novo.setObjectName("primario")
        self.btn_novo.setVisible(self.fin and pode_contratos(api))
        barra.addWidget(self.btn_novo)
        lay.addLayout(barra)
        colunas = ["Cliente", "Serviço contratado", "Início", "Situação"]
        if self.fin:
            colunas += ["Contratado", "Recebido", "A receber", "Em atraso"]
        self.tabela = _tabela(colunas, 1)
        self.tabela.setColumnHidden(0, cliente is not None)
        lay.addWidget(self.tabela, 1)
        self.info = rotulo("", "rotuloCampo")
        lay.addWidget(self.info)
        self.situacao.currentIndexChanged.connect(lambda _i: self.carregar())
        self.btn_novo.clicked.connect(self.novo)
        self.tabela.cellDoubleClicked.connect(lambda linha, _c: self.abrir_linha(linha))

    def carregar(self, _pagina: int = 1) -> None:
        try:
            with cursor_espera():
                r = self.api.listar_contratos(self.cliente[0] if self.cliente else None, self.situacao.currentData(),
                                              por_pagina=200)
        except ErroAPI as exc:
            self.info.setText(exc.mensagem)
            return
        self.contratos = r.itens
        linhas, cores = [], []
        for c in r.itens:
            linha = [c.cliente_nome or "", c.servico_contratado, data_br(c.data_inicio),
                     SITUACOES_CONTRATO.get(c.situacao, c.situacao)]
            if self.fin and c.totais:
                t = c.totais
                linha += [dinheiro_br(t.contratado), dinheiro_br(t.recebido), dinheiro_br(t.a_receber),
                          dinheiro_br(t.vencido)]
                cores.append(CORES["erro"] if t.vencido > 0 else None)
            else:
                cores.append(None)
            linhas.append(linha)
        _preencher(self.tabela, linhas, cores, (4, 5, 6, 7))
        self.info.setText("Nenhum contrato." if not r.total else
                          f"{r.total} contrato(s) · dê dois cliques para abrir")

    def abrir_linha(self, linha: int) -> None:
        if 0 <= linha < len(self.contratos):
            self.abrir(str(self.contratos[linha].id))

    def abrir(self, contrato_id: str) -> None:
        try:
            ficha = FichaContrato(self.api, contrato_id, self)
        except ErroAPI as exc:
            QMessageBox.warning(self, "Contrato", exc.mensagem)
            return
        ficha.alterado.connect(self.carregar)
        ficha.exec()

    def novo(self) -> None:
        d = DialogoContrato(self.api, self.cliente, self)
        if d.exec() and d.resultado:
            self.carregar()
            self.abrir(str(d.resultado.id))


class TelaContratos(QWidget):
    def __init__(self, api: ClienteAPI) -> None:
        super().__init__()
        lay = QVBoxLayout(self)
        lay.setContentsMargins(28, 24, 28, 20)
        lay.addWidget(rotulo("Contratos", "titulo"))
        self.painel = PainelContratos(api)
        self.painel.layout().setContentsMargins(0, 8, 0, 0)
        lay.addWidget(self.painel, 1)
        self._carregado = False

    def showEvent(self, evento) -> None:  # noqa: N802
        super().showEvent(evento)
        if not self._carregado:
            self._carregado = True
            self.painel.carregar()


# ============================================================================== despesas
class DialogoDespesa(QDialog):
    def __init__(self, api: ClienteAPI, despesa: Despesa | None = None, parent=None) -> None:
        super().__init__(parent)
        self.api = api
        self.original = despesa
        self.resultado: Despesa | None = None
        self.arquivo: Path | None = None
        self.setWindowTitle("Editar despesa" if despesa else "Nova despesa")
        self.setMinimumWidth(640)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(24, 18, 24, 18)
        lay.addWidget(rotulo("Editar despesa" if despesa else "Outras despesas · novo lançamento", "secao"))
        self.descricao = campo("Ex.: Gasolina para buscar o cliente", maximo=300)
        self.categoria = QComboBox()
        self.categoria.setMinimumHeight(36)
        for k, v in CATEGORIAS_DESPESA.items():
            self.categoria.addItem(v, k)
        self.valor = campo("0,00", maximo=20)
        self.data = campo("dd/mm/aaaa", maximo=10)
        self.data.setText(date.today().strftime("%d/%m/%Y"))
        atual_resp = str(despesa.responsavel_id) if despesa and despesa.responsavel_id else (
            str(api.usuario.id) if api.usuario else None)
        self.responsavel = _combo_usuarios(api, atual_resp, "—")
        self.cliente = SeletorCliente(api)
        self.processo = _combo_processos(api, None)
        self.obs = campo(maximo=2000)
        self.comp_nome = campo("Nenhum arquivo")
        self.comp_nome.setReadOnly(True)
        escolher = QPushButton("Anexar comprovante...")
        g = QGridLayout()
        g.addWidget(bloco_campo("Descrição *", self.descricao), 0, 0, 1, 2)
        g.addWidget(bloco_campo("Categoria *", self.categoria), 1, 0)
        g.addWidget(bloco_campo("Valor *", self.valor), 1, 1)
        g.addWidget(bloco_campo("Data *", self.data), 2, 0)
        g.addWidget(bloco_campo("Usuário responsável", self.responsavel), 2, 1)
        g.addWidget(bloco_campo("Cliente relacionado (opcional)", self.cliente), 3, 0)
        g.addWidget(bloco_campo("Processo relacionado (opcional)", self.processo), 3, 1)
        g.addWidget(bloco_campo("Observações", self.obs), 4, 0, 1, 2)
        g.addWidget(bloco_campo("Comprovante", self.comp_nome), 5, 0)
        g.addWidget(escolher, 5, 1, Qt.AlignmentFlag.AlignBottom)
        lay.addLayout(g)
        self.erro = rotulo("", "erro", True)
        lay.addWidget(self.erro)
        b, self.btn_salvar = _botoes(self, "Salvar" if despesa else "Lançar despesa")
        lay.addLayout(b)
        self.btn_salvar.clicked.connect(self.salvar)
        escolher.clicked.connect(self._escolher)
        self.cliente.alterado.connect(lambda cid: _recarregar_processos(api, self.processo, cid))
        if despesa:
            self.descricao.setText(despesa.descricao)
            self.categoria.setCurrentIndex(max(self.categoria.findData(despesa.categoria), 0))
            self.valor.setText(dinheiro_br(despesa.valor).replace("R$ ", ""))
            self.data.setText(despesa.data.strftime("%d/%m/%Y"))
            if despesa.cliente_id:
                self.cliente.definir(str(despesa.cliente_id), despesa.cliente_nome or "")
                self.processo.setCurrentIndex(max(self.processo.findData(
                    str(despesa.processo_id) if despesa.processo_id else None), 0))
            self.obs.setText(despesa.observacoes or "")
            self.comp_nome.setText(despesa.comprovante_nome or "Nenhum arquivo")
        ajustar_altura(self)

    def _escolher(self) -> None:
        arquivo, _ = QFileDialog.getOpenFileName(self, "Escolher comprovante")
        if arquivo:
            self.definir_comprovante(Path(arquivo))

    def definir_comprovante(self, arquivo: Path) -> None:
        self.arquivo = arquivo
        self.comp_nome.setText(arquivo.name)

    def salvar(self) -> None:
        try:
            valor = ler_dinheiro_br(self.valor.text())
            data = ler_data_br(self.data.text())
        except ValueError as exc:
            self.erro.setText(str(exc))
            ajustar_altura(self)
            return
        if not self.descricao.text().strip() or not valor or data is None:
            self.erro.setText("Preencha descrição, valor e data.")
            ajustar_altura(self)
            return
        dados: dict[str, Any] = {
            "descricao": self.descricao.text().strip(), "categoria": self.categoria.currentData(),
            "valor": str(valor), "data": data.isoformat(), "responsavel_id": self.responsavel.currentData(),
            "cliente_id": self.cliente.cliente_id, "processo_id": self.processo.currentData(),
            "observacoes": self.obs.text().strip() or None}
        try:
            with cursor_espera():
                if self.arquivo:
                    dados["comprovante_id"] = str(self.api.enviar_comprovante(self.arquivo).id)
                if self.original is None:
                    self.resultado = self.api.criar_despesa(dados)
                else:
                    self.resultado = self.api.atualizar_despesa(str(self.original.id),
                                                                dados | {"versao": self.original.versao})
        except ErroAPI as exc:
            self.erro.setText(exc.mensagem)
            ajustar_altura(self)
            return
        self.accept()


# ============================================================================ tela financeiro
class _Periodo(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("bloco")
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        hoje = date.today()
        self.inicio = campo("dd/mm/aaaa", maximo=10)
        self.fim = campo("dd/mm/aaaa", maximo=10)
        self.inicio.setText(hoje.replace(day=1).strftime("%d/%m/%Y"))
        self.fim.setText(hoje.replace(day=calendar.monthrange(hoje.year, hoje.month)[1]).strftime("%d/%m/%Y"))
        self.inicio.setMaximumWidth(130)
        self.fim.setMaximumWidth(130)
        self.btn = QPushButton("Atualizar")
        lay.addWidget(rotulo("Período:", "rotuloCampo"))
        lay.addWidget(self.inicio)
        lay.addWidget(rotulo("a", "rotuloCampo"))
        lay.addWidget(self.fim)
        lay.addWidget(self.btn)
        from PySide6.QtWidgets import QSizePolicy
        self.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Preferred)

    def valores(self) -> tuple[str, str]:
        i, f = ler_data_br(self.inicio.text()), ler_data_br(self.fim.text())
        if i is None or f is None:
            raise ValueError("Informe as datas do período.")
        return i.isoformat(), f.isoformat()


class TelaFinanceiro(QWidget):
    FILTROS = [("Em aberto", "abertas"), ("Vencidas", "vencidas"), ("A vencer", "a_vencer"), ("Pagas", "pagas"),
               ("Todas", "todas")]

    def __init__(self, api: ClienteAPI) -> None:
        super().__init__()
        self.api = api
        self.parcelas: list[Parcela] = []
        self.despesas: list[Despesa] = []
        lay = QVBoxLayout(self)
        lay.setContentsMargins(28, 24, 28, 20)
        topo = QHBoxLayout()
        topo.addWidget(rotulo("Financeiro", "titulo"))
        topo.addStretch()
        self.periodo = _Periodo()
        topo.addWidget(self.periodo)
        lay.addLayout(topo)
        lay.addWidget(rotulo("Área restrita: visível somente para a Master e pessoas autorizadas no financeiro.",
                             "rotuloCampo"))
        self.abas = QTabWidget()
        lay.addWidget(self.abas, 1)

        # Resumo
        aba = QWidget()
        la = QVBoxLayout(aba)
        la.setContentsMargins(14, 14, 14, 14)
        grade = QGridLayout()
        self.cartoes: dict[str, QLabel] = {}
        itens = [("total_contratado", "Total contratado"), ("total_recebido", "Total recebido"),
                 ("total_a_receber", "Total a receber"), ("total_vencido", "Em atraso"),
                 ("recebido_no_periodo", "Recebido no período"), ("previsto_no_periodo", "Previsto no período"),
                 ("despesas_no_periodo", "Despesas no período"), ("saldo_liquido_periodo", "Saldo líquido do período")]
        for i, (chave, titulo) in enumerate(itens):
            f, v = _cartao_valor(titulo)
            self.cartoes[chave] = v
            grade.addWidget(f, i // 4, i % 4)
        la.addLayout(grade)
        self.contagem = rotulo("", "rotuloCampo")
        la.addWidget(self.contagem)
        linha = QHBoxLayout()
        caixa_av = QVBoxLayout()
        caixa_av.addWidget(rotulo("Avisos de vencimento", "secao"))
        self.tabela_avisos = _tabela(["Aviso", "Cliente", "Parcela", "Vencimento", "Restante"], 1)
        caixa_av.addWidget(self.tabela_avisos)
        caixa_cat = QVBoxLayout()
        caixa_cat.addWidget(rotulo("Despesas por categoria", "secao"))
        self.tabela_cat = _tabela(["Categoria", "Valor"], 0)
        caixa_cat.addWidget(self.tabela_cat)
        linha.addLayout(caixa_av, 3)
        linha.addLayout(caixa_cat, 2)
        la.addLayout(linha, 1)
        self.abas.addTab(aba, "Resumo")

        # Parcelas
        aba = QWidget()
        lp = QVBoxLayout(aba)
        lp.setContentsMargins(12, 12, 12, 12)
        bp = QHBoxLayout()
        self.filtro = QComboBox()
        self.filtro.setMinimumHeight(36)
        for t, k in self.FILTROS:
            self.filtro.addItem(t, k)
        self.chk_periodo = QCheckBox("Somente vencimentos no período")
        bp.addWidget(self.filtro)
        bp.addWidget(self.chk_periodo)
        bp.addStretch()
        self.btn_receber = QPushButton("Registrar recebimento")
        self.btn_receber.setObjectName("primario")
        self.btn_abrir_contrato = QPushButton("Abrir contrato")
        bp.addWidget(self.btn_abrir_contrato)
        bp.addWidget(self.btn_receber)
        lp.addLayout(bp)
        self.tabela_parcelas = _tabela(["Vencimento", "Cliente", "Serviço", "Parcela", "Valor", "Recebido", "Restante",
                                        "Situação"], 2)
        lp.addWidget(self.tabela_parcelas, 1)
        self.info_parcelas = rotulo("", "rotuloCampo")
        lp.addWidget(self.info_parcelas)
        self.abas.addTab(aba, "Parcelas")

        # Recebimentos
        aba = QWidget()
        lr = QVBoxLayout(aba)
        lr.setContentsMargins(12, 12, 12, 12)
        self.tabela_receb = _tabela(["Data", "Cliente", "Parcela", "Valor", "Forma", "Registrado por", "Observações"], 6)
        lr.addWidget(self.tabela_receb, 1)
        self.info_receb = rotulo("", "rotuloCampo")
        lr.addWidget(self.info_receb)
        self.abas.addTab(aba, "Recebimentos")

        # Despesas
        aba = QWidget()
        ld = QVBoxLayout(aba)
        ld.setContentsMargins(12, 12, 12, 12)
        bd = QHBoxLayout()
        self.chk_canceladas = QCheckBox("Mostrar canceladas")
        bd.addWidget(self.chk_canceladas)
        bd.addStretch()
        self.btn_cancelar_despesa = QPushButton("Cancelar despesa")
        self.btn_editar_despesa = QPushButton("Editar")
        self.btn_nova_despesa = QPushButton("Nova despesa")
        self.btn_nova_despesa.setObjectName("primario")
        for b in (self.btn_cancelar_despesa, self.btn_editar_despesa, self.btn_nova_despesa):
            bd.addWidget(b)
        ld.addLayout(bd)
        self.tabela_despesas = _tabela(["Data", "Descrição", "Categoria", "Valor", "Responsável", "Cliente/Processo",
                                        "Comprovante"], 1)
        ld.addWidget(self.tabela_despesas, 1)
        self.info_despesas = rotulo("", "rotuloCampo")
        ld.addWidget(self.info_despesas)
        self.abas.addTab(aba, "Outras despesas")

        self.periodo.btn.clicked.connect(self.carregar)
        self.filtro.currentIndexChanged.connect(lambda _i: self.carregar_parcelas())
        self.chk_periodo.toggled.connect(lambda _v: self.carregar_parcelas())
        self.chk_canceladas.toggled.connect(lambda _v: self.carregar_despesas())
        self.btn_receber.clicked.connect(self.receber)
        self.btn_abrir_contrato.clicked.connect(self.abrir_contrato)
        self.tabela_parcelas.cellDoubleClicked.connect(lambda _l, _c: self.receber())
        self.btn_nova_despesa.clicked.connect(self.nova_despesa)
        self.btn_editar_despesa.clicked.connect(self.editar_despesa)
        self.btn_cancelar_despesa.clicked.connect(self.cancelar_despesa)
        self._carregado = False

    def showEvent(self, evento) -> None:  # noqa: N802
        super().showEvent(evento)
        if not self._carregado:
            self._carregado = True
            self.carregar()

    def carregar(self) -> None:
        self.carregar_resumo()
        self.carregar_parcelas()
        self.carregar_recebimentos()
        self.carregar_despesas()

    def _periodo(self) -> tuple[str, str] | None:
        try:
            return self.periodo.valores()
        except ValueError as exc:
            QMessageBox.warning(self, "Período", str(exc))
            return None

    def carregar_resumo(self) -> None:
        p = self._periodo()
        if not p:
            return
        try:
            with cursor_espera():
                r = self.api.resumo_financeiro(*p)
        except ErroAPI as exc:
            self.contagem.setText(exc.mensagem)
            return
        self.resumo = r
        for chave, lbl in self.cartoes.items():
            lbl.setText(dinheiro_br(getattr(r, chave)))
        cor = CORES["erro"] if r.total_vencido > 0 else CORES["dourado_claro"]
        self.cartoes["total_vencido"].setStyleSheet(f"font-size:14pt; font-weight:600; color:{cor};")
        cor = CORES["erro"] if r.saldo_liquido_periodo < 0 else CORES["sucesso"]
        self.cartoes["saldo_liquido_periodo"].setStyleSheet(f"font-size:14pt; font-weight:600; color:{cor};")
        self.contagem.setText(f"{r.parcelas_vencidas} parcela(s) vencida(s) · {r.parcelas_a_vencer} a vencer")
        cores = {"hoje": CORES["aviso"], "amanha": CORES["dourado_claro"], "atrasada": CORES["erro"]}
        _preencher(self.tabela_avisos, [[a.titulo, a.parcela.cliente_nome or "", rotulo_parcela(a.parcela),
                                         data_br(a.parcela.vencimento), dinheiro_br(a.parcela.valor_restante)]
                                        for a in r.avisos], [cores.get(a.tipo) for a in r.avisos], (4,))
        _preencher(self.tabela_cat, [[k, dinheiro_br(v)] for k, v in r.despesas_por_categoria.items()], None, (1,))

    def carregar_parcelas(self) -> None:
        p = self._periodo() if self.chk_periodo.isChecked() else (None, None)
        if p is None:
            return
        try:
            self.parcelas, total = self.api.listar_parcelas(self.filtro.currentData(), inicio=p[0], fim=p[1],
                                                            por_pagina=500)
        except ErroAPI as exc:
            self.info_parcelas.setText(exc.mensagem)
            return
        _preencher(self.tabela_parcelas, [[data_br(x.vencimento), x.cliente_nome or "", x.servico_contratado or "",
                                           rotulo_parcela(x), dinheiro_br(x.valor), dinheiro_br(x.valor_pago),
                                           dinheiro_br(x.valor_restante), situacao_parcela(x)] for x in self.parcelas],
                   [CORES["erro"] if x.atrasada else None for x in self.parcelas], (4, 5, 6))
        soma = sum((x.valor_restante for x in self.parcelas), Decimal("0"))
        self.info_parcelas.setText(f"{total} parcela(s)" + (f" · restante {dinheiro_br(soma)}" if soma else "")
                                   + (" · mostrando as 500 primeiras" if total > 500 else ""))

    def carregar_recebimentos(self) -> None:
        p = self._periodo()
        if not p:
            return
        try:
            pgs, total = self.api.listar_pagamentos(inicio=p[0], fim=p[1], por_pagina=500)
        except ErroAPI as exc:
            self.info_receb.setText(exc.mensagem)
            return
        _preencher(self.tabela_receb, [[data_br(x.data_recebimento), x.cliente_nome or "",
                                        "Entrada" if x.parcela_numero == 0 else f"Parcela {x.parcela_numero}",
                                        dinheiro_br(x.valor), FORMAS_PAGAMENTO.get(x.forma_pagamento, ""),
                                        x.registrado_por_nome or "",
                                        f"ESTORNADO: {x.motivo_estorno}" if x.estornado_em else (x.observacoes or "")]
                                       for x in pgs], [CORES["texto_suave"] if x.estornado_em else None for x in pgs],
                   (3,))
        soma = sum((x.valor for x in pgs if not x.estornado_em), Decimal("0"))
        self.info_receb.setText(f"{total} recebimento(s) no período · {dinheiro_br(soma)}")

    def carregar_despesas(self) -> None:
        p = self._periodo()
        if not p:
            return
        try:
            self.despesas, total = self.api.listar_despesas(p[0], p[1], incluir_canceladas=self.chk_canceladas.isChecked(),
                                                            por_pagina=500)
        except ErroAPI as exc:
            self.info_despesas.setText(exc.mensagem)
            return
        _preencher(self.tabela_despesas, [[data_br(d.data), d.descricao + (" (CANCELADA)" if d.cancelada_em else ""),
                                           CATEGORIAS_DESPESA.get(d.categoria, d.categoria), dinheiro_br(d.valor),
                                           d.responsavel_nome or "", " · ".join(x for x in [d.cliente_nome,
                                                                                           d.processo_rotulo] if x),
                                           d.comprovante_nome or ""] for d in self.despesas],
                   [CORES["texto_suave"] if d.cancelada_em else None for d in self.despesas], (3,))
        soma = sum((d.valor for d in self.despesas if not d.cancelada_em), Decimal("0"))
        self.info_despesas.setText(f"{total} despesa(s) · {dinheiro_br(soma)}")

    def _parcela(self) -> Parcela | None:
        linha = self.tabela_parcelas.currentRow()
        return self.parcelas[linha] if 0 <= linha < len(self.parcelas) and self.tabela_parcelas.selectedItems() else None

    def receber(self) -> None:
        p = self._parcela()
        if p is None or p.situacao != "aberta":
            QMessageBox.information(self, "Registrar recebimento", "Escolha uma parcela em aberto.")
            return
        if DialogoRecebimento(self.api, p, p.cliente_nome or "", self).exec():
            self.carregar()

    def abrir_contrato(self) -> None:
        p = self._parcela()
        if p is None:
            return
        ficha = FichaContrato(self.api, str(p.contrato_id), self)
        ficha.alterado.connect(self.carregar)
        ficha.exec()

    def _despesa(self) -> Despesa | None:
        linha = self.tabela_despesas.currentRow()
        return self.despesas[linha] if 0 <= linha < len(self.despesas) and self.tabela_despesas.selectedItems() else None

    def nova_despesa(self) -> None:
        if DialogoDespesa(self.api, None, self).exec():
            self.carregar()

    def editar_despesa(self) -> None:
        d = self._despesa()
        if d is None or d.cancelada_em:
            QMessageBox.information(self, "Editar despesa", "Escolha uma despesa não cancelada.")
            return
        if DialogoDespesa(self.api, d, self).exec():
            self.carregar()

    def cancelar_despesa(self) -> None:
        d = self._despesa()
        if d is None or d.cancelada_em:
            QMessageBox.information(self, "Cancelar despesa", "Escolha uma despesa não cancelada.")
            return
        motivo, ok = QInputDialog.getText(self, "Cancelar despesa",
                                          f"Cancelar \"{d.descricao}\" ({dinheiro_br(d.valor)})?\nInforme o motivo:")
        if not ok:
            return
        try:
            self.api.cancelar_despesa(str(d.id), motivo.strip(), d.versao)
        except ErroAPI as exc:
            QMessageBox.warning(self, "Cancelar despesa", exc.mensagem)
        self.carregar()
