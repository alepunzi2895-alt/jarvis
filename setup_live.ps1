param([switch]$Start)
$ErrorActionPreference = 'Stop'
$RepoRoot = $PSScriptRoot
$VenvPy = Join-Path $RepoRoot '.venv\Scripts\python.exe'
$TailscaleExe = Join-Path $env:ProgramFiles 'Tailscale\tailscale.exe'
if (-not (Test-Path -LiteralPath $VenvPy)) { throw 'Installa prima le dipendenze Python in .venv.' }
if (-not (Test-Path -LiteralPath $TailscaleExe)) { throw 'Installa Tailscale e accedi con lo stesso account del telefono.' }
$tailStatus = & $TailscaleExe status --json | ConvertFrom-Json
if ($LASTEXITCODE -ne 0 -or $tailStatus.BackendState -ne 'Running') { throw 'Accedi a Tailscale sul PC prima di continuare.' }
$dnsName = $tailStatus.Self.DNSName.TrimEnd('.')
if (-not $dnsName) { throw 'Abilita MagicDNS nella rete Tailscale.' }
$liveOrigin = 'https://' + $dnsName + ':8443'
$serveConfig = & $TailscaleExe serve status --json | ConvertFrom-Json
if ($LASTEXITCODE -ne 0) { throw 'Impossibile leggere Tailscale Serve.' }
$existingWeb = $serveConfig.Web.PSObject.Properties | Where-Object { $_.Name -eq ($dnsName + ':8443') }
$existingTCP = $serveConfig.TCP.PSObject.Properties | Where-Object { $_.Name -eq '8443' }
if ($existingTCP -and (-not $existingWeb -or $existingWeb.Value.Handlers.'/'.Proxy -ne 'http://127.0.0.1:8765')) {
    throw 'Porta Tailscale 8443 gia utilizzata: configurazione conservata.'
}
& $TailscaleExe serve --bg --https=8443 --yes http://127.0.0.1:8765
if ($LASTEXITCODE -ne 0) { throw 'HTTPS Tailscale non attivato.' }
@{port = 8765; origin = $liveOrigin} | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $RepoRoot '.live-config.json') -Encoding UTF8
New-Item -ItemType Directory -Force -Path (Join-Path $RepoRoot 'logs'), (Join-Path $RepoRoot 'scripts') | Out-Null
$Q = [char]34
function New-LiveLauncher([string]$Name, [string]$PythonArgs) {
    $launcher = Join-Path $RepoRoot "scripts\run_$($Name)_hidden.vbs"
    $logPath = Join-Path $RepoRoot "logs\$Name.log"
    $realCmd = "cmd.exe /c $Q$Q$VenvPy$Q $PythonArgs > $Q$logPath$Q 2>&1$Q"
    $escaped = $realCmd.Replace([string]$Q, "$Q$Q")
    @('Set objShell = CreateObject("WScript.Shell")',
      "objShell.CurrentDirectory = ""$RepoRoot""",
      "exitCode = objShell.Run(""$escaped"", 0, True)",
      'WScript.Quit exitCode') | Set-Content -LiteralPath $launcher -Encoding ASCII
    return $launcher
}
$vbsPath = New-LiveLauncher 'live' '-u -m core.live_server'
$currentUser = "$env:USERDOMAIN\$env:USERNAME"
$action = New-ScheduledTaskAction -Execute 'wscript.exe' -Argument "$Q$vbsPath$Q" -WorkingDirectory $RepoRoot
$trigger = New-ScheduledTaskTrigger -AtLogOn -User $currentUser
$settings = New-ScheduledTaskSettingsSet -RestartCount 5 -RestartInterval (New-TimeSpan -Minutes 2) `
    -ExecutionTimeLimit ([TimeSpan]::Zero) -MultipleInstances IgnoreNew -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries -StartWhenAvailable
Register-ScheduledTask -TaskName 'LiveBridge' -TaskPath '\JARVIS\' -Action $action -Trigger $trigger `
    -Settings $settings -Description 'JARVIS - voce privata iPhone/PC' -User $currentUser -RunLevel Limited -Force | Out-Null
$cleanupVbs = New-LiveLauncher 'audio_cleanup' '-u -c "from core.web_bridge import _prune_audio; _prune_audio()"'
$cleanupAction = New-ScheduledTaskAction -Execute 'wscript.exe' -Argument "$Q$cleanupVbs$Q" -WorkingDirectory $RepoRoot
$cleanupTrigger = New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(1) -RepetitionInterval (New-TimeSpan -Minutes 5)
$cleanupSettings = New-ScheduledTaskSettingsSet -ExecutionTimeLimit (New-TimeSpan -Minutes 2) `
    -MultipleInstances IgnoreNew -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable
Register-ScheduledTask -TaskName 'AudioCleanup' -TaskPath '\JARVIS\' -Action $cleanupAction -Trigger $cleanupTrigger `
    -Settings $cleanupSettings -Description 'JARVIS - conserva gli ultimi 5 audio completati' `
    -User $currentUser -RunLevel Limited -Force | Out-Null
if ($Start) {
    Start-ScheduledTask -TaskPath '\JARVIS\' -TaskName 'LiveBridge'
    Start-ScheduledTask -TaskPath '\JARVIS\' -TaskName 'AudioCleanup'
}
Write-Host "Dashboard privata: $liveOrigin"
Write-Host 'Password locale nel file .live-password (creato al primo avvio).'
Write-Host 'Disinstallazione autostart: ./uninstall_live.ps1'
