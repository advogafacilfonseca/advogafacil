"""Contratos e financeiro pela interface, contra o servidor real."""

from __future__ import annotations

from advoga_desktop.ui.telas import documentos as documentos_tela

from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

import pytest
from PySide6.QtCore import Qt
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QInputDialog, QMessageBox, QTableWidgetItem

from advoga_desktop.api_client.cliente import ClienteAPI, obter_certificado_servidor
from advoga_desktop.ui.componentes.formatos import dinheiro_br, ler_dinheiro_br
from advoga_desktop.ui.janela_principal import JanelaPrincipal
from advoga_desktop.ui.telas.clientes import FichaCliente
from advoga_desktop.ui.telas.financeiro import (
    DialogoContrato,
    DialogoDespesa,
    DialogoRecebimento,
    DialogoRenegociar,
    FichaContrato,
    TelaContratos,
    TelaFinanceiro,
    plano_local,
)
from tests.conftest import SENHA_MASTER, criar_usuario
from tests.desktop.test_fluxo_desktop import _captura, config_isolada, servidor, tema  # noqa: F401


@pytest.fixture
def api(servidor, master, tmp_path, monkeypatch):
    monkeypatch.setattr(documentos_tela, "PASTA_OVERRIDE", tmp_path / "local")
    a = ClienteAPI(servidor, obter_certificado_servidor(servidor))
    a.login("master", SENHA_MASTER)
    yield a
    a.fechar()


@pytest.fixture
def cliente_joao(api):
    c = api.criar_cliente({"nome_completo": "João Pedro da Silva"})
    return str(c.id), c.nome_completo


@pytest.fixture(autouse=True)
def sem_caixas(monkeypatch):
    avisos = []
    monkeypatch.setattr(QMessageBox, "information", lambda *a, **k: avisos.append(a[2]))
    monkeypatch.setattr(QMessageBox, "warning", lambda *a, **k: avisos.append(a[2]))
    return avisos


def _contrato(api, cliente_id, **extra):
    dados = {"cliente_id": cliente_id, "servico_contratado": "Defesa criminal em ação penal",
             "data_inicio": date.today().isoformat(), "valor_total": "6000", "valor_entrada": "1000",
             "quantidade_parcelas": 5, "primeiro_vencimento": (date.today() + timedelta(days=1)).isoformat()}
    dados.update(extra)
    return api.criar_contrato(dados)


def test_dinheiro_br():
    assert dinheiro_br(Decimal("1234.5")) == "R$ 1.234,50"
    assert ler_dinheiro_br("R$ 6.000,00") == Decimal("6000.00")
    assert ler_dinheiro_br("") is None
    with pytest.raises(ValueError):
        ler_dinheiro_br("abc")
    plano = plano_local(Decimal("1000"), 3, None, date(2027, 1, 31), None)
    assert [v for v, _ in plano] == [Decimal("333.33"), Decimal("333.33"), Decimal("333.34")]
    assert [d for _, d in plano] == [date(2027, 1, 31), date(2027, 2, 28), date(2027, 3, 31)]


def test_cadastrar_contrato_pela_tela(qtbot, tema, api, cliente_joao):
    d = DialogoContrato(api, cliente_joao)
    qtbot.addWidget(d)
    d.servico.setText("Defesa criminal em ação penal")
    d.responsavel.setCurrentIndex(1)
    d.total.setText("6.000,00")
    d.entrada.setText("1.000,00")
    d.qtd.setText("5")
    d.primeiro.setText("10/12/2030")
    assert d.previa.rowCount() == 5
    assert d.previa.item(4, 1).text() == "10/04/2031"
    assert d.previa.item(0, 2).text() == "R$ 1.000,00"
    assert "= R$ 6.000,00" in d.resumo.text()
    d.obs.setPlainText("Honorários conforme contrato assinado.")
    _captura(d, "20_novo_contrato")
    qtbot.mouseClick(d.btn_salvar, Qt.MouseButton.LeftButton)
    assert d.resultado is not None, d.erro.text()
    c = api.obter_contrato(str(d.resultado.id))
    assert c.totais.contratado == Decimal("6000.00") and c.totais.recebido == 0
    assert len(c.parcelas) == 6


def test_contrato_de_cliente_antigo_com_valor_ja_pago(qtbot, tema, api, cliente_joao):
    d = DialogoContrato(api, cliente_joao)
    qtbot.addWidget(d)
    d.servico.setText("Defesa criminal em ação penal")
    d.total.setText("6.000,00")
    d.ja_pago.setText("2.000,00")
    d.data_ja_pago.setText("10/01/2025")
    d.qtd.setText("4")
    d.primeiro.setText("10/12/2030")
    assert d.previa.rowCount() == 4 and d.previa.item(0, 2).text() == "R$ 1.000,00"
    assert d.resumo.text().startswith("Já pago R$ 2.000,00") and "= R$ 6.000,00" in d.resumo.text()
    _captura(d, "64_contrato_valor_ja_pago")
    qtbot.mouseClick(d.btn_salvar, Qt.MouseButton.LeftButton)
    assert d.resultado is not None, d.erro.text()
    c = api.obter_contrato(str(d.resultado.id))
    assert c.totais.recebido == Decimal("2000.00") and c.totais.a_receber == Decimal("4000.00")
    ficha = FichaContrato(api, str(c.id))
    qtbot.addWidget(ficha)
    assert ficha.tabela_parcelas.item(0, 0).text() == "Pago antes do sistema"
    assert ficha.cartoes["a_receber"].text() == "R$ 4.000,00"


def test_contrato_personalizado_e_erro_de_soma(qtbot, tema, api, cliente_joao):
    d = DialogoContrato(api, cliente_joao)
    qtbot.addWidget(d)
    d.servico.setText("Habeas corpus")
    d.total.setText("3000")
    d.qtd.setText("2")
    d.personalizar.setChecked(True)
    assert d.previa.rowCount() == 2
    for i, (venc, valor) in enumerate([("05/01/2031", "1.000,00"), ("05/03/2031", "1.500,00")]):
        d.previa.setItem(i, 1, QTableWidgetItem(venc))
        d.previa.setItem(i, 2, QTableWidgetItem(valor))
    assert "diferença de R$ 500,00" in d.resumo.text()
    qtbot.mouseClick(d.btn_salvar, Qt.MouseButton.LeftButton)
    assert d.resultado is None and d.erro.text()
    d.previa.setItem(1, 2, QTableWidgetItem("2.000,00"))
    qtbot.mouseClick(d.btn_salvar, Qt.MouseButton.LeftButton)
    assert d.resultado is not None, d.erro.text()
    vencs = [p.vencimento for p in api.obter_contrato(str(d.resultado.id)).parcelas]
    assert vencs == [date(2031, 1, 5), date(2031, 3, 5)]


def test_ficha_receber_parcial_estornar_cancelar_renegociar(qtbot, tema, api, cliente_joao, tmp_path, monkeypatch,
                                                            sem_caixas):
    c = _contrato(api, cliente_joao[0])
    ficha = FichaContrato(api, str(c.id))
    qtbot.addWidget(ficha)
    assert ficha.cartoes["a_receber"].text() == "R$ 6.000,00"
    assert ficha.tabela_parcelas.rowCount() == 6
    # Recebimento parcial da entrada, com comprovante
    ficha.tabela_parcelas.selectRow(0)
    comp = tmp_path / "pix.pdf"
    comp.write_bytes(b"%PDF-1.4 comprovante")

    def receber(self):
        self.valor.setText("400,00")
        self.forma.setCurrentIndex(self.forma.findData("pix"))
        self.definir_comprovante(comp)
        self.salvar()
        return self.result()

    monkeypatch.setattr(DialogoRecebimento, "exec", receber)
    ficha.receber()
    assert ficha.cartoes["recebido"].text() == "R$ 400,00"
    assert ficha.tabela_parcelas.item(0, 5).text() == "Paga em parte"
    assert ficha.tabela_receb.rowCount() == 1
    ficha.abas.setCurrentIndex(1)
    ficha.resize(1040, 700)
    _captura(ficha, "21_ficha_contrato")
    # Abrir comprovante
    abertos = []
    monkeypatch.setattr(QDesktopServices, "openUrl", lambda u: abertos.append(Path(u.toLocalFile())) or True)
    ficha.tabela_receb.selectRow(0)
    caminho = ficha.abrir_comprovante()
    assert caminho and caminho.read_bytes() == b"%PDF-1.4 comprovante"
    # Estorno
    monkeypatch.setattr(QInputDialog, "getText", lambda *a, **k: ("Valor lançado errado", True))
    ficha.estornar()
    assert ficha.cartoes["recebido"].text() == "R$ 0,00"
    assert "ESTORNADO" in ficha.tabela_receb.item(0, 6).text()
    # Recebimento total da entrada
    monkeypatch.setattr(DialogoRecebimento, "exec", lambda self: (self.salvar(), self.result())[1])
    ficha.tabela_parcelas.selectRow(0)
    ficha.receber()
    assert ficha.tabela_parcelas.item(0, 5).text() == "Paga"
    # Parcela paga não aceita novo recebimento
    ficha.tabela_parcelas.selectRow(0)
    ficha.receber()
    assert "não está em aberto" in sem_caixas[-1]
    # Cancelar parcela 5
    monkeypatch.setattr(QInputDialog, "getText", lambda *a, **k: ("Desconto concedido", True))
    ficha.tabela_parcelas.selectRow(5)
    ficha.cancelar_parcela()
    assert ficha.tabela_parcelas.item(5, 5).text() == "Cancelada"
    assert ficha.cartoes["cancelado"].text() == "R$ 1.000,00"
    # Renegociar parcelas 1 e 2 em 4 de R$ 500
    def reneg(self):
        for i in range(self.lista.count()):
            item = self.lista.item(i)
            item.setCheckState(Qt.CheckState.Checked if i < 2 else Qt.CheckState.Unchecked)
        assert "R$ 2.000,00" in self.saldo.text()
        self.qtd.setText("4")
        self.motivo.setText("Acordo com o cliente")
        self.salvar()
        return self.result()

    monkeypatch.setattr(DialogoRenegociar, "exec", reneg)
    ficha.renegociar()
    t = ficha.contrato.totais
    assert t.contratado == t.recebido + t.a_receber + t.cancelado
    assert sum(1 for p in ficha.contrato.parcelas if p.situacao == "renegociada") == 2
    assert ficha.tabela_parcelas.rowCount() == 10
    ficha.abas.setCurrentWidget(ficha.tabela_hist)
    textos = [ficha.tabela_hist.item(i, 2).text() for i in range(ficha.tabela_hist.rowCount())]
    assert any("Recebimento estornado" in x for x in textos) and any("renegociadas" in x for x in textos)
    _captura(ficha, "22_historico_contrato")
    # Cancelar contrato
    monkeypatch.setattr(QInputDialog, "getText", lambda *a, **k: ("Cliente desistiu", True))
    ficha.cancelar_contrato()
    assert ficha.contrato.situacao == "cancelado" and ficha.contrato.totais.a_receber == 0
    assert ficha.cartoes["recebido"].text() == "R$ 1.000,00"


def test_tela_financeiro_resumo_parcelas_despesas(qtbot, tema, api, cliente_joao, monkeypatch, tmp_path):
    hoje = date.today()
    _contrato(api, cliente_joao[0], valor_entrada="0", quantidade_parcelas=3, primeiro_vencimento=hoje.isoformat(),
              valor_total="3000")
    tela = TelaFinanceiro(api)
    qtbot.addWidget(tela)
    tela.resize(1180, 720)
    tela.periodo.inicio.setText((hoje - timedelta(days=40)).strftime("%d/%m/%Y"))
    tela.periodo.fim.setText((hoje + timedelta(days=70)).strftime("%d/%m/%Y"))
    tela.carregar()
    assert tela.cartoes["total_a_receber"].text() == "R$ 3.000,00"
    assert any("VENCE HOJE" in tela.tabela_avisos.item(i, 0).text() for i in range(tela.tabela_avisos.rowCount()))
    assert tela.tabela_parcelas.rowCount() == 3
    # Receber pela tela do financeiro
    monkeypatch.setattr(DialogoRecebimento, "exec", lambda self: (self.salvar(), self.result())[1])
    tela.tabela_parcelas.selectRow(0)
    tela.abas.setCurrentIndex(0)
    _captura(tela, "23_financeiro_resumo")
    tela.receber()
    assert tela.cartoes["recebido_no_periodo"].text() == "R$ 1.000,00"
    assert tela.tabela_receb.rowCount() == 1
    tela.filtro.setCurrentIndex(tela.filtro.findData("pagas"))
    assert tela.tabela_parcelas.rowCount() == 1
    # Despesa
    def lancar(self):
        self.descricao.setText("Gasolina para audiência em Campinas")
        self.categoria.setCurrentIndex(self.categoria.findData("combustivel"))
        self.valor.setText("150,00")
        self.cliente.definir(*cliente_joao)
        nota = tmp_path / "nota.jpg"
        nota.write_bytes(b"\xff\xd8 nota")
        self.definir_comprovante(nota)
        self.salvar()
        return self.result()

    monkeypatch.setattr(DialogoDespesa, "exec", lancar)
    tela.nova_despesa()
    assert tela.tabela_despesas.rowCount() == 1
    assert tela.tabela_despesas.item(0, 6).text() == "nota.jpg"
    assert tela.cartoes["despesas_no_periodo"].text() == "R$ 150,00"
    assert tela.cartoes["saldo_liquido_periodo"].text() == "R$ 850,00"
    tela.abas.setCurrentIndex(3)
    _captura(tela, "24_outras_despesas")
    # Editar e cancelar
    def editar(self):
        self.valor.setText("180,00")
        self.salvar()
        return self.result()

    monkeypatch.setattr(DialogoDespesa, "exec", editar)
    tela.tabela_despesas.selectRow(0)
    tela.editar_despesa()
    assert tela.tabela_despesas.item(0, 3).text() == "R$ 180,00"
    monkeypatch.setattr(QInputDialog, "getText", lambda *a, **k: ("Lançada em duplicidade", True))
    tela.tabela_despesas.selectRow(0)
    tela.cancelar_despesa()
    assert tela.tabela_despesas.rowCount() == 0
    tela.chk_canceladas.setChecked(True)
    assert "CANCELADA" in tela.tabela_despesas.item(0, 1).text()


def test_ficha_do_cliente_tem_aba_de_contratos(qtbot, tema, api, cliente_joao):
    _contrato(api, cliente_joao[0])
    ficha = FichaCliente(api, cliente_joao[0])
    qtbot.addWidget(ficha)
    ficha.abas.setCurrentWidget(ficha.painel_contratos)
    assert ficha.painel_contratos.tabela.rowCount() == 1
    assert ficha.painel_contratos.tabela.item(0, 4).text() == "R$ 6.000,00"
    _captura(ficha, "25_cliente_contratos")


def test_sigilo_financeiro_na_interface(qtbot, tema, api, servidor, cliente, token_master, cliente_joao):
    c = _contrato(api, cliente_joao[0])
    criar_usuario(cliente, token_master, "assistente", permissoes=["clientes", "contratos"])
    outro = ClienteAPI(servidor, api.certificado_pem)
    outro.login("assistente", "Definitiva2026")
    janela = JanelaPrincipal(outro)
    qtbot.addWidget(janela)
    menus = [b.text() for b in janela.grupo.buttons()]
    assert "Contratos" in menus and "Financeiro" not in menus
    tela = TelaContratos(outro)
    qtbot.addWidget(tela)
    tela.painel.carregar()
    assert tela.painel.tabela.columnCount() == 4 and tela.painel.tabela.rowCount() == 1
    assert not tela.painel.btn_novo.isVisibleTo(tela.painel)
    ficha = FichaContrato(outro, str(c.id))
    qtbot.addWidget(ficha)
    assert not ficha.cartoes and not hasattr(ficha, "tabela_parcelas")
    textos = " ".join(ficha.form.itemAt(i).widget().text() for i in range(ficha.form.count())
                      if ficha.form.itemAt(i).widget())
    assert "R$" not in textos and "permissão Financeiro" in textos
    ficha_cli = FichaCliente(outro, cliente_joao[0])
    qtbot.addWidget(ficha_cli)
    assert ficha_cli.abas.tabText(ficha_cli.abas.indexOf(ficha_cli.painel_contratos)) == "Contratos"
    # Master vê as duas seções
    janela_m = JanelaPrincipal(api)
    qtbot.addWidget(janela_m)
    menus = [b.text() for b in janela_m.grupo.buttons()]
    assert "Contratos" in menus and "Financeiro" in menus
    janela.close()
    janela_m.close()
