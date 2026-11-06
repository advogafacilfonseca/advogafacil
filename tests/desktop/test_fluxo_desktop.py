"""Fluxo real do aplicativo contra um servidor real (API + PostgreSQL), sem simulações."""

from __future__ import annotations

import socket
import threading
import time
from pathlib import Path

import pytest
import uvicorn
from PySide6.QtCore import Qt

from advoga_desktop.api_client.cliente import ClienteAPI, ServidorIndisponivel
from advoga_desktop.assistente.conexao import DialogoConexao
from advoga_desktop.assistente.criar_master import DialogoCriarMaster
from advoga_desktop.config_local import ConfigLocal, normalizar_endereco
from advoga_desktop.ui.janela_principal import JanelaPrincipal
from advoga_desktop.ui.telas.login import DialogoLogin
from advoga_desktop.ui.tema.tema import aplicar_tema
from tests.conftest import SENHA_MASTER

CAPTURAS = Path(__file__).parent / "capturas"


def _porta_livre() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture
def servidor(app):
    porta = _porta_livre()
    srv = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=porta, log_level="warning"))
    t = threading.Thread(target=srv.run, daemon=True)
    t.start()
    for _ in range(100):
        if srv.started:
            break
        time.sleep(0.05)
    yield f"http://127.0.0.1:{porta}"
    srv.should_exit = True
    t.join(timeout=5)


@pytest.fixture(autouse=True)
def config_isolada(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "cfg"))
    monkeypatch.setenv("APPDATA", str(tmp_path / "cfg"))


@pytest.fixture
def tema(qapp):
    aplicar_tema(qapp)


def _captura(widget, nome):
    widget.show()
    widget.adjustSize()
    CAPTURAS.mkdir(exist_ok=True)
    widget.grab().save(str(CAPTURAS / f"{nome}.png"))


def test_normalizar_endereco():
    assert normalizar_endereco("servidor") == "http://servidor:8765"
    assert normalizar_endereco("192.168.0.10:9000") == "http://192.168.0.10:9000"
    assert normalizar_endereco("https://srv.tailnet.ts.net/") == "https://srv.tailnet.ts.net:8765"
    assert normalizar_endereco("  ") == ""


def test_servidor_desligado_gera_aviso_claro():
    api = ClienteAPI(f"http://127.0.0.1:{_porta_livre()}", timeout=2)
    with pytest.raises(ServidorIndisponivel, match="Não foi possível conectar"):
        api.saude()


def test_conexao_master_login_e_janela(qtbot, tema, servidor, codigo):
    # 1) Conexão com o servidor
    config = ConfigLocal()
    dlg = DialogoConexao(config)
    qtbot.addWidget(dlg)
    dlg.endereco.setText(servidor.replace("http://", ""))
    qtbot.mouseClick(dlg.btn_testar, Qt.MouseButton.LeftButton)
    assert "Conectado ao servidor" in dlg.resultado.text()
    assert "aguardando a configuração inicial" in dlg.resultado.text()
    _captura(dlg, "01_conexao")
    qtbot.mouseClick(dlg.btn_salvar, Qt.MouseButton.LeftButton)
    assert ConfigLocal.carregar().endereco_servidor == servidor

    # 2) Criação da Master pelo assistente
    api = ClienteAPI(servidor)
    assert api.sistema_configurado() is False
    cm = DialogoCriarMaster(api)
    qtbot.addWidget(cm)
    cm.codigo.setText("ERRADO-0000")
    cm.nome.setText("Maria Advogada Teste")
    cm.usuario.setText("master")
    cm.email.setText("master@exemplo.com")
    cm.senha.setText(SENHA_MASTER)
    cm.confirmacao.setText(SENHA_MASTER)
    qtbot.mouseClick(cm.btn_criar, Qt.MouseButton.LeftButton)
    assert "Código de instalação inválido" in cm.erro.text()
    _captura(cm, "02_criar_master_erro")

    import advoga_desktop.assistente.criar_master as mod
    mod.avisar_sucesso = lambda *a, **k: None  # evita caixa modal no teste
    cm.codigo.setText(codigo)
    qtbot.mouseClick(cm.btn_criar, Qt.MouseButton.LeftButton)
    assert cm.result() == cm.DialogCode.Accepted
    assert api.sistema_configurado() is True

    # 3) Login (errado e certo)
    lg = DialogoLogin(api, ConfigLocal.carregar())
    qtbot.addWidget(lg)
    lg.usuario.setText("master")
    lg.senha.setText("senha-errada")
    qtbot.mouseClick(lg.btn_entrar, Qt.MouseButton.LeftButton)
    assert lg.erro.text() == "Usuário ou senha incorretos."
    _captura(lg, "03_login")
    lg.senha.setText(SENHA_MASTER)
    qtbot.mouseClick(lg.btn_entrar, Qt.MouseButton.LeftButton)
    assert lg.result() == lg.DialogCode.Accepted
    assert api.usuario.is_master

    # 4) Janela principal
    jan = JanelaPrincipal(api)
    qtbot.addWidget(jan)
    jan.resize(1280, 760)
    jan.show()
    qtbot.waitExposed(jan)
    _captura(jan, "04_janela_principal")
    assert "Servidor conectado" in jan.status_servidor.text()

    # 5) Sair encerra a sessão no servidor
    with qtbot.waitSignal(jan.sessao_encerrada, timeout=3000):
        jan.sair()
    assert api.token is None
