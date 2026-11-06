"""Agenda e Central de Pendências: compromissos, reagendamento, conclusão, avisos, vínculo com
processos e sigilo do financeiro."""

from __future__ import annotations

from datetime import UTC, date, datetime, time, timedelta

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import DBAPIError

from tests.conftest import auth, criar_usuario, login
from tests.servidor.test_financeiro import contrato
from tests.servidor.test_processos_documentos import cnj

AGORA = datetime.now(UTC).astimezone()
HOJE = AGORA.date()


def quando(dias: int = 0, hora: int = 14, minuto: int = 0) -> str:
    return datetime.combine(HOJE + timedelta(days=dias), time(hora, minuto)).astimezone().isoformat()


@pytest.fixture
def cli(cliente, token_master):
    return cliente.post("/api/clientes", headers=auth(token_master), json={"nome_completo": "Carlos Agenda"}).json()


def novo(cliente, token, **extra):
    corpo = {"titulo": "Reunião com o cliente", "tipo": "reuniao", "inicio": quando(3)} | extra
    r = cliente.post("/api/agenda/compromissos", headers=auth(token), json=corpo)
    assert r.status_code == 201, r.text
    return r.json()


def historico(cliente, token, cid):
    return [h["acao"] for h in cliente.get(f"/api/agenda/compromissos/{cid}/historico", headers=auth(token)).json()]


def test_criar_editar_reagendar_concluir(cliente, token_master, master, cli):
    r = cliente.post("/api/agenda/compromissos", headers=auth(token_master),
                     json={"titulo": "   ", "tipo": "reuniao", "inicio": quando(1)})
    assert r.status_code == 422 and "Título" in r.json()["detail"]
    r = cliente.post("/api/agenda/compromissos", headers=auth(token_master),
                     json={"titulo": "X", "tipo": "festa", "inicio": quando(1)})
    assert r.status_code == 422
    c = novo(cliente, token_master, cliente_id=cli["id"], responsavel_id=master["id"], local="Escritório",
             prioridade="alta", duracao_minutos=60, observacoes="Levar procuração")
    assert c["situacao"] == "agendado" and c["cliente_nome"] == "Carlos Agenda" and c["responsavel_nome"]
    assert not c["atrasado"] and c["reagendamentos"] == 0
    # Editar
    r = cliente.patch(f"/api/agenda/compromissos/{c['id']}", headers=auth(token_master),
                      json={"versao": c["versao"], "local": "Fórum de Campinas"})
    assert r.status_code == 200 and r.json()["local"] == "Fórum de Campinas"
    # Conflito de edição simultânea
    r2 = cliente.patch(f"/api/agenda/compromissos/{c['id']}", headers=auth(token_master),
                       json={"versao": c["versao"], "local": "Outro"})
    assert r2.status_code == 409
    c = r.json()
    # Reagendar
    r = cliente.post(f"/api/agenda/compromissos/{c['id']}/reagendar", headers=auth(token_master),
                     json={"versao": c["versao"], "inicio": c["inicio"]})
    assert r.status_code == 422
    r = cliente.post(f"/api/agenda/compromissos/{c['id']}/reagendar", headers=auth(token_master),
                     json={"versao": c["versao"], "inicio": quando(5, 9), "motivo": "Pedido do cliente"})
    assert r.status_code == 200 and r.json()["reagendamentos"] == 1
    c = r.json()
    # Concluir
    r = cliente.post(f"/api/agenda/compromissos/{c['id']}/concluir", headers=auth(token_master),
                     json={"versao": c["versao"], "observacao": "Cliente assinou a procuração"})
    assert r.status_code == 200 and r.json()["situacao"] == "concluido" and r.json()["concluido_por_nome"]
    c = r.json()
    # Concluído não muda mais
    r = cliente.post(f"/api/agenda/compromissos/{c['id']}/reagendar", headers=auth(token_master),
                     json={"versao": c["versao"], "inicio": quando(6)})
    assert r.status_code == 409 and "concluído" in r.json()["detail"]
    assert historico(cliente, token_master, c["id"]) == ["compromisso.concluido", "compromisso.reagendado",
                                                         "compromisso.editado", "compromisso.criado"]


def test_cancelar_exige_motivo_e_nao_apaga(cliente, token_master, url_banco):
    c = novo(cliente, token_master)
    r = cliente.post(f"/api/agenda/compromissos/{c['id']}/cancelar", headers=auth(token_master),
                     json={"versao": c["versao"], "motivo": ""})
    assert r.status_code == 422
    r = cliente.post(f"/api/agenda/compromissos/{c['id']}/cancelar", headers=auth(token_master),
                     json={"versao": c["versao"], "motivo": "Cliente desmarcou"})
    assert r.status_code == 200 and r.json()["motivo_cancelamento"] == "Cliente desmarcou"
    eng = create_engine(url_banco)
    with pytest.raises(DBAPIError):
        with eng.begin() as con:
            con.execute(text("DELETE FROM compromissos"))
    eng.dispose()


def test_visualizacao_por_periodo_e_filtros(cliente, token_master, master, cli):
    novo(cliente, token_master, titulo="Audiência A", tipo="audiencia", inicio=quando(0, 10), cliente_id=cli["id"])
    novo(cliente, token_master, titulo="Ligar para perito", tipo="ligacao", inicio=quando(1, 9),
         responsavel_id=master["id"])
    novo(cliente, token_master, titulo="Prazo de recurso", tipo="prazo", inicio=quando(10), dia_inteiro=True,
         prioridade="urgente")
    dia = datetime.combine(HOJE, time.min).astimezone()

    def periodo(ini, dias, **f):
        params = {"inicio": ini.isoformat(), "fim": (ini + timedelta(days=dias)).isoformat()} | f
        return [c["titulo"] for c in cliente.get("/api/agenda/compromissos", headers=auth(token_master),
                                                 params=params).json()["itens"]]

    assert periodo(dia, 1) == ["Audiência A"]                          # dia
    assert periodo(dia, 7) == ["Audiência A", "Ligar para perito"]     # semana
    assert len(periodo(dia, 31)) == 3                                  # mês
    assert periodo(dia, 31, tipo="prazo") == ["Prazo de recurso"]
    assert periodo(dia, 31, responsavel_id=master["id"]) == ["Ligar para perito"]
    assert periodo(dia, 31, cliente_id=cli["id"]) == ["Audiência A"]
    assert periodo(dia, 31, prioridade="urgente") == ["Prazo de recurso"]
    assert periodo(dia, 31, q="perito") == ["Ligar para perito"]
    assert periodo(dia, 31, q="carlos") == ["Audiência A"]
    prazo = cliente.get("/api/agenda/compromissos", headers=auth(token_master), params={"tipo": "prazo"}).json()
    assert prazo["itens"][0]["dia_inteiro"] and datetime.fromisoformat(prazo["itens"][0]["inicio"]) == \
        datetime.combine(HOJE + timedelta(days=10), time.min).astimezone()
    r = cliente.get("/api/agenda/compromissos", headers=auth(token_master),
                    params={"inicio": dia.isoformat(), "fim": (dia - timedelta(days=1)).isoformat()})
    assert r.status_code == 422


def test_avisos_da_agenda(cliente, token_master, master):
    novo(cliente, token_master, titulo="AIJ", tipo="audiencia", inicio=quando(1, 13))
    novo(cliente, token_master, titulo="Audiência hoje", tipo="audiencia", inicio=quando(0, 23, 59))
    novo(cliente, token_master, titulo="Reunião amanhã", tipo="reuniao", inicio=quando(1, 15))
    novo(cliente, token_master, titulo="Reunião hoje", tipo="reuniao", inicio=quando(0, 23, 58))
    novo(cliente, token_master, titulo="Ligar para Dr. Souza", tipo="ligacao", inicio=quando(-1, 10),
         responsavel_id=master["id"])
    novo(cliente, token_master, titulo="Retornar ao Carlos", tipo="retorno", inicio=quando(0, 0, 1))
    novo(cliente, token_master, titulo="Diligência ontem", tipo="diligencia", inicio=quando(-1, 9))
    novo(cliente, token_master, titulo="Prazo amanhã", tipo="prazo", inicio=quando(1), dia_inteiro=True)
    novo(cliente, token_master, titulo="Daqui a 5 dias", tipo="audiencia", inicio=quando(5))
    avisos = cliente.get("/api/agenda/avisos", headers=auth(token_master)).json()
    por_titulo = {a["compromisso"]["titulo"]: a["titulo"] for a in avisos}
    assert por_titulo == {
        "AIJ": "AMANHÃ TEM AUDIÊNCIA", "Audiência hoje": "HOJE TEM AUDIÊNCIA",
        "Reunião amanhã": "AMANHÃ TEM REUNIÃO", "Reunião hoje": "HOJE TEM REUNIÃO",
        "Ligar para Dr. Souza": "VOCÊ TEM UMA LIGAÇÃO PENDENTE",
        "Retornar ao Carlos": "EXISTE UM RETORNO DE CLIENTE PENDENTE",
        "Diligência ontem": "ATRASADO: DILIGÊNCIA", "Prazo amanhã": "PRAZO VENCE AMANHÃ",
    }
    assert avisos[0]["tipo"] == "atrasado"
    meus = cliente.get("/api/agenda/avisos", headers=auth(token_master), params={"somente_meus": True}).json()
    assert [a["compromisso"]["titulo"] for a in meus] == ["Ligar para Dr. Souza"]


def test_proxima_audiencia_do_processo_vira_compromisso(cliente, token_master, master, cli):
    r = cliente.post("/api/processos", headers=auth(token_master), json={
        "cliente_id": cli["id"], "numero_cnj": cnj(4321), "tipo_acao": "Ação Penal",
        "advogado_responsavel_id": master["id"], "proximo_evento_tipo": "audiencia",
        "proximo_evento_em": quando(7, 14, 30), "proximo_evento_descricao": "Audiência de instrução"})
    assert r.status_code == 201, r.text
    p = r.json()

    def espelho():
        itens = cliente.get("/api/agenda/compromissos", headers=auth(token_master),
                            params={"processo_id": p["id"]}).json()["itens"]
        return [c for c in itens if c["do_processo"] and c["situacao"] == "agendado"]

    [c] = espelho()
    assert c["titulo"] == "Audiência de instrução" and c["tipo"] == "audiencia" and c["cliente_nome"] == "Carlos Agenda"
    assert c["responsavel_id"] == master["id"] and c["processo_rotulo"].startswith("0004321")
    # Mudar a data no processo reagenda o compromisso
    r = cliente.patch(f"/api/processos/{p['id']}", headers=auth(token_master),
                      json={"versao": p["versao"], "proximo_evento_em": quando(8, 9)})
    assert r.status_code == 200, r.text
    [c] = espelho()
    assert datetime.fromisoformat(c["inicio"]) == datetime.fromisoformat(quando(8, 9)) and c["reagendamentos"] == 1
    # Reagendar na agenda muda a data no processo
    r = cliente.post(f"/api/agenda/compromissos/{c['id']}/reagendar", headers=auth(token_master),
                     json={"versao": c["versao"], "inicio": quando(9, 10)})
    assert r.status_code == 200, r.text
    p = cliente.get(f"/api/processos/{p['id']}", headers=auth(token_master)).json()
    assert datetime.fromisoformat(p["proximo_evento_em"]) == datetime.fromisoformat(quando(9, 10))
    # Tipo e processo do espelho só mudam na ficha do processo
    c = r.json()
    r = cliente.patch(f"/api/agenda/compromissos/{c['id']}", headers=auth(token_master),
                      json={"versao": c["versao"], "tipo": "reuniao"})
    assert r.status_code == 422 and "ficha do processo" in r.json()["detail"]
    # Concluir na agenda libera a "próxima audiência" do processo
    r = cliente.post(f"/api/agenda/compromissos/{c['id']}/concluir", headers=auth(token_master),
                     json={"versao": c["versao"]})
    assert r.status_code == 200
    p = cliente.get(f"/api/processos/{p['id']}", headers=auth(token_master)).json()
    assert p["proximo_evento_em"] is None and p["proximo_evento_tipo"] is None
    # Nova data no processo cria novo compromisso; retirar a data cancela o compromisso
    r = cliente.patch(f"/api/processos/{p['id']}", headers=auth(token_master), json={
        "versao": p["versao"], "proximo_evento_tipo": "prazo", "proximo_evento_em": quando(12, 18)})
    assert r.status_code == 200
    [c2] = espelho()
    assert c2["tipo"] == "prazo" and c2["id"] != c["id"] and c2["titulo"].startswith("Prazo · ")
    p = r.json()
    r = cliente.patch(f"/api/processos/{p['id']}", headers=auth(token_master), json={
        "versao": p["versao"], "proximo_evento_tipo": None, "proximo_evento_em": None})
    assert r.status_code == 200
    assert espelho() == []
    c2 = cliente.get(f"/api/agenda/compromissos/{c2['id']}", headers=auth(token_master)).json()
    assert c2["situacao"] == "cancelado" and "retirado do cadastro" in c2["motivo_cancelamento"]


def test_permissoes_agenda_e_pendencias(cliente, token_master, master, cli):
    c = novo(cliente, token_master, titulo="Retorno ao cliente", tipo="retorno", inicio=quando(-2),
             cliente_id=cli["id"])
    criar_usuario(cliente, token_master, "sem_nada", permissoes=["clientes"])
    criar_usuario(cliente, token_master, "pend", permissoes=["pendencias"])
    criar_usuario(cliente, token_master, "agenda", permissoes=["agenda"])
    t0 = login(cliente, "sem_nada", "Definitiva2026")
    tp = login(cliente, "pend", "Definitiva2026")
    ta = login(cliente, "agenda", "Definitiva2026")
    assert cliente.get("/api/agenda/compromissos", headers=auth(t0)).status_code == 403
    assert cliente.get("/api/pendencias", headers=auth(t0)).status_code == 403
    assert cliente.get("/api/pendencias", headers=auth(ta)).status_code == 403
    # Com "pendencias": consulta, atribui, reagenda e conclui; não cria nem cancela
    assert cliente.get("/api/pendencias", headers=auth(tp)).status_code == 200
    assert cliente.post("/api/agenda/compromissos", headers=auth(tp),
                        json={"titulo": "x", "tipo": "tarefa", "inicio": quando(1)}).status_code == 403
    assert cliente.post(f"/api/agenda/compromissos/{c['id']}/cancelar", headers=auth(tp),
                        json={"versao": c["versao"], "motivo": "teste"}).status_code == 403
    usuarios = {u["nome"]: u["id"] for u in cliente.get("/api/usuarios-ativos", headers=auth(tp)).json()}
    r = cliente.post(f"/api/agenda/compromissos/{c['id']}/atribuir", headers=auth(tp),
                     json={"versao": c["versao"], "responsavel_id": usuarios["Usuário agenda"]})
    assert r.status_code == 200 and r.json()["responsavel_nome"] == "Usuário agenda"
    assert "compromisso.atribuido" in historico(cliente, token_master, c["id"])
    # Quem tem agenda escolhe cliente pela busca mínima
    r = cliente.get("/api/clientes-opcoes", headers=auth(ta), params={"q": "carlos"})
    assert r.status_code == 200 and r.json()[0]["nome"] == "Carlos Agenda"
    r = cliente.post(f"/api/agenda/compromissos/{c['id']}/concluir", headers=auth(tp),
                     json={"versao": c["versao"] + 1})
    assert r.status_code == 200 and r.json()["concluido_por_nome"] == "Usuário pend"


def test_central_de_pendencias_e_sigilo_financeiro(cliente, token_master, master, cli):
    contrato(cliente, token_master, cli["id"], valor_entrada="1000.00", vencimento_entrada=(HOJE - timedelta(days=3)).isoformat())
    novo(cliente, token_master, titulo="Tarefa atrasada", tipo="tarefa", inicio=quando(-1, 8), prioridade="urgente",
         responsavel_id=master["id"])
    novo(cliente, token_master, titulo="Audiência hoje", tipo="audiencia", inicio=quando(0, 23, 59), cliente_id=cli["id"])
    novo(cliente, token_master, titulo="Reunião amanhã", tipo="reuniao", inicio=quando(1, 10))
    novo(cliente, token_master, titulo="Entrega na semana", tipo="entrega_documentos", inicio=quando(6, 10))
    novo(cliente, token_master, titulo="Longe demais", tipo="consulta", inicio=quando(40, 10))
    feita = novo(cliente, token_master, titulo="Já feita", tipo="ligacao", inicio=quando(-1, 9))
    cliente.post(f"/api/agenda/compromissos/{feita['id']}/concluir", headers=auth(token_master),
                 json={"versao": feita["versao"]})
    r = cliente.get("/api/pendencias", headers=auth(token_master)).json()
    assert r["financeiro_visivel"]
    titulos = [(i["grupo"], i["titulo"]) for i in r["itens"]]
    assert titulos[:2] == [("atrasado", "Tarefa atrasada"), ("atrasado", "Entrada · Defesa criminal")]
    assert ("hoje", "Audiência hoje") in titulos and ("amanha", "Reunião amanhã") in titulos
    assert ("proximos", "Entrega na semana") in titulos
    assert all(t != "Longe demais" and t != "Já feita" for _g, t in titulos)
    assert r["contagem"]["atrasado"] == 2
    # Filtros
    f = cliente.get("/api/pendencias", headers=auth(token_master), params={"responsavel_id": master["id"]}).json()
    assert [i["titulo"] for i in f["itens"]] == ["Tarefa atrasada"]
    f = cliente.get("/api/pendencias", headers=auth(token_master), params={"cliente_id": cli["id"]}).json()
    assert {i["titulo"] for i in f["itens"]} == {"Audiência hoje", "Entrada · Defesa criminal"}
    f = cliente.get("/api/pendencias", headers=auth(token_master), params={"ate": (HOJE + timedelta(days=45)).isoformat()}).json()
    assert "Longe demais" in [i["titulo"] for i in f["itens"]]
    f = cliente.get("/api/pendencias", headers=auth(token_master), params={"situacao": "concluido",
                                                                         "desde": (HOJE - timedelta(days=5)).isoformat()}).json()
    assert [i["titulo"] for i in f["itens"]] == ["Já feita"]
    f = cliente.get("/api/pendencias", headers=auth(token_master), params={"prioridade": "urgente"}).json()
    assert [i["titulo"] for i in f["itens"]] == ["Tarefa atrasada"]
    f = cliente.get("/api/pendencias", headers=auth(token_master), params={"tipo": "financeiro"}).json()
    assert [i["origem"] for i in f["itens"]] == ["parcela"]
    # Sem a permissão Financeiro: nenhuma parcela nem valor
    criar_usuario(cliente, token_master, "colega", permissoes=["pendencias", "agenda"])
    tc = login(cliente, "colega", "Definitiva2026")
    r = cliente.get("/api/pendencias", headers=auth(tc))
    corpo = r.text
    assert r.status_code == 200 and not r.json()["financeiro_visivel"]
    assert all(i["origem"] == "compromisso" for i in r.json()["itens"])
    assert "Entrada" not in corpo and '"valor"' not in corpo and all(i["parcela"] is None for i in r.json()["itens"])
    r = cliente.get("/api/pendencias", headers=auth(tc), params={"tipo": "financeiro"})
    assert r.status_code == 200 and r.json()["itens"] == []
