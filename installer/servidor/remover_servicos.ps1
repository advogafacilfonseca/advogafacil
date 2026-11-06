# Remove apenas os serviços e as regras de firewall. Os DADOS em C:\ProgramData\AdvogaFacil são preservados.
param([Parameter(Mandatory=$true)][string]$PastaPrograma)
$ErrorActionPreference = "Continue"
$Log = Join-Path $env:ProgramData "AdvogaFacil\logs\desinstalacao.log"
Start-Transcript -Path $Log -Append | Out-Null

$Servico = Join-Path $PastaPrograma "servico\AdvogaFacilServico.exe"
if (Get-Service AdvogaFacilServidor -ErrorAction SilentlyContinue) {
    & $Servico stop
    & $Servico uninstall
}
if (Get-Service AdvogaFacilPostgreSQL -ErrorAction SilentlyContinue) {
    Stop-Service AdvogaFacilPostgreSQL -Force -ErrorAction SilentlyContinue
    & (Join-Path $PastaPrograma "pgsql\bin\pg_ctl.exe") unregister -N AdvogaFacilPostgreSQL
}

# Regras de firewall: remove por nome e confere (tenta de novo se o Windows ainda não aplicou).
for ($i = 0; $i -lt 5; $i++) {
    $regras = Get-NetFirewallRule -DisplayName "Advoga Fácil Servidor*" -ErrorAction SilentlyContinue
    if (-not $regras) { break }
    $regras | Remove-NetFirewallRule -ErrorAction SilentlyContinue
    Start-Sleep -Seconds 2
}
if (Get-NetFirewallRule -DisplayName "Advoga Fácil Servidor*" -ErrorAction SilentlyContinue) {
    Write-Output "ATENÇÃO: não foi possível remover as regras de firewall do Advoga Fácil Servidor."
}
Stop-Transcript | Out-Null
