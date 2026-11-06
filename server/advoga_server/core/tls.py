"""Certificado HTTPS próprio do servidor.

Gerado uma única vez na instalação. O aplicativo de cada computador registra este
certificado na primeira conexão (e mostra a impressão digital para conferência) e,
a partir daí, só aceita conversar com este servidor. A migração de servidor leva o
mesmo certificado, para que os computadores continuem funcionando sem reconfigurar.
"""

from __future__ import annotations

import hashlib
import ipaddress
import os
import socket
from datetime import UTC, datetime, timedelta
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import NameOID

from .config import Configuracoes


def pasta_tls(cfg: Configuracoes) -> Path:
    return cfg.pasta_config / "tls"


def arquivos_tls(cfg: Configuracoes) -> tuple[Path, Path]:
    p = pasta_tls(cfg)
    return p / "servidor.key", p / "servidor.crt"


def impressao_digital(pem: str | bytes) -> str:
    cert = x509.load_pem_x509_certificate(pem.encode() if isinstance(pem, str) else pem)
    der = cert.public_bytes(serialization.Encoding.DER)
    h = hashlib.sha256(der).hexdigest().upper()
    return ":".join(h[i:i + 2] for i in range(0, len(h), 2))


def garantir_certificado(cfg: Configuracoes) -> tuple[Path, Path]:
    chave_arq, cert_arq = arquivos_tls(cfg)
    if chave_arq.exists() and cert_arq.exists():
        return chave_arq, cert_arq
    chave_arq.parent.mkdir(parents=True, exist_ok=True)

    chave = ec.generate_private_key(ec.SECP256R1())
    nome_maquina = socket.gethostname() or "servidor"
    nome = x509.Name([
        x509.NameAttribute(NameOID.ORGANIZATION_NAME, "Advoga Fácil"),
        x509.NameAttribute(NameOID.COMMON_NAME, f"Advoga Fácil Servidor ({nome_maquina})"[:64]),
    ])
    agora = datetime.now(UTC)
    alternativos = [x509.DNSName("localhost"), x509.DNSName(nome_maquina),
                    x509.IPAddress(ipaddress.ip_address("127.0.0.1"))]
    cert = (
        x509.CertificateBuilder()
        .subject_name(nome)
        .issuer_name(nome)
        .public_key(chave.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(agora - timedelta(days=1))
        .not_valid_after(agora + timedelta(days=3650))
        .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
        .add_extension(x509.SubjectAlternativeName(alternativos), critical=False)
        .add_extension(x509.KeyUsage(digital_signature=True, key_cert_sign=True, crl_sign=True,
                                     content_commitment=False, key_encipherment=False,
                                     data_encipherment=False, key_agreement=True,
                                     encipher_only=False, decipher_only=False), critical=True)
        .sign(chave, hashes.SHA256())
    )
    chave_arq.write_bytes(chave.private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
    if os.name != "nt":
        chave_arq.chmod(0o600)
    pem = cert.public_bytes(serialization.Encoding.PEM)
    cert_arq.write_bytes(pem)
    (chave_arq.parent / "IMPRESSAO_DIGITAL.txt").write_text(
        "Impressão digital do certificado do servidor Advoga Fácil (confira na primeira conexão):\n"
        f"{impressao_digital(pem)}\n", encoding="utf-8")
    return chave_arq, cert_arq
