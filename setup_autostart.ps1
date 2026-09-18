# JARVIS - avvio automatico all'accesso Windows.
#
# Registra due Scheduled Task (\JARVIS\Bot, \JARVIS\VoiceDaemon) che avviano
# bot.py e core.voice.daemon ad ogni logon dell'utente corrente, senza
# finestra visibile, con restart automatico se il processo crasha.
#
# Idempotente: rieseguibile senza precondizioni (bootstrap .venv se manca,
# -Force su Register-ScheduledTask). Non tocca start.bat/start_voice.bat,
# che restano il modo di avviare JARVIS a mano.
#
# Uso: powershell -ExecutionPolicy Bypass -File setup_autostart.ps1

$ErrorActionPreference = 'Stop'

$RepoRoot   = Split-Path -Parent $MyInvocation.MyCommand.Path
$VenvDir    = Join-Path $RepoRoot ".venv"
$VenvPy     = Join-Path $VenvDir "Scripts\python.exe"
$LogsDir    = Join-Path $RepoRoot "logs"
$ScriptsDir = Join-Path $RepoRoot "scripts"

# Un solo carattere di doppio apice: costruire le stringhe per
# concatenazione (invece di lettera-per-lettera dentro un literal
# PowerShell) evita l'inferno del triplo livello di escaping
# (PowerShell -> cmd.exe -> VBScript) che altrimenti serve per generare
# il launcher .vbs qui sotto.
$Q = [char]34

Write-Host "JARVIS - setup avvio automatico"
Write-Host "Repo: $RepoRoot"

if (-not (Test-Path $VenvPy)) {
    Write-Host "Creo .venv e installo le dipendenze (puo' richiedere qualche minuto)..."
    python -m venv $VenvDir
    & $VenvPy -m pip install -r (Join-Path $RepoRoot "requirements.txt")
}

New-Item -ItemType Directory -Force -Path $LogsDir | Out-Null
New-Item -ItemType Directory -Force -Path $ScriptsDir | Out-Null

function New-HiddenLauncher {
    <#
    Genera uno .vbs che lancia python.exe (finestra nascosta dal VBS) dentro un
    "cmd.exe /c" con stdout/stderr rediretti su file di log, e ASPETTA
    che il processo reale finisca prima di restituire il suo exit code.

    Due dettagli non ovvi, entrambi necessari:

    1. python.exe e' deliberato: il VBS nasconde la finestra, mentre cmd.exe
       resta agganciato al processo (pythonw.exe poteva restare orfano).
       Il redirect conserva stdout/stderr validi e un log leggibile.
    2. objShell.Run(..., 0, True) con il terzo parametro a True aspetta
       che il comando finisca e propaga il suo exit code. Se fosse False,
       Task Scheduler vedrebbe solo wscript.exe uscire subito con successo
       (il vero processo Python gira "dietro"), e il restart-on-failure
       configurato sul task non scatterebbe mai se poi il processo Python
       crasha per conto suo qualche secondo dopo.
    #>
    param(
        [Parameter(Mandatory)] [string]$Name,
        [Parameter(Mandatory)] [string]$PyArgs,
        [Parameter(Mandatory)] [string]$LogName
    )

    $vbsPath = Join-Path $ScriptsDir "$Name.vbs"
    $logPath = Join-Path $LogsDir $LogName

    # Comando reale voluto (il doppio apice subito dopo "/c " e' il trucco
    # standard cmd.exe per far sopravvivere path quotati con redirection
    # nella stessa riga):
    #   cmd.exe /c ""<python>" <args> > "<log>" 2>&1"
    $realCmd = "cmd.exe /c $Q$Q$VenvPy$Q $PyArgs > $Q$logPath$Q 2>&1$Q"

    # Dentro una stringa VBScript "...", ogni " letterale va raddoppiato.
    $vbsEscapedCmd = $realCmd.Replace([string]$Q, "$Q$Q")

    $vbsLines = @(
        'Set objShell = CreateObject("WScript.Shell")'
        "objShell.CurrentDirectory = ""$RepoRoot"""
        "exitCode = objShell.Run(""$vbsEscapedCmd"", 0, True)"
        'WScript.Quit exitCode'
    )
    Set-Content -Path $vbsPath -Value $vbsLines -Encoding ASCII
    return $vbsPath
}

$botVbs   = New-HiddenLauncher -Name "run_bot_hidden"   -PyArgs "bot.py"               -LogName "bot.log"
$voiceVbs = New-HiddenLauncher -Name "run_voice_hidden" -PyArgs "-m core.voice.daemon" -LogName "voice.log"

# Restart-on-failure vero (schtasks.exe da riga di comando non lo espone
# affatto - solo l'oggetto/XML del Task Scheduler ce l'ha).
$settings = New-ScheduledTaskSettingsSet `
    -RestartCount 5 `
    -RestartInterval (New-TimeSpan -Minutes 2) `
    -ExecutionTimeLimit ([TimeSpan]::Zero) `
    -MultipleInstances IgnoreNew `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -StartWhenAvailable
# Note su queste impostazioni:
# - ExecutionTimeLimit default di Task Scheduler e' 72 ore: ammazzerebbe
#   un processo sano dopo 3 giorni. Zero = nessun limite.
# - E' un portatile (vedi commento su JARVIS_MIC_DEVICE in .env): senza i
#   flag batteria, Task Scheduler ferma i task quando si stacca la corrente.
# - MultipleInstances IgnoreNew evita che Task Scheduler *stesso* lanci
#   due copie; non protegge da un avvio manuale di start.bat mentre il
#   task gira gia' (limite noto, non risolvibile senza toccare start.bat).

$currentUser = "$env:USERDOMAIN\$env:USERNAME"
$trigger = New-ScheduledTaskTrigger -AtLogOn -User $currentUser

$tasks = @(
    @{ Name = "Bot";         Vbs = $botVbs;   Descr = "JARVIS - bridge Telegram/web (bot.py)" }
    @{ Name = "VoiceDaemon"; Vbs = $voiceVbs; Descr = "JARVIS - daemon vocale nativo" }
)

foreach ($t in $tasks) {
    $action = New-ScheduledTaskAction -Execute "wscript.exe" -Argument "$Q$($t.Vbs)$Q" -WorkingDirectory $RepoRoot
    Register-ScheduledTask -TaskName $t.Name -TaskPath "\JARVIS\" `
        -Action $action -Trigger $trigger -Settings $settings `
        -Description $t.Descr -User $currentUser -RunLevel Limited -Force | Out-Null
    Write-Host "Registrato: \JARVIS\$($t.Name)"
}

Write-Host ""
Write-Host "Fatto. JARVIS partira' da solo al prossimo accesso (nessuna finestra visibile)."
Write-Host "Log: $LogsDir\bot.log , $LogsDir\voice.log"
Write-Host "Per disinstallare: powershell -ExecutionPolicy Bypass -File uninstall_autostart.ps1"
