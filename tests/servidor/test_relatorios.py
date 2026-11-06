"""Painel inicial e relatórios: permissões, filtros, totais e exportação em PDF e Excel."""

from __future__ import annotations

import io
from datetime import date, timedelta
from decimal import Decimal

import pytest
from openpyxl import load_workbook

from tests.conftest import auth, criar_usuario, login
from tests.servidor.test_agenda import novo, quando
from tests.servidor.test_financeiro import contrato, pagar
from tests.servidor.test_processos_documentos import novo_processo

D = Decimal
HOJE = date.today()


def rel(cliente, token, tipo, **params):
    r = cliente.get(f"/api/relatorios/{tipo}", headers=auth(token), params=params)
    assert r.status_code == 200, r.text
    return r.json()


def planilha(conteudo: bytes):
    return load_workbook(io.BytesIO(conteudo)).active


@pytest.fixture
def escritorio(cliente, token_master, master):
    """Dados mínimos de um escritório para os relatórios."""
    h = auth(token_master)
    ana = cliente.post("/api/clientes", headers=h, json={
        "nome_completo": "Ana Relatório", "cpf": "52998224725", "cidade": "Campinas", "uf": "SP",
        "advogado_responsavel_id": master["id"], "data_inicio_atendimento": (HOJE - timedelta(days=10)).isoformat()}).json()
    bruno = cliente.post("/api/clientes", headers=h, json={
        "nome_completo": "Bruno Relatório", "data_inicio_atendimento": (HOJE - timedelta(days=400)).isoformat()}).json()
    r = cliente.post(f"/api/clientes/{bruno['id']}/encerrar", headers=h,
                     json={"versao": bruno["versao"], "motivo": "Processo finalizado"})
    assert r.status_code == 200, r.text
    proc = novo_processo(cliente, token_master, ana["id"], advogado_responsavel_id=master["id"])
    novo(cliente, token_master, titulo="Audiência de instrução", tipo="audiencia", inicio=quando(2, 14),
         cliente_id=ana["id"], processo_id=proc["id"], responsavel_id=master["id"], local="Fórum Criminal")
    novo(cliente, token_master, titulo="Prazo de alegações finais", tipo="prazo", inicio=quando(-1, 18),
         cliente_id=ana["id"])
    c = contrato(cliente, token_master, ana["id"], valor_total="3000.00", valor_entrada="1000.00",
                 quantidade_parcelas=2, valor_parcela="1000.00",
                 primeiro_vencimento=(HOJE - timedelta(days=3)).isoformat(), dia_vencimento=(HOJE - timedelta(days=3)).day)
    assert pagar(cliente, token_master, c["parcelas"][0]["id"], "1000.00").status_code == 201
    pg = pagar(cliente, token_master, c["parcelas"][1]["id"], "200.00", forma_pagamento="dinheiro").json()
    r = cliente.post(f"/api/financeiro/pagamentos/{pg['id']}/estornar", headers=h, json={"motivo": "Valor errado"})
    assert r.status_code == 200, r.text
    cliente.post("/api/financeiro/despesas", headers=h, json={
        "descricao": "Gasolina para buscar cliente", "categoria": "combustivel", "valor": "80.00",
        "data": HOJE.isoformat(), "cliente_id": ana["id"]})
    return {"ana": ana, "bruno": bruno, "processo": proc, "contrato": c}


def test_quem_pode_gerar_cada_relatorio(cliente, token_master, escritorio, db):
    criar_usuario(cliente, token_master, "secretaria", permissoes=["clientes", "contratos", "agenda"])
    t = login(cliente, "secretaria", "Definitiva2026")
    disp = cliente.get("/api/relatorios/disponiveis", headers=auth(t)).json()
    assert set(disp) == {"clientes", "contratos", "audiencias", "prazos", "pendencias"}
    assert len(cliente.get("/api/relatorios/disponiveis", headers=auth(token_master)).json()) == 10
    # Relatórios financeiros: bloqueados no servidor em qualquer formato
    for tipo in ("parcelas", "recebimentos", "despesas", "resultado_financeiro"):
        for formato in ("json", "pdf", "xlsx"):
            r = cliente.get(f"/api/relatorios/{tipo}", headers=auth(t), params={"formato": formato})
            assert r.status_code == 403, (tipo, formato)
    assert cliente.get("/api/relatorios/processos", headers=auth(t)).status_code == 403
    # Contratos sem Financeiro: sem nenhuma coluna ou total com valores, também no Excel
    c = rel(cliente, t, "contratos")
    assert [x["titulo"] for x in c["colunas"]] == ["Início", "Cliente", "Serviço contratado", "Responsável", "Situação"]
    assert "Financeiro" in c["observacao"] and not c["confidencial"]
    assert all("R$" not in x["valor"] for x in c["totais"])
    r = cliente.get("/api/relatorios/contratos", headers=auth(t), params={"formato": "xlsx"})
    ws = planilha(r.content)
    textos = " ".join(str(v) for linha in ws.iter_rows(values_only=True) for v in linha if v is not None)
    assert "R$" not in textos and "3000" not in textos and "Ana Relatório" in textos
    # Painel: sem bloco financeiro e sem áreas não liberadas
    p = cliente.get("/api/painel", headers=auth(t)).json()
    assert p["financeiro"] is None and p["processos_em_andamento"] is None
    assert p["clientes_ativos"] == 1 and p["proximas_audiencias"][0]["titulo"] == "Audiência de instrução"
    # Tentativas negadas ficam na auditoria
    hist = cliente.get("/api/auditoria", headers=auth(token_master), params={"acao": "acesso.negado"}).json()["itens"]
    assert any((h["detalhes"] or {}).get("relatorio") == "parcelas" for h in hist)


def test_relatorios_financeiros_e_totais(cliente, token_master, escritorio):
    p = rel(cliente, token_master, "parcelas")
    por_parcela = {l[3]: l for l in p["linhas"]}
    assert set(por_parcela) == {"Entrada", "1", "2"}
    assert por_parcela["Entrada"][7] == "Paga" and por_parcela["1"][7] == "Vencida"
    assert por_parcela["2"][7] == "Em aberto" and D(por_parcela["1"][6]) == D("1000")
    totais = {t["rotulo"]: t["valor"] for t in p["totais"]}
    assert totais["Total pago"] == "R$ 1.000,00" and totais["Total em aberto"] == "R$ 2.000,00"
    assert totais["Em atraso"] == "R$ 1.000,00" and p["confidencial"]
    vencidas = rel(cliente, token_master, "parcelas", situacao="vencida")
    assert len(vencidas["linhas"]) == 1
    r = rel(cliente, token_master, "recebimentos")
    totais = {t["rotulo"]: t["valor"] for t in r["totais"]}
    assert totais["Total recebido (válidos)"] == "R$ 1.000,00" and totais["Estornados (não somam)"] == "R$ 200,00"
    assert any(l[7].startswith("Estornado (Valor errado)") for l in r["linhas"])
    d = rel(cliente, token_master, "despesas")
    assert {t["rotulo"]: t["valor"] for t in d["totais"]}["Combustível"] == "R$ 80,00"
    res = rel(cliente, token_master, "resultado_financeiro")
    assert len(res["linhas"]) == 1 and D(res["linhas"][0][1]) == D("1000") and D(res["linhas"][0][3]) == D("920")
    totais = {t["rotulo"]: t["valor"] for t in res["totais"]}
    assert totais["Saldo líquido do período"] == "R$ 920,00"
    assert totais["Total contratado (vigentes)"] == "R$ 3.000,00"
    # Vários meses
    res = rel(cliente, token_master, "resultado_financeiro", inicio=(HOJE - timedelta(days=70)).isoformat(),
              fim=HOJE.isoformat())
    assert len(res["linhas"]) >= 3
    # Contratos com Financeiro: valores
    c = rel(cliente, token_master, "contratos")
    assert c["linhas"][0][5:] == ["3000.00", "1000.00", "2000.00"] and c["confidencial"]


def test_exportar_pdf_e_excel(cliente, token_master, escritorio):
    h = auth(token_master)
    r = cliente.get("/api/relatorios/parcelas", headers=h, params={"formato": "pdf"})
    assert r.status_code == 200 and r.content.startswith(b"%PDF") and len(r.content) > 5000
    assert r.headers["content-type"] == "application/pdf"
    assert "relatorio-parcelas-" in r.headers["content-disposition"] and r.headers["cache-control"] == "no-store"
    r = cliente.get("/api/relatorios/recebimentos", headers=h, params={"formato": "xlsx"})
    assert r.status_code == 200
    ws = planilha(r.content)
    linhas = list(ws.iter_rows(values_only=True))
    assert linhas[0][0] == "Relatório de recebimentos"
    assert any(l and l[0] and "CONFIDENCIAL" in str(l[0]) for l in linhas)
    i = next(n for n, l in enumerate(linhas) if l[0] == "Data")
    assert linhas[i][:6] == ("Data", "Cliente", "Serviço contratado", "Parcela", "Forma", "Valor")
    valores = [l[5] for l in linhas[i + 1:i + 3]]
    assert all(isinstance(v, (int, float)) for v in valores) and sorted(valores) == [200, 1000]
    cel = ws.cell(i + 2, 6)
    assert "R$" in cel.number_format and ws.cell(i + 2, 1).number_format == "DD/MM/YYYY"
    # Todos os relatórios exportam nos dois formatos, inclusive vazios
    for tipo in cliente.get("/api/relatorios/disponiveis", headers=h).json():
        for formato in ("pdf", "xlsx"):
            r = cliente.get(f"/api/relatorios/{tipo}", headers=h,
                            params={"formato": formato, "inicio": "2001-01-01", "fim": "2001-01-31"})
            assert r.status_code == 200, (tipo, formato, r.text)
    hist = cliente.get("/api/auditoria", headers=h, params={"acao": "relatorio.exportado"}).json()["itens"]
    assert len(hist) >= 22 and {"tipo", "formato", "linhas", "filtros"} <= set(hist[0]["detalhes"])
    assert cliente.get("/api/relatorios/parcelas", headers=h, params={"formato": "docx"}).status_code == 422
    assert cliente.get("/api/relatorios/inexistente", headers=h).status_code == 404


def test_filtros(cliente, token_master, master, escritorio):
    ana, bruno = escritorio["ana"]["id"], escritorio["bruno"]["id"]
    todos = rel(cliente, token_master, "clientes")
    assert [l[0] for l in todos["linhas"]] == ["Ana Relatório", "Bruno Relatório"]
    assert todos["linhas"][0][1] == "529.982.247-25" and todos["linhas"][0][4] == "Campinas/SP"
    assert [l[0] for l in rel(cliente, token_master, "clientes", situacao="encerrado")["linhas"]] == ["Bruno Relatório"]
    assert [l[0] for l in rel(cliente, token_master, "clientes", responsavel_id=master["id"])["linhas"]] == ["Ana Relatório"]
    recentes = rel(cliente, token_master, "clientes", inicio=(HOJE - timedelta(days=30)).isoformat())
    assert [l[0] for l in recentes["linhas"]] == ["Ana Relatório"] and "Período: a partir de" in recentes["filtros"][0]
    p = rel(cliente, token_master, "processos", cliente_id=ana)
    assert len(p["linhas"]) == 1 and p["linhas"][0][1] == "Ana Relatório" and "Cliente: Ana Relatório" in p["filtros"]
    assert rel(cliente, token_master, "processos", cliente_id=bruno)["linhas"] == []
    aud = rel(cliente, token_master, "audiencias")
    assert [l[1] for l in aud["linhas"]] == ["Audiência de instrução"] and aud["linhas"][0][4] == "Fórum Criminal"
    prz = rel(cliente, token_master, "prazos", situacao="atrasado")
    assert [l[1] for l in prz["linhas"]] == ["Prazo de alegações finais"] and prz["linhas"][0][6] == "Atrasado"
    pend = rel(cliente, token_master, "pendencias")
    tipos = {l[2] for l in pend["linhas"]}
    assert {"Audiência", "Prazo", "Financeiro"} <= tipos
    assert all("R$" not in str(c) for l in pend["linhas"] for c in l)
    # Quem não tem Financeiro não vê as parcelas na lista de pendências
    criar_usuario(cliente, token_master, "estagiario", permissoes=["pendencias"])
    t = login(cliente, "estagiario", "Definitiva2026")
    assert "Financeiro" not in {l[2] for l in rel(cliente, t, "pendencias")["linhas"]}
    # Validações
    h = auth(token_master)
    assert cliente.get("/api/relatorios/clientes", headers=h, params={"situacao": "xyz"}).status_code == 422
    r = cliente.get("/api/relatorios/clientes", headers=h, params={"inicio": "2026-02-10", "fim": "2026-02-01"})
    assert r.status_code == 422 and "anterior" in r.json()["detail"]
    assert cliente.get("/api/relatorios/resultado_financeiro", headers=h, params={"cliente_id": ana}).status_code == 422


def test_painel_da_master(cliente, token_master, escritorio):
    p = cliente.get("/api/painel", headers=auth(token_master)).json()
    assert p["clientes_ativos"] == 1 and p["processos_em_andamento"] == 1
    assert p["total_atrasados"] == 1 and p["atrasados"][0]["titulo"] == "Prazo de alegações finais"
    assert [a["titulo"] for a in p["proximas_audiencias"]] == ["Audiência de instrução"]
    f = p["financeiro"]
    assert D(f["recebido_no_mes"]) == D("1000") and D(f["despesas_no_mes"]) == D("80")
    assert D(f["saldo_do_mes"]) == D("920") and D(f["total_vencido"]) == D("1000") and f["parcelas_vencidas"] == 1
