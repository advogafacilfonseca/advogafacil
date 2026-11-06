"""Informações para conectar os computadores do escritório a este servidor.

Gera o arquivo COMO_CONECTAR.txt na pasta de configuração (o instalador cria um atalho para ele):
nome do computador, endereços na rede local e na Tailscale, porta e impressão digital do
certificado, que cada computador confere na primeira conexão.
"""

from __future__ import annotations

import ipaddress
import json
import shutil
import socket
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from .config import Configuracoes

REDE_TAILSCALE = ipaddress.ip_network("100.64.0.0/10")


@dataclass
class InfoConexao:
    nome_computador: str
    porta: int
    impressao_digital: str
    enderecos_rede_local: list[str] = field(default_factory=list)
    tailscale_ip: str | None = None
    tailscale_nome: str | None = None
    tailscale_situacao: str = "Tailscale não encontrada neste computador."


def _programa_tailscale() -> str | None:
    achado = shutil.which("tailscale")
    if achado:
        return achado
    padrao = Path(r"C:\Program Files\Tailscale\tailscale.exe")
    return str(padrao) if padrao.exists() else None


def _tailscale(info: InfoConexao) -> None:
    prog = _programa_tailscale()
    if not prog:
        return
    try:
        r = subprocess.run([prog, "status", "--json"], capture_output=True, timeout=15,
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        dados = json.loads(r.stdout or b"{}")
    except (OSError, subprocess.TimeoutExpired, ValueError):
        info.tailscale_situacao = "Tailscale instalada, mas não respondeu. Abra a Tailscale e entre na conta."
        return
    estado = dados.get("BackendState")
    eu = dados.get("Self") or {}
    ips = [ip for ip in eu.get("TailscaleIPs") or [] if ":" not in ip]
    if estado != "Running" or not ips:
        info.tailscale_situacao = "Tailscale instalada, mas desconectada. Abra a Tailscale e entre na conta do escritório."
        return
    info.tailscale_ip = ips[0]
    info.tailscale_nome = (eu.get("DNSName") or "").rstrip(".") or None
    info.tailscale_situacao = "Conectada."


def enderecos_locais() -> list[str]:
    nomes: set[str] = set()
    try:
        for res in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            nomes.add(res[4][0])
    except OSError:
        pass
    validos = []
    for ip in sorted(nomes):
        end = ipaddress.ip_address(ip)
        if end.is_loopback or end in REDE_TAILSCALE or end.is_link_local:
            continue
        validos.append(ip)
    return validos


def coletar(cfg: Configuracoes) -> InfoConexao:
    from .tls import garantir_certificado, impressao_digital

    _chave, cert = garantir_certificado(cfg)
    info = InfoConexao(nome_computador=socket.gethostname() or "servidor", porta=cfg.porta,
                       impressao_digital=impressao_digital(cert.read_bytes()),
                       enderecos_rede_local=enderecos_locais())
    _tailscale(info)
    return info


def texto(info: InfoConexao) -> str:
    p = info.porta
    linhas = [
        "COMO CONECTAR OS COMPUTADORES AO ADVOGA FÁCIL SERVIDOR",
        "=" * 56,
        "",
        "No aplicativo Advoga Fácil de cada computador, na tela \"Conexão com o servidor\",",
        "informe UM dos endereços abaixo e clique em \"Testar conexão\".",
        "",
        "Neste próprio computador (servidor):",
        f"    127.0.0.1:{p}",
        "",
        "Na rede do escritório (mesmo Wi-Fi ou cabo):",
        f"    {info.nome_computador}:{p}",
    ]
    linhas += [f"    {ip}:{p}" for ip in info.enderecos_rede_local]
    linhas += ["", "Fora do escritório, pela Tailscale (recomendado para notebooks):"]
    if info.tailscale_ip:
        if info.tailscale_nome:
            linhas.append(f"    {info.tailscale_nome}:{p}")
        linhas.append(f"    {info.tailscale_ip}:{p}")
    else:
        linhas.append(f"    {info.tailscale_situacao}")
    linhas += [
        "",
        "Na primeira conexão, o aplicativo mostra a impressão digital do certificado.",
        "Ela precisa ser IGUAL a esta (confira pelo menos o começo e o fim):",
        f"    {info.impressao_digital}",
        "",
        "Segurança: o servidor só aceita conexões da rede local e da Tailscale. Ele não fica",
        "exposto na internet e o banco de dados só aceita conexões do próprio computador.",
    ]
    return "\n".join(linhas) + "\n"


def gravar(cfg: Configuracoes) -> tuple[Path, InfoConexao]:
    info = coletar(cfg)
    arq = cfg.pasta_config / "COMO_CONECTAR.txt"
    arq.parent.mkdir(parents=True, exist_ok=True)
    arq.write_text(texto(info), encoding="utf-8")
    return arq, info
