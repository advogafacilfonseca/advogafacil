"""Processos, movimentações, documentos e pesquisa global com esses registros."""

from __future__ import annotations

import hashlib
from datetime import date, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select, text
from sqlalchemy.exc import DBAPIError

from advoga_server.models import Auditoria, Documento
from advoga_shared.validacoes import cnj_valido, digito_cnj, formatar_cnj
from tests.conftest import auth, criar_usuario, login


def cnj(seq: int, origem: str = "0100") -> str:
    s = f"{seq:07d}"
    return f"{s}-{digito_cnj(s, '2024', '8', '26', origem)}.2024.8.26.{origem}"


@pytest.fixture
def cli(cliente, token_master):
    r = cliente.post("/api/clientes", headers=auth(token_master), json={"nome_completo": "João Pedro da Silva"})
    return r.json()


def novo_processo(cliente, token, cliente_id, **extra):
    corpo = {"cliente_id": cliente_id, "numero_cnj": cnj(1), "tipo_acao": "Ação Penal",
             "area_juridica": "Penal", "tribunal": "TJSP", "comarca": "Campinas", "vara": "2ª Vara Criminal",
             "parte_contraria": "Ministério Público do Estado", "data_distribuicao": "2024-03-10",
             "fase_processual": "Instrução"} | extra
    r = cliente.post("/api/processos", headers=auth(token), json=corpo)
    assert r.status_code == 201, r.text
    return r.json()


def anexar(cliente, token, cliente_id, nome="peticao.pdf", conteudo=b"%PDF-1.4 conteudo de teste", **params):
    return cliente.post("/api/documentos", headers=auth(token) | {"Content-Type": "application/pdf"},
                        params={"cliente_id": cliente_id, "nome": nome} | params, content=conteudo)


# ------------------------------------------------------------------ processos
def test_numero_cnj_validado():
    assert cnj_valido(cnj(1)) and formatar_cnj(cnj(1).replace("-", "").replace(".", "")) == cnj(1)
    errado = cnj(1)[:8] + ("0" if cnj(1)[8] != "0" else "1") + cnj(1)[9:]
    assert not cnj_valido(errado)


def test_cadastro_de_processo_com_todos_os_campos(cliente, token_master, cli, master):
    quando = "2030-05-20T14:30:00-03:00"
    p = novo_processo(cliente, token_master, cli["id"], advogado_responsavel_id=master["id"],
                      proximo_evento_tipo="audiencia", proximo_evento_em=quando,
                      proximo_evento_descricao="Audiência de instrução", descricao="Defesa no caso X",
                      observacoes="Réu primário")
    assert p["numero_cnj"] == cnj(1).replace("-", "").replace(".", "")
    assert p["cliente_nome"] == "João Pedro da Silva" and p["situacao"] == "em_andamento"
    assert p["advogado_responsavel_nome"] == "Maria Advogada Teste"
    for campo in ("tipo_acao", "area_juridica", "tribunal", "comarca", "vara", "parte_contraria",
                  "data_distribuicao", "fase_processual", "proximo_evento_tipo", "proximo_evento_em",
                  "proximo_evento_descricao", "descricao", "observacoes"):
        assert p[campo], campo
    h = auth(token_master)
    r = cliente.post("/api/processos", headers=h, json={"cliente_id": cli["id"], "numero_cnj": "1234567-00.2024.8.26.0100"})
    assert r.status_code == 422 and "dígito verificador" in r.json()["detail"]
    r = cliente.post("/api/processos", headers=h, json={"cliente_id": cli["id"], "numero_cnj": cnj(1)})
    assert r.status_code == 409 and "João Pedro da Silva" in r.json()["detail"]
    r = cliente.post("/api/processos", headers=h, json={"cliente_id": cli["id"], "proximo_evento_tipo": "prazo"})
    assert r.status_code == 422 and "tipo e a data juntos" in r.json()["detail"]
    r = cliente.post("/api/processos", headers=h, json={"cliente_id": "00000000-0000-0000-0000-000000000000"})
    assert r.status_code == 422
    # Processo sem número (ex.: inquérito ainda sem numeração) é permitido
    assert cliente.post("/api/processos", headers=h, json={"cliente_id": cli["id"], "tipo_acao": "Inquérito"}
                        ).status_code == 201


def test_edicao_simultanea_e_historico(cliente, token_master, cli):
    p = novo_processo(cliente, token_master, cli["id"])
    h = auth(token_master)
    r = cliente.patch(f"/api/processos/{p['id']}", headers=h, json={"versao": p["versao"], "situacao": "suspenso",
                                                                    "fase_processual": "Recurso"})
    assert r.status_code == 200 and r.json()["situacao"] == "suspenso"
    r2 = cliente.patch(f"/api/processos/{p['id']}", headers=h, json={"versao": p["versao"], "vara": "1ª Vara"})
    assert r2.status_code == 409 and "alterado por outra pessoa" in r2.json()["detail"]
    hist = cliente.get(f"/api/processos/{p['id']}/historico", headers=h).json()
    assert [i["acao"] for i in hist] == ["processo.editado", "processo.criado"]
    assert hist[0]["detalhes"]["fase_processual"] == {"antes": "Instrução", "depois": "Recurso"}


def test_movimentacoes_sao_historico_imutavel(cliente, token_master, cli, url_banco):
    p = novo_processo(cliente, token_master, cli["id"])
    h = auth(token_master)
    for d, txt in (("2024-04-01", "Denúncia recebida"), ("2024-06-15", "Audiência realizada")):
        r = cliente.post(f"/api/processos/{p['id']}/movimentacoes", headers=h,
                         json={"data_movimentacao": d, "descricao": txt})
        assert r.status_code == 201 and r.json()["registrado_por_nome"] == "Maria Advogada Teste"
    movs = cliente.get(f"/api/processos/{p['id']}/movimentacoes", headers=h).json()
    assert [m["descricao"] for m in movs] == ["Audiência realizada", "Denúncia recebida"]
    eng = create_engine(url_banco)
    for sql in ("UPDATE movimentacoes_processo SET descricao = 'x'", "DELETE FROM movimentacoes_processo",
                f"DELETE FROM processos WHERE id = '{p['id']}'"):
        with pytest.raises(DBAPIError):
            with eng.begin() as c:
                c.execute(text(sql))
    eng.dispose()


def test_lista_de_processos_com_filtros(cliente, token_master, cli):
    h = auth(token_master)
    outro = cliente.post("/api/clientes", headers=h, json={"nome_completo": "Ana Souza"}).json()
    amanha = (date.today() + timedelta(days=1)).isoformat() + "T09:00:00-03:00"
    novo_processo(cliente, token_master, cli["id"], numero_cnj=cnj(10), proximo_evento_tipo="prazo",
                  proximo_evento_em=amanha)
    novo_processo(cliente, token_master, cli["id"], numero_cnj=cnj(11), situacao="arquivado")
    novo_processo(cliente, token_master, outro["id"], numero_cnj=cnj(12), parte_contraria="Empresa Ômega Ltda")
    todos = cliente.get("/api/processos", headers=h).json()
    assert todos["total"] == 3 and todos["itens"][0]["proximo_evento_tipo"] == "prazo"  # mais urgente primeiro
    assert cliente.get("/api/processos", headers=h, params={"cliente_id": cli["id"]}).json()["total"] == 2
    assert cliente.get("/api/processos", headers=h, params={"situacao": "arquivado"}).json()["total"] == 1
    r = cliente.get("/api/processos", headers=h, params={"q": "omega"}).json()
    assert [i["cliente_nome"] for i in r["itens"]] == ["Ana Souza"]
    opcoes = cliente.get("/api/processos-opcoes", headers=h, params={"cliente_id": cli["id"]}).json()
    assert len(opcoes) == 2 and all("Ação Penal" in o["rotulo"] for o in opcoes)


# ------------------------------------------------------------------ pesquisa global
def test_pesquisa_global_por_numero_de_processo(cliente, token_master, cli):
    novo_processo(cliente, token_master, cli["id"], numero_cnj=cnj(4321))
    h = auth(token_master)
    for termo in (cnj(4321), cnj(4321).replace(".", "").replace("-", ""), "0004321", f"{cnj(4321)[:12]}"):
        r = cliente.get("/api/pesquisa", headers=h, params={"q": termo}).json()
        assert [i["tipo"] for i in r["itens"]] == ["processo"], termo
        assert r["itens"][0]["titulo"].startswith(cnj(4321))
    r = cliente.get("/api/pesquisa", headers=h, params={"q": "ministerio publico"}).json()
    assert [i["tipo"] for i in r["itens"]] == ["processo"]


def test_pesquisa_global_mistura_tipos_e_pagina(cliente, token_master, cli):
    h = auth(token_master)
    for i in range(3):
        cliente.post("/api/clientes", headers=h, json={"nome_completo": f"Silva Cliente {i}"})
    novo_processo(cliente, token_master, cli["id"], parte_contraria="Pedro Silva Junior")
    anexar(cliente, token_master, cli["id"], nome="Procuração Silva.pdf")
    tudo = cliente.get("/api/pesquisa", headers=h, params={"q": "silva", "por_pagina": 50}).json()
    assert tudo["total"] == 6
    assert [i["tipo"] for i in tudo["itens"]] == ["cliente"] * 4 + ["processo", "documento"]
    vistos = []
    for pagina in (1, 2, 3):
        r = cliente.get("/api/pesquisa", headers=h, params={"q": "silva", "por_pagina": 2, "pagina": pagina}).json()
        assert r["total"] == 6 and len(r["itens"]) == 2
        vistos += [i["id"] for i in r["itens"]]
    assert vistos == [i["id"] for i in tudo["itens"]]


def test_pesquisa_global_respeita_permissoes(cliente, token_master, cli):
    novo_processo(cliente, token_master, cli["id"], parte_contraria="João Ninguém")
    anexar(cliente, token_master, cli["id"], nome="joao-rg.pdf")
    criar_usuario(cliente, token_master, "proc", permissoes=["processos"])
    criar_usuario(cliente, token_master, "docs", permissoes=["documentos"])
    tp, td = login(cliente, "proc", "Definitiva2026"), login(cliente, "docs", "Definitiva2026")
    r = cliente.get("/api/pesquisa", headers=auth(tp), params={"q": "joao"}).json()
    assert {i["tipo"] for i in r["itens"]} == {"processo"}
    r = cliente.get("/api/pesquisa", headers=auth(td), params={"q": "joao"}).json()
    assert {i["tipo"] for i in r["itens"]} == {"documento"}
    # Escolher cliente ao cadastrar processo: só nome e situação, sem CPF/telefones
    op = cliente.get("/api/clientes-opcoes", headers=auth(tp), params={"q": "joao"}).json()
    assert op == [{"id": cli["id"], "nome": "João Pedro da Silva", "situacao": "ativo"}]
    assert cliente.get("/api/clientes", headers=auth(tp)).status_code == 403
    assert cliente.get("/api/processos", headers=auth(td)).status_code == 403
    assert cliente.get("/api/documentos", headers=auth(tp)).status_code == 403
    criar_usuario(cliente, token_master, "nada", permissoes=["agenda"])
    tn = login(cliente, "nada", "Definitiva2026")
    assert cliente.get("/api/clientes-opcoes", headers=auth(tn), params={"q": "joao"}).status_code == 403


# ------------------------------------------------------------------ documentos
def test_anexar_baixar_e_organizar_por_cliente_e_processo(cliente, token_master, cli, cfg, db):
    p = novo_processo(cliente, token_master, cli["id"])
    conteudo = b"%PDF-1.4 " + bytes(range(256)) * 400
    r = anexar(cliente, token_master, cli["id"], nome="Denúncia.pdf", conteudo=conteudo, processo_id=p["id"],
               descricao="Cópia da denúncia")
    assert r.status_code == 201, r.text
    d = r.json()
    assert d["tamanho"] == len(conteudo) and d["sha256"] == hashlib.sha256(conteudo).hexdigest()
    assert d["processo_rotulo"].startswith(cnj(1)) and d["enviado_por_nome"] == "Maria Advogada Teste"
    caminho = cfg.pasta_documentos / cli["id"] / p["id"] / f"{d['id']}.pdf"
    assert caminho.read_bytes() == conteudo
    assert not list((cfg.pasta_documentos / ".recebendo").iterdir())
    b = cliente.get(f"/api/documentos/{d['id']}/arquivo", headers=auth(token_master))
    assert b.status_code == 200 and b.content == conteudo
    assert "Den%C3%BAncia.pdf" in b.headers["content-disposition"]
    # Documento geral do cliente (sem processo)
    g = anexar(cliente, token_master, cli["id"], nome="RG.jpg", conteudo=b"\xff\xd8\xff imagem").json()
    assert (cfg.pasta_documentos / cli["id"] / "geral" / f"{g['id']}.jpg").exists()
    h = auth(token_master)
    assert cliente.get("/api/documentos", headers=h, params={"processo_id": p["id"]}).json()["total"] == 1
    assert cliente.get("/api/documentos", headers=h, params={"cliente_id": cli["id"]}).json()["total"] == 2
    assert cliente.get("/api/documentos", headers=h, params={"cliente_id": cli["id"], "somente_geral": True}
                       ).json()["total"] == 1
    # Vincular o documento geral ao processo move o arquivo para a pasta do processo
    r = cliente.patch(f"/api/documentos/{g['id']}", headers=h, json={"versao": g["versao"], "processo_id": p["id"],
                                                                      "nome_arquivo": "RG do cliente.jpg"})
    assert r.status_code == 200 and r.json()["nome_arquivo"] == "RG do cliente.jpg"
    assert (cfg.pasta_documentos / cli["id"] / p["id"] / f"{g['id']}.jpg").exists()
    assert not (cfg.pasta_documentos / cli["id"] / "geral" / f"{g['id']}.jpg").exists()
    r = cliente.patch(f"/api/documentos/{g['id']}", headers=h, json={"versao": r.json()["versao"],
                                                                      "nome_arquivo": "RG.exe"})
    assert r.status_code == 422


def test_arquivos_recusados(cliente, token_master, cli):
    for nome in ("virus.exe", "script.ps1", "atalho.lnk", "../../../etc/passwd.bat"):
        r = anexar(cliente, token_master, cli["id"], nome=nome)
        assert r.status_code == 422 and "não é aceito" in r.json()["detail"], nome
    assert anexar(cliente, token_master, cli["id"], conteudo=b"").status_code == 422
    outro = cliente.post("/api/clientes", headers=auth(token_master), json={"nome_completo": "Outra Pessoa"}).json()
    p = novo_processo(cliente, token_master, outro["id"])
    r = anexar(cliente, token_master, cli["id"], processo_id=p["id"])
    assert r.status_code == 422 and "não pertence a este cliente" in r.json()["detail"]
    # Nome com pastas: só o nome do arquivo é guardado
    r = anexar(cliente, token_master, cli["id"], nome="C:\\Users\\x\\..\\laudo.pdf")
    assert r.status_code == 201 and r.json()["nome_arquivo"] == "laudo.pdf"


def test_remocao_controlada_e_restauracao_pela_master(cliente, token_master, cli, cfg, db):
    criar_usuario(cliente, token_master, "docs", permissoes=["documentos"])
    td = login(cliente, "docs", "Definitiva2026")
    d = anexar(cliente, td, cli["id"], nome="contrato.docx").json()
    r = cliente.post(f"/api/documentos/{d['id']}/remover", headers=auth(td), json={"versao": d["versao"], "motivo": "x"})
    assert r.status_code == 422  # motivo obrigatório
    r = cliente.post(f"/api/documentos/{d['id']}/remover", headers=auth(td),
                     json={"versao": d["versao"], "motivo": "Enviado por engano"})
    assert r.status_code == 200 and r.json()["removido_por_nome"] == "Usuário docs"
    # Sai das listas e do download para os demais; o arquivo permanece guardado
    assert cliente.get("/api/documentos", headers=auth(td), params={"cliente_id": cli["id"]}).json()["total"] == 0
    assert cliente.get(f"/api/documentos/{d['id']}/arquivo", headers=auth(td)).status_code == 404
    assert cliente.get("/api/documentos", headers=auth(td), params={"removidos": True}).status_code == 403
    assert (cfg.pasta_documentos / cli["id"] / "geral" / f"{d['id']}.docx").exists()
    # A Master consulta os removidos e restaura
    rem = cliente.get("/api/documentos", headers=auth(token_master), params={"removidos": True}).json()
    assert rem["total"] == 1 and rem["itens"][0]["motivo_remocao"] == "Enviado por engano"
    v = rem["itens"][0]["versao"]
    assert cliente.post(f"/api/documentos/{d['id']}/restaurar", headers=auth(td), params={"versao": v}
                        ).status_code == 403
    r = cliente.post(f"/api/documentos/{d['id']}/restaurar", headers=auth(token_master), params={"versao": v})
    assert r.status_code == 200 and r.json()["removido_em"] is None
    acoes = db.scalars(select(Auditoria.acao).where(Auditoria.entidade_id == d["id"]).order_by(Auditoria.id)).all()
    assert acoes == ["documento.anexado", "documento.removido", "documento.restaurado"]


def test_banco_nao_apaga_documentos(cliente, token_master, cli, url_banco):
    d = anexar(cliente, token_master, cli["id"]).json()
    eng = create_engine(url_banco)
    with pytest.raises(DBAPIError, match="não pode ser apagado"):
        with eng.begin() as c:
            c.execute(text("DELETE FROM documentos WHERE id = :i"), {"i": d["id"]})
    eng.dispose()


def test_reenvio_do_mesmo_anexo_nao_duplica(cliente, token_master, cli, cfg, db):
    cab = auth(token_master) | {"Content-Type": "application/pdf", "Idempotency-Key": "anexo-teste-0001"}
    params = {"cliente_id": cli["id"], "nome": "laudo.pdf"}
    r1 = cliente.post("/api/documentos", headers=cab, params=params, content=b"%PDF laudo")
    r2 = cliente.post("/api/documentos", headers=cab, params=params, content=b"%PDF laudo")
    assert r1.status_code == r2.status_code == 201 and r1.json()["id"] == r2.json()["id"]
    assert len(db.scalars(select(Documento)).all()) == 1
    assert len(list((cfg.pasta_documentos / cli["id"] / "geral").iterdir())) == 1
    assert not list((cfg.pasta_documentos / ".recebendo").iterdir())


def test_arquivo_ausente_no_servidor_e_avisado(cliente, token_master, cli, cfg):
    d = anexar(cliente, token_master, cli["id"]).json()
    (cfg.pasta_documentos / cli["id"] / "geral" / f"{d['id']}.pdf").unlink()
    r = cliente.get(f"/api/documentos/{d['id']}/arquivo", headers=auth(token_master))
    assert r.status_code == 410 and "cópia de segurança" in r.json()["detail"]
