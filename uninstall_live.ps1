# Disabilita solo l'avvio automatico. Nessun processo o log viene rimosso.
foreach ($name in @('LiveBridge', 'AudioCleanup')) {
    $task = Get-ScheduledTask -TaskPath '\JARVIS\' -TaskName $name -ErrorAction SilentlyContinue
    if ($task) { Unregister-ScheduledTask -TaskPath '\JARVIS\' -TaskName $name -Confirm:$false }
}
Write-Host 'Task LiveBridge/AudioCleanup rimossi. Il processo attivo resta fino alla chiusura della sessione.'
Write-Host 'Per disattivare anche HTTPS privato: tailscale serve --https=8443 off'
