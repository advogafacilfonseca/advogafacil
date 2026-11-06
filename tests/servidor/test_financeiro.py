"""Contratos e financeiro: geração de parcelas, baixas, renegociação, despesas e sigilo."""

from __future__ import annotations

import threading
from datetime import date, timedelta
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.exc import DBAPIError

from tests.conftest import auth, criar_usuario, login

D = Decimal
HOJE = date.today()


@pytest.fixture
def cli(cliente, token_master):
    return cliente.post("/api/clientes", headers=auth(token_master), json={"nome_completo": "Cliente Financeiro"}).json()


def contrato(cliente, token, cliente_id, **extra):
    corpo = {"cliente_id": cliente_id, "servico_contratado": "Defesa criminal", "data_inicio": HOJE.isoformat(),
             "valor_total": "6000.00", "valor_entrada": "1000.00", "quantidade_parcelas": 10,
             "valor_parcela": "500.00", "primeiro_vencimento": (HOJE + timedelta(days=30)).isoformat()} | extra
    r = cliente.post("/api/contratos", headers=auth(token), json=corpo)
    assert r.status_code == 201, r.text
    return r.json()


def pagar(cliente, token, parcela_id, valor, **extra):
    return cliente.post("/api/financeiro/pagamentos", headers=auth(token), json={
        "parcela_id": parcela_id, "valor": valor, "data_recebimento": HOJE.isoformat(), "forma_pagamento": "pix"} | extra)


def totais(cliente, token, contrato_id):
    t = cliente.get(f"/api/contratos/{contrato_id}", headers=auth(token)).json()["totais"]
    return {k: D(v) for k, v in t.items()}


def invariante(t):
    assert t["contratado"] == t["recebido"] + t["a_receber"] + t["cancelado"], t


def test_exemplo_do_escritorio_contrato_nao_e_dinheiro_recebido(cliente, token_master, cli):
    c = contrato(cliente, token_master, cli["id"])
    parcelas = c["parcelas"]
    assert len(parcelas) == 11 and parcelas[0]["tipo"] == "entrada" and D(parcelas[0]["valor"]) == D("1000")
    assert all(D(p["valor"]) == D("500") for p in parcelas[1:])
    t = totais(cliente, token_master, c["id"])
    assert t["contratado"] == D("6000") and t["recebido"] == 0 and t["a_receber"] == D("6000")
    # Entrada efetivamente recebida
    assert pagar(cliente, token_master, parcelas[0]["id"], "1000.00").status_code == 201
    t = totais(cliente, token_master, c["id"])
    assert t["recebido"] == D("1000") and t["a_receber"] == D("5000")
    invariante(t)


def test_vencimentos_e_divisao_automatica(cliente, token_master, cli):
    c = contrato(cliente, token_master, cli["id"], valor_total="1000.00", valor_entrada="0", quantidade_parcelas=3,
                 valor_parcela=None, primeiro_vencimento="2027-01-31", dia_vencimento=31)
    ps = c["parcelas"]
    assert [D(p["valor"]) for p in ps] == [D("333.33"), D("333.33"), D("333.34")]
    assert [p["vencimento"] for p in ps] == ["2027-01-31", "2027-02-28", "2027-03-31"]
    c = contrato(cliente, token_master, cli["id"], valor_total="900.00", valor_entrada="0", valor_parcela=None,
                 quantidade_parcelas=None, parcelas_personalizadas=[
                     {"valor": "100.00", "vencimento": "2027-05-10"}, {"valor": "800.00", "vencimento": "2027-09-01"}])
    assert [(D(p["valor"]), p["vencimento"]) for p in c["parcelas"]] == [(D("100"), "2027-05-10"), (D("800"), "2027-09-01")]


def test_condicoes_invalidas(cliente, token_master, cli):
    h = auth(token_master)
    base = {"cliente_id": cli["id"], "servico_contratado": "Defesa", "data_inicio": HOJE.isoformat()}
    casos = [
        ({"valor_total": "6000", "valor_entrada": "1000", "quantidade_parcelas": 10, "valor_parcela": "450",
          "primeiro_vencimento": "2027-01-10"}, "somam R$ 4.500,00"),
        ({"valor_total": "100", "valor_entrada": "200"}, "maior que o valor total"),
        ({"valor_total": "100", "valor_entrada": "0"}, "quantidade de parcelas"),
        ({"valor_total": "100", "quantidade_parcelas": 2}, "primeiro vencimento"),
        ({"valor_total": "100", "parcelas_personalizadas": [{"valor": "50", "vencimento": "2027-01-01"}]}, "deve ser igual"),
        ({"valor_total": "-5"}, "deve ser maior que 0"),
        ({"valor_total": "10.123"}, "2 casas decimais"),
    ]
    for corpo, msg in casos:
        r = cliente.post("/api/contratos", headers=h, json=base | corpo)
        assert r.status_code == 422 and msg in r.json()["detail"], (corpo, r.json())


def test_baixa_parcial_integral_e_quitacao(cliente, token_master, cli, db):
    c = contrato(cliente, token_master, cli["id"], valor_total="1000.00", valor_entrada="400.00", quantidade_parcelas=1,
                 valor_parcela="600.00")
    entrada, parcela = c["parcelas"]
    assert pagar(cliente, token_master, parcela["id"], "250.00").status_code == 201
    r = pagar(cliente, token_master, parcela["id"], "400.00")
    assert r.status_code == 422 and "maior que o restante" in r.json()["detail"] and "R$ 350,00" in r.json()["detail"]
    assert pagar(cliente, token_master, parcela["id"], "350.00", forma_pagamento="dinheiro",
                 observacoes="Pago no escritório").status_code == 201
    r = pagar(cliente, token_master, parcela["id"], "1.00")
    assert r.status_code == 400  # parcela já paga
    pagar(cliente, token_master, entrada["id"], "400.00")
    c2 = cliente.get(f"/api/contratos/{c['id']}", headers=auth(token_master)).json()
    assert c2["situacao"] == "quitado" and all(p["situacao"] == "paga" for p in c2["parcelas"])
    pgs = cliente.get("/api/financeiro/pagamentos", headers=auth(token_master), params={"contrato_id": c["id"]}).json()
    assert pgs["total"] == 3 and {p["registrado_por_nome"] for p in pgs["itens"]} == {"Maria Advogada Teste"}


def test_pagamentos_simultaneos_nao_ultrapassam_a_parcela(app, cliente, token_master, cli):
    c = contrato(cliente, token_master, cli["id"])
    pid = c["parcelas"][1]["id"]  # R$ 500
    status = []

    def tentar():
        with TestClient(app) as t:
            status.append(pagar(t, token_master, pid, "300.00").status_code)

    ts = [threading.Thread(target=tentar) for _ in range(4)]
    [t.start() for t in ts]
    [t.join() for t in ts]
    assert sorted(status) == [201, 422, 422, 422]


def test_reenvio_do_mesmo_pagamento_nao_duplica(cliente, token_master, cli):
    c = contrato(cliente, token_master, cli["id"])
    h = auth(token_master) | {"Idempotency-Key": "pagamento-0001-xyz"}
    corpo = {"parcela_id": c["parcelas"][0]["id"], "valor": "100.00", "data_recebimento": HOJE.isoformat(),
             "forma_pagamento": "pix"}
    r1 = cliente.post("/api/financeiro/pagamentos", headers=h, json=corpo)
    r2 = cliente.post("/api/financeiro/pagamentos", headers=h, json=corpo)
    assert r1.json()["id"] == r2.json()["id"]
    assert totais(cliente, token_master, c["id"])["recebido"] == D("100")


def test_estorno_e_recebimento_imutavel(cliente, token_master, cli, url_banco):
    c = contrato(cliente, token_master, cli["id"], valor_total="500.00", valor_entrada="0", quantidade_parcelas=1,
                 valor_parcela="500.00")
    pid = c["parcelas"][0]["id"]
    pg = pagar(cliente, token_master, pid, "500.00").json()
    assert cliente.get(f"/api/contratos/{c['id']}", headers=auth(token_master)).json()["situacao"] == "quitado"
    r = cliente.post(f"/api/financeiro/pagamentos/{pg['id']}/estornar", headers=auth(token_master),
                     json={"motivo": "Pix devolvido pelo banco"})
    assert r.status_code == 200 and r.json()["motivo_estorno"] == "Pix devolvido pelo banco"
    c2 = cliente.get(f"/api/contratos/{c['id']}", headers=auth(token_master)).json()
    assert c2["situacao"] == "ativo" and c2["parcelas"][0]["situacao"] == "aberta"
    assert D(c2["totais"]["recebido"]) == 0
    assert cliente.post(f"/api/financeiro/pagamentos/{pg['id']}/estornar", headers=auth(token_master),
                        json={"motivo": "de novo"}).status_code == 400
    eng = create_engine(url_banco)
    for sql in (f"UPDATE pagamentos SET valor = 1 WHERE id = '{pg['id']}'", "DELETE FROM pagamentos",
                "DELETE FROM parcelas", "DELETE FROM contratos"):
        with pytest.raises(DBAPIError):
            with eng.begin() as conn:
                conn.execute(text(sql))
    eng.dispose()


def test_cancelamento_de_parcela_e_de_contrato(cliente, token_master, cli):
    c = contrato(cliente, token_master, cli["id"])
    ps = c["parcelas"]
    pagar(cliente, token_master, ps[0]["id"], "1000.00")
    pagar(cliente, token_master, ps[1]["id"], "200.00")
    r = cliente.post(f"/api/financeiro/parcelas/{ps[1]['id']}/cancelar", headers=auth(token_master),
                     json={"versao": ps[1]["versao"], "motivo": "Desconto concedido"})
    assert r.status_code == 409  # versão mudou com o pagamento: precisa atualizar a tela
    atual = next(p for p in cliente.get(f"/api/contratos/{c['id']}", headers=auth(token_master)).json()["parcelas"]
                 if p["id"] == ps[1]["id"])
    r = cliente.post(f"/api/financeiro/parcelas/{ps[1]['id']}/cancelar", headers=auth(token_master),
                     json={"versao": atual["versao"], "motivo": "Desconto concedido"})
    assert r.status_code == 200 and D(r.json()["valor_baixado"]) == D("300")
    t = totais(cliente, token_master, c["id"])
    assert t["recebido"] == D("1200") and t["cancelado"] == D("300") and t["a_receber"] == D("4500")
    invariante(t)
    v = cliente.get(f"/api/contratos/{c['id']}", headers=auth(token_master)).json()["versao"]
    r = cliente.post(f"/api/contratos/{c['id']}/cancelar", headers=auth(token_master),
                     json={"versao": v, "motivo": "Cliente desistiu"})
    assert r.status_code == 200 and r.json()["situacao"] == "cancelado"
    t = {k: D(x) for k, x in r.json()["totais"].items()}
    assert t["a_receber"] == 0 and t["cancelado"] == D("4800") and t["recebido"] == D("1200")
    invariante(t)


def test_renegociacao(cliente, token_master, cli):
    c = contrato(cliente, token_master, cli["id"])
    ps = c["parcelas"]
    pagar(cliente, token_master, ps[0]["id"], "1000.00")
    pagar(cliente, token_master, ps[9]["id"], "100.00")
    atrasadas = [ps[8]["id"], ps[9]["id"], ps[10]["id"]]  # restante 500 + 400 + 500 = 1400
    r = cliente.post(f"/api/contratos/{c['id']}/renegociar", headers=auth(token_master), json={
        "versao": c["versao"], "parcelas_ids": atrasadas, "novo_valor": "1500.00", "quantidade_parcelas": 3,
        "primeiro_vencimento": (HOJE + timedelta(days=60)).isoformat(), "motivo": "Acordo com juros"})
    assert r.status_code == 200, r.text
    novo = r.json()
    renegociadas = [p for p in novo["parcelas"] if p["situacao"] == "renegociada"]
    novas = [p for p in novo["parcelas"] if p["numero"] > 10]
    assert len(renegociadas) == 3 and [p["numero"] for p in novas] == [11, 12, 13]
    assert sum(D(p["valor"]) for p in novas) == D("1500")
    t = {k: D(x) for k, x in novo["totais"].items()}
    assert t["contratado"] == D("6100") and t["recebido"] == D("1100")
    invariante(t)
    hist = cliente.get(f"/api/contratos/{c['id']}/historico", headers=auth(token_master)).json()
    assert hist[0]["acao"] == "contrato.renegociado" and hist[0]["detalhes"]["saldo_anterior"] == "1400.00"


def test_sigilo_financeiro(cliente, token_master, cli):
    c = contrato(cliente, token_master, cli["id"])
    pagar(cliente, token_master, c["parcelas"][0]["id"], "1000.00")
    criar_usuario(cliente, token_master, "contr", permissoes=["contratos", "clientes"])
    criar_usuario(cliente, token_master, "nada", permissoes=["clientes", "processos", "documentos", "agenda"])
    tc, tn = login(cliente, "contr", "Definitiva2026"), login(cliente, "nada", "Definitiva2026")
    # Com "Contratos" mas sem "Financeiro": vê o serviço contratado, nunca valores
    r = cliente.get(f"/api/contratos/{c['id']}", headers=auth(tc)).json()
    assert r["servico_contratado"] == "Defesa criminal" and r["financeiro_visivel"] is False
    assert r["totais"] is None and r["parcelas"] is None
    lista = cliente.get("/api/contratos", headers=auth(tc)).json()
    assert lista["itens"][0]["totais"] is None
    hist = cliente.get(f"/api/contratos/{c['id']}/historico", headers=auth(tc)).json()
    assert [h["acao"] for h in hist] == ["contrato.criado"] and hist[0]["detalhes"] is None
    corpo = {"cliente_id": cli["id"], "servico_contratado": "Outro", "data_inicio": HOJE.isoformat(),
             "valor_total": "100", "valor_entrada": "100"}
    assert cliente.post("/api/contratos", headers=auth(tc), json=corpo).status_code == 403
    assert cliente.patch(f"/api/contratos/{c['id']}", headers=auth(tc), json={
        "versao": c["versao"], "observacoes": "Cliente prefere contato por WhatsApp"}).status_code == 200
    # Sem nenhuma das duas: nada
    for t in (tc, tn):
        for rota in ("/api/financeiro/parcelas", "/api/financeiro/pagamentos", "/api/financeiro/despesas",
                     f"/api/financeiro/resumo?inicio={HOJE}&fim={HOJE}"):
            assert cliente.get(rota, headers=auth(t)).status_code == 403, rota
    assert cliente.get("/api/contratos", headers=auth(tn)).status_code == 403
    assert pagar(cliente, tc, c["parcelas"][1]["id"], "10.00").status_code == 403
    # A pesquisa global não traz nada financeiro
    r = cliente.get("/api/pesquisa", headers=auth(tn), params={"q": "Defesa criminal"}).json()
    assert r["itens"] == []


def test_despesas_e_resumo(cliente, token_master, cli, master):
    h = auth(token_master)
    c = contrato(cliente, token_master, cli["id"], valor_total="1500.00", valor_entrada="500.00",
                 quantidade_parcelas=2, valor_parcela="500.00",
                 primeiro_vencimento=(HOJE - timedelta(days=5)).isoformat(),
                 dia_vencimento=(HOJE - timedelta(days=5)).day)
    pagar(cliente, token_master, c["parcelas"][0]["id"], "500.00")
    d1 = cliente.post("/api/financeiro/despesas", headers=h, json={
        "descricao": "Gasolina para buscar cliente", "categoria": "combustivel", "valor": "120.50",
        "data": HOJE.isoformat(), "cliente_id": cli["id"]})
    assert d1.status_code == 201 and d1.json()["responsavel_nome"] == "Maria Advogada Teste"
    d2 = cliente.post("/api/financeiro/despesas", headers=h, json={
        "descricao": "Estacionamento fórum", "categoria": "estacionamento", "valor": "30.00", "data": HOJE.isoformat()}).json()
    r = cliente.patch(f"/api/financeiro/despesas/{d2['id']}", headers=h, json={"versao": d2["versao"], "valor": "35.00"})
    assert r.status_code == 200 and D(r.json()["valor"]) == D("35")
    hist = cliente.get(f"/api/financeiro/despesas/{d2['id']}/historico", headers=h).json()
    assert hist[0]["detalhes"]["valor"] == {"antes": "30.00", "depois": "35.00"}
    inicio, fim = (HOJE - timedelta(days=40)).isoformat(), (HOJE + timedelta(days=40)).isoformat()
    res = cliente.get("/api/financeiro/resumo", headers=h, params={"inicio": inicio, "fim": fim}).json()
    assert D(res["total_contratado"]) == D("1500") and D(res["total_recebido"]) == D("500")
    assert D(res["total_a_receber"]) == D("1000") and D(res["total_vencido"]) == D("500")
    assert res["parcelas_vencidas"] == 1 and res["parcelas_a_vencer"] == 1
    assert D(res["despesas_no_periodo"]) == D("155.50") and D(res["saldo_liquido_periodo"]) == D("344.50")
    assert res["despesas_por_categoria"] == {"Combustível": "120.50", "Estacionamento": "35.00"}
    assert [a["titulo"] for a in res["avisos"]] == ["PARCELA ATRASADA HÁ 5 DIAS"]
    # Cancelar despesa atualiza o resumo
    v = cliente.get("/api/financeiro/despesas", headers=h).json()["itens"]
    alvo = next(x for x in v if x["categoria"] == "combustivel")
    cliente.post(f"/api/financeiro/despesas/{alvo['id']}/cancelar", headers=h,
                 json={"versao": alvo["versao"], "motivo": "Lançada em duplicidade"})
    res = cliente.get("/api/financeiro/resumo", headers=h, params={"inicio": inicio, "fim": fim}).json()
    assert D(res["despesas_no_periodo"]) == D("35")


def test_avisos_amanha_e_hoje(cliente, token_master, cli):
    contrato(cliente, token_master, cli["id"], valor_total="300.00", valor_entrada="0", valor_parcela=None,
             quantidade_parcelas=None, parcelas_personalizadas=[
                 {"valor": "100.00", "vencimento": HOJE.isoformat()},
                 {"valor": "100.00", "vencimento": (HOJE + timedelta(days=1)).isoformat()},
                 {"valor": "100.00", "vencimento": (HOJE + timedelta(days=2)).isoformat()}])
    res = cliente.get("/api/financeiro/resumo", headers=auth(token_master),
                      params={"inicio": HOJE.isoformat(), "fim": HOJE.isoformat()}).json()
    assert [a["titulo"] for a in res["avisos"]] == ["PAGAMENTO VENCE HOJE", "AMANHÃ TEM PAGAMENTO"]
    hoje_id = res["avisos"][0]["parcela"]["id"]
    pagar(cliente, token_master, hoje_id, "100.00")  # pagou: o aviso daquela parcela para
    res = cliente.get("/api/financeiro/resumo", headers=auth(token_master),
                      params={"inicio": HOJE.isoformat(), "fim": HOJE.isoformat()}).json()
    assert [a["titulo"] for a in res["avisos"]] == ["AMANHÃ TEM PAGAMENTO"]


def test_comprovante_restrito_ao_financeiro(cliente, token_master, cli, cfg):
    c = contrato(cliente, token_master, cli["id"])
    r = cliente.post("/api/financeiro/comprovantes", headers=auth(token_master) | {"Content-Type": "image/png"},
                     params={"nome": "comprovante pix.png"}, content=b"\x89PNG comprovante")
    assert r.status_code == 201
    comp = r.json()
    pg = pagar(cliente, token_master, c["parcelas"][0]["id"], "1000.00", comprovante_id=comp["id"]).json()
    assert pg["comprovante_nome"] == "comprovante pix.png"
    b = cliente.get(f"/api/financeiro/comprovantes/{comp['id']}/arquivo", headers=auth(token_master))
    assert b.status_code == 200 and b.content == b"\x89PNG comprovante"
    criar_usuario(cliente, token_master, "docs", permissoes=["documentos"])
    td = login(cliente, "docs", "Definitiva2026")
    assert cliente.get(f"/api/financeiro/comprovantes/{comp['id']}/arquivo", headers=auth(td)).status_code == 403
    assert cliente.get("/api/documentos", headers=auth(td)).json()["total"] == 0
    assert (cfg.pasta_documentos / "_financeiro").exists()


def test_valor_ja_pago_de_cliente_antigo(cliente, token_master, cli):
    """Cliente que já era do escritório: o que ele pagou antes do cadastro soma no recebido."""
    antes = (HOJE - timedelta(days=90)).isoformat()
    c = contrato(cliente, token_master, cli["id"], valor_ja_pago="2000.00", data_valor_ja_pago=antes,
                 valor_entrada="0", quantidade_parcelas=8, valor_parcela="500.00")
    anterior = [p for p in c["parcelas"] if p["tipo"] == "anterior"]
    assert len(anterior) == 1 and D(anterior[0]["valor"]) == D("2000") and anterior[0]["situacao"] == "paga"
    assert anterior[0]["vencimento"] == antes
    assert len([p for p in c["parcelas"] if p["tipo"] == "parcela"]) == 8
    t = totais(cliente, token_master, c["id"])
    assert t["recebido"] == D("2000") and t["a_receber"] == D("4000")
    invariante(t)
    pagamentos = cliente.get("/api/financeiro/pagamentos", headers=auth(token_master),
                             params={"contrato_id": c["id"]}).json()["itens"]
    assert [(D(p["valor"]), p["forma_pagamento"], p["data_recebimento"]) for p in pagamentos] == [
        (D("2000"), "anterior", antes)]

    # Tudo já pago antes do sistema: contrato nasce quitado, sem parcelas a receber
    q = contrato(cliente, token_master, cli["id"], valor_ja_pago="6000.00", valor_entrada="0",
                 quantidade_parcelas=None, valor_parcela=None, primeiro_vencimento=None)
    assert q["situacao"] == "quitado" and [p["tipo"] for p in q["parcelas"]] == ["anterior"]

    # Já pago + entrada maior que o total, data futura, e a forma "anterior" não serve para recebimentos comuns
    h = auth(token_master)
    base = {"cliente_id": cli["id"], "servico_contratado": "Defesa", "data_inicio": HOJE.isoformat(),
            "valor_total": "1000.00"}
    r = cliente.post("/api/contratos", headers=h, json=base | {"valor_ja_pago": "800.00", "valor_entrada": "300.00"})
    assert r.status_code == 422 and "já pago" in r.text
    r = cliente.post("/api/contratos", headers=h, json=base | {
        "valor_ja_pago": "1000.00", "data_valor_ja_pago": (HOJE + timedelta(days=1)).isoformat()})
    assert r.status_code == 422 and "futuro" in r.text
    aberta = next(p for p in c["parcelas"] if p["tipo"] == "parcela")
    assert pagar(cliente, token_master, aberta["id"], "500.00", forma_pagamento="anterior").status_code == 422
