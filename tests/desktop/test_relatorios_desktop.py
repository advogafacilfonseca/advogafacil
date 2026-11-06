"""Painel inicial e relatórios pela interface, contra o servidor real."""

from __future__ import annotations

from datetime import date, datetime, time, timedelta

import pytest
from openpyxl import load_workbook
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QFileDialog

from advoga_desktop.api_client.cliente import ClienteAPI, obter_certificado_servidor
from advoga_desktop.ui.janela_principal import JanelaPrincipal
from advoga_desktop.ui.telas import documentos as documentos_tela
from advoga_desktop.ui.telas.painel import TelaPainel
from advoga_desktop.ui.telas.relatorios import TelaRelatorios
from tests.conftest import SENHA_MASTER, criar_usuario
from tests.desktop.test_fluxo_desktop import _captura, config_isolada, servidor, tema  # noqa: F401

HOJE = date.today()


def em(dias: int, hora: int = 10) -> str:
    return datetime.combine(HOJE + timedelta(days=dias), time(hora, 0)).astimezone().isoformat()


@pytest.fixture
def api(servidor, master, tmp_path, monkeypatch):
    monkeypatch.setattr(documentos_tela, "PASTA_OVERRIDE", tmp_path / "local")
    a = ClienteAPI(servidor, obter_certificado_servidor(servidor))
    a.login("master", SENHA_MASTER)
    yield a
    a.fechar()


@pytest.fixture
def dados(api):
    c = api.criar_cliente({"nome_completo": "Cliente Teste Relatório"})
    api.criar_processo({"cliente_id": str(c.id), "tipo_acao": "Ação Penal"})
    api.criar_compromisso({"titulo": "Audiência de instrução", "tipo": "audiencia", "inicio": em(2, 14),
                           "cliente_id": str(c.id)})
    api.criar_compromisso({"titulo": "Ligar para o cliente", "tipo": "ligacao", "inicio": em(0, 23)})
    ct = api.criar_contrato({"cliente_id": str(c.id), "servico_contratado": "Defesa criminal",
                             "data_inicio": HOJE.isoformat(), "valor_total": "2000", "valor_entrada": "500",
                             "quantidade_parcelas": 3, "primeiro_vencimento": (HOJE + timedelta(days=3)).isoformat()})
    api.registrar_pagamento({"parcela_id": str(ct.parcelas[0].id), "valor": "500", "forma_pagamento": "pix",
                             "data_recebimento": HOJE.isoformat()})
    api.criar_despesa({"descricao": "Estacionamento do fórum", "categoria": "estacionamento", "valor": "25",
                       "data": HOJE.isoformat()})
    return c


def test_painel_com_e_sem_financeiro(qtbot, tema, api, servidor, dados, cliente, token_master):
    tela = TelaPainel(api)
    qtbot.addWidget(tela)
    tela.resize(1200, 860)
    tela.carregar()
    assert tela.ind["clientes"][1].text() == "1" and tela.ind["processos"][1].text() == "1"
    assert tela.ind["hoje"][1].text() == "1" and tela.lista_audiencias.lista.count() == 1
    assert not tela.caixa_fin.isHidden() and tela.fin["recebido"].text() == "R$ 500,00"
    assert tela.fin["despesas"].text() == "R$ 25,00" and tela.fin["saldo"].text() == "R$ 475,00"
    _captura(tela, "50_painel_inicial")
    # Pessoa sem Financeiro e sem Processos: só os blocos liberados, nenhum valor
    criar_usuario(cliente, token_master, "assistente", permissoes=["clientes", "agenda"])
    outro = ClienteAPI(servidor, api.certificado_pem)
    outro.login("assistente", "Definitiva2026")
    t2 = TelaPainel(outro)
    qtbot.addWidget(t2)
    t2.carregar()
    assert t2.caixa_fin.isHidden() and t2.ind["processos"][0].isHidden()
    assert not t2.ind["clientes"][0].isHidden() and t2.lista_hoje.lista.count() == 1
    rel = TelaRelatorios(outro)
    qtbot.addWidget(rel)
    opcoes = [rel.tipo.itemData(i) for i in range(rel.tipo.count())]
    assert opcoes == ["clientes", "audiencias", "prazos", "pendencias"]
    janela = JanelaPrincipal(outro)
    qtbot.addWidget(janela)
    menus = [b.text() for b in janela.grupo.buttons()]
    assert "Relatórios" in menus and "Financeiro" not in menus
    janela.close()
    outro.fechar()


def test_gerar_e_exportar(qtbot, tema, api, dados, tmp_path, monkeypatch):
    abertos = []
    monkeypatch.setattr(QDesktopServices, "openUrl", lambda url: abertos.append(url.toLocalFile()) or True)
    tela = TelaRelatorios(api)
    qtbot.addWidget(tela)
    tela.resize(1250, 760)
    assert tela.tipo.count() == 10
    tela.tipo.setCurrentIndex(tela.tipo.findData("parcelas"))
    assert tela.inicio.text() == HOJE.replace(day=1).strftime("%d/%m/%Y")
    tela.inicio.clear()
    tela.fim.clear()
    tela.gerar()
    assert tela.erro.text() == "" and tela.tabela.rowCount() == 4
    assert tela.tabela.horizontalHeaderItem(4).text() == "Valor"
    assert "R$ 500,00" in tela.totais.text() and "Confidencial" in tela.info.text()
    _captura(tela, "51_relatorio_parcelas")
    # Filtro de situação
    tela.situacao.setCurrentIndex(tela.situacao.findData("paga"))
    tela.gerar()
    assert tela.tabela.rowCount() == 1 and tela.tabela.item(0, 3).text() == "Entrada"
    # Período inválido
    tela.inicio.setText("10/02/2026")
    tela.fim.setText("01/02/2026")
    tela.gerar()
    assert "anterior" in tela.erro.text()
    tela.inicio.clear()
    tela.fim.clear()
    # Exportar PDF e Excel
    destino_pdf = tmp_path / "parcelas"
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *a, **k: (str(destino_pdf), ""))
    tela.exportar("pdf")
    arquivo = tmp_path / "parcelas.pdf"
    assert arquivo.read_bytes().startswith(b"%PDF") and abertos[-1] == str(arquivo)
    assert "Relatório salvo" in tela.msg.text()
    destino_xlsx = tmp_path / "recebimentos.xlsx"
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *a, **k: (str(destino_xlsx), ""))
    tela.tipo.setCurrentIndex(tela.tipo.findData("recebimentos"))
    tela.exportar("xlsx")
    ws = load_workbook(destino_xlsx).active
    assert ws["A1"].value == "Relatório de recebimentos"
    # Cancelar a janela de salvar não faz nada
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *a, **k: ("", ""))
    tela.msg.clear()
    tela.exportar("pdf")
    assert tela.msg.text() == ""
    # Resultado financeiro: sem filtros de responsável e cliente
    tela.tipo.setCurrentIndex(tela.tipo.findData("resultado_financeiro"))
    assert not tela.bloco_cliente.isEnabled() and not tela.situacao.isEnabled()
    tela.gerar()
    assert tela.tabela.rowCount() == 1 and "Saldo líquido do período: <b>R$ 475,00</b>" in tela.totais.text()
    _captura(tela, "52_resultado_financeiro")
