"""Migração de servidor pela interface: exportar no servidor antigo, importar no servidor novo pelo
assistente da primeira abertura, concluir com o código de confirmação e recusar o servidor antigo."""

from __future__ import annotations

import pytest

from advoga_desktop.api_client.cliente import ClienteAPI, obter_certificado_servidor
from advoga_desktop.assistente.criar_master import DialogoCriarMaster
from advoga_desktop.assistente.importar_migracao import DialogoImportarMigracao
from advoga_desktop.config_local import MSG_SUBSTITUIDO, ConfigLocal, conferir_servidor
from advoga_desktop.ui.janela_principal import JanelaPrincipal
from advoga_desktop.ui.telas import documentos as documentos_tela
from advoga_desktop.ui.telas.migracao import TelaMigracao
from tests.conftest import SENHA_MASTER, criar_usuario
from tests.desktop.test_fluxo_desktop import _captura, config_isolada, servidor, tema  # noqa: F401
from tests.servidor.test_migracao import servidor_novo

SENHA_PACOTE = "Senha do pacote 2026!"


@pytest.fixture
def api(servidor, master, tmp_path, monkeypatch):
    monkeypatch.setattr(documentos_tela, "PASTA_OVERRIDE", tmp_path / "local")
    a = ClienteAPI(servidor, obter_certificado_servidor(servidor))
    a.login("master", SENHA_MASTER)
    yield a
    a.fechar()


def test_conferir_servidor_recusa_o_antigo():
    cfg = ConfigLocal()
    assert conferir_servidor(cfg, "id-antigo", "ativo", None) is None and cfg.servidor_id == "id-antigo"
    # O computador conecta ao servidor novo, que informa ter substituído o antigo
    assert conferir_servidor(cfg, "id-novo", "ativo", "id-antigo") is None
    assert cfg.servidor_id == "id-novo" and cfg.servidores_substituidos == ["id-antigo"]
    # Mesmo que o antigo volte a funcionar (migração cancelada por engano), ele é recusado
    assert conferir_servidor(cfg, "id-antigo", "ativo", None) == MSG_SUBSTITUIDO
    assert conferir_servidor(ConfigLocal(), "qualquer", "desativado", None) == MSG_SUBSTITUIDO
    assert ConfigLocal.carregar().servidores_substituidos == ["id-antigo"]


def test_migracao_pela_interface(qtbot, tema, api, tmp_path, url_banco):
    api.criar_cliente({"nome_completo": "Cliente Migração Tela"})
    id_antigo = str(api.saude().servidor_id)
    tela = TelaMigracao(api)
    qtbot.addWidget(tela)
    tela.resize(1250, 1050)
    tela.confirmar = lambda *_: True
    tela.carregar()
    assert tela.grupo_exportar.isEnabled() and not tela.grupo_concluir.isEnabled()
    tela.destino.setText(str(tmp_path / "pen"))
    tela.verificar()
    assert tela.res_destino.text().startswith("✓")
    tela.senha.setText(SENHA_PACOTE)
    tela.senha2.setText("outra senha qualquer")
    tela.exportar()
    assert "confirmação" in tela.erro.text()
    tela.senha2.setText(SENHA_PACOTE)
    tela.senha_master_exp.setText("senha errada 1")
    tela.exportar()
    assert "Senha da Master" in tela.erro.text()
    tela.senha_master_exp.setText(SENHA_MASTER)
    tela.exportar()
    assert "Exportação iniciada" in tela.msg.text() and tela.senha.text() == ""
    qtbot.waitUntil(lambda: (tela.carregar() or True) and tela.estado.atual is not None
                    and tela.estado.atual.situacao == "exportada", timeout=60000)
    assert tela.grupo_concluir.isEnabled() and not tela.grupo_exportar.isEnabled()
    assert "SOMENTE LEITURA" in tela.andamento.text()
    _captura(tela, "62_migracao_exportada")
    pacote = tela.estado.atual.arquivo

    with servidor_novo(tmp_path, url_banco) as (c2, _cfg2, codigo, _url2):
        api2 = ClienteAPI("http://testserver")
        api2._http = c2
        # Primeira abertura do aplicativo no servidor novo: o assistente oferece a importação
        inicial = DialogoCriarMaster(api2)
        qtbot.addWidget(inicial)
        assert inicial.btn_importar.text() == "Importar dados de outro servidor"
        imp = DialogoImportarMigracao(api2)
        qtbot.addWidget(imp)
        imp.codigo.setText(codigo)
        imp.pacote.setText(pacote)
        imp.senha.setText("senha errada errada")
        imp.importar()
        qtbot.waitUntil(lambda: imp.erro.text() != "", timeout=60000)
        assert "Senha incorreta" in imp.erro.text() and imp.btn_importar.isEnabled()
        imp.senha.setText(SENHA_PACOTE)
        imp.importar()
        qtbot.waitUntil(lambda: imp.resultado is not None, timeout=60000)
        codigo_conf = imp.codigo_confirmacao.text()
        assert len(codigo_conf) == 14 and not imp.btn_concluir.isHidden()
        assert "conta de envio" not in imp.pendencias.text()  # não havia conta de envio conectada
        _captura(imp, "63_importacao_concluida")
        # Este computador passa a recusar o servidor antigo
        local = ConfigLocal()
        s = api2.saude()
        assert conferir_servidor(local, s.servidor_id, s.servidor_status, s.migrado_de) is None
        assert local.servidores_substituidos == [id_antigo]
        # A Master entra no servidor novo com a mesma senha e baixa o relatório
        api2.login("master", SENHA_MASTER)
        t2 = TelaMigracao(api2)
        qtbot.addWidget(t2)
        t2.carregar()
        assert "Recebeu os dados de outro servidor" in t2.situacao.text()
        linha = next(i for i, m in enumerate(t2.estado.historico) if m.tipo == "importacao")
        t2.tabela.selectRow(linha)
        assert t2.btn_relatorio.isEnabled()
        abertos = []
        t2.escolher_arquivo = lambda _s: str(tmp_path / "relatorio.pdf")
        t2.abrir_arquivo = abertos.append
        t2.salvar_relatorio()
        assert (tmp_path / "relatorio.pdf").read_bytes().startswith(b"%PDF") and abertos

    # Servidor antigo: concluir com o código mostrado no servidor novo
    tela.carregar()
    tela.codigo.setText("AAAA-BBBB-CCCC")
    tela.senha_master_conc.setText(SENHA_MASTER)
    tela.concluir()
    assert "Código de confirmação inválido" in tela.erro.text()
    tela.codigo.setText(codigo_conf)
    tela.concluir()
    assert "desativado" in tela.msg.text() and not tela.grupo_concluir.isEnabled()
    s_antigo = api.saude()
    assert s_antigo.servidor_status == "desativado"
    assert conferir_servidor(local, s_antigo.servidor_id, s_antigo.servidor_status, s_antigo.migrado_de) \
        == MSG_SUBSTITUIDO


def test_somente_master_ve_a_migracao(qtbot, tema, api, servidor, cliente, token_master):
    criar_usuario(cliente, token_master, "socia", permissoes=["clientes", "financeiro", "configuracoes",
                                                              "admin_usuarios"])
    outro = ClienteAPI(servidor, api.certificado_pem)
    outro.login("socia", "Definitiva2026")
    janela = JanelaPrincipal(outro)
    qtbot.addWidget(janela)
    assert "Migração de servidor" not in [b.text() for b in janela.grupo.buttons()]
    janela.close()
    janela_m = JanelaPrincipal(api)
    qtbot.addWidget(janela_m)
    assert "Migração de servidor" in [b.text() for b in janela_m.grupo.buttons()]
