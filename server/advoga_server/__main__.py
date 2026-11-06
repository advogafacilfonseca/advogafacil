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


def _restaurar(args) -> int:
    import getpass
    from pathlib import Path

    from .core.migracoes import atualizar_banco
    from .services import backup

    cfg = obter_configuracoes()
    cfg.garantir_pastas()
    url = args.banco or cfg.url_banco()
    senha = None
    if Path(args.origem).suffix.lower() == ".afbk":
        senha = getpass.getpass("Senha da cópia criptografada: ")
    try:
        r = backup.restaurar(cfg, Path(args.origem), url, senha=senha)
    except backup.FalhaBackup as exc:
        print(f"RESTAURAÇÃO NÃO REALIZADA: {exc}")
        return 1
    except Exception as exc:  # noqa: BLE001
        print(f"RESTAURAÇÃO NÃO REALIZADA: {exc.__class__.__name__}: {exc}")
        return 1
    atualizar_banco(url)
    print(f"Restauração concluída: versão {r['versao']}, {r['registros']} registros e {r['arquivos']} arquivo(s) "
          "conferidos.")
    print("Agora inicie o serviço do Advoga Fácil Servidor e conecte a conta de envio de e-mail de novo.")
    return 0


def _importar_migracao(args) -> int:
    import getpass
    from pathlib import Path

    from .services import migracao

    cfg = obter_configuracoes()
    cfg.garantir_pastas()
    senha = getpass.getpass("Senha do pacote de migração: ")
    try:
        r = migracao.importar(cfg, Path(args.pacote), senha)
    except Exception as exc:  # noqa: BLE001
        print(f"IMPORTAÇÃO NÃO REALIZADA: {exc}")
        print("O banco deste servidor continua vazio. Corrija o problema e tente de novo.")
        return 1
    print(r["mensagem"])
    for t in r["tabelas"]:
        print(f"  {t['nome']:45} {t['origem']:>8} -> {t['destino']:>8}  {'OK' if t['conferida'] else 'DIFERENTE'}")
    print(f"  Documentos e comprovantes conferidos: {r['arquivos']}")
    print()
    print(f"CÓDIGO DE CONFIRMAÇÃO (informe no servidor antigo): {r['codigo']}")
    print("O que falta fazer:")
    for p in r["pendencias"]:
        print(f"  - {p}")
    print("Relatório gravado em:", cfg.pasta_dados / "migracoes")
    return 0


def _backup_agora(args) -> int:
    from .core.db import configurar_banco, obter_sessao
    from .services import backup

    cfg = obter_configuracoes()
    configurar_banco(cfg.url_banco())
    db = next(obter_sessao())
    try:
        if args.comando == "backup":
            e = backup.executar(db, cfg, args.tipo, "manual")
        else:
            e = backup.testar_restauracao(db, cfg, "manual")
        print(f"{'Concluído' if e.situacao == 'sucesso' else 'FALHOU'}: {e.mensagem}")
        return 0 if e.situacao == "sucesso" else 1
    finally:
        db.close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="advoga-servidor", description="Servidor do Advoga Fácil")
    sub = parser.add_subparsers(dest="comando", required=True)
    sub.add_parser("servir", help="Atualiza o banco e inicia a API")
    sub.add_parser("migrar", help="Somente atualiza a estrutura do banco")
    sub.add_parser("codigo-instalacao", help="Mostra o código para criar a conta Master")
    b = sub.add_parser("backup", help="Faz um backup agora (usa a configuração da Central de Backups)")
    b.add_argument("--tipo", choices=["completo", "rapido"], default="completo")
    sub.add_parser("testar-restauracao", help="Restaura o último backup num banco temporário e confere")
    r = sub.add_parser("restaurar", help="Restaura um backup num banco VAZIO (veja o guia de recuperação)")
    r.add_argument("--origem", required=True, help="Pasta do backup, pasta de uma versão ou arquivo .afbk")
    r.add_argument("--banco", help="URL do banco de destino (padrão: o banco deste servidor)")
    im = sub.add_parser("importar-migracao",
                        help="Importa o pacote de migração (.afmig) num servidor recém-instalado")
    im.add_argument("--pacote", required=True, help="Caminho do arquivo .afmig")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

    if args.comando == "importar-migracao":
        return _importar_migracao(args)
    if args.comando == "restaurar":
        return _restaurar(args)
    if args.comando in ("backup", "testar-restauracao"):
        return _backup_agora(args)

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
