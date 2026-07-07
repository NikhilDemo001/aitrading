# stop_bot.ps1 - cleanly stops the bot AND its watchdog.
# Without the STOP sentinel the watchdog would immediately restart the bot.
# (ASCII only: PowerShell 5.1 reads BOM-less files as ANSI.)

$repo = Split-Path -Parent $MyInvocation.MyCommand.Path
$logDir = Join-Path $repo "logs"
New-Item -ItemType Directory -Force $logDir | Out-Null

# 1. Tell the watchdog not to restart.
New-Item -ItemType File -Force (Join-Path $logDir "STOP") | Out-Null

# 2. Stop the bot process listening on :5000.
$conn = Get-NetTCPConnection -LocalPort 5000 -State Listen -ErrorAction SilentlyContinue
if ($conn) {
    $botPid = ($conn | Select-Object -First 1).OwningProcess
    Stop-Process -Id $botPid -Force -Confirm:$false
    Write-Output "Bot process (PID $botPid) stopped. Watchdog will exit on its own."
} else {
    Write-Output "No bot listening on :5000. STOP sentinel left for any running watchdog."
}
