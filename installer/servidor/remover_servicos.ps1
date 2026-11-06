# Remove apenas os serviços. Os DADOS em C:\ProgramData\AdvogaFacil são preservados.
param([Parameter(Mandatory=$true)][string]$PastaPrograma)
$Servico = Join-Path $PastaPrograma "servico\AdvogaFacilServico.exe"
if (Get-Service AdvogaFacilServidor -ErrorAction SilentlyContinue) { & $Servico stop; & $Servico uninstall }
if (Get-Service AdvogaFacilPostgreSQL -ErrorAction SilentlyContinue) {
    Stop-Service AdvogaFacilPostgreSQL
    & (Join-Path $PastaPrograma "pgsql\bin\pg_ctl.exe") unregister -N AdvogaFacilPostgreSQL
}
Get-NetFirewallRule -DisplayName "Advoga Fácil Servidor*" -ErrorAction SilentlyContinue | Remove-NetFirewallRule
