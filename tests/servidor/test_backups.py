"""Central de Backups: backup real (pg_dump + documentos), integridade, retenção, cópia criptografada,
teste de restauração, restauração em "outro computador", alertas e agendamento."""

from __future__ import annotations

import json
import time
import uuid
from datetime import timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

from advoga_server.api.deps import obter_cfg
from advoga_server.app import criar_app
from advoga_server.core.config import Configuracoes
from advoga_server.services import backup as svc
from advoga_server.services.arquivo_cifrado import ArquivoInvalido
from tests.conftest import ADMIN, SENHA_MASTER, auth, criar_usuario, login
from tests.servidor.test_processos_documentos import anexar

SENHA_COPIA = "Senha da copia 2026!"


def configurar(cliente, token, destino: Path, **extra) -> dict:
    corpo = {"ativo": True, "destino": str(destino), "intervalo_horas": 4, "hora_completo": "23:00",
             "reter_dias": 60, "teste_restauracao_dias": 7} | extra
    r = cliente.put("/api/backups/configuracao", headers=auth(token), json=corpo)
    assert r.status_code == 200, r.text
    return r.json()


@pytest.fixture
def escritorio(cliente, token_master):
    h = auth(token_master)
    cli = cliente.post("/api/clientes", headers=h, json={"nome_completo": "Cliente Backup"}).json()
    d1 = anexar(cliente, token_master, cli["id"], nome="procuracao.pdf", conteudo=b"%PDF-1.4 procuracao " * 50)
    assert d1.status_code == 201, d1.text
    r = cliente.post("/api/financeiro/comprovantes", headers=h | {"Content-Type": "image/png"},
                     params={"nome": "pix.png"}, content=b"\x89PNG comprovante de teste")
    assert r.status_code == 201
    return {"cliente": cli, "documento": d1.json(), "comprovante": r.json()}


def test_backup_completo_rapido_e_teste_de_restauracao(cliente, token_master, escritorio, db, cfg, tmp_path):
    hd = tmp_path / "hd-externo" / "Backups"
    configurar(cliente, token_master, hd)
    e = svc.executar(db, cfg, "completo", "manual")
    assert e.situacao == "sucesso", e.mensagem
    raiz = hd / svc.RAIZ
    versao = raiz / "versoes" / e.versao
    manifesto = json.loads((versao / "manifesto.json").read_text(encoding="utf-8"))
    assert manifesto["banco"]["contagens"]["clientes"] == 1 and len(manifesto["documentos"]) == 2
    assert (raiz / "LEIA-ME.txt").exists() and (versao / "banco.dump").stat().st_size > 1000
    for a in manifesto["documentos"]:
        assert svc._sha256_arquivo(raiz / "documentos" / a["caminho"]) == a["sha256"]
    assert any(a["caminho"].startswith("_financeiro/") for a in manifesto["documentos"])
    assert e.arquivos_novos == 2 and "Integridade conferida" in e.mensagem
    # Rápido: nada novo para copiar; depois de um novo documento, só ele é copiado
    e2 = svc.executar(db, cfg, "rapido", "manual")
    assert e2.situacao == "sucesso" and e2.arquivos_novos == 0
    anexar(cliente, token_master, escritorio["cliente"]["id"], nome="sentenca.pdf", conteudo=b"%PDF-1.4 sentenca")
    e3 = svc.executar(db, cfg, "rapido", "manual")
    assert e3.arquivos_novos == 1 and e3.arquivos_total == 3
    # Teste de restauração: banco temporário restaurado, contagens iguais, e apagado no fim
    t = svc.testar_restauracao(db, cfg, "manual")
    assert t.situacao == "sucesso", t.mensagem
    assert t.versao == e3.versao and "3 arquivo(s) conferidos" in t.mensagem
    eng = create_engine(ADMIN)
    with eng.connect() as c:
        restos = c.execute(text("SELECT count(*) FROM pg_database WHERE datname LIKE 'advoga_teste_restauracao_%'"))
        assert restos.scalar_one() == 0
    eng.dispose()
    # Estado e histórico pela API
    est = cliente.get("/api/backups/estado", headers=auth(token_master)).json()
    assert est["ultimo_completo"]["versao"] == e.versao and est["ultimo_teste"]["situacao"] == "sucesso"
    assert est["destino"]["disponivel"] and not any("falhou" in a for a in est["alertas"])
    hist = cliente.get("/api/backups/historico", headers=auth(token_master)).json()
    assert [h["tipo"] for h in hist] == ["teste_restauracao", "rapido", "rapido", "completo"]


def test_documento_corrompido_no_servidor_e_detectado(cliente, token_master, escritorio, db, cfg, tmp_path):
    configurar(cliente, token_master, tmp_path / "hd")
    assert svc.executar(db, cfg, "completo").situacao == "sucesso"
    original = cfg.pasta_documentos / escritorio["documento"]["id"]  # caminho real vem do banco
    caminho = db.execute(text("SELECT caminho FROM documentos")).scalar_one()
    original = cfg.pasta_documentos / caminho
    original.write_bytes(b"conteudo alterado por defeito no disco")
    e = svc.executar(db, cfg, "completo")
    assert e.situacao == "falhou" and "corrompido no servidor" in e.mensagem
    # A cópia boa continua no backup e a Master recebe o alerta
    copia = tmp_path / "hd" / svc.RAIZ / "documentos" / caminho
    assert copia.read_bytes().startswith(b"%PDF-1.4 procuracao")
    avisos = cliente.get("/api/notificacoes/minhas", headers=auth(token_master)).json()["itens"]
    assert any(a["titulo"] == "FALHA NO BACKUP COMPLETO" and a["categoria"] == "backups" for a in avisos)


def test_hd_desconectado_sem_espaco_e_alertas(cliente, token_master, escritorio, db, cfg, tmp_path, monkeypatch):
    configurar(cliente, token_master, tmp_path / "hd")
    monkeypatch.setattr(svc, "_raiz_unidade", lambda p: tmp_path / "unidade-E-desconectada")
    e = svc.executar(db, cfg, "completo")
    assert e.situacao == "falhou" and "HD externo desconectado" in e.mensagem
    est = svc.estado(db, cfg)
    assert any("HD externo desconectado" in a for a in est.alertas) and not est.destino.disponivel
    svc.verificar_destino_periodicamente(db)
    svc.verificar_destino_periodicamente(db)  # não duplica o aviso do dia
    avisos = cliente.get("/api/notificacoes/minhas", headers=auth(token_master)).json()["itens"]
    assert [a["titulo"] for a in avisos].count("HD DE BACKUP DESCONECTADO") == 1
    assert any(a["titulo"] == "FALHA NO BACKUP COMPLETO" for a in avisos)
    # Quem não é Master não recebe nem vê avisos de backup
    criar_usuario(cliente, token_master, "socia", permissoes=["agenda", "notificacoes", "financeiro"])
    t = login(cliente, "socia", "Definitiva2026")
    assert cliente.get("/api/notificacoes/minhas", headers=auth(t)).json()["itens"] == []
    monkeypatch.undo()
    # Sem espaço
    import shutil
    from collections import namedtuple

    Uso = namedtuple("Uso", "total used free")
    monkeypatch.setattr(shutil, "disk_usage", lambda p: Uso(10**9, 10**9 - 10**6, 10**6))
    e = svc.executar(db, cfg, "rapido")
    assert e.situacao == "falhou" and "Sem espaço" in e.mensagem


def test_copia_criptografada_e_restauracao_em_outro_computador(cliente, token_master, master, escritorio, db, cfg,
                                                               tmp_path, url_banco):
    h = auth(token_master)
    r = cliente.put("/api/backups/configuracao", headers=h, json={
        "ativo": True, "destino": str(tmp_path / "hd"), "copia_secundaria_ativa": True,
        "destino_secundario": str(tmp_path / "nuvem")})
    assert r.status_code == 422 and "senha" in r.json()["detail"]
    r = cliente.post("/api/backups/senha-copia", headers=h, json={"senha": "curta", "confirmacao": "curta"})
    assert r.status_code == 422
    r = cliente.post("/api/backups/senha-copia", headers=h, json={"senha": SENHA_COPIA, "confirmacao": SENHA_COPIA})
    assert r.status_code == 200
    conf = configurar(cliente, token_master, tmp_path / "hd", copia_secundaria_ativa=True,
                      destino_secundario=str(tmp_path / "nuvem"), reter_copias_secundarias=1)
    assert conf["senha_copia_definida"]
    # A senha não fica guardada
    valor = db.execute(text("SELECT valor::text FROM configuracoes WHERE chave = 'backups.chave'")).scalar_one()
    assert SENHA_COPIA not in valor
    e = svc.executar(db, cfg, "completo")
    assert e.situacao == "sucesso", e.mensagem
    assert e.copia_secundaria.startswith("Gravada e conferida")
    copias = list((tmp_path / "nuvem").glob("*.afbk"))
    assert len(copias) == 1
    conteudo = copias[0].read_bytes()
    assert b"Cliente Backup" not in conteudo and b"procuracao" not in conteudo
    # Senha errada, arquivo alterado e arquivo cortado são recusados
    with pytest.raises(ArquivoInvalido, match="Senha incorreta"):
        svc.verificar_copia_cifrada(copias[0], senha="senha errada 123")
    alterado = tmp_path / "alterado.afbk"
    dados = bytearray(conteudo)
    dados[len(dados) // 2] ^= 0xFF
    alterado.write_bytes(bytes(dados))
    with pytest.raises((ArquivoInvalido, svc.FalhaBackup)):
        svc.verificar_copia_cifrada(alterado, senha=SENHA_COPIA)
    cortado = tmp_path / "cortado.afbk"
    cortado.write_bytes(conteudo[:-40])
    with pytest.raises(ArquivoInvalido, match="incompleta|danificada"):
        svc.verificar_copia_cifrada(cortado, senha=SENHA_COPIA)
    # Retenção da cópia: fica só a mais recente
    time.sleep(1.1)
    assert svc.executar(db, cfg, "completo").situacao == "sucesso"
    assert len(list((tmp_path / "nuvem").glob("*.afbk"))) == 1

    # "Outro computador": banco novo e vazio, pasta de dados nova; restaura da cópia criptografada
    nome = f"advoga_restaurado_{uuid.uuid4().hex[:8]}"
    admin = create_engine(ADMIN, isolation_level="AUTOCOMMIT")
    with admin.connect() as c:
        c.execute(text(f'CREATE DATABASE "{nome}"'))
    url_novo = make_url(url_banco).set(database=nome).render_as_string(hide_password=False)
    novo_cfg = Configuracoes(pasta_dados=tmp_path / "outro-computador", database_url=url_novo,
                             servico_avisos=False, servico_backups=False)
    novo_cfg.garantir_pastas()
    try:
        copia = next((tmp_path / "nuvem").glob("*.afbk"))
        with pytest.raises(ArquivoInvalido):
            svc.restaurar(novo_cfg, copia, url_novo, senha="errada errada", aviso=lambda m: None)
        r = svc.restaurar(novo_cfg, copia, url_novo, senha=SENHA_COPIA, aviso=lambda m: None)
        assert r["arquivos"] == 2 and r["registros"] > 0
        caminho = db.execute(text("SELECT caminho FROM documentos")).scalar_one()
        assert (novo_cfg.pasta_documentos / caminho).read_bytes().startswith(b"%PDF-1.4 procuracao")
        # Banco que já tem dados: recusado
        with pytest.raises(svc.FalhaBackup, match="não está vazio"):
            svc.restaurar(novo_cfg, tmp_path / "hd", url_novo, aviso=lambda m: None)
        # O sistema restaurado funciona: a Master entra e vê o cliente e o documento
        app2 = criar_app(novo_cfg)
        app2.dependency_overrides[obter_cfg] = lambda: novo_cfg
        with TestClient(app2) as c2:
            r = c2.post("/api/auth/login", json={"nome_usuario": "master", "senha": SENHA_MASTER})
            assert r.status_code == 200, r.text
            t2 = r.json()["token"]
            assert c2.get("/api/clientes", headers=auth(t2)).json()["itens"][0]["nome_completo"] == "Cliente Backup"
            doc_id = escritorio["documento"]["id"]
            b = c2.get(f"/api/documentos/{doc_id}/arquivo", headers=auth(t2))
            assert b.status_code == 200 and b.content.startswith(b"%PDF-1.4 procuracao")
            # Por segurança, a senha da cópia não vale no outro computador (chave do servidor diferente)
            est = c2.get("/api/backups/estado", headers=auth(t2)).json()
            assert est["configuracao"]["destino"] == str(tmp_path / "hd")
        from advoga_server.core.db import configurar_banco
        configurar_banco(url_banco)
    finally:
        with admin.connect() as c:
            c.execute(text(f'DROP DATABASE IF EXISTS "{nome}" WITH (FORCE)'))
        admin.dispose()


def test_restaurar_da_pasta_do_hd(cliente, token_master, escritorio, db, cfg, tmp_path, url_banco):
    configurar(cliente, token_master, tmp_path / "hd")
    assert svc.executar(db, cfg, "completo").situacao == "sucesso"
    nome = f"advoga_restaurado_{uuid.uuid4().hex[:8]}"
    admin = create_engine(ADMIN, isolation_level="AUTOCOMMIT")
    with admin.connect() as c:
        c.execute(text(f'CREATE DATABASE "{nome}"'))
    url_novo = make_url(url_banco).set(database=nome).render_as_string(hide_password=False)
    novo_cfg = Configuracoes(pasta_dados=tmp_path / "pc2", database_url=url_novo)
    novo_cfg.garantir_pastas()
    # Servidor recém-instalado no outro computador: estrutura criada, sem Master e sem dados
    from advoga_server.core.migracoes import atualizar_banco

    atualizar_banco(url_novo)
    eng = create_engine(url_novo)
    with eng.begin() as c:
        c.execute(text("INSERT INTO identidade_servidor (id, servidor_id, status) VALUES (1, gen_random_uuid(), 'ativo')"))
    eng.dispose()
    try:
        # Backup danificado no HD: a restauração recusa antes de mexer em qualquer coisa
        doc = next(p for p in (tmp_path / "hd" / svc.RAIZ / "documentos").rglob("*.pdf"))
        bom = doc.read_bytes()
        doc.write_bytes(b"danificado")
        with pytest.raises(svc.FalhaBackup, match="danificado"):
            svc.restaurar(novo_cfg, tmp_path / "hd", url_novo, aviso=lambda m: None)
        doc.write_bytes(bom)
        r = svc.restaurar(novo_cfg, tmp_path / "hd", url_novo, aviso=lambda m: None)
        assert r["arquivos"] == 2
        eng = create_engine(url_novo)
        with eng.connect() as c:
            assert c.execute(text("SELECT nome_completo FROM clientes")).scalar_one() == "Cliente Backup"
            sid = c.execute(text("SELECT servidor_id::text FROM identidade_servidor")).scalar_one()
        eng.dispose()
        assert sid == r["servidor_id"]
    finally:
        with admin.connect() as c:
            c.execute(text(f'DROP DATABASE IF EXISTS "{nome}" WITH (FORCE)'))
        admin.dispose()


def test_retencao(cliente, token_master, escritorio, db, cfg, tmp_path):
    configurar(cliente, token_master, tmp_path / "hd", reter_dias=7)
    raiz = tmp_path / "hd" / svc.RAIZ
    antigas = ["2020-01-01_230000_completo", "2020-01-02_230000_completo", "2020-01-03_100000_rapido",
               "2020-01-04_230000_completo", "2020-01-05_230000_completo"]
    for v in antigas:
        (raiz / "versoes" / v).mkdir(parents=True)
    (raiz / "versoes" / "pasta-da-pessoa").mkdir()
    e = svc.executar(db, cfg, "completo")
    restantes = sorted(p.name for p in (raiz / "versoes").iterdir())
    # Fica: os 3 completos mais recentes (o novo + 2 antigos) e pastas que não são do sistema
    assert restantes == ["2020-01-04_230000_completo", "2020-01-05_230000_completo", e.versao, "pasta-da-pessoa"]


def test_api_somente_master_e_validacoes(cliente, token_master, escritorio, tmp_path):
    criar_usuario(cliente, token_master, "admin", permissoes=["admin_usuarios", "configuracoes", "financeiro"])
    t = login(cliente, "admin", "Definitiva2026")
    for metodo, rota in [("get", "/api/backups/estado"), ("get", "/api/backups/historico"),
                         ("post", "/api/backups/testar-restauracao")]:
        assert getattr(cliente, metodo)(rota, headers=auth(t)).status_code == 403
    assert cliente.post("/api/backups/executar", headers=auth(t), json={"tipo": "completo"}).status_code == 403
    h = auth(token_master)
    r = cliente.put("/api/backups/configuracao", headers=h, json={"ativo": True, "destino": "Backups"})
    assert r.status_code == 422 and "caminho completo" in r.json()["detail"]
    r = cliente.put("/api/backups/configuracao", headers=h, json={"ativo": True})
    assert r.status_code == 422
    assert cliente.post("/api/backups/executar", headers=h, json={"tipo": "completo"}).status_code == 422
    v = cliente.get("/api/backups/verificar-destino", headers=h, params={"caminho": str(tmp_path)}).json()
    assert v["disponivel"] and "livres" in v["mensagem"]
    # Backup pela API (em segundo plano)
    configurar(cliente, token_master, tmp_path / "hd")
    r = cliente.post("/api/backups/executar", headers=h, json={"tipo": "completo"})
    assert r.status_code == 202
    for _ in range(200):
        est = cliente.get("/api/backups/estado", headers=h).json()
        if est["em_andamento"] is None and est["ultimo_sucesso"]:
            break
        time.sleep(0.1)
    assert est["ultimo_completo"] is not None, est
    hist = cliente.get("/api/backups/historico", headers=h).json()
    assert hist[0]["origem"] == "manual" and hist[0]["iniciado_por_nome"] == "Maria Advogada Teste"
    acoes = [a["acao"] for a in cliente.get("/api/auditoria", headers=h).json()["itens"]]
    assert "backups.configurados" in acoes and "backups.executar" in acoes


def test_agendamento(cliente, token_master, escritorio, db, cfg, tmp_path):
    assert svc.tarefa_devida(db) is None  # desligado
    configurar(cliente, token_master, tmp_path / "hd", intervalo_horas=4, teste_restauracao_dias=7)
    assert svc.tarefa_devida(db) == "completo"
    assert svc.executar(db, cfg, "completo").situacao == "sucesso"
    assert svc.tarefa_devida(db) == "teste_restauracao"
    assert svc.testar_restauracao(db, cfg).situacao == "sucesso"
    assert svc.tarefa_devida(db) is None
    daqui_5h = svc.agora() + timedelta(hours=5)
    assert svc.tarefa_devida(db, daqui_5h) in ("rapido", "completo")
    amanha = svc.agora() + timedelta(days=1, hours=1)
    assert svc.tarefa_devida(db, amanha) == "completo"
    # Serviço em segundo plano executa o que está devido
    from advoga_server.services.servico_backups import ServicoBackups

    assert ServicoBackups(cfg).executar_uma_vez() in (None, "rapido", "completo")
