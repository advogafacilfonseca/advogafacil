"""Notificações pela interface: avisos no cabeçalho, configuração de destinatários e histórico."""

from __future__ import annotations

from datetime import UTC, date, datetime, time, timedelta

import pytest
from PySide6.QtWidgets import QMessageBox

from advoga_desktop.api_client.cliente import ClienteAPI, obter_certificado_servidor
from advoga_desktop.ui.janela_principal import JanelaPrincipal
from advoga_desktop.ui.telas.agenda import FichaCompromisso
from advoga_desktop.ui.telas.notificacoes import PainelAvisos, TelaNotificacoes
from advoga_server.services import notificacoes as svc
from tests.conftest import SENHA_MASTER, criar_usuario
from tests.desktop.test_fluxo_desktop import _captura, config_isolada, servidor, tema  # noqa: F401

HOJE = date.today()
MEIO_DIA = datetime.combine(HOJE, time(12, 0)).astimezone()


def em(dias: int, hora: int = 10) -> str:
    return datetime.combine(HOJE + timedelta(days=dias), time(hora, 0)).astimezone().isoformat()


@pytest.fixture
def api(servidor, master, tmp_path, monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "local"))
    a = ClienteAPI(servidor, obter_certificado_servidor(servidor))
    a.login("master", SENHA_MASTER)
    yield a
    a.fechar()


@pytest.fixture(autouse=True)
def sem_caixas(monkeypatch):
    avisos = []
    monkeypatch.setattr(QMessageBox, "information", lambda *a, **k: avisos.append(a[2]))
    monkeypatch.setattr(QMessageBox, "warning", lambda *a, **k: avisos.append(a[2]))
    return avisos


@pytest.fixture
def equipe(cliente, token_master):
    return {
        "ana": criar_usuario(cliente, token_master, "ana", permissoes=["agenda", "notificacoes"]),
        "bia": criar_usuario(cliente, token_master, "bia", permissoes=["pendencias", "financeiro", "notificacoes"]),
        "caio": criar_usuario(cliente, token_master, "caio", permissoes=["clientes"]),
    }


def test_configurar_destinatarios_e_historico(qtbot, tema, api, equipe, db, sem_caixas):
    tela = TelaNotificacoes(api)
    qtbot.addWidget(tela)
    tela.resize(1200, 720)
    tela.carregar()
    ana, bia, caio = (equipe[k]["id"] for k in ("ana", "bia", "caio"))
    # Caio não tem "Recebimento de notificações": desabilitado; Ana não pode receber financeiro
    assert not tela.caixas[("audiencias", caio)].isEnabled()
    assert not tela.caixas[("financeiro", ana)].isEnabled() and tela.caixas[("financeiro", bia)].isEnabled()
    tela.caixas[("audiencias", ana)].setChecked(True)
    tela.caixas[("audiencias", bia)].setChecked(True)
    tela.caixas[("financeiro", bia)].setChecked(True)
    tela.caixas_resp["audiencias"].setChecked(False)
    tela.hora.setText("7h")
    tela.salvar()
    assert "Horário inválido" in tela.erro.text()
    tela.hora.setText("06:30")
    tela.salvar()
    assert sem_caixas[-1] == "Configuração salva."
    cfg = api.configuracao_notificacoes()
    aud = next(c for c in cfg.categorias if c.categoria == "audiencias")
    assert {str(x) for x in aud.usuarios_ids} == {ana, bia} and aud.incluir_responsavel is False
    assert cfg.hora_inicio == "06:30"
    _captura(tela, "40_notificacoes_destinatarios")
    # Gera avisos (sem conta de envio configurada) e confere o histórico
    api.criar_compromisso({"titulo": "Audiência de instrução", "tipo": "audiencia", "inicio": em(1, 14),
                           "local": "Fórum Criminal"})
    svc.executar_ciclo(db, None, MEIO_DIA, usar_configurado=False)
    tela.abas.setCurrentIndex(2)
    tela.carregar_historico()
    assert tela.tabela_hist.rowCount() == 2
    assert {tela.tabela_hist.item(i, 1).text() for i in range(2)} == {"Usuário ana", "Usuário bia"}
    assert "não configurado" in tela.tabela_hist.item(0, 3).text()
    _captura(tela, "41_historico_envios")
    # Reenviar (volta para a fila)
    tela.tabela_hist.selectRow(0)
    tela.reenviar()
    assert "Aguardando envio" in tela.tabela_hist.item(0, 3).text() or \
        "Aguardando envio" in tela.tabela_hist.item(1, 3).text()


def test_botao_de_avisos_e_painel(qtbot, tema, api, servidor, equipe, db, monkeypatch):
    cfg = api.configuracao_notificacoes()
    cats = [{"categoria": c.categoria, "usuarios_ids": [str(x) for x in c.usuarios_ids] +
             ([equipe["ana"]["id"]] if c.categoria in ("reunioes", "ligacoes_retornos") else []),
             "incluir_responsavel": bool(c.incluir_responsavel)} for c in cfg.categorias]
    api.salvar_configuracao_notificacoes({"categorias": cats, "email_ativo": True, "hora_inicio": "07:00"})
    api.criar_compromisso({"titulo": "Reunião com o cliente", "tipo": "reuniao", "inicio": em(1, 15)})
    api.criar_compromisso({"titulo": "Ligar para o perito", "tipo": "ligacao", "inicio": em(0, 23)})
    svc.executar_ciclo(db, None, MEIO_DIA, usar_configurado=False)
    outro = ClienteAPI(servidor, api.certificado_pem)
    outro.login("ana", "Definitiva2026")
    janela = JanelaPrincipal(outro)
    qtbot.addWidget(janela)
    assert janela.btn_avisos.text() == "Avisos (2)"
    menus = [b.text() for b in janela.grupo.buttons()]
    assert "Notificações" not in menus  # só a Master configura
    painel = PainelAvisos(outro)
    qtbot.addWidget(painel)
    assert painel.lista.count() == 2
    textos = [painel.lista.item(i).text() for i in range(2)]
    assert any(t.startswith("AMANHÃ TEM REUNIÃO") for t in textos)
    _captura(painel, "42_meus_avisos")
    # Dois cliques abre o compromisso e marca como lido
    abertos = []
    monkeypatch.setattr(FichaCompromisso, "exec", lambda self: abertos.append(self.titulo.text()) or 0)
    painel.abrir(painel.lista.item(0))
    assert abertos and outro.minhas_notificacoes(True).nao_lidas == 1
    painel.marcar_todos()
    janela.atualizar_avisos()
    assert janela.btn_avisos.text() == "Avisos"
    janela.close()
    outro.fechar()
    assert datetime.now(UTC)


def test_conectar_conta_google_pela_tela(qtbot, tema, api, monkeypatch, sem_caixas):
    import httpx
    from PySide6.QtGui import QDesktopServices
    from urllib.parse import parse_qs, urlparse

    from advoga_server.services import email_google
    from tests.servidor.test_email_google import GoogleFalso

    import tests.servidor.test_email_google as modulo_teste
    google = GoogleFalso()
    monkeypatch.setattr(email_google, "transporte", httpx.MockTransport(google))
    email_google._tokens.clear()
    tela = TelaNotificacoes(api)
    qtbot.addWidget(tela)
    tela.resize(1200, 720)
    tela.carregar()
    tela.abas.setCurrentIndex(1)
    assert "Nenhuma conta" in tela.estado_email.text() and not tela.btn_testar.isEnabled()
    tela.conectar_google()
    assert "Informe o ID" in tela.msg_email.text()
    tela.client_id.setText("1234567890-abc.apps.googleusercontent.com")
    tela.client_secret.setText("segredo-do-cliente")

    def navegador(url):
        q = parse_qs(urlparse(url.toString()).query)
        redirect = q["redirect_uri"][0]
        monkeypatch.setattr(modulo_teste, "REDIRECT", redirect)
        with httpx.Client(trust_env=False) as h:  # o "navegador" volta para o aplicativo com o código
            r = h.get(redirect, params={"code": "abcdef", "state": q["state"][0]})
        assert "Conta conectada" in r.text
        return True

    monkeypatch.setattr(QDesktopServices, "openUrl", navegador)
    tela.conectar_google()
    assert not tela.btn_conectar.isEnabled()
    tela._verificar_retorno()
    assert "conectada" in tela.msg_email.text(), tela.msg_email.text()
    assert "notificacoes@escritorio-teste.com.br" in tela.estado_email.text()
    assert tela.btn_testar.isEnabled() and tela.btn_conectar.isEnabled() and tela.client_secret.text() == ""
    _captura(tela, "43_conta_de_envio")
    tela.testar_email()
    assert "E-mail de teste enviado" in tela.msg_email.text() and len(google.enviados) == 1
