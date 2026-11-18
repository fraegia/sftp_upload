# Creates ONE scheduled task: runs "pythonw.exe sftp_push.py" once (no window) at logon of $TaskUser, as that user.
# Requires interval_seconds > 0 in config.ini (the script then keeps running by itself).
# Usage: install_task.bat           -> create / update the task
#        install_task.bat remove    -> delete the task

$TaskName     = 'SessionAdapter to CentralSite'
$TaskUser     = 'user'
$Pythonw      = 'C:\PythonXX\pythonw.exe'   # <-- set the real path of your pythonw.exe
$DelaySeconds = 30                          # wait after logon (network and SessionAdapter get time to start)

if ($args -contains 'remove') {
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
    Write-Host "Task '$TaskName' removed."
    exit
}

if (-not (Test-Path $Pythonw)) {
    $found = Get-Command pythonw.exe -ErrorAction SilentlyContinue
    if ($found) { $Pythonw = $found.Source }
}
if (-not (Test-Path $Pythonw)) {
    Write-Host "pythonw.exe not found. Edit `$Pythonw at the top of install_task.ps1."
    exit 1
}

$Script    = Join-Path $PSScriptRoot 'sftp_push.py'
$action    = New-ScheduledTaskAction -Execute $Pythonw -Argument ('"{0}"' -f $Script) -WorkingDirectory $PSScriptRoot
$trigger   = New-ScheduledTaskTrigger -AtLogOn -User $TaskUser
$trigger.Delay = "PT${DelaySeconds}S"
$principal = New-ScheduledTaskPrincipal -UserId $TaskUser -LogonType Interactive -RunLevel Limited
$settings  = New-ScheduledTaskSettingsSet -MultipleInstances IgnoreNew `
    -ExecutionTimeLimit ([TimeSpan]::Zero) `
    -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
    -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1)

Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger `
    -Principal $principal -Settings $settings -Force | Out-Null

Write-Host "Task '$TaskName' created."
Write-Host "It runs: $Pythonw `"$Script`""
Write-Host "Once, $DelaySeconds seconds after '$TaskUser' logs on, with no window."
