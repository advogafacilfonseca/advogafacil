"""Comunicação do aplicativo com o servidor. O app nunca acessa o banco diretamente."""

from __future__ import annotations

import hashlib
import mimetypes
import os
import platform
import ssl
import time
import uuid
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import httpx

from advoga_shared.esquemas import (
    Cliente,
    Documento,
    ItemAuditoria,
    Movimentacao,
    OpcaoCliente,
    OpcaoProcesso,
    OpcaoUsuario,
    PaginaAuditoria,
    PaginaClientes,
    PaginaDocumentos,
    PaginaPesquisa,
    PaginaProcessos,
    Processo,
    Saude,
    SessaoCriada,
    UsuarioDetalhe,
    UsuarioPublico,
)


class ErroAPI(Exception):
    def __init__(self, mensagem: str, status: int | None = None) -> None:
        super().__init__(mensagem)
        self.mensagem = mensagem
        self.status = status


class ServidorIndisponivel(ErroAPI):
    pass


class SessaoExpirada(ErroAPI):
    pass


MSG_CERTIFICADO = (
    "O certificado de segurança do servidor não confere com o registrado neste computador. "
    "Por segurança, a conexão foi bloqueada. Se o servidor foi trocado ou reinstalado, use "
    "\"Alterar servidor\" e confira a nova impressão digital com a Advogada Master."
)


def obter_certificado_servidor(endereco: str, timeout: float = 6.0) -> str:
    """Baixa o certificado apresentado pelo servidor (para registro na primeira conexão)."""
    partes = urlsplit(endereco)
    try:
        return ssl.get_server_certificate((partes.hostname, partes.port or 443), timeout=timeout)
    except (OSError, ssl.SSLError) as exc:
        raise ServidorIndisponivel(
            "Não foi possível conectar ao servidor do Advoga Fácil. Verifique se o computador "
            "servidor está ligado e se o endereço está correto."
        ) from exc


def impressao_digital(pem: str) -> str:
    der = ssl.PEM_cert_to_DER_cert(pem)
    h = hashlib.sha256(der).hexdigest().upper()
    return ":".join(h[i:i + 2] for i in range(0, len(h), 2))


def _contexto_ssl(pem: str) -> ssl.SSLContext:
    ctx = ssl.create_default_context(cadata=pem)
    # O certificado é fixado (somente este servidor é aceito); o nome usado para
    # chegar até ele pode variar (IP da rede local, nome da Tailscale).
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_REQUIRED
    return ctx


class ClienteAPI:
    TENTATIVAS_GRAVACAO = 3

    def __init__(self, endereco: str, certificado_pem: str | None = None, timeout: float = 10.0) -> None:
        self.endereco = endereco.rstrip("/")
        self.certificado_pem = certificado_pem or ""
        self.token: str | None = None
        self.usuario: UsuarioPublico | None = None
        verificar: Any = True
        if self.endereco.startswith("https://"):
            if not self.certificado_pem:
                raise ErroAPI("Certificado do servidor não registrado. Configure a conexão novamente.")
            verificar = _contexto_ssl(self.certificado_pem)
        self._http = httpx.Client(base_url=self.endereco, timeout=timeout, verify=verificar)

    def fechar(self) -> None:
        self._http.close()

    # ------------------------------------------------------------------ base
    def _enviar(self, metodo: str, rota: str, cabecalhos: dict[str, str], **kw: Any) -> httpx.Response:
        try:
            return self._http.request(metodo, rota, headers=cabecalhos, **kw)
        except httpx.TimeoutException as exc:
            raise ServidorIndisponivel(
                "O servidor demorou demais para responder. Verifique a conexão e tente novamente."
            ) from exc
        except httpx.HTTPError as exc:
            if "CERTIFICATE_VERIFY_FAILED" in str(exc):
                raise ErroAPI(MSG_CERTIFICADO) from exc
            raise ServidorIndisponivel(
                "Não foi possível conectar ao servidor do Advoga Fácil. Verifique se o computador "
                "servidor está ligado e se este computador está na rede do escritório ou na Tailscale."
            ) from exc

    def _requisitar(self, metodo: str, rota: str, gravacao: bool = False, **kw: Any) -> Any:
        cabecalhos = kw.pop("headers", {})
        if self.token:
            cabecalhos["Authorization"] = f"Bearer {self.token}"
        if not gravacao:
            r = self._enviar(metodo, rota, cabecalhos, **kw)
        else:
            # Gravação segura: a mesma chave acompanha as novas tentativas, então o servidor
            # nunca grava a operação duas vezes, mesmo que a resposta tenha se perdido.
            cabecalhos["Idempotency-Key"] = uuid.uuid4().hex
            for tentativa in range(self.TENTATIVAS_GRAVACAO):
                try:
                    r = self._enviar(metodo, rota, cabecalhos, **kw)
                    break
                except ServidorIndisponivel:
                    if tentativa == self.TENTATIVAS_GRAVACAO - 1:
                        raise ServidorIndisponivel(
                            "A conexão com o servidor caiu e a operação não pôde ser confirmada. "
                            "Nada foi gravado em duplicidade. Verifique a conexão e tente novamente."
                        ) from None
                    time.sleep(1.5 * (tentativa + 1))
        return self._tratar_resposta(r)

    def _tratar_resposta(self, r: httpx.Response) -> Any:
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

    # -------------------------------------------------------------- usuários
    def listar_usuarios(self) -> list[UsuarioDetalhe]:
        return [UsuarioDetalhe.model_validate(u) for u in self._requisitar("GET", "/api/usuarios")]

    def criar_usuario(self, dados: dict[str, Any]) -> UsuarioDetalhe:
        return UsuarioDetalhe.model_validate(self._requisitar("POST", "/api/usuarios", gravacao=True, json=dados))

    def atualizar_usuario(self, usuario_id: str, dados: dict[str, Any]) -> UsuarioDetalhe:
        return UsuarioDetalhe.model_validate(
            self._requisitar("PATCH", f"/api/usuarios/{usuario_id}", gravacao=True, json=dados))

    def definir_permissoes(self, usuario_id: str, permissoes: list[str]) -> UsuarioDetalhe:
        return UsuarioDetalhe.model_validate(self._requisitar(
            "PUT", f"/api/usuarios/{usuario_id}/permissoes", gravacao=True, json={"permissoes": permissoes}))

    def alterar_situacao_usuario(self, usuario_id: str, ativo: bool) -> UsuarioDetalhe:
        acao = "reativar" if ativo else "desativar"
        return UsuarioDetalhe.model_validate(
            self._requisitar("POST", f"/api/usuarios/{usuario_id}/{acao}", gravacao=True))

    def redefinir_senha_usuario(self, usuario_id: str, senha: str) -> UsuarioDetalhe:
        return UsuarioDetalhe.model_validate(self._requisitar(
            "POST", f"/api/usuarios/{usuario_id}/redefinir-senha", gravacao=True,
            json={"senha_provisoria": senha}))

    # ------------------------------------------------------------- auditoria
    def auditoria(self, **filtros: Any) -> PaginaAuditoria:
        params = {k: v for k, v in filtros.items() if v not in (None, "")}
        return PaginaAuditoria.model_validate(self._requisitar("GET", "/api/auditoria", params=params))

    # -------------------------------------------------------------- clientes
    def listar_clientes(self, q: str = "", situacao: str | None = None, pagina: int = 1,
                        por_pagina: int = 50) -> PaginaClientes:
        params: dict[str, Any] = {"pagina": pagina, "por_pagina": por_pagina}
        if q.strip():
            params["q"] = q.strip()
        if situacao:
            params["situacao"] = situacao
        return PaginaClientes.model_validate(self._requisitar("GET", "/api/clientes", params=params))

    def obter_cliente(self, cliente_id: str) -> Cliente:
        return Cliente.model_validate(self._requisitar("GET", f"/api/clientes/{cliente_id}"))

    def criar_cliente(self, dados: dict[str, Any]) -> Cliente:
        return Cliente.model_validate(self._requisitar("POST", "/api/clientes", gravacao=True, json=dados))

    def atualizar_cliente(self, cliente_id: str, dados: dict[str, Any]) -> Cliente:
        return Cliente.model_validate(
            self._requisitar("PATCH", f"/api/clientes/{cliente_id}", gravacao=True, json=dados))

    def encerrar_cliente(self, cliente_id: str, motivo: str, versao: int) -> Cliente:
        return Cliente.model_validate(self._requisitar(
            "POST", f"/api/clientes/{cliente_id}/encerrar", gravacao=True, json={"motivo": motivo, "versao": versao}))

    def reativar_cliente(self, cliente_id: str, versao: int) -> Cliente:
        return Cliente.model_validate(self._requisitar(
            "POST", f"/api/clientes/{cliente_id}/reativar", gravacao=True, params={"versao": versao}))

    def historico_cliente(self, cliente_id: str) -> list[ItemAuditoria]:
        return [ItemAuditoria.model_validate(i)
                for i in self._requisitar("GET", f"/api/clientes/{cliente_id}/historico")]

    def pesquisar(self, termo: str, pagina: int = 1, por_pagina: int = 20) -> PaginaPesquisa:
        return PaginaPesquisa.model_validate(self._requisitar(
            "GET", "/api/pesquisa", params={"q": termo, "pagina": pagina, "por_pagina": por_pagina}))

    def usuarios_ativos(self) -> list[OpcaoUsuario]:
        return [OpcaoUsuario.model_validate(u) for u in self._requisitar("GET", "/api/usuarios-ativos")]

    def clientes_opcoes(self, termo: str) -> list[OpcaoCliente]:
        return [OpcaoCliente.model_validate(c) for c in self._requisitar("GET", "/api/clientes-opcoes",
                                                                         params={"q": termo})]

    def cliente_opcao(self, cliente_id: str) -> OpcaoCliente:
        return OpcaoCliente.model_validate(self._requisitar("GET", f"/api/clientes-opcoes/{cliente_id}"))

    # ------------------------------------------------------------- processos
    def listar_processos(self, q: str = "", cliente_id: str | None = None, situacao: str | None = None,
                         pagina: int = 1, por_pagina: int = 50) -> PaginaProcessos:
        params = {"q": q.strip() or None, "cliente_id": cliente_id, "situacao": situacao,
                  "pagina": pagina, "por_pagina": por_pagina}
        return PaginaProcessos.model_validate(self._requisitar(
            "GET", "/api/processos", params={k: v for k, v in params.items() if v not in (None, "")}))

    def obter_processo(self, processo_id: str) -> Processo:
        return Processo.model_validate(self._requisitar("GET", f"/api/processos/{processo_id}"))

    def criar_processo(self, dados: dict[str, Any]) -> Processo:
        return Processo.model_validate(self._requisitar("POST", "/api/processos", gravacao=True, json=dados))

    def atualizar_processo(self, processo_id: str, dados: dict[str, Any]) -> Processo:
        return Processo.model_validate(
            self._requisitar("PATCH", f"/api/processos/{processo_id}", gravacao=True, json=dados))

    def movimentacoes(self, processo_id: str) -> list[Movimentacao]:
        return [Movimentacao.model_validate(m)
                for m in self._requisitar("GET", f"/api/processos/{processo_id}/movimentacoes")]

    def nova_movimentacao(self, processo_id: str, data_iso: str, descricao: str) -> Movimentacao:
        return Movimentacao.model_validate(self._requisitar(
            "POST", f"/api/processos/{processo_id}/movimentacoes", gravacao=True,
            json={"data_movimentacao": data_iso, "descricao": descricao}))

    def historico_processo(self, processo_id: str) -> list[ItemAuditoria]:
        return [ItemAuditoria.model_validate(i)
                for i in self._requisitar("GET", f"/api/processos/{processo_id}/historico")]

    def processos_opcoes(self, cliente_id: str) -> list[OpcaoProcesso]:
        return [OpcaoProcesso.model_validate(p)
                for p in self._requisitar("GET", "/api/processos-opcoes", params={"cliente_id": cliente_id})]

    # ------------------------------------------------------------ documentos
    def listar_documentos(self, q: str = "", cliente_id: str | None = None, processo_id: str | None = None,
                          somente_geral: bool = False, removidos: bool = False, pagina: int = 1,
                          por_pagina: int = 50) -> PaginaDocumentos:
        params: dict[str, Any] = {"q": q.strip() or None, "cliente_id": cliente_id, "processo_id": processo_id,
                                  "pagina": pagina, "por_pagina": por_pagina}
        if somente_geral:
            params["somente_geral"] = "true"
        if removidos:
            params["removidos"] = "true"
        return PaginaDocumentos.model_validate(self._requisitar(
            "GET", "/api/documentos", params={k: v for k, v in params.items() if v not in (None, "")}))

    def obter_documento(self, doc_id: str) -> Documento:
        return Documento.model_validate(self._requisitar("GET", f"/api/documentos/{doc_id}"))

    def anexar_documento(self, arquivo: Path, cliente_id: str, processo_id: str | None = None,
                         descricao: str | None = None, nome: str | None = None) -> Documento:
        """Envia o arquivo em partes. Se a conexão cair, reenvia com a mesma chave (sem duplicar)."""
        arquivo = Path(arquivo)
        if not arquivo.is_file():
            raise ErroAPI("Arquivo não encontrado neste computador.")
        tipo = mimetypes.guess_type(arquivo.name)[0] or "application/octet-stream"
        params = {"cliente_id": cliente_id, "nome": nome or arquivo.name}
        if processo_id:
            params["processo_id"] = processo_id
        if descricao:
            params["descricao"] = descricao
        cab = {"Authorization": f"Bearer {self.token}", "Content-Type": tipo,
               "Content-Length": str(os.path.getsize(arquivo)), "Idempotency-Key": uuid.uuid4().hex}
        for tentativa in range(self.TENTATIVAS_GRAVACAO):
            try:
                with open(arquivo, "rb") as f:
                    r = self._enviar("POST", "/api/documentos", cab, params=params, content=_em_partes(f),
                                     timeout=httpx.Timeout(30.0, write=600.0, read=120.0))
                break
            except ServidorIndisponivel:
                if tentativa == self.TENTATIVAS_GRAVACAO - 1:
                    raise ServidorIndisponivel(
                        "A conexão com o servidor caiu durante o envio e o anexo não pôde ser confirmado. "
                        "Nada foi gravado em duplicidade. Verifique a conexão e tente novamente.") from None
                time.sleep(1.5 * (tentativa + 1))
        return Documento.model_validate(self._tratar_resposta(r))

    def baixar_documento(self, doc_id: str, destino: Path) -> Path:
        """Baixa o arquivo, confere a impressão SHA-256 e só então grava no destino."""
        destino = Path(destino)
        destino.parent.mkdir(parents=True, exist_ok=True)
        parcial = destino.with_name(destino.name + ".baixando")
        cab = {"Authorization": f"Bearer {self.token}"}
        try:
            with self._http.stream("GET", f"/api/documentos/{doc_id}/arquivo", headers=cab,
                                   timeout=httpx.Timeout(30.0, read=300.0)) as r:
                if r.status_code >= 400:
                    r.read()
                    self._tratar_resposta(r)
                esperado = r.headers.get("X-Documento-SHA256", "")
                h = hashlib.sha256()
                with open(parcial, "wb") as f:
                    for bloco in r.iter_bytes(1024 * 256):
                        h.update(bloco)
                        f.write(bloco)
        except httpx.HTTPError as exc:
            parcial.unlink(missing_ok=True)
            raise ServidorIndisponivel("A conexão com o servidor caiu durante o download. Tente novamente.") from exc
        except BaseException:
            parcial.unlink(missing_ok=True)
            raise
        if esperado and h.hexdigest() != esperado:
            parcial.unlink(missing_ok=True)
            raise ErroAPI("O arquivo recebido não confere com o original (falha na transferência). Tente novamente.")
        os.replace(parcial, destino)
        return destino

    def atualizar_documento(self, doc_id: str, dados: dict[str, Any]) -> Documento:
        return Documento.model_validate(
            self._requisitar("PATCH", f"/api/documentos/{doc_id}", gravacao=True, json=dados))

    def remover_documento(self, doc_id: str, motivo: str, versao: int) -> Documento:
        return Documento.model_validate(self._requisitar(
            "POST", f"/api/documentos/{doc_id}/remover", gravacao=True, json={"motivo": motivo, "versao": versao}))

    def restaurar_documento(self, doc_id: str, versao: int) -> Documento:
        return Documento.model_validate(self._requisitar(
            "POST", f"/api/documentos/{doc_id}/restaurar", gravacao=True, params={"versao": versao}))


def _em_partes(arquivo, tamanho: int = 1024 * 256):
    while bloco := arquivo.read(tamanho):
        yield bloco
