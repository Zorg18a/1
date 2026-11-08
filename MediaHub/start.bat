@echo off
cd /d "%~dp0"
py -m pip install -q -U "yt-dlp[default]" playwright
py app.py
pause
