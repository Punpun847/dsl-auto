cd "D:\terminter01\gyso-backend-main (4)\gyso-backend-main"
$host.UI.RawUI.WindowTitle = "GYSO Monitor"
while ($true) {
    Clear-Host
    $now = Get-Date -Format "HH:mm:ss"
    Write-Host "=== STATUS @ $now ===" -ForegroundColor Cyan
    Write-Host ""
    for ($i = 1; $i -le 4; $i++) {
        Write-Host "--- Worker $i ---" -ForegroundColor Yellow
        $logFile = "celery$i.log"
        if (Test-Path $logFile) {
            $lines = Get-Content $logFile -Tail 2
            foreach ($line in $lines) {
                Write-Host $line -ForegroundColor White
            }
        }
        Write-Host ""
    }
    Write-Host "--- bulk_run ---" -ForegroundColor Magenta
    if (Test-Path "bulk_run.log") {
        Get-Content "bulk_run.log" -Tail 2 | ForEach-Object { Write-Host $_ -ForegroundColor White }
    }
    Start-Sleep 5
}
