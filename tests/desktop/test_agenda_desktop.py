"""Agenda e Central de Pendências pela interface, contra o servidor real."""

from __future__ import annotations

from advoga_desktop.ui.telas import documentos as documentos_tela

from datetime import date, datetime, time, timedelta

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QInputDialog, QMessageBox

from advoga_desktop.api_client.cliente import ClienteAPI, obter_certificado_servidor
from advoga_desktop.ui.janela_principal import JanelaPrincipal
from advoga_desktop.ui.telas import agenda as mod_agenda
from advoga_desktop.ui.telas.agenda import (
    DialogoAtribuir,
    DialogoCompromisso,
    DialogoReagendar,
    FichaCompromisso,
    TelaAgenda,
    TelaPendencias,
)
from tests.conftest import SENHA_MASTER, criar_usuario
from tests.desktop.test_fluxo_desktop import _captura, config_isolada, servidor, tema  # noqa: F401
from tests.servidor.test_processos_documentos import cnj

HOJE = date.today()


def em(dias: int, hora: int = 10, minuto: int = 0) -> str:
    return datetime.combine(HOJE + timedelta(days=dias), time(hora, minuto)).astimezone().isoformat()


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


@pytest.fixture
def semana(api, cliente_joao):
    """Alguns compromissos fictícios (nomes de teste) espalhados pela semana."""
    base = HOJE - timedelta(days=HOJE.weekday())
    dados = [
        ("Audiência de instrução", "audiencia", (base - HOJE).days + 2, 14, "alta", cliente_joao[0]),
        ("Reunião com o cliente", "reuniao", 0, 23, "normal", cliente_joao[0]),
        ("Ligar para o perito", "ligacao", 1, 9, "normal", None),
        ("Protocolar memoriais", "prazo", 3, 18, "urgente", cliente_joao[0]),
        ("Retorno ao cliente", "retorno", -1, 16, "normal", cliente_joao[0]),
    ]
    criados = []
    for titulo, tipo, dias, hora, prio, cli in dados:
        criados.append(api.criar_compromisso({"titulo": titulo, "tipo": tipo, "inicio": em(dias, hora),
                                               "prioridade": prio, "cliente_id": cli,
                                               "responsavel_id": str(api.usuario.id),
                                               "local": "Fórum Criminal" if tipo == "audiencia" else None}))
    return criados


def test_agendar_pela_tela(qtbot, tema, api, cliente_joao):
    d = DialogoCompromisso(api, dia=HOJE + timedelta(days=2))
    qtbot.addWidget(d)
    qtbot.mouseClick(d.btn_salvar, Qt.MouseButton.LeftButton)
    assert "título" in d.erro.text()
    d.titulo.setText("Audiência de custódia")
    d.tipo.setCurrentIndex(d.tipo.findData("audiencia"))
    d.cliente.definir(*cliente_joao)
    d.hora.setText("25:00")
    qtbot.mouseClick(d.btn_salvar, Qt.MouseButton.LeftButton)
    assert "Horário inválido" in d.erro.text()
    d.hora.setText("14:30")
    d.duracao.setCurrentIndex(d.duracao.findData(60))
    d.local.setText("Fórum Criminal, sala 4")
    d.prioridade.setCurrentIndex(d.prioridade.findData("alta"))
    d.obs.setPlainText("Levar documentos pessoais do cliente.")
    d.erro.setText("")
    _captura(d, "30_novo_compromisso")
    qtbot.mouseClick(d.btn_salvar, Qt.MouseButton.LeftButton)
    assert d.resultado is not None, d.erro.text()
    c = d.resultado
    assert c.cliente_nome == "João Pedro da Silva" and c.responsavel_id == api.usuario.id
    assert c.inicio.astimezone().strftime("%d/%m/%Y %H:%M") == (HOJE + timedelta(days=2)).strftime("%d/%m/%Y") + " 14:30"
    # Prazo de dia inteiro
    d2 = DialogoCompromisso(api)
    qtbot.addWidget(d2)
    d2.titulo.setText("Prazo para resposta à acusação")
    d2.tipo.setCurrentIndex(d2.tipo.findData("prazo"))
    d2.dia_inteiro.setChecked(True)
    assert not d2.hora.isEnabled()
    qtbot.mouseClick(d2.btn_salvar, Qt.MouseButton.LeftButton)
    assert d2.resultado is not None and d2.resultado.dia_inteiro


def test_visoes_dia_semana_mes(qtbot, tema, api, semana):
    tela = TelaAgenda(api)
    qtbot.addWidget(tela)
    tela.resize(1280, 760)
    tela.carregar()
    # Semana (padrão)
    titulos = [tela.dias_semana[i].lista.item(j).text() for i in range(7)
               for j in range(tela.dias_semana[i].lista.count())]
    assert len([t for t in titulos if "Reunião com o cliente" in t]) == 1
    hoje = tela.dias_semana[HOJE.weekday()]
    assert any("23:00  Reunião com o cliente" == hoje.lista.item(j).text() for j in range(hoje.lista.count()))
    assert tela.avisos.count() >= 3
    avisos = [tela.avisos.item(i).text() for i in range(tela.avisos.count())]
    assert any(a.startswith("HOJE TEM REUNIÃO") for a in avisos)
    assert any(a.startswith("EXISTE UM RETORNO DE CLIENTE PENDENTE") for a in avisos)
    _captura(tela, "31_agenda_semana")
    # Mês
    tela.mudar_visao("mes")
    assert tela.paginas.currentIndex() == 2
    celula = next(d for d in tela.dias_mes if d.dia == HOJE)
    assert any("Reunião com o cliente" in celula.lista.item(j).text() for j in range(celula.lista.count()))
    _captura(tela, "32_agenda_mes")
    # Clicar no dia abre a visão diária
    celula.escolher_dia.emit(HOJE)
    assert tela.visao == "dia" and tela.paginas.currentIndex() == 0
    linhas = [tela.tabela_dia.item(i, 1).text() for i in range(tela.tabela_dia.rowCount())]
    assert "Reunião com o cliente" in linhas
    _captura(tela, "33_agenda_dia")
    # Navegação
    tela.mover(1)
    assert tela.referencia == HOJE + timedelta(days=1)
    tela.ir_hoje()
    assert tela.referencia == HOJE
    # Filtro por tipo
    tela.tipo.setCurrentIndex(tela.tipo.findData("ligacao"))
    tela.mudar_visao("semana")
    titulos = [tela.dias_semana[i].lista.item(j).text() for i in range(7) for j in range(tela.dias_semana[i].lista.count())]
    assert all("Ligar" in t for t in titulos)


def test_ficha_reagendar_atribuir_concluir_cancelar(qtbot, tema, api, semana, servidor, cliente, token_master,
                                                    monkeypatch):
    criar_usuario(cliente, token_master, "colega", permissoes=["agenda", "pendencias"])
    reuniao = next(c for c in semana if c.titulo == "Reunião com o cliente")
    ficha = FichaCompromisso(api, str(reuniao.id))
    qtbot.addWidget(ficha)
    assert "Reunião" in ficha.subtitulo.text()

    def reagendar(self):
        self.data.setText((HOJE + timedelta(days=4)).strftime("%d/%m/%Y"))
        self.hora.setText("15:00")
        self.motivo.setText("Cliente pediu outro dia")
        self.salvar()
        return self.result()

    monkeypatch.setattr(DialogoReagendar, "exec", reagendar)
    ficha.btn_reagendar.click()
    assert ficha.compromisso.reagendamentos == 1
    assert ficha.compromisso.inicio.astimezone().hour == 15

    def atribuir(self):
        self.responsavel.setCurrentIndex(self.responsavel.findText("Usuário colega"))
        self.salvar()
        return self.result()

    monkeypatch.setattr(DialogoAtribuir, "exec", atribuir)
    ficha.btn_atribuir.click()
    assert ficha.compromisso.responsavel_nome == "Usuário colega"
    monkeypatch.setattr(QInputDialog, "getText", lambda *a, **k: ("Contrato assinado", True))
    ficha.btn_concluir.click()
    assert ficha.compromisso.situacao == "concluido" and not ficha.btn_reagendar.isEnabled()
    ficha.abas.setCurrentWidget(ficha.tabela_hist)
    textos = [ficha.tabela_hist.item(i, 2).text() for i in range(ficha.tabela_hist.rowCount())]
    assert any(t.startswith("Concluído. Contrato assinado") for t in textos)
    assert any(t.startswith("Reagendado. de ") and "Cliente pediu outro dia" in t for t in textos)
    assert any("para Usuário colega" in t for t in textos)
    _captura(ficha, "34_historico_compromisso")
    # Cancelar outro
    ligar = next(c for c in semana if c.titulo == "Ligar para o perito")
    f2 = FichaCompromisso(api, str(ligar.id))
    qtbot.addWidget(f2)
    monkeypatch.setattr(QInputDialog, "getText", lambda *a, **k: ("Perito respondeu por e-mail", True))
    f2.btn_cancelar.click()
    assert f2.compromisso.situacao == "cancelado"
    assert "Perito respondeu" in f2.compromisso.motivo_cancelamento


def test_editar_compromisso_do_processo(qtbot, tema, api, cliente_joao):
    p = api.criar_processo({"cliente_id": cliente_joao[0], "numero_cnj": cnj(777), "tipo_acao": "Ação Penal",
                            "proximo_evento_tipo": "audiencia", "proximo_evento_em": em(5, 13, 30),
                            "proximo_evento_descricao": "Audiência de instrução e julgamento"})
    [c] = api.listar_compromissos(processo_id=str(p.id)).itens
    assert c.do_processo
    d = DialogoCompromisso(api, c)
    qtbot.addWidget(d)
    assert not d.tipo.isEnabled() and not d.processo.isEnabled() and d.aviso_processo.isVisibleTo(d)
    d.hora.setText("15:00")
    d.local.setText("Fórum de Campinas")
    qtbot.mouseClick(d.btn_salvar, Qt.MouseButton.LeftButton)
    assert d.resultado is not None, d.erro.text()
    p = api.obter_processo(str(p.id))
    assert p.proximo_evento_em.astimezone().strftime("%H:%M") == "15:00"


def test_central_de_pendencias(qtbot, tema, api, semana, cliente_joao, monkeypatch):
    api.criar_contrato({"cliente_id": cliente_joao[0], "servico_contratado": "Defesa criminal",
                        "data_inicio": HOJE.isoformat(), "valor_total": "2000", "valor_entrada": "500",
                        "vencimento_entrada": (HOJE - timedelta(days=2)).isoformat(), "quantidade_parcelas": 1,
                        "primeiro_vencimento": (HOJE + timedelta(days=60)).isoformat()})
    tela = TelaPendencias(api)
    qtbot.addWidget(tela)
    tela.resize(1280, 760)
    tela.carregar()
    titulos = [tela.tabela.item(i, 3).text() for i in range(tela.tabela.rowCount())]
    assert "Retorno ao cliente" in titulos and any("Entrada" in t and "R$ 500,00" in t for t in titulos)
    assert tela.cartoes["financeiro"].text() == "1"
    _captura(tela, "35_central_pendencias")
    # Filtro por prioridade
    tela.prioridade.setCurrentIndex(tela.prioridade.findData("urgente"))
    assert [tela.tabela.item(i, 3).text() for i in range(tela.tabela.rowCount())] == ["Protocolar memoriais"]
    tela.prioridade.setCurrentIndex(0)
    # Concluir pela central
    linha = next(i for i, it in enumerate(tela.itens) if it.titulo == "Retorno ao cliente")
    tela.tabela.selectRow(linha)
    monkeypatch.setattr(QInputDialog, "getText", lambda *a, **k: ("Cliente informado", True))
    tela.btn_concluir.click()
    assert all(it.titulo != "Retorno ao cliente" for it in tela.itens)
    tela.situacao.setCurrentIndex(tela.situacao.findData("concluido"))
    tela.desde.setText((HOJE - timedelta(days=7)).strftime("%d/%m/%Y"))
    tela.carregar()
    assert [it.titulo for it in tela.itens] == ["Retorno ao cliente"]


def test_central_sem_financeiro_e_menus(qtbot, tema, api, servidor, cliente, token_master, semana, cliente_joao):
    api.criar_contrato({"cliente_id": cliente_joao[0], "servico_contratado": "Defesa criminal",
                        "data_inicio": HOJE.isoformat(), "valor_total": "2000", "valor_entrada": "2000",
                        "vencimento_entrada": (HOJE - timedelta(days=2)).isoformat()})
    criar_usuario(cliente, token_master, "estagiario", permissoes=["pendencias"])
    outro = ClienteAPI(servidor, api.certificado_pem)
    outro.login("estagiario", "Definitiva2026")
    janela = JanelaPrincipal(outro)
    qtbot.addWidget(janela)
    menus = [b.text() for b in janela.grupo.buttons()]
    assert "Central de Pendências" in menus and "Agenda" not in menus and "Financeiro" not in menus
    tela = TelaPendencias(outro)
    qtbot.addWidget(tela)
    tela.carregar()
    assert "financeiro" not in tela.cartoes and not tela.btn_receber.isVisibleTo(tela)
    assert all(i.origem == "compromisso" for i in tela.itens) and tela.itens
    assert tela.tipo.findData("financeiro") == -1
    janela_m = JanelaPrincipal(api)
    qtbot.addWidget(janela_m)
    menus = [b.text() for b in janela_m.grupo.buttons()]
    assert menus.index("Agenda") < menus.index("Central de Pendências") < menus.index("Financeiro")
    janela.close()
    janela_m.close()
    outro.fechar()
    assert mod_agenda.DIAS_SEMANA[HOJE.weekday()]
