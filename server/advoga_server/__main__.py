"""Linha de comando do servidor: advoga-servidor <comando>."""

from __future__ import annotations

import argparse
import logging
import sys

from .core.config import obter_configuracoes


def _preparar() -> None:
    from .core.db import configurar_banco, obter_sessao
    from .core.migracoes import atualizar_banco
    from .services.servidor import obter_identidade, preparar_codigo_instalacao

    cfg = obter_configuracoes()
    cfg.garantir_pastas()
    url = cfg.url_banco()
    atualizar_banco(url)
    configurar_banco(url)
    db = next(obter_sessao())
    try:
        obter_identidade(db)
        codigo = preparar_codigo_instalacao(db, cfg)
        if codigo:
            print("Sistema ainda não configurado.")
            print(f"Código de instalação (uso único): {codigo}")
            print(f"Também gravado em: {cfg.arquivo_codigo_instalacao}")
    finally:
        db.close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="advoga-servidor", description="Servidor do Advoga Fácil")
    sub = parser.add_subparsers(dest="comando", required=True)
    sub.add_parser("servir", help="Atualiza o banco e inicia a API")
    sub.add_parser("migrar", help="Somente atualiza a estrutura do banco")
    sub.add_parser("codigo-instalacao", help="Mostra o código para criar a conta Master")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

    if args.comando in ("migrar", "codigo-instalacao"):
        _preparar()
        cfg = obter_configuracoes()
        if cfg.https:
            from .core.tls import garantir_certificado

            garantir_certificado(cfg)
        return 0

    import uvicorn

    from .app import criar_app

    _preparar()
    cfg = obter_configuracoes()
    opcoes_tls = {}
    if cfg.https:
        from .core.tls import garantir_certificado, impressao_digital

        chave, cert = garantir_certificado(cfg)
        opcoes_tls = {"ssl_keyfile": str(chave), "ssl_certfile": str(cert)}
        print(f"HTTPS ativo. Impressão digital do certificado: {impressao_digital(cert.read_bytes())}")
    uvicorn.run(criar_app(cfg), host=cfg.host, port=cfg.porta, log_level="info", **opcoes_tls)
    return 0


if __name__ == "__main__":
    sys.exit(main())
