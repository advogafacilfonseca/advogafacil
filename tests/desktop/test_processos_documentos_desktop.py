"""Processos e documentos pela interface, contra o servidor real."""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest
from PySide6.QtCore import Qt
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QFileDialog, QInputDialog

from advoga_desktop.api_client.cliente import ClienteAPI, obter_certificado_servidor
from advoga_desktop.ui.janela_principal import JanelaPrincipal
from advoga_desktop.ui.telas import documentos as mod_docs
from advoga_desktop.ui.telas.clientes import FichaCliente
from advoga_desktop.ui.telas.documentos import DialogoAnexar, PainelDocumentos, TelaDocumentos
from advoga_desktop.ui.telas.processos import DialogoMovimentacao, DialogoProcesso, FichaProcesso, TelaProcessos
from tests.conftest import SENHA_MASTER, criar_usuario
from tests.desktop.test_fluxo_desktop import _captura, config_isolada, servidor, tema  # noqa: F401
from tests.servidor.test_processos_documentos import cnj


@pytest.fixture
def api(servidor, master, tmp_path, monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "local"))
    a = ClienteAPI(servidor, obter_certificado_servidor(servidor))
    a.login("master", SENHA_MASTER)
    yield a
    a.fechar()


@pytest.fixture
def abertos(monkeypatch):
    lista = []
    monkeypatch.setattr(QDesktopServices, "openUrl", lambda url: lista.append(Path(url.toLocalFile())) or True)
    return lista


@pytest.fixture
def cliente_joao(api):
    c = api.criar_cliente({"nome_completo": "João Pedro da Silva"})
    return str(c.id), c.nome_completo


def test_cadastrar_processo_pela_tela(qtbot, tema, api, cliente_joao):
    d = DialogoProcesso(api)
    qtbot.addWidget(d)
    qtbot.mouseClick(d.btn_salvar, Qt.MouseButton.LeftButton)
    assert "Escolha o cliente" in d.erro.text()
    # Escolha do cliente pela busca
    from advoga_desktop.ui.componentes.seletores import DialogoEscolherCliente
    esc = DialogoEscolherCliente(api)
    qtbot.addWidget(esc)
    esc.busca.setText("joao silva")
    esc.procurar()
    assert esc.lista.count() == 1
    esc._confirmar()
    d.cliente.definir(*esc.escolhido)
    assert d.cliente.nome.text() == "João Pedro da Silva"
    d.numero.setText("1234567-00.2024.8.26.0100")
    d.tipo.setText("Ação Penal")
    d.area.setCurrentText("Penal")
    d.tribunal.setText("TJSP")
    d.comarca.setText("Campinas")
    d.vara.setText("2ª Vara Criminal")
    d.parte.setText("Ministério Público do Estado de São Paulo")
    d.responsavel.setCurrentIndex(1)
    d.distribuicao.setText("10/03/2024")
    d.fase.setCurrentText("Instrução")
    d.evento_tipo.setCurrentIndex(d.evento_tipo.findData("audiencia"))
    qtbot.mouseClick(d.btn_salvar, Qt.MouseButton.LeftButton)
    assert "informe a data e hora" in d.erro.text()
    d.evento_em.setText("20/05/2030 14:30")
    d.evento_desc.setText("Audiência de instrução e julgamento")
    d.descricao.setPlainText("Defesa em ação penal.")
    _captura(d, "14_cadastrar_processo")
    qtbot.mouseClick(d.btn_salvar, Qt.MouseButton.LeftButton)
    assert "dígito verificador" in d.erro.text()
    d.numero.setText(cnj(1234567 % 10_000_000))
    qtbot.mouseClick(d.btn_salvar, Qt.MouseButton.LeftButton)
    assert d.resultado is not None, d.erro.text()
    p = d.resultado
    assert p.cliente_nome == "João Pedro da Silva" and p.advogado_responsavel_nome == "Maria Advogada Teste"
    assert p.proximo_evento_em.astimezone().strftime("%d/%m/%Y %H:%M") == "20/05/2030 14:30"

    # Ficha do processo, movimentações e histórico
    ficha = FichaProcesso(api, str(p.id))
    qtbot.addWidget(ficha)
    assert ficha.titulo.text().startswith(cnj(1234567)) and "Audiência 20/05/2030 14:30" in ficha.subtitulo.text()
    mv = DialogoMovimentacao(api, str(p.id))
    qtbot.addWidget(mv)
    mv.data.setText("15/04/2024")
    mv.descricao.setPlainText("Denúncia recebida pelo juízo.")
    qtbot.mouseClick(mv.btn_salvar, Qt.MouseButton.LeftButton)
    assert mv.resultado is not None
    ficha.carregar_movimentacoes()
    assert ficha.tabela_mov.item(0, 1).text() == "Denúncia recebida pelo juízo."
    assert ficha.abas.tabText(1) == "Movimentações (1)"
    _captura(ficha, "15_ficha_processo")
    ed = DialogoProcesso(api, ficha.processo, parent=ficha)
    qtbot.addWidget(ed)
    assert ed.numero.text() == cnj(1234567) and ed.evento_em.text() == "20/05/2030 14:30"
    ed.situacao.setCurrentIndex(ed.situacao.findData("suspenso"))
    qtbot.mouseClick(ed.btn_salvar, Qt.MouseButton.LeftButton)
    assert ed.resultado.situacao == "suspenso"
    ficha.abas.setCurrentWidget(ficha.tabela_hist)
    textos = [ficha.tabela_hist.item(i, 2).text() for i in range(ficha.tabela_hist.rowCount())]
    assert textos[0] == "Dados alterados. Situação: em_andamento → suspenso"
    assert "Movimentação registrada. Denúncia recebida pelo juízo." in textos


def test_tela_processos_e_aba_na_ficha_do_cliente(qtbot, tema, api, cliente_joao):
    outro = api.criar_cliente({"nome_completo": "Ana Souza"})
    api.criar_processo({"cliente_id": cliente_joao[0], "numero_cnj": cnj(1), "tipo_acao": "Habeas Corpus"})
    api.criar_processo({"cliente_id": cliente_joao[0], "numero_cnj": cnj(2), "situacao": "arquivado"})
    api.criar_processo({"cliente_id": str(outro.id), "numero_cnj": cnj(3), "parte_contraria": "Empresa Ômega"})
    tela = TelaProcessos(api)
    qtbot.addWidget(tela)
    tela.resize(1200, 600)
    tela.show()
    painel = tela.painel
    assert painel.total == 3
    painel.busca.setText("omega")
    qtbot.waitUntil(lambda: painel.total == 1, timeout=3000)
    assert painel.tabela.item(0, 1).text() == "Ana Souza"
    painel.busca.setText("")
    qtbot.waitUntil(lambda: painel.total == 3, timeout=3000)
    painel.situacao.setCurrentIndex(painel.situacao.findData("arquivado"))
    assert painel.total == 1
    painel.situacao.setCurrentIndex(0)
    _captura(tela, "16_lista_processos")

    ficha = FichaCliente(api, cliente_joao[0])
    qtbot.addWidget(ficha)
    nomes = [ficha.abas.tabText(i) for i in range(ficha.abas.count())]
    assert nomes == ["Dados pessoais", "Processos", "Documentos", "Histórico"]
    ficha.abas.setCurrentWidget(ficha.painel_processos)
    assert ficha.painel_processos.total == 2 and ficha.painel_processos.tabela.isColumnHidden(1)


def test_documentos_anexar_abrir_salvar_editar_remover_restaurar(qtbot, tema, api, cliente_joao, tmp_path,
                                                                 abertos, monkeypatch):
    p = api.criar_processo({"cliente_id": cliente_joao[0], "numero_cnj": cnj(7), "tipo_acao": "Ação Penal"})
    arq1 = tmp_path / "Procuração assinada.pdf"
    arq1.write_bytes(b"%PDF-1.4 " + b"x" * 300_000)
    arq2 = tmp_path / "foto documento.jpg"
    arq2.write_bytes(b"\xff\xd8\xff" + b"y" * 1000)
    ficha = FichaCliente(api, cliente_joao[0])
    qtbot.addWidget(ficha)
    painel: PainelDocumentos = ficha.painel_docs
    ficha.abas.setCurrentWidget(painel)

    # Anexar dois arquivos de uma vez: o cliente já vem preenchido; escolhe o processo
    monkeypatch.setattr(DialogoAnexar, "exec", lambda self: (
        self.processo.setCurrentIndex(self.processo.findData(str(p.id))),
        self.descricao.setText("Documentos iniciais"), self.enviar(), self.result())[-1])
    dlg = painel.anexar_arquivos([str(arq1), str(arq2)])
    assert len(dlg.anexados) == 2 and dlg.cliente.nome.text() == "João Pedro da Silva"
    assert painel.tabela.rowCount() == 2
    nomes = {painel.tabela.item(i, 0).text() for i in range(2)}
    assert nomes == {"Procuração assinada.pdf", "foto documento.jpg"}
    linha = [painel.tabela.item(i, 0).text() for i in range(2)].index("Procuração assinada.pdf")
    painel.tabela.selectRow(linha)
    assert painel.tabela.item(linha, 2).text().startswith(cnj(7))
    _captura(ficha, "17_documentos_cliente")

    # Abrir: cópia conferida, aberta no programa padrão, apagada ao sair
    caminho = painel.abrir()
    assert abertos == [caminho] and caminho.read_bytes() == arq1.read_bytes()
    assert mod_docs.pasta_visualizacao() in caminho.parents

    # Salvar cópia
    destino = tmp_path / "copia.pdf"
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *a, **k: (str(destino), ""))
    painel.salvar_copia()
    assert hashlib.sha256(destino.read_bytes()).hexdigest() == hashlib.sha256(arq1.read_bytes()).hexdigest()

    # Editar (renomear)
    from advoga_desktop.ui.telas.documentos import DialogoEditarDocumento
    ed = DialogoEditarDocumento(api, painel.selecionado())
    qtbot.addWidget(ed)
    ed.nome.setText("Procuração.pdf")
    qtbot.mouseClick(ed.btn_salvar, Qt.MouseButton.LeftButton)
    assert ed.resultado and ed.resultado.nome_arquivo == "Procuração.pdf"
    painel.carregar(1)

    # Remover com motivo; some da lista; Master vê em "Mostrar removidos" e restaura
    linha = [painel.tabela.item(i, 0).text() for i in range(2)].index("Procuração.pdf")
    painel.tabela.selectRow(linha)
    monkeypatch.setattr(QInputDialog, "getText", lambda *a, **k: ("Versão errada", True))
    painel.remover()
    assert painel.tabela.rowCount() == 1
    painel.chk_removidos.setChecked(True)
    assert painel.tabela.rowCount() == 1 and "Versão errada" in painel.tabela.item(0, 3).text()
    assert painel.btn_restaurar.isVisibleTo(painel) and not painel.btn_anexar.isVisibleTo(painel)
    painel.tabela.selectRow(0)
    painel.restaurar()
    painel.chk_removidos.setChecked(False)
    assert painel.tabela.rowCount() == 2

    # Ficha do processo mostra só os documentos dele
    fp = FichaProcesso(api, str(p.id))
    qtbot.addWidget(fp)
    fp.abas.setCurrentWidget(fp.painel_docs)
    assert fp.painel_docs.tabela.rowCount() == 2


def test_pesquisa_global_abre_processo_e_documento(qtbot, tema, api, cliente_joao, tmp_path, abertos, monkeypatch):
    api.criar_processo({"cliente_id": cliente_joao[0], "numero_cnj": cnj(55), "tipo_acao": "Revisão Criminal"})
    arq = tmp_path / "laudo pericial.pdf"
    arq.write_bytes(b"%PDF laudo")
    api.anexar_documento(arq, cliente_joao[0])
    janela = JanelaPrincipal(api)
    qtbot.addWidget(janela)
    janela.show()
    menus = [b.text() for b in janela.grupo.buttons()]
    assert menus[:4] == ["Painel inicial", "Clientes", "Processos", "Documentos"]
    janela.pesquisa.setText(cnj(55))
    janela._pesquisar()
    res = janela.tela_resultados
    assert res.tabela.rowCount() == 1 and res.tabela.item(0, 0).text() == "Processo"
    fichas = []
    monkeypatch.setattr(FichaProcesso, "exec", lambda self: fichas.append(self.titulo.text()) or 0)
    res._abrir(0)
    assert fichas and fichas[0].startswith(cnj(55))
    janela.pesquisa.setText("laudo")
    janela._pesquisar()
    assert res.tabela.item(0, 0).text() == "Documento"
    _captura(janela, "18_pesquisa_documento")
    res._abrir(0)
    assert abertos and abertos[-1].read_bytes() == b"%PDF laudo"
    pasta = mod_docs.pasta_visualizacao()
    assert pasta.exists()
    janela.sair()
    assert not pasta.exists()  # cópias de leitura apagadas ao sair


def test_usuario_so_com_documentos(qtbot, tema, api, servidor, cliente, token_master, cliente_joao, tmp_path):
    criar_usuario(cliente, token_master, "secretaria", permissoes=["documentos"])
    outro = ClienteAPI(servidor, api.certificado_pem)
    outro.login("secretaria", "Definitiva2026")
    janela = JanelaPrincipal(outro)
    qtbot.addWidget(janela)
    menus = [b.text() for b in janela.grupo.buttons()]
    assert "Documentos" in menus and "Clientes" not in menus and "Processos" not in menus
    tela = TelaDocumentos(outro)
    qtbot.addWidget(tela)
    arq = tmp_path / "rg.png"
    arq.write_bytes(b"\x89PNG imagem")
    d = DialogoAnexar(outro, [str(arq)], parent=tela)
    qtbot.addWidget(d)
    qtbot.mouseClick(d.btn_enviar, Qt.MouseButton.LeftButton)
    assert "Escolha o cliente" in d.erro.text()
    d.cliente.definir(*cliente_joao)  # escolhido pela busca (nome e situação apenas)
    qtbot.mouseClick(d.btn_enviar, Qt.MouseButton.LeftButton)
    assert len(d.anexados) == 1
    tela.painel.carregar(1)
    assert tela.painel.tabela.rowCount() == 1 and not tela.painel.chk_removidos.isVisibleTo(tela.painel)
    janela.close()
    outro.fechar()
