@echo off
rem Creates (or removes) the scheduled task. See install_task.ps1 for the settings.
rem Creating the task for another user needs an Administrator Command Prompt;
rem if you are logged on as the task user, a normal double-click is enough.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0install_task.ps1" %*
echo.
pause
