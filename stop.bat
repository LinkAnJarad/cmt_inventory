@echo off
if not exist flask.pid (
    echo No PID file found. Is Flask running?
    exit /b
)

set /p PID=<flask.pid
echo Stopping Flask app with PID %PID%...
taskkill /PID %PID% /F

del flask.pid
echo Flask app stopped.
