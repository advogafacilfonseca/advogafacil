# -*- mode: python ; coding: utf-8 -*-
# Gera o servidor "Advoga Fácil Servidor" (pasta dist/AdvogaFacilServidor).
from pathlib import Path

RAIZ = Path(SPECPATH).resolve().parents[1]
SRV = RAIZ / "server" / "advoga_server"

a = Analysis(
    [str(Path(SPECPATH) / "entrada_servidor.py")],
    pathex=[str(RAIZ / "server"), str(RAIZ / "shared")],
    datas=[(str(SRV / "alembic.ini"), "advoga_server"),
           (str(SRV / "alembic"), "advoga_server/alembic")],
    hiddenimports=["advoga_server.alembic.env", "psycopg", "psycopg_binary",
                   "uvicorn.logging", "uvicorn.loops.auto", "uvicorn.protocols.http.auto",
                   "uvicorn.protocols.websockets.auto", "uvicorn.lifespan.on", "email_validator"],
    excludes=["tkinter", "PySide6"],
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz, a.scripts, [],
    exclude_binaries=True,
    name="AdvogaFacilServidor",
    icon=str(RAIZ / "installer" / "icones" / "advoga_facil.ico"),
    console=True,
    version=str(RAIZ / "installer" / "pyinstaller" / "versao_windows.txt"),
)
coll = COLLECT(exe, a.binaries, a.datas, name="AdvogaFacilServidor")
