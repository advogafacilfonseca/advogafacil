"""Central de Backups pela interface, contra o servidor real (backup e teste de restauração reais)."""

from __future__ import annotations

import pytest

from advoga_desktop.api_client.cliente import ClienteAPI, obter_certificado_servidor
from advoga_desktop.ui.janela_principal import JanelaPrincipal
from advoga_desktop.ui.telas import documentos as documentos_tela
from advoga_desktop.ui.telas.backups import TelaBackups
from tests.conftest import SENHA_MASTER, criar_usuario
from tests.desktop.test_fluxo_desktop import _captura, config_isolada, servidor, tema  # noqa: F401


@pytest.fixture
def api(servidor, master, tmp_path, monkeypatch):
    monkeypatch.setattr(documentos_tela, "PASTA_OVERRIDE", tmp_path / "local")
    a = ClienteAPI(servidor, obter_certificado_servidor(servidor))
    a.login("master", SENHA_MASTER)
    yield a
    a.fechar()


def test_configurar_fazer_backup_e_testar(qtbot, tema, api, tmp_path):
    api.criar_cliente({"nome_completo": "Cliente Teste Backup"})
    tela = TelaBackups(api)
    qtbot.addWidget(tela)
    tela.resize(1250, 900)
    tela.carregar()
    assert "DESLIGADOS" in tela.alertas.text() and not tela.btn_completo.isEnabled()
    # Pasta relativa recusada
    tela.ativo.setChecked(True)
    tela.destino.setText("Backups")
    tela.salvar()
    assert "caminho completo" in tela.erro_cfg.text()
    # Verificar e salvar
    hd = tmp_path / "hd-externo"
    hd.mkdir()
    tela.destino.setText(str(hd / "Backups"))
    tela.verificar(tela.destino, tela.res_destino)
    assert tela.res_destino.text().startswith("✓")
    tela.salvar()
    assert tela.erro_cfg.text() == "" and tela.btn_completo.isEnabled()
    # Senha da cópia: confirmação diferente e depois correta
    tela.senha.setText("uma senha longa 2026")
    tela.senha2.setText("outra senha longa 2026")
    tela.definir_senha()
    assert "confere" in tela.erro_cfg.text()
    tela.senha2.setText("uma senha longa 2026")
    tela.definir_senha()
    assert tela.situacao_senha.text() == "Definida." and tela.senha.text() == ""
    # Backup completo e acompanhamento até terminar
    tela.executar("completo")
    assert "Backup iniciado" in tela.msg.text()
    qtbot.waitUntil(lambda: (tela._atualizar_andamento() or True) and tela.estado.em_andamento is None
                    and tela.estado.ultimo_completo is not None, timeout=60000)
    assert tela.tabela.rowCount() == 1 and tela.tabela.item(0, 3).text() == "Concluído"
    assert "Integridade conferida" in tela.tabela.item(0, 7).text()
    # Teste de restauração
    tela.testar()
    qtbot.waitUntil(lambda: (tela._atualizar_andamento() or True) and tela.estado.ultimo_teste is not None,
                    timeout=60000)
    assert tela.estado.ultimo_teste.situacao == "sucesso"
    tela.abas.setCurrentIndex(0)
    _captura(tela, "60_central_de_backups")
    tela.abas.setCurrentIndex(1)
    _captura(tela, "61_historico_backups")


def test_somente_master_ve_a_central(qtbot, tema, api, servidor, cliente, token_master):
    criar_usuario(cliente, token_master, "socia", permissoes=["clientes", "financeiro", "configuracoes",
                                                              "admin_usuarios"])
    outro = ClienteAPI(servidor, api.certificado_pem)
    outro.login("socia", "Definitiva2026")
    janela = JanelaPrincipal(outro)
    qtbot.addWidget(janela)
    assert "Central de Backups" not in [b.text() for b in janela.grupo.buttons()]
    janela.close()
    janela_m = JanelaPrincipal(api)
    qtbot.addWidget(janela_m)
    assert "Central de Backups" in [b.text() for b in janela_m.grupo.buttons()]
