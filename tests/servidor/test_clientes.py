"""Clientes, pesquisa global e isolamento por permissão."""

from __future__ import annotations

import threading

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select, text
from sqlalchemy.exc import DBAPIError

import pytest

from advoga_server.models import Auditoria, Cliente
from tests.conftest import auth, criar_usuario, login

CPF_A = "529.982.247-25"
CPF_B = "111.444.777-35"


def novo(cliente, token, nome, **extra):
    corpo = {"nome_completo": nome} | extra
    r = cliente.post("/api/clientes", headers=auth(token), json=corpo)
    assert r.status_code == 201, r.text
    return r.json()


@pytest.fixture
def base(cliente, token_master):
    """Cadastro de exemplo (nomes fictícios, usados apenas no teste)."""
    nomes = ["João Gomes Pereira", "João Pedro da Silva", "João Carlos Oliveira", "João Henrique Santos",
             "Maria Joana Prado", "Ana Beatriz Souza"]
    ids = {}
    for i, n in enumerate(nomes):
        extra = {}
        if i == 0:
            extra = {"cpf": CPF_A, "telefone_principal": "(11) 98765-4321", "cidade": "Campinas", "uf": "sp"}
        if i == 5:
            extra = {"telefone_secundario": "(19) 3333-2222"}
        ids[n] = novo(cliente, token_master, n, **extra)["id"]
    return ids


def test_cadastro_com_validacoes(cliente, token_master):
    c = novo(cliente, token_master, "  Pessoa   de Teste ", cpf=CPF_A, telefone_principal="(11) 98765-4321",
             cep="13010-000", uf="sp", data_nascimento="1990-05-20", email="Pessoa@Exemplo.com")
    assert c["nome_completo"] == "Pessoa de Teste"
    assert c["cpf"] == "52998224725" and c["telefone_principal"] == "11987654321"
    assert c["uf"] == "SP" and c["email"] == "pessoa@exemplo.com" and c["situacao"] == "ativo"
    h = auth(token_master)
    assert "CPF inválido" in cliente.post("/api/clientes", headers=h, json={
        "nome_completo": "X Y Z", "cpf": "123.456.789-00"}).json()["detail"]
    assert "Telefone inválido" in cliente.post("/api/clientes", headers=h, json={
        "nome_completo": "X Y Z", "telefone_principal": "1234"}).json()["detail"]
    assert "Data de nascimento" in cliente.post("/api/clientes", headers=h, json={
        "nome_completo": "X Y Z", "data_nascimento": "2999-01-01"}).json()["detail"]


def test_cpf_duplicado_bloqueado(cliente, token_master):
    novo(cliente, token_master, "Primeiro Cliente", cpf=CPF_A)
    r = cliente.post("/api/clientes", headers=auth(token_master), json={"nome_completo": "Outro Nome", "cpf": CPF_A})
    assert r.status_code == 409 and "Primeiro Cliente" in r.json()["detail"]


def test_homonimo_pede_confirmacao(cliente, token_master, db):
    novo(cliente, token_master, "José da Silva", data_nascimento="1980-01-01")
    h = auth(token_master)
    r = cliente.post("/api/clientes", headers=h, json={"nome_completo": "Jose da SILVA"})
    assert r.status_code == 428 and "confirme" in r.json()["detail"]
    # Nascimento diferente = outra pessoa: não pede confirmação
    assert cliente.post("/api/clientes", headers=h, json={
        "nome_completo": "José da Silva", "data_nascimento": "1975-03-03"}).status_code == 201
    # Confirmado: cadastra (pessoas com nomes iguais são registros distintos, pelo identificador)
    assert cliente.post("/api/clientes", headers=h, json={
        "nome_completo": "José da Silva", "confirmar_possivel_duplicidade": True}).status_code == 201
    assert db.scalar(select(func.count()).select_from(Cliente)) == 3


def test_pesquisa_a_partir_de_tres_letras(cliente, token_master, base):
    h = auth(token_master)
    assert cliente.get("/api/pesquisa", headers=h, params={"q": "Jo"}).status_code == 422
    r = cliente.get("/api/pesquisa", headers=h, params={"q": "Joã"}).json()
    titulos = [i["titulo"] for i in r["itens"]]
    assert set(titulos) >= {"João Gomes Pereira", "João Pedro da Silva", "João Carlos Oliveira", "João Henrique Santos"}
    # Os que começam com o termo vêm primeiro
    assert all(t.startswith("João") for t in titulos[:4])


def test_pesquisa_sem_acento_e_sem_maiusculas(cliente, token_master, base):
    h = auth(token_master)
    r = cliente.get("/api/pesquisa", headers=h, params={"q": "joao"}).json()
    assert r["total"] == 4
    r = cliente.get("/api/pesquisa", headers=h, params={"q": "OLIVEIRA"}).json()
    assert [i["titulo"] for i in r["itens"]] == ["João Carlos Oliveira"]
    # Primeiro nome + sobrenome
    r = cliente.get("/api/pesquisa", headers=h, params={"q": "joao silva"}).json()
    assert [i["titulo"] for i in r["itens"]] == ["João Pedro da Silva"]


def test_pesquisa_por_cpf_e_telefone(cliente, token_master, base):
    h = auth(token_master)
    r = cliente.get("/api/pesquisa", headers=h, params={"q": "529.982"}).json()
    assert [i["titulo"] for i in r["itens"]] == ["João Gomes Pereira"]
    assert "CPF 529.982.247-25" in r["itens"][0]["resumo"] and "Campinas/SP" in r["itens"][0]["resumo"]
    r = cliente.get("/api/pesquisa", headers=h, params={"q": "98765"}).json()
    assert [i["titulo"] for i in r["itens"]] == ["João Gomes Pereira"]
    r = cliente.get("/api/pesquisa", headers=h, params={"q": "(19) 3333"}).json()
    assert [i["titulo"] for i in r["itens"]] == ["Ana Beatriz Souza"]


def test_pesquisa_com_paginacao(cliente, token_master, base):
    h = auth(token_master)
    p1 = cliente.get("/api/pesquisa", headers=h, params={"q": "joao", "por_pagina": 3}).json()
    p2 = cliente.get("/api/pesquisa", headers=h, params={"q": "joao", "por_pagina": 3, "pagina": 2}).json()
    assert p1["total"] == 4 and len(p1["itens"]) == 3 and len(p2["itens"]) == 1
    assert not {i["id"] for i in p1["itens"]} & {i["id"] for i in p2["itens"]}


def test_caracteres_especiais_nao_quebram_pesquisa(cliente, token_master, base):
    h = auth(token_master)
    for termo in ("%%%", "___", "jo%", "' OR 1=1 --"):
        r = cliente.get("/api/pesquisa", headers=h, params={"q": termo})
        assert r.status_code == 200 and r.json()["total"] == 0


def test_sem_permissao_clientes_nao_ve_nada(cliente, token_master, base):
    criar_usuario(cliente, token_master, "sem", permissoes=["agenda"])
    t = login(cliente, "sem", "Definitiva2026")
    h = auth(t)
    assert cliente.get("/api/pesquisa", headers=h, params={"q": "joao"}).json()["itens"] == []
    assert cliente.get("/api/clientes", headers=h).status_code == 403
    assert cliente.get(f"/api/clientes/{base['João Gomes Pereira']}", headers=h).status_code == 403
    assert cliente.post("/api/clientes", headers=h, json={"nome_completo": "Tentativa"}).status_code == 403
    assert cliente.get(f"/api/clientes/{base['João Gomes Pereira']}/historico", headers=h).status_code == 403


def test_edicao_e_controle_de_edicao_simultanea(cliente, token_master, base, db):
    h = auth(token_master)
    cid = base["Maria Joana Prado"]
    atual = cliente.get(f"/api/clientes/{cid}", headers=h).json()
    v = atual["versao"]
    r1 = cliente.patch(f"/api/clientes/{cid}", headers=h, json={"versao": v, "cidade": "Santos", "uf": "SP"})
    assert r1.status_code == 200 and r1.json()["versao"] == v + 1
    # Segunda pessoa editando a versão antiga: recusado, nada é sobrescrito
    r2 = cliente.patch(f"/api/clientes/{cid}", headers=h, json={"versao": v, "cidade": "Outra"})
    assert r2.status_code == 409 and "alterado por outra pessoa" in r2.json()["detail"]
    assert cliente.get(f"/api/clientes/{cid}", headers=h).json()["cidade"] == "Santos"
    hist = cliente.get(f"/api/clientes/{cid}/historico", headers=h).json()
    assert hist[0]["acao"] == "cliente.editado" and hist[0]["detalhes"]["cidade"]["depois"] == "Santos"


def test_edicao_concorrente_real(app, token_master, base):
    cid = base["Ana Beatriz Souza"]
    with TestClient(app) as c:
        v = c.get(f"/api/clientes/{cid}", headers=auth(token_master)).json()["versao"]
    status = []

    def editar(n):
        with TestClient(app) as c:
            status.append(c.patch(f"/api/clientes/{cid}", headers=auth(token_master),
                                  json={"versao": v, "observacoes": f"edição {n}"}).status_code)

    ts = [threading.Thread(target=editar, args=(i,)) for i in range(4)]
    [t.start() for t in ts]
    [t.join() for t in ts]
    assert status.count(200) == 1 and status.count(409) == 3


def test_encerrar_preserva_registro_e_reativar(cliente, token_master, base, url_banco):
    h = auth(token_master)
    cid = base["João Henrique Santos"]
    v = cliente.get(f"/api/clientes/{cid}", headers=h).json()["versao"]
    r = cliente.post(f"/api/clientes/{cid}/encerrar", headers=h, json={"motivo": "Processo finalizado", "versao": v})
    assert r.status_code == 200 and r.json()["situacao"] == "encerrado"
    # Continua consultável e na pesquisa (marcado como encerrado)
    p = cliente.get("/api/pesquisa", headers=h, params={"q": "henrique"}).json()
    assert "Atendimento encerrado" in p["itens"][0]["resumo"]
    ativos = cliente.get("/api/clientes", headers=h, params={"situacao": "ativo"}).json()
    assert cid not in [i["id"] for i in ativos["itens"]]
    r = cliente.post(f"/api/clientes/{cid}/reativar", headers=h, params={"versao": r.json()["versao"]})
    assert r.json()["situacao"] == "ativo"
    # O banco não permite apagar clientes
    eng = create_engine(url_banco)
    with pytest.raises(DBAPIError, match="não pode ser apagado"):
        with eng.begin() as c:
            c.execute(text("DELETE FROM clientes WHERE id = :i"), {"i": cid})
    eng.dispose()


def test_responsavel_deve_ser_usuario_ativo(cliente, token_master, master):
    h = auth(token_master)
    c = novo(cliente, token_master, "Cliente Com Responsável", advogado_responsavel_id=master["id"])
    assert c["advogado_responsavel_nome"] == "Maria Advogada Teste"
    r = cliente.post("/api/clientes", headers=h, json={"nome_completo": "Outro Cliente",
                     "advogado_responsavel_id": "00000000-0000-0000-0000-000000000000"})
    assert r.status_code == 422


def test_auditoria_de_clientes(cliente, token_master, base, db):
    acoes = db.scalars(select(Auditoria.acao).where(Auditoria.entidade == "cliente")).all()
    assert acoes.count("cliente.criado") == len(base)
