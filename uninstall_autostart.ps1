# JARVIS - disinstalla l'avvio automatico registrato da setup_autostart.ps1.
#
# Rimuove i due Scheduled Task (\JARVIS\Bot, \JARVIS\VoiceDaemon). Non
# uccide processi gia' in esecuzione ne' tocca logs/ - solo la
# registrazione in Task Scheduler. Sicuro da rieseguire se i task sono
# gia' assenti.
#
# Uso: powershell -ExecutionPolicy Bypass -File uninstall_autostart.ps1

$ErrorActionPreference = 'Stop'

$TaskNames = @("Bot", "VoiceDaemon")

foreach ($name in $TaskNames) {
    $existing = Get-ScheduledTask -TaskName $name -TaskPath "\JARVIS\" -ErrorAction SilentlyContinue
    if ($existing) {
        Unregister-ScheduledTask -TaskName $name -TaskPath "\JARVIS\" -Confirm:$false
        Write-Host "Rimosso: \JARVIS\$name"
    } else {
        Write-Host "Non presente (gia' rimosso o mai registrato): \JARVIS\$name"
    }
}

Write-Host ""
Write-Host "Fatto. start.bat/start_voice.bat restano il modo per avviare JARVIS a mano."
