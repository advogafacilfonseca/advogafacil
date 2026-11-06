"""Comunicação do aplicativo com o servidor. O app nunca acessa o banco diretamente."""

from __future__ import annotations

import platform
from typing import Any

import httpx

from advoga_shared.esquemas import Saude, SessaoCriada, UsuarioPublico


class ErroAPI(Exception):
    def __init__(self, mensagem: str, status: int | None = None) -> None:
        super().__init__(mensagem)
        self.mensagem = mensagem
        self.status = status


class ServidorIndisponivel(ErroAPI):
    pass


class SessaoExpirada(ErroAPI):
    pass


class ClienteAPI:
    def __init__(self, endereco: str, timeout: float = 10.0) -> None:
        self.endereco = endereco.rstrip("/")
        self.token: str | None = None
        self.usuario: UsuarioPublico | None = None
        self._http = httpx.Client(base_url=self.endereco, timeout=timeout)

    def fechar(self) -> None:
        self._http.close()

    # ------------------------------------------------------------------ base
    def _requisitar(self, metodo: str, rota: str, **kw: Any) -> Any:
        cabecalhos = kw.pop("headers", {})
        if self.token:
            cabecalhos["Authorization"] = f"Bearer {self.token}"
        try:
            r = self._http.request(metodo, rota, headers=cabecalhos, **kw)
        except httpx.TimeoutException as exc:
            raise ServidorIndisponivel(
                "O servidor demorou demais para responder. Verifique a conexão e tente novamente."
            ) from exc
        except httpx.HTTPError as exc:
            raise ServidorIndisponivel(
                "Não foi possível conectar ao servidor do Advoga Fácil. Verifique se o computador "
                "servidor está ligado e se este computador está na rede do escritório ou na Tailscale."
            ) from exc
        if r.status_code >= 400:
            try:
                detalhe = r.json().get("detail")
            except ValueError:
                detalhe = None
            mensagem = detalhe if isinstance(detalhe, str) else "O servidor recusou a operação."
            if r.status_code == 401 and self.token:
                self.token = None
                raise SessaoExpirada(mensagem, 401)
            if r.status_code == 503:
                raise ServidorIndisponivel(mensagem, 503)
            raise ErroAPI(mensagem, r.status_code)
        return r.json() if r.content else None

    # --------------------------------------------------------------- sistema
    def saude(self) -> Saude:
        return Saude.model_validate(self._requisitar("GET", "/api/saude"))

    def sistema_configurado(self) -> bool:
        return bool(self._requisitar("GET", "/api/setup/status")["configurado"])

    def criar_master(self, dados: dict[str, str]) -> UsuarioPublico:
        return UsuarioPublico.model_validate(self._requisitar("POST", "/api/setup/master", json=dados))

    # ---------------------------------------------------------- autenticação
    def login(self, nome_usuario: str, senha: str) -> UsuarioPublico:
        dados = {"nome_usuario": nome_usuario, "senha": senha,
                 "dispositivo": platform.node()[:120] or None}
        sessao = SessaoCriada.model_validate(self._requisitar("POST", "/api/auth/login", json=dados))
        self.token = sessao.token
        self.usuario = sessao.usuario
        return sessao.usuario

    def logout(self) -> None:
        if self.token:
            try:
                self._requisitar("POST", "/api/auth/logout")
            finally:
                self.token = None
                self.usuario = None

    def eu(self) -> UsuarioPublico:
        self.usuario = UsuarioPublico.model_validate(self._requisitar("GET", "/api/auth/eu"))
        return self.usuario

    def trocar_senha(self, atual: str, nova: str, confirmacao: str) -> str:
        r = self._requisitar("POST", "/api/auth/trocar-senha", json={
            "senha_atual": atual, "nova_senha": nova, "nova_senha_confirmacao": confirmacao})
        return r["mensagem"]
