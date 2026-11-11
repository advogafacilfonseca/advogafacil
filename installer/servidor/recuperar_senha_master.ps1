# Recuperação da senha da conta Master (atalho no menu Iniciar do servidor).
# Só funciona no próprio computador servidor e como administrador do Windows.
$ErrorActionPreference = "Stop"
$eu = [Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()
if (-not $eu.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    # Pede a elevação (janela "Deseja permitir...?") e roda de novo como administrador.
    Start-Process powershell.exe -Verb RunAs -ArgumentList "-NoProfile -ExecutionPolicy Bypass -File `"$PSCommandPath`""
    exit
}
$Host.UI.RawUI.WindowTitle = "Advoga Fácil - Recuperar a senha da Master"
$Exe = Join-Path (Split-Path $PSScriptRoot -Parent) "servidor\AdvogaFacilServidor.exe"
Write-Host ""
Write-Host "RECUPERAR A SENHA DA CONTA MASTER" -ForegroundColor Yellow
Write-Host ""
Write-Host "Será criada uma senha provisória para a Master. A senha atual deixa de funcionar,"
Write-Host "as sessões abertas da Master são encerradas e a troca fica registrada na Auditoria."
Write-Host ""
$resp = Read-Host "Digite SIM para continuar"
if ($resp.Trim().ToUpper() -ne "SIM") { Write-Host "Nada foi alterado."; Read-Host "Pressione Enter para fechar"; exit }
Write-Host ""
& $Exe recuperar-senha-master
Write-Host ""
if ($LASTEXITCODE -eq 0) {
    Write-Host "Anote a senha provisória, abra o Advoga Fácil e entre com ela." -ForegroundColor Green
    Write-Host "O sistema vai pedir para você criar uma senha nova."
} else {
    Write-Host "Não foi possível redefinir a senha. Confira se o serviço do banco está ligado." -ForegroundColor Red
}
Write-Host ""
Read-Host "Pressione Enter para fechar"
