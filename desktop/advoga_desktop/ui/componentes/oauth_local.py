"""Recebe o retorno da autorização do Google no próprio computador (endereço 127.0.0.1).

O navegador volta para http://127.0.0.1:<porta>/ com o código de autorização; este receptor
captura o código, mostra uma página simples e encerra. Nada fica acessível pela rede.
"""

from __future__ import annotations

import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import parse_qs, urlparse

PAGINA = """<!doctype html><html lang="pt-BR"><meta charset="utf-8"><title>Advoga Fácil</title>
<body style="font-family:sans-serif;background:#0E0E10;color:#EDEDED;text-align:center;padding-top:80px">
<h2 style="color:#E2C275">{titulo}</h2><p>{texto}</p></body></html>"""


class ReceptorOAuth:
    def __init__(self) -> None:
        self.resultado: dict[str, str] | None = None
        receptor = self

        class _Manipulador(BaseHTTPRequestHandler):
            def do_GET(self) -> None:  # noqa: N802
                q = {k: v[0] for k, v in parse_qs(urlparse(self.path).query).items()}
                if "code" not in q and "error" not in q:
                    self.send_response(404)
                    self.end_headers()
                    return
                receptor.resultado = q
                ok = "code" in q
                corpo = PAGINA.format(
                    titulo="Conta conectada" if ok else "Autorização não concluída",
                    texto="Pode fechar esta janela e voltar ao Advoga Fácil." if ok else
                    "A autorização foi cancelada ou recusada. Volte ao Advoga Fácil e tente de novo.")
                dados = corpo.encode()
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(dados)))
                self.end_headers()
                self.wfile.write(dados)

            def log_message(self, *args) -> None:  # silencioso
                pass

        self._servidor = HTTPServer(("127.0.0.1", 0), _Manipulador)
        self._thread = threading.Thread(target=self._servidor.serve_forever, daemon=True)

    @property
    def endereco(self) -> str:
        return f"http://127.0.0.1:{self._servidor.server_port}/"

    def iniciar(self) -> None:
        self._thread.start()

    def encerrar(self) -> None:
        self._servidor.shutdown()
        self._servidor.server_close()
