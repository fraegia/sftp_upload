@echo off
rem Usage: run.bat [config.ini]   (default: config.ini next to this file)
py -3 "%~dp0sftp_push.py" %*
exit /b %errorlevel%
