@echo off
cd /d "%~dp0"
py -3 -m pip install -r requirements.txt || goto :error
py -3 app.py
:error
pause
