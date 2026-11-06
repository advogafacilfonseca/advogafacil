"""Arquivo de backup criptografado (.afbk) para a cópia em armazenamento externo separado.

Formato:
  "AFBK" + versão (1 byte) + tamanho do cabeçalho (4 bytes) + cabeçalho JSON
  blocos: tamanho (4 bytes) + AES-256-GCM(bloco de até 1 MB)
  bloco final vazio marcado como "fim" (detecta arquivo cortado)

A chave vem da senha da cópia (scrypt). Sem a senha, o arquivo não pode ser aberto.
O conteúdo é um arquivo .tar com a versão do backup (banco + manifesto + documentos).
"""

from __future__ import annotations

import base64
import io
import json
import os
import struct

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.scrypt import Scrypt

MAGICO = b"AFBK\x01"
BLOCO = 1024 * 1024
SCRYPT = {"n": 2 ** 15, "r": 8, "p": 1}


class ArquivoInvalido(Exception):
    pass


def derivar_chave(senha: str, sal: bytes, n: int = SCRYPT["n"], r: int = SCRYPT["r"], p: int = SCRYPT["p"]) -> bytes:
    return Scrypt(salt=sal, length=32, n=n, r=r, p=p).derive(senha.encode("utf-8"))


def _nonce(prefixo: bytes, contador: int) -> bytes:
    return prefixo + struct.pack(">I", contador)


class Cifrador(io.RawIOBase):
    """Arquivo somente-escrita: o que entra é gravado criptografado em `destino`."""

    def __init__(self, destino, chave: bytes, sal: bytes, extra: dict | None = None) -> None:
        super().__init__()
        self._f = destino
        self._aes = AESGCM(chave)
        self._prefixo = os.urandom(8)
        self._contador = 0
        self._buffer = bytearray()
        cab = json.dumps({"kdf": "scrypt", **SCRYPT, "sal": base64.b64encode(sal).decode(),
                          "nonce": base64.b64encode(self._prefixo).decode(), **(extra or {})}).encode()
        self._f.write(MAGICO + struct.pack(">I", len(cab)) + cab)
        self._cab = cab

    def writable(self) -> bool:
        return True

    def _gravar_bloco(self, dados: bytes, fim: bool) -> None:
        aad = self._cab + (b"fim" if fim else b"bloco")
        cifrado = self._aes.encrypt(_nonce(self._prefixo, self._contador), dados, aad)
        self._contador += 1
        self._f.write(struct.pack(">I", len(cifrado)) + cifrado)

    def write(self, b) -> int:
        self._buffer.extend(b)
        while len(self._buffer) >= BLOCO:
            self._gravar_bloco(bytes(self._buffer[:BLOCO]), False)
            del self._buffer[:BLOCO]
        return len(b)

    def finalizar(self) -> None:
        if self._buffer:
            self._gravar_bloco(bytes(self._buffer), False)
            self._buffer.clear()
        self._gravar_bloco(b"", True)


def ler_cabecalho(f) -> tuple[dict, bytes]:
    inicio = f.read(len(MAGICO) + 4)
    if len(inicio) < len(MAGICO) + 4 or inicio[:len(MAGICO)] != MAGICO:
        raise ArquivoInvalido("Este arquivo não é uma cópia criptografada do Advoga Fácil.")
    (n,) = struct.unpack(">I", inicio[len(MAGICO):])
    cab = f.read(n)
    try:
        return json.loads(cab), cab
    except ValueError as exc:
        raise ArquivoInvalido("Cabeçalho da cópia criptografada danificado.") from exc


class Decifrador(io.RawIOBase):
    """Leitura sequencial do conteúdo original. Confere cada bloco (falha se alterado ou cortado)."""

    def __init__(self, origem, senha: str | None = None, chave: bytes | None = None) -> None:
        super().__init__()
        self._f = origem
        self.cabecalho, self._cab = ler_cabecalho(origem)
        sal = base64.b64decode(self.cabecalho["sal"])
        if chave is None:
            if senha is None:
                raise ArquivoInvalido("Informe a senha da cópia criptografada.")
            chave = derivar_chave(senha, sal, self.cabecalho["n"], self.cabecalho["r"], self.cabecalho["p"])
        self._aes = AESGCM(chave)
        self._prefixo = base64.b64decode(self.cabecalho["nonce"])
        self._contador = 0
        self._pendente = b""
        self._terminou = False

    def readable(self) -> bool:
        return True

    def _proximo(self) -> None:
        tam = self._f.read(4)
        if len(tam) < 4:
            raise ArquivoInvalido("A cópia criptografada está incompleta (arquivo cortado).")
        (n,) = struct.unpack(">I", tam)
        cifrado = self._f.read(n)
        if len(cifrado) < n:
            raise ArquivoInvalido("A cópia criptografada está incompleta (arquivo cortado).")
        nonce = _nonce(self._prefixo, self._contador)
        self._contador += 1
        for marca in (b"bloco", b"fim"):
            try:
                dados = self._aes.decrypt(nonce, cifrado, self._cab + marca)
            except InvalidTag:
                continue
            if marca == b"fim":
                self._terminou = True
            self._pendente += dados
            return
        if self._contador == 1:
            raise ArquivoInvalido("Senha incorreta ou cópia criptografada danificada.")
        raise ArquivoInvalido("A cópia criptografada está danificada (falha na verificação de integridade).")

    def readinto(self, b) -> int:
        while not self._pendente and not self._terminou:
            self._proximo()
        n = min(len(b), len(self._pendente))
        b[:n] = self._pendente[:n]
        self._pendente = self._pendente[n:]
        return n
