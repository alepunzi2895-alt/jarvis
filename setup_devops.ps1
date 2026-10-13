$ErrorActionPreference = 'Stop'
$jarvisRoot = $PSScriptRoot
$jarvisConfig = Get-Content -LiteralPath (Join-Path $jarvisRoot '.azure-devops.json') -Raw | ConvertFrom-Json
$jarvisCli = Get-Command az -ErrorAction SilentlyContinue
if ($jarvisCli) { $jarvisCliPath = $jarvisCli.Source }
else { $jarvisCliPath = Join-Path $env:ProgramFiles 'Microsoft SDKs\Azure\CLI2\wbin\az.cmd' }
if (-not (Test-Path -LiteralPath $jarvisCliPath)) { throw 'Installa Microsoft Azure CLI e riprova.' }
$jarvisPreviousConfig = $env:AZURE_CONFIG_DIR
try {
    $env:AZURE_CONFIG_DIR = Join-Path $jarvisRoot '.azure-auth'
    & $jarvisCliPath login --tenant $jarvisConfig.tenant --skip-subscription-discovery --scope '499b84ac-1321-427f-aa17-267ca6975798/.default' --output none
    if ($LASTEXITCODE -ne 0) { throw 'Accesso Microsoft non completato.' }
    Write-Output 'Accesso Microsoft completato. JARVIS puo leggere i deploy.'
} finally {
    $env:AZURE_CONFIG_DIR = $jarvisPreviousConfig
}
