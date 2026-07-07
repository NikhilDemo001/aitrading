# watchdog.ps1 - keeps the trading bot alive and captures its console output.
# (ASCII only: PowerShell 5.1 reads BOM-less files as ANSI and chokes on unicode dashes.)
#
# Why this exists (2026-07-06): the bot process died silently mid-session (~14:35); the
# 15:10 square-off never ran and positions sat unmanaged until a manual kill switch at
# 20:51. There was no log file, so the crash cause is unknowable. This script:
#   1. writes ALL bot output (stdout+stderr) to logs\bot_YYYY-MM-DD.log
#   2. restarts the bot automatically if the process exits for any reason
#   3. backs off 30s when the bot dies within 60s of starting (crash-loop guard)
#
# Start:  powershell -NoProfile -ExecutionPolicy Bypass -File watchdog.ps1
# Stop:   .\stop_bot.ps1   (creates logs\STOP so the watchdog exits instead of restarting)

$repo = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $repo   # main.py resolves config.json/static/certs relative to cwd

$logDir = Join-Path $repo "logs"
New-Item -ItemType Directory -Force $logDir | Out-Null
$stopFile = Join-Path $logDir "STOP"

# Single instance: if the bot (or another watchdog's bot) already listens on :5000, leave.
if (Get-NetTCPConnection -LocalPort 5000 -State Listen -ErrorAction SilentlyContinue) {
    Write-Output "Bot already listening on :5000 - watchdog exiting."
    exit 0
}

# A stale STOP sentinel from a previous shutdown must not block this start.
if (Test-Path $stopFile) { Remove-Item $stopFile -Force }

$env:PYTHONIOENCODING = "utf-8"
$env:PYTHONUNBUFFERED = "1"

while ($true) {
    $log = Join-Path $logDir ("bot_" + (Get-Date -Format "yyyy-MM-dd") + ".log")

    # Re-check every iteration: if another process owns :5000 (second watchdog, manual
    # start), exit instead of crash-looping on a port that will never bind.
    if (Get-NetTCPConnection -LocalPort 5000 -State Listen -ErrorAction SilentlyContinue) {
        Add-Content $log "===== WATCHDOG: another process owns :5000 - exiting. ====="
        break
    }

    $started = Get-Date
    Add-Content $log ("`n===== WATCHDOG: starting bot at " + $started.ToString("yyyy-MM-dd HH:mm:ss") + " =====")

    # cmd.exe does the redirection: PS 5.1 wraps native stderr in ErrorRecords, cmd does not.
    cmd /c "python main.py >> `"$log`" 2>&1"
    $code = $LASTEXITCODE

    $ranSeconds = [int]((Get-Date) - $started).TotalSeconds
    Add-Content $log ("===== WATCHDOG: bot exited code=$code after ${ranSeconds}s at " + (Get-Date -Format "HH:mm:ss") + " =====")

    if (Test-Path $stopFile) {
        Add-Content $log "===== WATCHDOG: STOP sentinel found - not restarting. ====="
        Remove-Item $stopFile -Force
        break
    }

    if ($ranSeconds -lt 60) {
        Add-Content $log "===== WATCHDOG: bot died within 60s - waiting 30s before restart (crash-loop guard). ====="
        Start-Sleep -Seconds 30
    } else {
        Start-Sleep -Seconds 5
    }
}
