@echo off
REM Go to the directory where this .bat file is located
cd /d "%~dp0"

REM Activate your conda environment (replace 'myenv' with your env name)
call conda activate cmt_inventory

REM Run your Flask app
pythonw app.py

REM Keep window open
echo Running inventory system
pause