"""Envio pela conta Google oficial do escritório (Gmail ou Google Workspace), com OAuth 2.0.

- A Master autoriza uma vez, pelo navegador, na tela de login do próprio Google. O sistema nunca
  vê a senha da conta. Só é pedida a permissão de ENVIAR e-mails (gmail.send): o sistema não lê
  a caixa de entrada.
- O token de acesso fica no banco criptografado com a chave deste servidor (core/cofre.py).
- A troca do código pelo token acontece no servidor, que é quem envia os avisos.
"""

from __future__ import annotations

import base64
import hashlib
import secrets
import threading
import time as relogio
import uuid
from datetime import UTC, datetime, timedelta
from email.message import EmailMessage
from urllib.parse import urlencode

import httpx
from fastapi import HTTPException
from sqlalchemy.orm import Session

from advoga_shared.esquemas import AutorizacaoGoogle, ConcluirGoogle, EstadoEmail, IniciarGoogle

from ..core.cofre import SegredoIndisponivel, cifrar, decifrar
from ..core.config import Configuracoes
from ..models import Configuracao, Usuario
from . import auditoria
from .email import ErroEnvio, Mensagem
from .servidor import obter_identidade

URL_AUTORIZACAO = "https://accounts.google.com/o/oauth2/v2/auth"
URL_TOKEN = "https://oauth2.googleapis.com/token"
URL_PERFIL = "https://gmail.googleapis.com/gmail/v1/users/me/profile"
URL_ENVIO = "https://gmail.googleapis.com/gmail/v1/users/me/messages/send"
ESCOPO = "https://www.googleapis.com/auth/gmail.send"
CHAVE = "email.servico"
VALIDADE_PEDIDO = timedelta(minutes=15)

# Para testes: transporte HTTP substituível (httpx.MockTransport).
transporte: httpx.BaseTransport | None = None

_pedidos: dict[str, dict] = {}  # state -> dados do pedido de autorização em andamento
_trava = threading.Lock()
_tokens: dict[str, tuple[str, float]] = {}  # refresh_token (hash) -> (access_token, expira_em)


def _cliente_http() -> httpx.Client:
    return httpx.Client(timeout=30, transport=transporte)


def _agora() -> datetime:
    return datetime.now(UTC)


# ============================================================================ autorização
def iniciar(dados: IniciarGoogle, ator: Usuario) -> AutorizacaoGoogle:
    verificador = secrets.token_urlsafe(64)
    desafio = base64.urlsafe_b64encode(hashlib.sha256(verificador.encode()).digest()).decode().rstrip("=")
    state = secrets.token_urlsafe(32)
    with _trava:
        for k in [k for k, v in _pedidos.items() if v["criado"] < _agora() - VALIDADE_PEDIDO]:
            _pedidos.pop(k, None)
        _pedidos[state] = {"client_id": dados.client_id.strip(), "client_secret": dados.client_secret.strip(),
                           "redirect_uri": dados.redirect_uri, "verificador": verificador, "criado": _agora(),
                           "usuario_id": ator.id}
    params = {"client_id": dados.client_id.strip(), "redirect_uri": dados.redirect_uri, "response_type": "code",
              "scope": ESCOPO, "access_type": "offline", "prompt": "consent", "state": state,
              "code_challenge": desafio, "code_challenge_method": "S256"}
    return AutorizacaoGoogle(url=f"{URL_AUTORIZACAO}?{urlencode(params)}", state=state)


def _erro_google(r: httpx.Response) -> str:
    try:
        corpo = r.json()
    except ValueError:
        return f"HTTP {r.status_code}"
    erro = corpo.get("error")
    if isinstance(erro, dict):
        return erro.get("message") or str(erro)
    return corpo.get("error_description") or str(erro or r.status_code)


def concluir(db: Session, cfg: Configuracoes, ator: Usuario, dados: ConcluirGoogle, ip: str | None) -> EstadoEmail:
    with _trava:
        pedido = _pedidos.pop(dados.state, None)
    if pedido is None or pedido["criado"] < _agora() - VALIDADE_PEDIDO or pedido["usuario_id"] != ator.id:
        raise HTTPException(422, "Autorização expirada ou inválida. Clique em \"Conectar conta Google\" de novo.")
    try:
        with _cliente_http() as http:
            r = http.post(URL_TOKEN, data={
                "code": dados.code, "client_id": pedido["client_id"], "client_secret": pedido["client_secret"],
                "redirect_uri": pedido["redirect_uri"], "grant_type": "authorization_code",
                "code_verifier": pedido["verificador"]})
            if r.status_code != 200:
                raise HTTPException(422, f"O Google recusou a autorização: {_erro_google(r)}")
            tokens = r.json()
            if not tokens.get("refresh_token"):
                raise HTTPException(422, "O Google não liberou o acesso permanente. Remova o acesso do Advoga Fácil "
                                         "em myaccount.google.com/permissions e conecte de novo.")
            if ESCOPO not in tokens.get("scope", ESCOPO).split():
                raise HTTPException(422, "A permissão de enviar e-mails não foi concedida. Conecte de novo e marque "
                                         "a opção de envio.")
            p = http.get(URL_PERFIL, headers={"Authorization": f"Bearer {tokens['access_token']}"})
            remetente = p.json().get("emailAddress") if p.status_code == 200 else None
    except httpx.HTTPError as exc:
        raise HTTPException(502, "Não foi possível falar com o Google. Verifique a internet do servidor.") from exc
    if not remetente:
        raise HTTPException(422, "Não foi possível identificar o endereço da conta Google autorizada.")
    valor = {"tipo": "google", "remetente": remetente, "client_id": pedido["client_id"],
             "client_secret": cifrar(cfg, pedido["client_secret"]), "refresh_token": cifrar(cfg, tokens["refresh_token"]),
             "conectado_em": _agora().isoformat(), "conectado_por": str(ator.id),
             "servidor_id": str(obter_identidade(db).servidor_id)}
    linha = db.get(Configuracao, CHAVE)
    if linha is None:
        db.add(Configuracao(chave=CHAVE, valor=valor, atualizado_por=ator.id))
    else:
        linha.valor, linha.atualizado_por = valor, ator.id
    db.flush()
    auditoria.registrar(db, "email.conectado", usuario_id=ator.id, entidade="configuracao", entidade_id=CHAVE,
                        detalhes={"tipo": "google", "remetente": remetente}, ip=ip)
    return estado(db, cfg)


def desconectar(db: Session, ator: Usuario, ip: str | None) -> None:
    linha = db.get(Configuracao, CHAVE)
    if linha is None:
        return
    remetente = (linha.valor or {}).get("remetente")
    db.delete(linha)
    db.flush()
    auditoria.registrar(db, "email.desconectado", usuario_id=ator.id, entidade="configuracao", entidade_id=CHAVE,
                        detalhes={"remetente": remetente}, ip=ip)


def estado(db: Session, cfg: Configuracoes) -> EstadoEmail:
    linha = db.get(Configuracao, CHAVE)
    if linha is None:
        return EstadoEmail(configurado=False, mensagem="Nenhuma conta de envio conectada. Os avisos aparecem só no "
                                                       "aplicativo até a conta oficial ser conectada.")
    v = linha.valor
    autor = db.get(Usuario, uuid.UUID(v["conectado_por"])) if v.get("conectado_por") else None
    base = dict(configurado=True, tipo=v.get("tipo"), remetente=v.get("remetente"),
                conectado_em=datetime.fromisoformat(v["conectado_em"]) if v.get("conectado_em") else None,
                conectado_por_nome=autor.nome_completo if autor else None)
    if _segredos(db, cfg, v) is None:
        return EstadoEmail(**base, precisa_reconectar=True,
                           mensagem="A conta precisa ser conectada de novo neste servidor (por segurança, a "
                                    "autorização não é transferida entre servidores).")
    return EstadoEmail(**base, mensagem=f"Os avisos são enviados por {v.get('remetente')}.")


def _segredos(db: Session, cfg: Configuracoes, v: dict) -> tuple[str, str] | None:
    if v.get("servidor_id") != str(obter_identidade(db).servidor_id):
        return None
    try:
        return decifrar(cfg, v["client_secret"]), decifrar(cfg, v["refresh_token"])
    except (SegredoIndisponivel, KeyError):
        return None


# ================================================================================= envio
class EnviadorGoogle:
    def __init__(self, remetente: str, client_id: str, client_secret: str, refresh_token: str) -> None:
        self.remetente = remetente
        self._client_id = client_id
        self._client_secret = client_secret
        self._refresh = refresh_token
        self._chave_cache = hashlib.sha256(refresh_token.encode()).hexdigest()

    def _token(self, http: httpx.Client) -> str:
        em_cache = _tokens.get(self._chave_cache)
        if em_cache and em_cache[1] > relogio.time() + 60:
            return em_cache[0]
        r = http.post(URL_TOKEN, data={"client_id": self._client_id, "client_secret": self._client_secret,
                                       "refresh_token": self._refresh, "grant_type": "refresh_token"})
        if r.status_code in (400, 401):
            raise ErroEnvio("A autorização da conta Google foi revogada ou expirou. A Master precisa conectar a "
                            f"conta de novo em Notificações ({_erro_google(r)}).", temporaria=False)
        if r.status_code != 200:
            raise ErroEnvio(f"Google indisponível ao renovar o acesso ({_erro_google(r)}).")
        dados = r.json()
        _tokens[self._chave_cache] = (dados["access_token"], relogio.time() + int(dados.get("expires_in", 3600)))
        return dados["access_token"]

    def enviar(self, msg: Mensagem) -> None:
        m = EmailMessage()
        m["From"] = f"Advoga Fácil <{self.remetente}>"
        m["To"] = msg.para
        m["Subject"] = msg.assunto
        m.set_content(msg.texto)
        bruto = base64.urlsafe_b64encode(m.as_bytes()).decode()
        try:
            with _cliente_http() as http:
                token = self._token(http)
                r = http.post(URL_ENVIO, json={"raw": bruto}, headers={"Authorization": f"Bearer {token}"})
                if r.status_code == 401:  # token vencido antes do previsto: renova uma vez
                    _tokens.pop(self._chave_cache, None)
                    token = self._token(http)
                    r = http.post(URL_ENVIO, json={"raw": bruto}, headers={"Authorization": f"Bearer {token}"})
        except httpx.HTTPError as exc:
            raise ErroEnvio(f"Sem conexão com o Google: {exc.__class__.__name__}.") from exc
        if r.status_code == 200:
            return
        detalhe = _erro_google(r)
        if r.status_code == 429 or r.status_code >= 500:
            raise ErroEnvio(f"Google ocupado ou indisponível ({detalhe}).")
        raise ErroEnvio(f"O Google recusou o envio ({detalhe}).", temporaria=False)


def obter(db: Session, cfg: Configuracoes) -> EnviadorGoogle | None:
    linha = db.get(Configuracao, CHAVE)
    if linha is None or (linha.valor or {}).get("tipo") != "google":
        return None
    segredos = _segredos(db, cfg, linha.valor)
    if segredos is None:
        return None
    return EnviadorGoogle(linha.valor["remetente"], linha.valor["client_id"], *segredos)


def enviar_teste(db: Session, cfg: Configuracoes, ator: Usuario, para: str | None, ip: str | None) -> str:
    enviador = obter(db, cfg)
    if enviador is None:
        raise HTTPException(409, "Nenhuma conta de envio conectada neste servidor.")
    destino = para or ator.email
    try:
        enviador.enviar(Mensagem(para=destino, assunto="[Advoga Fácil] Teste de envio",
                                 texto="Este é um e-mail de teste do Advoga Fácil.\n\nSe você recebeu esta mensagem, "
                                       "os avisos automáticos do escritório estão sendo enviados corretamente."))
    except ErroEnvio as exc:
        auditoria.registrar(db, "email.teste", usuario_id=ator.id, detalhes={"para": destino, "resultado": "falha",
                                                                           "erro": exc.mensagem}, ip=ip)
        db.commit()
        raise HTTPException(502, f"O teste falhou: {exc.mensagem}") from exc
    auditoria.registrar(db, "email.teste", usuario_id=ator.id, detalhes={"para": destino, "resultado": "enviado"},
                        ip=ip)
    return destino
