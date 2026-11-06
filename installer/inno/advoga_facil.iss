; Instalador do aplicativo Advoga Fácil (cada computador do escritório).
; Compilar no Windows: iscc installer\inno\advoga_facil.iss  (após o PyInstaller)
#define Versao "0.1.0"

[Setup]
AppId={{8F1AD3C1-DD04-4067-BB82-A38E38D5ACBB}
AppName=Advoga Fácil
AppVersion={#Versao}
AppPublisher=Advoga Fácil
DefaultDirName={autopf}\Advoga Fácil
DefaultGroupName=Advoga Fácil
UninstallDisplayIcon={app}\AdvogaFacil.exe
SetupIconFile=..\icones\advoga_facil.ico
OutputDir=..\..\dist\instaladores
OutputBaseFilename=AdvogaFacil-Instalador-{#Versao}
Compression=lzma2/max
SolidCompression=yes
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0
WizardStyle=modern
PrivilegesRequired=admin

[Languages]
Name: "ptbr"; MessagesFile: "compiler:Languages\BrazilianPortuguese.isl"

[Tasks]
Name: "atalhodesktop"; Description: "Criar atalho na área de trabalho"; GroupDescription: "Atalhos:"

[Files]
Source: "..\..\dist\AdvogaFacil\*"; DestDir: "{app}"; Flags: recursesubdirs ignoreversion

[Icons]
Name: "{group}\Advoga Fácil"; Filename: "{app}\AdvogaFacil.exe"
Name: "{group}\Desinstalar Advoga Fácil"; Filename: "{uninstallexe}"
Name: "{autodesktop}\Advoga Fácil"; Filename: "{app}\AdvogaFacil.exe"; Tasks: atalhodesktop

[Run]
Filename: "{app}\AdvogaFacil.exe"; Description: "Abrir o Advoga Fácil"; Flags: nowait postinstall skipifsilent

; A desinstalação remove apenas o programa. Nenhum dado do escritório fica neste computador
; (os dados ficam no servidor), e a configuração local (%APPDATA%\AdvogaFacil) é preservada.
