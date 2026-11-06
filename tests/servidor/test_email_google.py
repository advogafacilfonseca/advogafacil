"""Conta oficial de envio pelo Google (OAuth 2.0), com o Google simulado."""

from __future__ import annotations

import base64
import json
from urllib.parse import parse_qs, urlparse

import httpx
import pytest

from advoga_server.services import email_google
from advoga_server.services import notificacoes as svc_notif
from advoga_server.services.email import ErroEnvio, Mensagem
from tests.conftest import auth, criar_usuario, login

REDIRECT = "http://127.0.0.1:53123/"


class GoogleFalso:
    def __init__(self) -> None:
        self.enviados: list[dict] = []
        self.refresh_valido = True
        self.envio_status = 200
        self.trocas = 0

    def __call__(self, req: httpx.Request) -> httpx.Response:
        url = str(req.url)
        if url == email_google.URL_TOKEN:
            dados = parse_qs(req.content.decode())
            if dados["grant_type"] == ["authorization_code"]:
                assert dados["code_verifier"][0] and dados["redirect_uri"] == [REDIRECT]
                if dados["code"] == ["codigo-ruim"]:
                    return httpx.Response(400, json={"error": "invalid_grant", "error_description": "Bad Request"})
                self.trocas += 1
                return httpx.Response(200, json={"access_token": "acesso-1", "expires_in": 3600,
                                                 "refresh_token": "renovacao-secreta", "scope": email_google.ESCOPO})
            if not self.refresh_valido:
                return httpx.Response(400, json={"error": "invalid_grant", "error_description": "Token has been revoked."})
            return httpx.Response(200, json={"access_token": "acesso-2", "expires_in": 3600})
        if url == email_google.URL_PERFIL:
            return httpx.Response(200, json={"emailAddress": "notificacoes@escritorio-teste.com.br"})
        if url == email_google.URL_ENVIO:
            if self.envio_status != 200:
                return httpx.Response(self.envio_status, json={"error": {"message": "Falha simulada"}})
            corpo = json.loads(req.content)
            self.enviados.append({"auth": req.headers["Authorization"],
                                  "mime": base64.urlsafe_b64decode(corpo["raw"]).decode()})
            return httpx.Response(200, json={"id": "abc"})
        return httpx.Response(404)


@pytest.fixture
def google(monkeypatch):
    falso = GoogleFalso()
    monkeypatch.setattr(email_google, "transporte", httpx.MockTransport(falso))
    email_google._tokens.clear()
    return falso


def conectar(cliente, token):
    r = cliente.post("/api/email/google/iniciar", headers=auth(token), json={
        "client_id": "1234567890-abc.apps.googleusercontent.com", "client_secret": "segredo-do-cliente",
        "redirect_uri": REDIRECT})
    assert r.status_code == 200, r.text
    q = parse_qs(urlparse(r.json()["url"]).query)
    assert q["scope"] == [email_google.ESCOPO] and q["code_challenge_method"] == ["S256"]
    assert q["access_type"] == ["offline"] and q["redirect_uri"] == [REDIRECT]
    return r.json()["state"]


def test_conectar_conta_google_e_testar(cliente, token_master, master, google, db, cfg):
    assert cliente.get("/api/email/estado", headers=auth(token_master)).json()["configurado"] is False
    state = conectar(cliente, token_master)
    r = cliente.post("/api/email/google/concluir", headers=auth(token_master), json={"state": "x" * 20, "code": "abcdef"})
    assert r.status_code == 422 and "expirada" in r.json()["detail"]
    r = cliente.post("/api/email/google/concluir", headers=auth(token_master), json={"state": state, "code": "abcdef"})
    assert r.status_code == 200, r.text
    e = r.json()
    assert e["configurado"] and e["remetente"] == "notificacoes@escritorio-teste.com.br" and not e["precisa_reconectar"]
    # O state só vale uma vez
    r = cliente.post("/api/email/google/concluir", headers=auth(token_master), json={"state": state, "code": "abcdef"})
    assert r.status_code == 422
    # Segredos criptografados no banco
    from advoga_server.models import Configuracao
    db.expire_all()
    valor = db.get(Configuracao, email_google.CHAVE).valor
    assert "renovacao-secreta" not in json.dumps(valor) and "segredo-do-cliente" not in json.dumps(valor)
    # Teste de envio para o e-mail da Master
    r = cliente.post("/api/email/testar", headers=auth(token_master), json={})
    assert r.status_code == 200 and r.json()["enviado_para"] == master["email"]
    mime = google.enviados[0]["mime"]
    assert f"To: {master['email']}" in mime and "Teste de envio" in mime
    assert "notificacoes@escritorio-teste.com.br" in mime and google.enviados[0]["auth"] == "Bearer acesso-2"
    # Somente a Master
    criar_usuario(cliente, token_master, "outra", permissoes=["notificacoes", "configuracoes"])
    t = login(cliente, "outra", "Definitiva2026")
    assert cliente.get("/api/email/estado", headers=auth(t)).status_code == 403
    assert cliente.post("/api/email/google/iniciar", headers=auth(t), json={
        "client_id": "1234567890-abc", "client_secret": "segredo", "redirect_uri": REDIRECT}).status_code == 403


def test_codigo_recusado_e_redirect_invalido(cliente, token_master, google):
    r = cliente.post("/api/email/google/iniciar", headers=auth(token_master), json={
        "client_id": "1234567890-abc", "client_secret": "segredo", "redirect_uri": "https://site-externo.com/cb"})
    assert r.status_code == 422
    state = conectar(cliente, token_master)
    r = cliente.post("/api/email/google/concluir", headers=auth(token_master),
                     json={"state": state, "code": "codigo-ruim"})
    assert r.status_code == 422 and "recusou" in r.json()["detail"]
    assert cliente.get("/api/email/estado", headers=auth(token_master)).json()["configurado"] is False


def test_falhas_do_google_e_avisos_enviados_pelo_ciclo(cliente, token_master, master, google, db, cfg):
    state = conectar(cliente, token_master)
    cliente.post("/api/email/google/concluir", headers=auth(token_master), json={"state": state, "code": "abcdef"})
    enviador = email_google.obter(db, cfg)
    assert enviador is not None
    # Indisponível: temporária; recusa: definitiva
    google.envio_status = 503
    with pytest.raises(ErroEnvio) as e:
        enviador.enviar(Mensagem("a@b.com", "x", "y"))
    assert e.value.temporaria
    google.envio_status = 400
    with pytest.raises(ErroEnvio) as e:
        enviador.enviar(Mensagem("a@b.com", "x", "y"))
    assert not e.value.temporaria
    # Autorização revogada: definitiva, com orientação
    google.envio_status = 200
    google.refresh_valido = False
    email_google._tokens.clear()
    with pytest.raises(ErroEnvio) as e:
        enviador.enviar(Mensagem("a@b.com", "x", "y"))
    assert not e.value.temporaria and "conectar a conta de novo" in e.value.mensagem
    r = cliente.post("/api/email/testar", headers=auth(token_master), json={})
    assert r.status_code == 502 and "teste falhou" in r.json()["detail"]
    # O ciclo usa a conta configurada
    google.refresh_valido = True
    email_google._tokens.clear()
    from datetime import UTC, datetime, time
    from tests.servidor.test_agenda import novo, quando
    atual = cliente.get("/api/notificacoes/configuracao", headers=auth(token_master)).json()
    cats = [{"categoria": c["categoria"], "usuarios_ids": [master["id"]] if c["categoria"] == "reunioes" else [],
             "incluir_responsavel": False} for c in atual["categorias"]]
    cliente.put("/api/notificacoes/configuracao", headers=auth(token_master),
                json={"categorias": cats, "email_ativo": True, "hora_inicio": "07:00"})
    novo(cliente, token_master, titulo="Reunião", tipo="reuniao", inicio=quando(1, 10))
    meio_dia = datetime.combine(datetime.now(UTC).astimezone().date(), time(12)).astimezone()
    r = svc_notif.executar_ciclo(db, agora=meio_dia, cfg=cfg)
    assert r.enviadas == 1
    assert "AMANHÃ TEM REUNIÃO" in google.enviados[-1]["mime"]


def test_migracao_exige_nova_conexao_e_desconectar(cliente, token_master, google, db, cfg):
    state = conectar(cliente, token_master)
    cliente.post("/api/email/google/concluir", headers=auth(token_master), json={"state": state, "code": "abcdef"})
    # Outro servidor (sem a chave deste): o token não pode ser usado
    (cfg.pasta_config / "segredos.chave").rename(cfg.pasta_config / "chave-antiga")
    e = cliente.get("/api/email/estado", headers=auth(token_master)).json()
    assert e["configurado"] and e["precisa_reconectar"] and "conectada de novo" in e["mensagem"]
    assert email_google.obter(db, cfg) is None
    r = cliente.post("/api/email/desconectar", headers=auth(token_master))
    assert r.status_code == 200 and r.json()["configurado"] is False
    hist = cliente.get("/api/auditoria", headers=auth(token_master)).json()["itens"]
    acoes = [h["acao"] for h in hist]
    assert "email.conectado" in acoes and "email.desconectado" in acoes
