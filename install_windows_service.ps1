<#
install_windows_service.ps1 - run clipshare automatically at Windows logon.

Registers a Scheduled Task that starts clipshare in the background (hidden,
no console window) using pythonw.exe, so it works like a service:
- starts when you log in,
- restarts automatically if it exits unexpectedly,
- keeps sharing the clipboard as long as the session is active.

For a true Windows service (Services.msc) you can instead wrap the same
command with NSSM (https://nssm.cc), see README.md.

Usage (run in PowerShell):
  powershell -ExecutionPolicy Bypass -File install_windows_service.ps1 -Install
  powershell -ExecutionPolicy Bypass -File install_windows_service.ps1 -Status
  powershell -ExecutionPolicy Bypass -File install_windows_service.ps1 -Restart
  powershell -ExecutionPolicy Bypass -File install_windows_service.ps1 -Uninstall

Optional parameters:
  -RepoDir <path>    clipshare folder (default: this script's folder)
  -PythonExe <path>  pythonw.exe path (auto-detected if omitted)
  -RecvDir  <path>   where received files are stored
                     (default: <RepoDir>\clipshare_recv)
  -Peers   "a,b,c"   explicit peer IPs, comma separated (default: auto-discovery)
  -TaskName <name>   scheduled task name (default: clipshare)
#>

param(
    [switch]$Install,
    [switch]$Restart,
    [switch]$Uninstall,
    [switch]$Status,
    [string]$RepoDir = (Split-Path -Parent $MyInvocation.MyCommand.Path),
    [string]$PythonExe = "",
    [string]$RecvDir = "",
    [string]$Peers = "",
    [string]$TaskName = "clipshare"
)

$ErrorActionPreference = "Stop"

function Get-PythonW {
    if ($PythonExe -and (Test-Path $PythonExe)) { return (Resolve-Path $PythonExe).Path }
    $patterns = @(
        "$env:LOCALAPPDATA\Programs\Python\Python*\pythonw.exe",
        "$env:LOCALAPPDATA\Programs\Python\Python3*\pythonw.exe",
        "C:\Python*\pythonw.exe",
        "C:\Program Files\Python*\pythonw.exe"
    )
    foreach ($p in $patterns) {
        $hit = Get-ChildItem -Path $p -ErrorAction SilentlyContinue | Select-Object -First 1
        if ($hit) { return $hit.FullName }
    }
    $cmd = Get-Command pythonw.exe -ErrorAction SilentlyContinue
    if ($cmd) { return $cmd.Source }
    throw "pythonw.exe not found. Reinstall Python (check 'Add python.exe to PATH') or pass -PythonExe."
}

function Install-ClipshareTask {
    $py = Get-PythonW
    $script = Join-Path $RepoDir "clipshare.py"
    if (-not (Test-Path $script)) { throw "clipshare.py not found in: $RepoDir" }
    if (-not $RecvDir) { $RecvDir = Join-Path $RepoDir "clipshare_recv" }
    if (-not (Test-Path $RecvDir)) { New-Item -ItemType Directory -Path $RecvDir | Out-Null }

    $arg = "`"$script`" --recv-dir `"$RecvDir`""
    if ($Peers) {
        $peerList = (($Peers -split ",") | ForEach-Object { $_.Trim() } | Where-Object { $_ })
        foreach ($ip in $peerList) { $arg += " --peer `"$ip`"" }
    }

    $action    = New-ScheduledTaskAction -Execute $py -Argument $arg -WorkingDirectory $RepoDir
    $trigger   = New-ScheduledTaskTrigger -AtLogOn
    $settings  = New-ScheduledTaskSettingsSet `
                     -Hidden `
                     -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
                     -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1) `
                     -ExecutionTimeLimit ([TimeSpan]::Zero)
    $principal = New-ScheduledTaskPrincipal -UserId "$env:USERDOMAIN\$env:USERNAME" `
                     -LogonType Interactive -RunLevel Limited

    Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger `
                           -Settings $settings -Principal $principal -Force | Out-Null
    Start-ScheduledTask -TaskName $TaskName
    Write-Host "[*] clipshare task '$TaskName' installed and started."
    Write-Host "[*] Python      : $py"
    Write-Host "[*] Script      : $script"
    Write-Host "[*] Recv dir    : $RecvDir"
}

function Uninstall-ClipshareTask {
    Stop-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false -ErrorAction SilentlyContinue
    Write-Host "[*] clipshare task '$TaskName' removed."
}

function Show-ClipshareTask {
    $t = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
    if ($t) {
        Get-ScheduledTaskInfo -TaskName $TaskName |
            Select-Object TaskName, LastRunTime, LastTaskResult, NextRunTime, NumberOfMissedRuns |
            Format-List
    } else {
        Write-Host "[*] Task '$TaskName' is not installed."
    }
}

function Restart-ClipshareTask {
    if (-not (Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue)) {
        Write-Host "[!] Task '$TaskName' is not installed. Run -Install first."
        return
    }
    Stop-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
    Start-ScheduledTask -TaskName $TaskName
    Write-Host "[*] Task '$TaskName' restarted."
    Show-ClipshareTask
}

if ($Install)    { Install-ClipshareTask }
elseif ($Restart) { Restart-ClipshareTask }
elseif ($Uninstall) { Uninstall-ClipshareTask }
elseif ($Status) { Show-ClipshareTask }
else {
    Write-Host "Usage: $($MyInvocation.MyCommand.Name) -Install | -Restart | -Status | -Uninstall"
    Write-Host "See the comment header for options."
}
