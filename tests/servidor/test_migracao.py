"""Assistente de migração do servidor: exportação no servidor antigo, importação num servidor novo
(outro banco PostgreSQL e outra pasta de dados), conferência de cada tabela e de cada documento,
relatório, código de confirmação e desativação do servidor antigo (nunca duas bases oficiais)."""

from __future__ import annotations

import time
import uuid
from contextlib import contextmanager
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

from advoga_server.api.deps import obter_cfg
from advoga_server.app import criar_app
from advoga_server.core.config import Configuracoes
from advoga_server.core.db import configurar_banco, obter_sessao
from advoga_server.core.migracoes import atualizar_banco
from advoga_server.services import migracao as svc
from advoga_server.services.servidor import limpar_cache_status, obter_identidade, preparar_codigo_instalacao
from tests.conftest import ADMIN, SENHA_MASTER, auth, criar_usuario, login
from tests.servidor.test_agenda import quando
from tests.servidor.test_financeiro import contrato, pagar
from tests.servidor.test_processos_documentos import anexar, novo_processo

SENHA_PACOTE = "Senha do pacote 2026!"


@pytest.fixture
def escritorio(cliente, token_master, master):
    h = auth(token_master)
    criar_usuario(cliente, token_master, "socia", permissoes=["clientes", "processos", "financeiro", "agenda",
                                                              "pendencias", "documentos"])
    cli = cliente.post("/api/clientes", headers=h, json={"nome_completo": "Cliente da Migração",
                                                         "cpf": "529.982.247-25"}).json()
    proc = novo_processo(cliente, token_master, cli["id"])
    doc = anexar(cliente, token_master, cli["id"], nome="procuracao.pdf", conteudo=b"%PDF-1.4 procuracao " * 80,
                 processo_id=proc["id"])
    assert doc.status_code == 201, doc.text
    ct = contrato(cliente, token_master, cli["id"])
    parcela = cliente.get("/api/financeiro/parcelas", headers=h, params={"contrato_id": ct["id"]}).json()["itens"][0]
    comp = cliente.post("/api/financeiro/comprovantes", headers=h | {"Content-Type": "image/png"},
                        params={"nome": "pix.png"}, content=b"\x89PNG comprovante migracao").json()
    p = pagar(cliente, token_master, parcela["id"], parcela["valor"], comprovante_id=comp["id"])
    assert p.status_code == 201, p.text
    r = cliente.post("/api/agenda/compromissos", headers=h, json={
        "titulo": "Audiência de instrução", "tipo": "audiencia", "inicio": quando(5), "cliente_id": cli["id"]})
    assert r.status_code == 201, r.text
    r = cliente.post("/api/agenda/compromissos", headers=h, json={
        "titulo": "Juntar documentos", "tipo": "tarefa", "inicio": quando(2), "pendencia": True})
    assert r.status_code == 201, r.text
    r = cliente.put("/api/backups/configuracao", headers=h, json={"ativo": False, "destino": "/mnt/hd-backup"})
    assert r.status_code == 200, r.text
    r = cliente.post("/api/backups/senha-copia", headers=h, json={"senha": "senha da copia 2026",
                                                                  "confirmacao": "senha da copia 2026"})
    assert r.status_code == 200
    return {"cliente": cli, "processo": proc, "documento": doc.json(), "contrato": ct}


def _simular_conta_google(db) -> None:
    db.execute(text("INSERT INTO configuracoes (chave, valor) VALUES ('email.servico', "
                    "'{\"tipo\": \"google\", \"refresh_token\": \"gAAAA-cifrado-com-a-chave-do-servidor\"}')"))
    db.commit()


def _esperar(cliente, token, situacoes=("exportada", "falhou"), timeout=60) -> dict:
    limite = time.monotonic() + timeout
    while time.monotonic() < limite:
        e = cliente.get("/api/migracao/estado", headers=auth(token)).json()
        ultima = e["historico"][0] if e["historico"] else None
        if ultima and ultima["situacao"] in situacoes:
            return e
        time.sleep(0.2)
    raise AssertionError("A exportação não terminou a tempo")


def _exportar(cliente, token, destino: Path, **extra) -> dict:
    corpo = {"destino": str(destino), "senha": SENHA_PACOTE, "confirmacao": SENHA_PACOTE,
             "senha_master": SENHA_MASTER} | extra
    r = cliente.post("/api/migracao/exportar", headers=auth(token), json=corpo)
    assert r.status_code == 202, r.text
    return _esperar(cliente, token)


@contextmanager
def servidor_novo(tmp_path: Path, url_banco: str):
    """Outro computador: banco PostgreSQL novo (só com a estrutura) e pasta de dados nova."""
    nome = f"advoga_novo_{uuid.uuid4().hex[:8]}"
    admin = create_engine(ADMIN, isolation_level="AUTOCOMMIT")
    with admin.connect() as c:
        c.execute(text(f'CREATE DATABASE "{nome}"'))
    url = make_url(url_banco).set(database=nome).render_as_string(hide_password=False)
    cfg = Configuracoes(pasta_dados=tmp_path / "computador-novo", database_url=url, servico_avisos=False,
                        servico_backups=False)
    cfg.garantir_pastas()
    atualizar_banco(url)
    try:
        app = criar_app(cfg)  # o banco global passa a ser o do servidor novo
        app.dependency_overrides[obter_cfg] = lambda: cfg
        limpar_cache_status()
        gen = obter_sessao()
        db = next(gen)
        obter_identidade(db)
        codigo = preparar_codigo_instalacao(db, cfg)
        db.close()
        with TestClient(app) as c:
            yield c, cfg, codigo, url
    finally:
        configurar_banco(url_banco)
        limpar_cache_status()
        with admin.connect() as c:
            c.execute(text(f'DROP DATABASE IF EXISTS "{nome}" WITH (FORCE)'))
        admin.dispose()


def _importar(c2, codigo, pacote, senha=SENHA_PACOTE, timeout=60) -> dict:
    r = c2.post("/api/setup/importar", json={"codigo_instalacao": codigo, "pacote": str(pacote), "senha": senha})
    assert r.status_code == 202, r.text
    limite = time.monotonic() + timeout
    while time.monotonic() < limite:
        a = c2.get("/api/setup/importacao", headers={"X-Codigo-Instalacao": codigo}).json()
        if a["situacao"] in ("sucesso", "falhou"):
            return a
        time.sleep(0.2)
    raise AssertionError("A importação não terminou a tempo")


def test_migracao_completa_para_outro_computador(cliente, token_master, escritorio, db, cfg, tmp_path, url_banco):
    h = auth(token_master)
    _simular_conta_google(db)
    id_antigo = cliente.get("/api/saude").json()["servidor_id"]
    totais_origem = cliente.get(f"/api/contratos/{escritorio['contrato']['id']}", headers=h).json()["totais"]
    contagens_origem = {t: db.execute(text(f'SELECT count(*) FROM "{t}"')).scalar_one()
                        for t in ("usuarios", "permissoes_usuario", "clientes", "processos", "documentos",
                                  "contratos", "parcelas", "pagamentos", "comprovantes", "compromissos",
                                  "configuracoes", "auditoria")}

    # Validações da exportação
    r = cliente.post("/api/migracao/exportar", headers=h, json={
        "destino": str(tmp_path / "pen"), "senha": SENHA_PACOTE, "confirmacao": SENHA_PACOTE,
        "senha_master": "senha errada 123"})
    assert r.status_code == 403 and "Senha da Master" in r.json()["detail"]
    r = cliente.post("/api/migracao/exportar", headers=h, json={
        "destino": "pen", "senha": SENHA_PACOTE, "confirmacao": SENHA_PACOTE, "senha_master": SENHA_MASTER})
    assert r.status_code == 422 and "caminho completo" in r.json()["detail"]
    r = cliente.post("/api/migracao/exportar", headers=h, json={
        "destino": str(tmp_path / "pen"), "senha": "curta", "confirmacao": "curta", "senha_master": SENHA_MASTER})
    assert r.status_code == 422

    estado = _exportar(cliente, token_master, tmp_path / "pen")
    atual = estado["atual"]
    assert atual["situacao"] == "exportada", atual["mensagem"]
    assert estado["servidor_status"] == "em_migracao"
    pacote = Path(atual["arquivo"])
    assert pacote.exists() and pacote.suffix == ".afmig" and pacote.parent == tmp_path / "pen"
    assert b"Cliente da Migra" not in pacote.read_bytes() and b"procuracao" not in pacote.read_bytes()
    assert {t["tabela"]: t["origem"] for t in atual["tabelas"]}["clientes"] == 1
    assert atual["arquivos_total"] == 2

    # Servidor antigo em migração: somente leitura (consulta e login continuam)
    r = cliente.post("/api/clientes", headers=h, json={"nome_completo": "Não pode gravar"})
    assert r.status_code == 423 and "somente leitura" in r.json()["detail"]
    assert cliente.get("/api/clientes", headers=h).status_code == 200
    t_socia = login(cliente, "socia", "Definitiva2026")
    assert cliente.post("/api/clientes", headers=auth(t_socia), json={"nome_completo": "X"}).status_code == 423
    r = cliente.post("/api/migracao/exportar", headers=h, json={
        "destino": str(tmp_path / "pen2"), "senha": SENHA_PACOTE, "confirmacao": SENHA_PACOTE,
        "senha_master": SENHA_MASTER})
    assert r.status_code == 409
    pdf_exp = cliente.get(f"/api/migracao/{atual['id']}/relatorio.pdf", headers=h)
    assert pdf_exp.status_code == 200 and pdf_exp.content.startswith(b"%PDF")

    with servidor_novo(tmp_path, url_banco) as (c2, cfg2, codigo, url2):
        assert c2.get("/api/setup/status").json()["configurado"] is False
        # Código de instalação errado, pacote inexistente, senha errada
        r = c2.post("/api/setup/importar", json={"codigo_instalacao": "AAAA-BBBB-CCCC", "pacote": str(pacote),
                                                 "senha": SENHA_PACOTE})
        assert r.status_code == 403
        r = c2.post("/api/setup/importar", json={"codigo_instalacao": codigo, "pacote": str(tmp_path / "x.afmig"),
                                                 "senha": SENHA_PACOTE})
        assert r.status_code == 422
        assert c2.get("/api/setup/importacao", headers={"X-Codigo-Instalacao": "ERRADO"}).status_code == 403
        a = _importar(c2, codigo, pacote, senha="outra senha qualquer")
        assert a["situacao"] == "falhou" and "Senha incorreta" in a["mensagem"]
        assert c2.get("/api/setup/status").json()["configurado"] is False

        # Importação correta
        a = _importar(c2, codigo, pacote)
        assert a["situacao"] == "sucesso", a["mensagem"]
        rel = a["relatorio"]
        assert all(t["conferida"] for t in rel["tabelas"]), rel["tabelas"]
        assert rel["arquivos_conferidos"] == 2
        assert any("conta de envio" in p for p in rel["pendencias"])
        assert any("senha da cópia" in p for p in rel["pendencias"])
        codigo_confirmacao = a["codigo_confirmacao"]
        assert len(codigo_confirmacao) == 14
        assert list((cfg2.pasta_dados / "migracoes").glob("relatorio_importacao_*.txt"))
        assert not cfg2.arquivo_codigo_instalacao.exists()

        # Servidor novo: identidade nova, ligado ao antigo, oficial
        s = c2.get("/api/saude").json()
        assert s["servidor_status"] == "ativo" and s["configurado"]
        assert s["servidor_id"] != id_antigo and s["migrado_de"] == id_antigo
        assert c2.post("/api/setup/importar", json={"codigo_instalacao": codigo, "pacote": str(pacote),
                                                    "senha": SENHA_PACOTE}).status_code == 409

        # Ninguém precisa recadastrar nada: mesmos usuários, senhas e permissões
        t2 = login(c2, "master", SENHA_MASTER)
        h2 = auth(t2)
        ts = login(c2, "socia", "Definitiva2026")
        eu = c2.get("/api/auth/eu", headers=auth(ts)).json()
        assert set(eu["permissoes"]) == {"clientes", "processos", "financeiro", "agenda", "pendencias", "documentos"}
        assert c2.get("/api/usuarios", headers=auth(ts)).status_code == 403
        clientes = c2.get("/api/clientes", headers=h2).json()["itens"]
        assert [c["nome_completo"] for c in clientes] == ["Cliente da Migração"]
        assert c2.get(f"/api/processos/{escritorio['processo']['id']}", headers=h2).status_code == 200
        b = c2.get(f"/api/documentos/{escritorio['documento']['id']}/arquivo", headers=h2)
        assert b.status_code == 200 and b.content == b"%PDF-1.4 procuracao " * 80
        ct = c2.get(f"/api/contratos/{escritorio['contrato']['id']}", headers=h2).json()
        assert ct["totais"] == totais_origem and float(ct["totais"]["recebido"]) > 0
        pags = c2.get("/api/financeiro/pagamentos", headers=h2).json()["itens"]
        assert len(pags) == 1 and pags[0]["comprovante_id"]
        cb = c2.get(f"/api/financeiro/comprovantes/{pags[0]['comprovante_id']}/arquivo", headers=h2)
        assert cb.status_code == 200 and cb.content == b"\x89PNG comprovante migracao"
        assert len(c2.get("/api/agenda/compromissos", headers=h2, params={
            "inicio": quando(-1), "fim": quando(30)}).json()) == 2
        assert len(c2.get("/api/pendencias", headers=h2).json()) >= 1
        eng2 = create_engine(url2)
        with eng2.connect() as c:
            for t, n in contagens_origem.items():
                novo = c.execute(text(f'SELECT count(*) FROM "{t}"')).scalar_one()
                if t == "configuracoes":
                    assert novo == n - 2  # conta Google e senha da cópia não são transferidas
                elif t == "auditoria":
                    assert novo > n  # histórico preservado (e acrescido do registro da migração)
                else:
                    assert novo == n, t
            chaves = {r[0] for r in c.execute(text("SELECT chave FROM configuracoes"))}
            assert "email.servico" not in chaves and "backups.chave" not in chaves and "backups.config" in chaves
            # Sessões do servidor antigo não valem no novo
            assert c.execute(text("SELECT count(*) FROM sessoes WHERE encerrada_em IS NULL")).scalar_one() == 2
        eng2.dispose()
        assert c2.get("/api/clientes", headers=h).status_code == 401
        est = c2.get("/api/backups/estado", headers=h2).json()
        assert est["configuracao"]["destino"] == "/mnt/hd-backup" and not est["configuracao"]["senha_copia_definida"]
        e2 = c2.get("/api/migracao/estado", headers=h2).json()
        assert e2["servidor_status"] == "ativo" and e2["migrado_de"] == id_antigo and e2["atual"] is None
        imp = next(m for m in e2["historico"] if m["tipo"] == "importacao")
        pdf = c2.get(f"/api/migracao/{imp['id']}/relatorio.pdf", headers=h2)
        assert pdf.status_code == 200 and pdf.content.startswith(b"%PDF")
        avisos = c2.get("/api/notificacoes/minhas", headers=h2).json()
        assert any("Migração" in n["titulo"] for n in (avisos["itens"] if isinstance(avisos, dict) else avisos))
        # O servidor novo grava normalmente
        assert c2.post("/api/clientes", headers=h2, json={"nome_completo": "Cliente Novo"}).status_code == 201

    # De volta ao servidor antigo: código errado e depois o correto -> desativado de vez
    r = cliente.post("/api/migracao/concluir", headers=h, json={"codigo": "AAAA-BBBB-CCCC",
                                                                "senha_master": SENHA_MASTER})
    assert r.status_code == 403 and "Código de confirmação" in r.json()["detail"]
    r = cliente.post("/api/migracao/concluir", headers=h, json={"codigo": codigo_confirmacao.lower().replace("-", ""),
                                                                "senha_master": SENHA_MASTER})
    assert r.status_code == 200, r.text
    assert r.json()["situacao"] == "concluida"
    s = cliente.get("/api/saude").json()
    assert s["servidor_status"] == "desativado"
    r = cliente.post("/api/auth/login", json={"nome_usuario": "master", "senha": SENHA_MASTER})
    assert r.status_code == 410 and "servidor novo" in r.json()["detail"]
    assert cliente.get("/api/clientes", headers=h).status_code == 410
    assert db.execute(text("SELECT count(*) FROM sessoes WHERE encerrada_em IS NULL")).scalar_one() == 0


def test_cancelar_e_falhas_da_exportacao(cliente, token_master, escritorio, db, cfg, tmp_path):
    h = auth(token_master)
    # Arquivo corrompido no servidor: a exportação falha e o servidor volta ao normal
    caminho = db.execute(text("SELECT caminho FROM documentos")).scalar_one()
    original = (cfg.pasta_documentos / caminho).read_bytes()
    (cfg.pasta_documentos / caminho).write_bytes(b"alterado")
    e = _exportar(cliente, token_master, tmp_path / "pen")
    ultima = e["historico"][0]
    assert ultima["situacao"] == "falhou" and "corrompido" in ultima["mensagem"]
    assert e["servidor_status"] == "ativo" and e["atual"] is None
    assert not list((tmp_path / "pen").glob("*.afmig*"))
    assert cliente.post("/api/clientes", headers=h, json={"nome_completo": "Grava de novo"}).status_code == 201
    (cfg.pasta_documentos / caminho).write_bytes(original)

    # Exporta e cancela: volta a ser o servidor oficial e o pacote é apagado
    e = _exportar(cliente, token_master, tmp_path / "pen")
    pacote = Path(e["atual"]["arquivo"])
    assert pacote.exists()
    assert cliente.post("/api/migracao/cancelar", headers=h, json={"senha_master": "errada"}).status_code == 403
    r = cliente.post("/api/migracao/cancelar", headers=h, json={"senha_master": SENHA_MASTER})
    assert r.status_code == 200 and r.json()["situacao"] == "cancelada"
    assert not pacote.exists()
    assert cliente.get("/api/saude").json()["servidor_status"] == "ativo"
    assert cliente.post("/api/clientes", headers=h, json={"nome_completo": "Depois do cancelamento"}).status_code == 201
    assert cliente.post("/api/migracao/concluir", headers=h, json={"codigo": "AAAA-BBBB-CCCC",
                                                                   "senha_master": SENHA_MASTER}).status_code == 409
    acoes = {r[0] for r in db.execute(text("SELECT acao FROM auditoria WHERE acao LIKE 'migracao.%'"))}
    assert {"migracao.exportacao_iniciada", "migracao.exportacao_falhou", "migracao.exportada",
            "migracao.cancelada", "migracao.senha_incorreta"} <= acoes


def test_importacao_com_falha_na_conferencia_deixa_o_servidor_vazio(cliente, token_master, escritorio, tmp_path,
                                                                     url_banco, monkeypatch):
    e = _exportar(cliente, token_master, tmp_path / "pen")
    pacote = Path(e["atual"]["arquivo"])
    cliente.post("/api/migracao/cancelar", headers=auth(token_master), json={"senha_master": SENHA_MASTER})
    assert not pacote.exists()
    e = _exportar(cliente, token_master, tmp_path / "pen")
    pacote = Path(e["atual"]["arquivo"])
    original = svc._conferir_tabelas

    def adulterado(url, manifesto):
        linhas = original(url, manifesto)
        linhas[2]["conferida"] = False
        return linhas

    monkeypatch.setattr(svc, "_conferir_tabelas", adulterado)
    with servidor_novo(tmp_path, url_banco) as (c2, cfg2, codigo, url2):
        a = _importar(c2, codigo, pacote)
        assert a["situacao"] == "falhou" and "conferência do banco falhou" in a["mensagem"]
        assert "continua vazio" in a["mensagem"]
        # O banco novo voltou a ficar vazio e o mesmo código de instalação continua valendo
        assert c2.get("/api/setup/status").json()["configurado"] is False
        eng = create_engine(url2)
        with eng.connect() as c:
            assert c.execute(text("SELECT count(*) FROM clientes")).scalar_one() == 0
        eng.dispose()
        monkeypatch.setattr(svc, "_conferir_tabelas", original)
        a = _importar(c2, codigo, pacote)
        assert a["situacao"] == "sucesso", a["mensagem"]
        # Um arquivo que não é pacote de migração é recusado
        falso = tmp_path / "falso.afmig"
        falso.write_bytes(b"nao e um pacote")
        with pytest.raises(Exception):
            svc.importar(cfg2, falso, SENHA_PACOTE, aviso=lambda _t: None)


def test_somente_master_e_servicos_parados(cliente, token_master, escritorio, db, cfg, tmp_path):
    t = login(cliente, "socia", "Definitiva2026")
    for metodo, rota in [("get", "/api/migracao/estado"), ("post", "/api/migracao/cancelar")]:
        r = getattr(cliente, metodo)(rota, headers=auth(t), **({"json": {"senha_master": "x"}} if metodo == "post"
                                                                 else {}))
        assert r.status_code == 403
    # Em migração, o servidor não faz backups nem envia avisos (o servidor novo fará)
    from advoga_server.services.servico_avisos import ServicoAvisos
    from advoga_server.services.servico_backups import ServicoBackups

    _exportar(cliente, token_master, tmp_path / "pen")
    assert ServicoBackups(cfg).executar_uma_vez() is None
    assert ServicoAvisos(60, cfg).executar_uma_vez() is None
