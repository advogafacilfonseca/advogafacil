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
def servidor(app, cfg):
    """Servidor real com HTTPS (certificado próprio), como na instalação."""
    from advoga_server.core.tls import garantir_certificado

    chave, cert = garantir_certificado(cfg)
    porta = _porta_livre()
    srv = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=porta, log_level="warning",
                                        ssl_keyfile=str(chave), ssl_certfile=str(cert)))
    t = threading.Thread(target=srv.run, daemon=True)
    t.start()
    for _ in range(100):
        if srv.started:
            break
        time.sleep(0.05)
    yield f"https://127.0.0.1:{porta}"
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
    from PySide6.QtWidgets import QDialog

    widget.show()
    if isinstance(widget, QDialog):
        widget.adjustSize()
    CAPTURAS.mkdir(exist_ok=True)
    widget.grab().save(str(CAPTURAS / f"{nome}.png"))


def test_normalizar_endereco():
    assert normalizar_endereco("servidor") == "https://servidor:8765"
    assert normalizar_endereco("192.168.0.10:9000") == "https://192.168.0.10:9000"
    assert normalizar_endereco("http://127.0.0.1") == "http://127.0.0.1:8765"
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
    dlg.endereco.setText(servidor.replace("https://", ""))
    qtbot.mouseClick(dlg.btn_testar, Qt.MouseButton.LeftButton)
    assert "Conectado ao servidor" in dlg.resultado.text()
    assert "aguardando a configuração inicial" in dlg.resultado.text()
    assert "Impressão digital" in dlg.resultado.text()
    _captura(dlg, "01_conexao")
    qtbot.mouseClick(dlg.btn_salvar, Qt.MouseButton.LeftButton)
    salvo = ConfigLocal.carregar()
    assert salvo.endereco_servidor == servidor
    assert "BEGIN CERTIFICATE" in salvo.certificado_pem

    # 2) Criação da Master pelo assistente
    api = ClienteAPI(servidor, salvo.certificado_pem)
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


def _outro_certificado(tmp_path) -> str:
    from advoga_server.core.config import Configuracoes
    from advoga_server.core.tls import garantir_certificado

    _, cert = garantir_certificado(Configuracoes(pasta_dados=tmp_path / "outro", database_url="x"))
    return cert.read_text()


def test_https_recusa_servidor_com_certificado_diferente(servidor, codigo, cfg, tmp_path):
    from advoga_desktop.api_client.cliente import ErroAPI, impressao_digital, obter_certificado_servidor
    from advoga_server.core.tls import arquivos_tls, impressao_digital as digital_servidor

    pem = obter_certificado_servidor(servidor)
    # A impressão digital vista pelo app é a mesma gravada no servidor
    assert impressao_digital(pem) == digital_servidor(arquivos_tls(cfg)[1].read_bytes())
    assert ClienteAPI(servidor, pem).saude().banco == "ok"
    # Um certificado diferente (outro servidor, ou alguém se passando pelo servidor) é recusado
    falso = ClienteAPI(servidor, _outro_certificado(tmp_path))
    with pytest.raises(ErroAPI, match="certificado de segurança"):
        falso.saude()


def test_usuarios_pela_interface(qtbot, tema, servidor, master, monkeypatch):
    from PySide6.QtWidgets import QMessageBox

    from advoga_desktop.api_client.cliente import obter_certificado_servidor
    from advoga_desktop.ui.telas.trocar_senha import DialogoTrocarSenha
    from advoga_desktop.ui.telas.usuarios import DialogoNovoUsuario, TelaUsuarios

    monkeypatch.setattr(QMessageBox, "information", lambda *a, **k: None)
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.StandardButton.Yes)
    pem = obter_certificado_servidor(servidor)
    api = ClienteAPI(servidor, pem)
    api.login("master", SENHA_MASTER)

    # Cadastro pela tela
    dlg = DialogoNovoUsuario(api)
    qtbot.addWidget(dlg)
    dlg.nome.setText("Advogado Dois Teste")
    dlg.cargo.setText("Advogado associado")
    dlg.usuario.setText("adv2")
    dlg.email.setText("adv2@exemplo.com")
    dlg.permissoes.caixas[next(p for p in dlg.permissoes.caixas if p.value == "clientes")].setChecked(True)
    senha_provisoria = dlg.senha.text()
    _captura(dlg, "05_novo_usuario")
    qtbot.mouseClick(dlg.btn_salvar, Qt.MouseButton.LeftButton)
    assert dlg.criado is not None and [p.value for p in dlg.criado.permissoes] == ["clientes"]

    # Tela de usuários: selecionar, conceder agenda, salvar
    tela = TelaUsuarios(api)
    qtbot.addWidget(tela)
    tela.resize(1200, 760)
    tela.show()
    qtbot.waitExposed(tela)
    linha = next(i for i, u in enumerate(tela.usuarios) if u.nome_usuario == "adv2")
    tela.tabela.selectRow(linha)
    assert tela.permissoes.caixas[next(p for p in tela.permissoes.caixas if p.value == "agenda")].isEnabled()
    tela.permissoes.caixas[next(p for p in tela.permissoes.caixas if p.value == "agenda")].setChecked(True)
    tela.salvar_permissoes()
    atual = next(u for u in api.listar_usuarios() if u.nome_usuario == "adv2")
    assert sorted(p.value for p in atual.permissoes) == ["agenda", "clientes"]
    qtbot.wait(100)
    _captura(tela, "06_usuarios_permissoes")

    # A Master selecionada: permissões travadas
    tela.tabela.selectRow(next(i for i, u in enumerate(tela.usuarios) if u.is_master))
    assert not tela.btn_salvar_perm.isEnabled() and not tela.btn_situacao.isEnabled()

    # Primeiro acesso do novo usuário: troca obrigatória
    api2 = ClienteAPI(servidor, pem)
    u2 = api2.login("adv2", senha_provisoria)
    assert u2.deve_trocar_senha
    troca = DialogoTrocarSenha(api2, obrigatoria=True)
    qtbot.addWidget(troca)
    troca.atual.setText(senha_provisoria)
    troca.nova.setText("MinhaSenha2026")
    troca.conf.setText("MinhaSenha2026")
    _captura(troca, "07_troca_obrigatoria")
    qtbot.mouseClick(troca.btn_salvar, Qt.MouseButton.LeftButton)
    assert troca.result() == troca.DialogCode.Accepted
    assert api2.eu().deve_trocar_senha is False


def test_tela_auditoria(qtbot, tema, servidor, master):
    from advoga_desktop.api_client.cliente import obter_certificado_servidor
    from advoga_desktop.ui.telas.auditoria import TelaAuditoria

    api = ClienteAPI(servidor, obter_certificado_servidor(servidor))
    api.login("master", SENHA_MASTER)
    tela = TelaAuditoria(api)
    qtbot.addWidget(tela)
    tela.resize(1200, 700)
    tela.show()
    qtbot.waitExposed(tela)
    assert tela.total >= 2  # Master criada + login
    textos = [tela.tabela.item(i, 2).text() for i in range(tela.tabela.rowCount())]
    assert "Conta Master criada" in textos and "Entrada no sistema" in textos
    qtbot.wait(100)
    _captura(tela, "08_auditoria")


def test_gravacao_repetida_apos_queda_nao_duplica(servidor, master, monkeypatch):
    """Simula a perda da resposta: o app reenvia com a mesma chave e o servidor não duplica."""
    import httpx

    from advoga_desktop.api_client.cliente import obter_certificado_servidor

    api = ClienteAPI(servidor, obter_certificado_servidor(servidor))
    api.login("master", SENHA_MASTER)
    original = api._http.request
    chamadas = {"n": 0}

    def resposta_perdida(*a, **k):
        r = original(*a, **k)
        chamadas["n"] += 1
        if chamadas["n"] == 1:
            raise httpx.ReadError("conexão caiu antes da resposta")
        return r

    monkeypatch.setattr(api._http, "request", resposta_perdida)
    monkeypatch.setattr("advoga_desktop.api_client.cliente.time.sleep", lambda s: None)
    u = api.criar_usuario({"nome_completo": "Sem Duplicar", "nome_usuario": "semdup",
                           "email": "s@exemplo.com", "senha_provisoria": "Provisoria2026"})
    assert chamadas["n"] == 2
    monkeypatch.setattr(api._http, "request", original)
    assert [x.nome_usuario for x in api.listar_usuarios()].count("semdup") == 1
    assert u.nome_usuario == "semdup"
