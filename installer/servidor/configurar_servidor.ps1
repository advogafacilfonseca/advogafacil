# Configuração do servidor Advoga Fácil. Executado pelo instalador (como administrador).
# É idempotente: pode rodar de novo em uma atualização sem apagar dados.
param([Parameter(Mandatory=$true)][string]$PastaPrograma)
$ErrorActionPreference = "Stop"

$Dados   = Join-Path $env:ProgramData "AdvogaFacil"
$Config  = Join-Path $Dados "config"
$PgData  = Join-Path $Dados "postgres\data"
$PgBin   = Join-Path $PastaPrograma "pgsql\bin"
$Porta   = 5433
$Log     = Join-Path $Dados "logs\instalacao.log"

foreach ($p in @($Dados, $Config, (Join-Path $Dados "documentos"), (Join-Path $Dados "logs"), (Join-Path $Dados "postgres"))) {
    New-Item -ItemType Directory -Force -Path $p | Out-Null
}
Start-Transcript -Path $Log -Append | Out-Null

# Somente Administradores e SYSTEM acessam a pasta de dados.
icacls $Dados /inheritance:r /grant:r "*S-1-5-32-544:(OI)(CI)F" "*S-1-5-18:(OI)(CI)F" | Out-Null
# O serviço do PostgreSQL roda como "Serviço de Rede" e precisa acessar somente a pasta do banco.
icacls (Join-Path $Dados "postgres") /grant:r "*S-1-5-20:(OI)(CI)F" | Out-Null
icacls $Dados /grant "*S-1-5-20:(X)" | Out-Null

function Nova-Senha([int]$n = 32) {
    $bytes = New-Object byte[] $n
    [System.Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($bytes)
    return ([Convert]::ToBase64String($bytes) -replace '[+/=]', 'x').Substring(0, $n)
}

$ArqServidor = Join-Path $Config "servidor.json"
if (-not (Test-Path (Join-Path $PgData "PG_VERSION"))) {
    $SenhaSuper = Nova-Senha
    $SenhaApp   = Nova-Senha
    # O initdb abandona os privilégios de administrador ao rodar (exigência do PostgreSQL). Por isso,
    # durante a criação do banco, o usuário que instala recebe acesso explícito só à pasta do banco;
    # o acesso é retirado logo depois.
    $Eu = [System.Security.Principal.WindowsIdentity]::GetCurrent().User.Value
    New-Item -ItemType Directory -Force -Path $PgData | Out-Null
    icacls $Dados /grant "*${Eu}:(RX)" | Out-Null
    icacls (Join-Path $Dados "postgres") /grant "*${Eu}:(OI)(CI)F" | Out-Null
    $pw = Join-Path $env:TEMP ("pw_" + [guid]::NewGuid().ToString() + ".txt")
    Set-Content -Path $pw -Value $SenhaSuper -NoNewline -Encoding ascii
    & "$PgBin\initdb.exe" -D $PgData -U postgres --pwfile=$pw -E UTF8 --auth=scram-sha-256 `
        --locale-provider=icu --icu-locale=pt-BR --locale=C
    $codigoInitdb = $LASTEXITCODE
    Remove-Item $pw -Force
    icacls $Dados /remove:g "*$Eu" | Out-Null
    icacls (Join-Path $Dados "postgres") /remove:g "*$Eu" | Out-Null
    if ($codigoInitdb -ne 0) { throw "Falha ao inicializar o PostgreSQL." }

    Add-Content (Join-Path $PgData "postgresql.conf") "`nlisten_addresses = '127.0.0.1'`nport = $Porta`n"
    & "$PgBin\pg_ctl.exe" register -N AdvogaFacilPostgreSQL -D $PgData -S auto
    Start-Service AdvogaFacilPostgreSQL
    Start-Sleep -Seconds 3

    $env:PGPASSWORD = $SenhaSuper
    & "$PgBin\psql.exe" -h 127.0.0.1 -p $Porta -U postgres -v ON_ERROR_STOP=1 `
        -c "CREATE ROLE advoga LOGIN PASSWORD '$SenhaApp';" `
        -c "CREATE DATABASE advoga OWNER advoga ENCODING 'UTF8';"
    if ($LASTEXITCODE -ne 0) { throw "Falha ao criar o banco do Advoga Fácil." }
    Remove-Item Env:\PGPASSWORD

    $cfg = @{
        database_url = "postgresql+psycopg://advoga:$SenhaApp@127.0.0.1:$Porta/advoga"
        postgres_superusuario = "postgres"
        postgres_superusuario_senha = $SenhaSuper
        postgres_porta = $Porta
        postgres_bin = $PgBin
    } | ConvertTo-Json
    Set-Content -Path $ArqServidor -Value $cfg -Encoding utf8
} else {
    if ((Get-Service AdvogaFacilPostgreSQL -ErrorAction SilentlyContinue) -eq $null) {
        & "$PgBin\pg_ctl.exe" register -N AdvogaFacilPostgreSQL -D $PgData -S auto
    }
    Start-Service AdvogaFacilPostgreSQL
    Start-Sleep -Seconds 3

    # Atualização: cópia de segurança do banco ANTES de atualizar a estrutura (fica em
    # C:\ProgramData\AdvogaFacil\atualizacoes; as 5 mais recentes são mantidas).
    $cfgAtual = Get-Content $ArqServidor -Raw | ConvertFrom-Json
    $PastaAtu = Join-Path $Dados "atualizacoes"
    New-Item -ItemType Directory -Force -Path $PastaAtu | Out-Null
    $Copia = Join-Path $PastaAtu ("antes-da-atualizacao_" + (Get-Date -Format "yyyy-MM-dd_HHmmss") + ".dump")
    $env:PGPASSWORD = $cfgAtual.postgres_superusuario_senha
    & "$PgBin\pg_dump.exe" -h 127.0.0.1 -p $Porta -U postgres -d advoga -Fc -f $Copia
    $codigoDump = $LASTEXITCODE
    Remove-Item Env:\PGPASSWORD
    if ($codigoDump -ne 0) { throw "Falha na cópia de segurança antes da atualização. Nada foi alterado no banco." }
    Get-ChildItem $PastaAtu -Filter "antes-da-atualizacao_*.dump" | Sort-Object Name -Descending |
        Select-Object -Skip 5 | Remove-Item -Force
}

# Cria/atualiza a estrutura do banco e gera o código de instalação (se ainda não houver Master).
& (Join-Path $PastaPrograma "servidor\AdvogaFacilServidor.exe") migrar
if ($LASTEXITCODE -ne 0) { throw "Falha ao preparar a estrutura do banco." }

# Serviço da API.
$Servico = Join-Path $PastaPrograma "servico\AdvogaFacilServico.exe"
if ((Get-Service AdvogaFacilServidor -ErrorAction SilentlyContinue) -eq $null) {
    & $Servico install
}
& $Servico restart

# Firewall: API acessível só pela rede local CONFIÁVEL (perfil Particular/Domínio) e pela
# Tailscale (100.64.0.0/10). Em redes públicas (Wi-Fi de café, aeroporto), só pela Tailscale.
# Nunca pela internet. O PostgreSQL não tem regra: ele só escuta em 127.0.0.1.
Get-NetFirewallRule -DisplayName "Advoga Fácil Servidor*" -ErrorAction SilentlyContinue | Remove-NetFirewallRule
New-NetFirewallRule -DisplayName "Advoga Fácil Servidor (rede do escritório)" -Direction Inbound -Protocol TCP `
    -LocalPort 8765 -RemoteAddress LocalSubnet -Action Allow -Profile Private,Domain | Out-Null
New-NetFirewallRule -DisplayName "Advoga Fácil Servidor (Tailscale)" -Direction Inbound -Protocol TCP `
    -LocalPort 8765 -RemoteAddress 100.64.0.0/10 -Action Allow -Profile Any | Out-Null

# Arquivo com os endereços e a impressão digital do certificado (atalho no menu Iniciar).
& (Join-Path $PastaPrograma "servidor\AdvogaFacilServidor.exe") informacoes | Out-Null

# A pasta de dados só abre como administrador. Os atalhos do menu Iniciar abrem o Bloco de Notas
# sem elevação, então a pessoa que instalou recebe leitura APENAS destes dois arquivos (o resto da
# pasta config, com senhas e chaves, continua restrito a Administradores e SYSTEM).
$Instalador = [System.Security.Principal.WindowsIdentity]::GetCurrent().User.Value
foreach ($arq in @("CODIGO_DE_INSTALACAO.txt", "COMO_CONECTAR.txt")) {
    $caminho = Join-Path $Config $arq
    if (Test-Path $caminho) { icacls $caminho /grant "*${Instalador}:(R)" | Out-Null }
}

Stop-Transcript | Out-Null
