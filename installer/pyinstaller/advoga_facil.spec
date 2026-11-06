# -*- mode: python ; coding: utf-8 -*-
# Gera o aplicativo desktop "Advoga Fácil" (pasta dist/AdvogaFacil).
# Executar a partir da raiz do repositório:  pyinstaller installer/pyinstaller/advoga_facil.spec
from pathlib import Path

RAIZ = Path(SPECPATH).resolve().parents[1]
RECURSOS = RAIZ / "desktop" / "advoga_desktop" / "recursos"

a = Analysis(
    [str(Path(SPECPATH) / "entrada_app.py")],
    pathex=[str(RAIZ / "desktop"), str(RAIZ / "shared")],
    datas=[(str(RECURSOS / "logo.png"), "advoga_desktop/recursos"),
           (str(RECURSOS / "icone.png"), "advoga_desktop/recursos")],
    hiddenimports=["email_validator"],
    excludes=["tkinter", "PySide6.QtWebEngineCore", "PySide6.QtWebEngineWidgets",
              "PySide6.Qt3DCore", "PySide6.QtQuick", "PySide6.QtQml", "fastapi", "sqlalchemy"],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz, a.scripts, [],
    exclude_binaries=True,
    name="AdvogaFacil",
    icon=str(RAIZ / "installer" / "icones" / "advoga_facil.ico"),
    console=False,
    version=str(RAIZ / "installer" / "pyinstaller" / "versao_windows.txt"),
)
coll = COLLECT(exe, a.binaries, a.datas, name="AdvogaFacil")
