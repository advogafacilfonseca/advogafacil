"""Arquivo COMO_CONECTAR.txt gerado pelo instalador (sem e com a Tailscale)."""

from __future__ import annotations

import json
import subprocess

from advoga_server.__main__ import main
from advoga_server.core import conexao
from advoga_server.core.tls import arquivos_tls, impressao_digital


def test_informacoes_sem_tailscale(cfg, monkeypatch, capsys):
    monkeypatch.setattr(conexao, "_programa_tailscale", lambda: None)
    monkeypatch.setattr("advoga_server.__main__.obter_configuracoes", lambda: cfg)
    assert main(["informacoes"]) == 0
    arq = cfg.pasta_config / "COMO_CONECTAR.txt"
    conteudo = arq.read_text(encoding="utf-8")
    digital = impressao_digital(arquivos_tls(cfg)[1].read_bytes())
    assert digital in conteudo and f"127.0.0.1:{cfg.porta}" in conteudo
    assert "Tailscale não encontrada" in conteudo
    assert digital in capsys.readouterr().out


def test_informacoes_com_tailscale(cfg, monkeypatch):
    monkeypatch.setattr(conexao, "_programa_tailscale", lambda: "tailscale")
    saida = {"BackendState": "Running", "Self": {"TailscaleIPs": ["100.101.102.103", "fd7a::1"],
                                                 "DNSName": "notebook-master.tail1234.ts.net."}}

    def falso(*_a, **_k):
        return subprocess.CompletedProcess([], 0, json.dumps(saida).encode(), b"")

    monkeypatch.setattr(conexao.subprocess, "run", falso)
    _arq, info = conexao.gravar(cfg)
    assert info.tailscale_ip == "100.101.102.103" and info.tailscale_nome == "notebook-master.tail1234.ts.net"
    t = conexao.texto(info)
    assert "notebook-master.tail1234.ts.net:8765" in t and "100.101.102.103:8765" in t
    saida["BackendState"] = "Stopped"
    _arq, info = conexao.gravar(cfg)
    assert info.tailscale_ip is None and "desconectada" in conexao.texto(info)
