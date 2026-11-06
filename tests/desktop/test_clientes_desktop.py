"""Clientes e pesquisa global pela interface, contra o servidor real."""

from __future__ import annotations

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QInputDialog, QMessageBox

from advoga_desktop.api_client.cliente import ClienteAPI, obter_certificado_servidor
from advoga_desktop.ui.janela_principal import JanelaPrincipal
from advoga_desktop.ui.telas.clientes import DialogoCliente, FichaCliente, TelaClientes
from tests.conftest import SENHA_MASTER, criar_usuario, login
from tests.desktop.test_fluxo_desktop import _captura, config_isolada, servidor, tema  # noqa: F401


@pytest.fixture
def api(servidor, master):
    a = ClienteAPI(servidor, obter_certificado_servidor(servidor))
    a.login("master", SENHA_MASTER)
    yield a
    a.fechar()


def _cadastrar(qtbot, api, nome, **campos):
    d = DialogoCliente(api)
    qtbot.addWidget(d)
    d.nome.setText(nome)
    for k, v in campos.items():
        getattr(d, k).setText(v)
    qtbot.mouseClick(d.btn_salvar, Qt.MouseButton.LeftButton)
    return d


def test_cadastro_ficha_edicao_e_encerramento(qtbot, tema, api, monkeypatch):
    d = DialogoCliente(api)
    qtbot.addWidget(d)
    d.nome.setText("Cliente Fictício de Teste")
    d.cpf.setText("123.456.789-00")
    d.tel1.setText("(11) 98765-4321")
    d.nascimento.setText("20/05/1990")
    d.cidade.setText("Campinas")
    d.uf.setCurrentIndex(d.uf.findData("SP"))
    d.responsavel.setCurrentIndex(1)
    _captura(d, "09_cadastrar_cliente")
    qtbot.mouseClick(d.btn_salvar, Qt.MouseButton.LeftButton)
    assert "CPF inválido" in d.erro.text() and d.resultado is None
    d.nascimento.setText("31/02/1990")
    d.cpf.setText("529.982.247-25")
    qtbot.mouseClick(d.btn_salvar, Qt.MouseButton.LeftButton)
    assert "Data inválida" in d.erro.text()
    d.nascimento.setText("20/05/1990")
    qtbot.mouseClick(d.btn_salvar, Qt.MouseButton.LeftButton)
    assert d.resultado is not None and d.resultado.cpf == "52998224725"
    assert d.resultado.advogado_responsavel_nome == "Maria Advogada Teste"
    cid = str(d.resultado.id)

    # CPF repetido é recusado pela tela com a mensagem do servidor
    d2 = _cadastrar(qtbot, api, "Outra Pessoa", cpf="52998224725")
    assert "Já existe cliente cadastrado com este CPF" in d2.erro.text()

    # Ficha
    ficha = FichaCliente(api, cid)
    qtbot.addWidget(ficha)
    assert ficha.titulo.text() == "Cliente Fictício de Teste"
    textos = [ficha.form.itemAt(i).widget().text() for i in range(ficha.form.count())]
    assert "529.982.247-25" in textos and "(11) 98765-4321" in textos and "20/05/1990" in textos
    _captura(ficha, "10_ficha_cliente")

    # Edição pela ficha
    ed = DialogoCliente(api, ficha.cliente, ficha)
    qtbot.addWidget(ed)
    assert ed.cpf.text() == "529.982.247-25" and ed.uf.currentData() == "SP"
    ed.bairro.setText("Centro")
    qtbot.mouseClick(ed.btn_salvar, Qt.MouseButton.LeftButton)
    assert ed.resultado and ed.resultado.bairro == "Centro"
    ficha._apos_gravar(ed.resultado)

    # Edição simultânea: outra pessoa grava antes; a tela recusa sem sobrescrever
    velha = DialogoCliente(api, api.obter_cliente(cid))
    qtbot.addWidget(velha)
    api.atualizar_cliente(cid, {"versao": ficha.cliente.versao, "cidade": "Santos"})
    velha.cidade.setText("Sorocaba")
    qtbot.mouseClick(velha.btn_salvar, Qt.MouseButton.LeftButton)
    assert "alterado por outra pessoa" in velha.erro.text()
    assert api.obter_cliente(cid).cidade == "Santos"

    # Encerrar e reativar
    ficha.carregar()
    monkeypatch.setattr(QInputDialog, "getText", lambda *a, **k: ("Processo finalizado", True))
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.StandardButton.Yes)
    ficha.encerrar()
    assert ficha.cliente.situacao == "encerrado" and "Processo finalizado" in ficha.situacao.text()
    assert ficha.btn_reativar.isVisibleTo(ficha) and not ficha.btn_encerrar.isVisibleTo(ficha)
    ficha.reativar()
    assert ficha.cliente.situacao == "ativo"

    # Histórico
    ficha.abas.setCurrentWidget(ficha.tabela_hist)
    linhas = [ficha.tabela_hist.item(i, 2).text() for i in range(ficha.tabela_hist.rowCount())]
    assert linhas[0] == "Cliente reativado"
    assert any(t.startswith("Atendimento encerrado. Motivo: Processo finalizado") for t in linhas)
    assert any("Bairro: — → Centro" in t for t in linhas)
    assert linhas[-1] == "Cliente cadastrado"
    _captura(ficha, "11_ficha_historico")


def test_homonimo_pede_confirmacao_na_tela(qtbot, tema, api, monkeypatch):
    _cadastrar(qtbot, api, "José da Silva")
    respostas = iter([QMessageBox.StandardButton.No, QMessageBox.StandardButton.Yes])
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: next(respostas))
    d = _cadastrar(qtbot, api, "Jose da Silva")
    assert d.resultado is None and d.isVisible() is False or d.resultado is None
    d = _cadastrar(qtbot, api, "Jose da Silva")
    assert d.resultado is not None
    assert api.listar_clientes("jose silva").total == 2


def test_tela_clientes_procura_e_paginacao(qtbot, tema, api):
    for i in range(55):
        api.criar_cliente({"nome_completo": f"Cliente Teste {i:02d}"})
    api.criar_cliente({"nome_completo": "João Gomes Pereira", "telefone_principal": "11999990000"})
    tela = TelaClientes(api)
    qtbot.addWidget(tela)
    tela.show()
    assert tela.total == 56 and tela.tabela.rowCount() == 50 and tela.btn_prox.isEnabled()
    qtbot.mouseClick(tela.btn_prox, Qt.MouseButton.LeftButton)
    assert tela.tabela.rowCount() == 6 and tela.pagina == 2
    tela.busca.setText("jo")
    assert "pelo menos 3" in tela.info.text()
    tela.busca.setText("joao")
    qtbot.waitUntil(lambda: tela.tabela.rowCount() == 1, timeout=3000)
    assert tela.tabela.item(0, 0).text() == "João Gomes Pereira"
    assert tela.tabela.item(0, 2).text() == "(11) 99999-0000"
    tela.busca.setText("99999")
    qtbot.waitUntil(lambda: tela.tabela.item(0, 0) and tela.tabela.item(0, 0).text() == "João Gomes Pereira"
                    and tela.tabela.rowCount() == 1, timeout=3000)
    tela.busca.setText("")
    qtbot.waitUntil(lambda: tela.total == 56, timeout=3000)
    tela.resize(1050, 700)
    _captura(tela, "12_lista_clientes")


def test_pesquisa_global_no_cabecalho(qtbot, tema, api, monkeypatch):
    api.criar_cliente({"nome_completo": "João Pedro da Silva", "cpf": "52998224725", "cidade": "Campinas", "uf": "SP"})
    api.criar_cliente({"nome_completo": "Maria Joana Prado"})
    janela = JanelaPrincipal(api)
    qtbot.addWidget(janela)
    janela.show()
    janela.pesquisa.setText("Jo")
    qtbot.wait(600)
    assert janela.paginas.currentIndex() != janela.indice_resultados
    janela.pesquisa.setText("joão")
    qtbot.waitUntil(lambda: janela.paginas.currentIndex() == janela.indice_resultados, timeout=3000)
    res = janela.tela_resultados
    assert res.tabela.rowCount() == 1 and res.tabela.item(0, 1).text() == "João Pedro da Silva"
    assert "CPF 529.982.247-25" in res.tabela.item(0, 2).text()
    _captura(janela, "13_pesquisa_global")
    janela.pesquisa.setText("529.982")
    qtbot.keyClick(janela.pesquisa, Qt.Key.Key_Return)
    assert res.tabela.rowCount() == 1
    # Selecionar o resultado abre a ficha do cliente
    abertas = []
    monkeypatch.setattr(FichaCliente, "exec", lambda self: abertas.append(self.titulo.text()) or 0)
    res._abrir(0)
    assert abertas == ["João Pedro da Silva"]


def test_sem_permissao_nao_ve_clientes(qtbot, tema, api, servidor, cliente, token_master):
    api.criar_cliente({"nome_completo": "João Pedro da Silva"})
    criar_usuario(cliente, token_master, "agenda1", permissoes=["agenda"])
    outro = ClienteAPI(servidor, api.certificado_pem)
    outro.login("agenda1", "Definitiva2026")
    janela = JanelaPrincipal(outro)
    qtbot.addWidget(janela)
    menus = [b.text() for b in janela.grupo.buttons()]
    assert "Clientes" not in menus and janela.tela_clientes is None
    janela.pesquisa.setText("joao")
    janela._pesquisar()
    assert janela.tela_resultados.tabela.rowCount() == 0
    assert janela.tela_resultados.info.text() == "Nada encontrado."
    outro.fechar()
