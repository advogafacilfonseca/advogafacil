; Instalador do servidor Advoga Fácil (somente no computador servidor).
; Inclui: API, PostgreSQL 16 (embutido, acessível só pelo próprio computador) e serviços do Windows.
; Os dados ficam em C:\ProgramData\AdvogaFacil e NÃO são apagados na desinstalação.
#define Versao "0.1.0"

[Setup]
AppId={{46C88E3C-024C-454A-9B61-1619169CBBF7}
AppName=Advoga Fácil Servidor
AppVersion={#Versao}
AppPublisher=Advoga Fácil
DefaultDirName={autopf}\Advoga Fácil Servidor
DefaultGroupName=Advoga Fácil Servidor
UninstallDisplayIcon={app}\servidor\AdvogaFacilServidor.exe
SetupIconFile=..\icones\advoga_facil.ico
OutputDir=..\..\dist\instaladores
OutputBaseFilename=AdvogaFacilServidor-Instalador-{#Versao}
Compression=lzma2/max
SolidCompression=yes
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0
WizardStyle=modern
PrivilegesRequired=admin

[Languages]
Name: "ptbr"; MessagesFile: "compiler:Languages\BrazilianPortuguese.isl"

[Files]
Source: "..\..\dist\AdvogaFacilServidor\*"; DestDir: "{app}\servidor"; Flags: recursesubdirs ignoreversion
Source: "..\..\dist\pgsql\*"; DestDir: "{app}\pgsql"; Flags: recursesubdirs ignoreversion
Source: "..\..\dist\winsw\WinSW-x64.exe"; DestDir: "{app}\servico"; DestName: "AdvogaFacilServico.exe"; Flags: ignoreversion
Source: "..\servidor\AdvogaFacilServico.xml"; DestDir: "{app}\servico"; Flags: ignoreversion
Source: "..\servidor\configurar_servidor.ps1"; DestDir: "{app}\scripts"; Flags: ignoreversion
Source: "..\servidor\remover_servicos.ps1"; DestDir: "{app}\scripts"; Flags: ignoreversion

[Icons]
Name: "{group}\Código de instalação (conta Master)"; Filename: "{commonappdata}\AdvogaFacil\config\CODIGO_DE_INSTALACAO.txt"
Name: "{group}\Como conectar os computadores"; Filename: "{commonappdata}\AdvogaFacil\config\COMO_CONECTAR.txt"
Name: "{group}\Pasta de dados do servidor"; Filename: "{commonappdata}\AdvogaFacil"
Name: "{group}\Desinstalar Advoga Fácil Servidor"; Filename: "{uninstallexe}"

[Run]
Filename: "powershell.exe"; Parameters: "-NoProfile -ExecutionPolicy Bypass -File ""{app}\scripts\configurar_servidor.ps1"" -PastaPrograma ""{app}"""; StatusMsg: "Configurando banco de dados e serviços do servidor..."; Flags: runhidden waituntilterminated

[UninstallRun]
Filename: "powershell.exe"; Parameters: "-NoProfile -ExecutionPolicy Bypass -File ""{app}\scripts\remover_servicos.ps1"" -PastaPrograma ""{app}"""; Flags: runhidden waituntilterminated; RunOnceId: "RemoverServicos"

[Code]
// Numa atualização, os serviços precisam parar antes de os arquivos serem substituídos
// (programas em execução ficam travados pelo Windows). Os dados não são tocados.
procedure PararServico(const Nome: String);
var
  Codigo: Integer;
begin
  Exec(ExpandConstant('{sys}\net.exe'), 'stop ' + Nome + ' /y', '', SW_HIDE, ewWaitUntilTerminated, Codigo);
end;

function PrepareToInstall(var NeedsRestart: Boolean): String;
begin
  PararServico('AdvogaFacilServidor');
  PararServico('AdvogaFacilPostgreSQL');
  Result := '';
end;
