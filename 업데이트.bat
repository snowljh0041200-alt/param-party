@echo off
chcp 65001 >nul
cd /d "%~dp0"
git add .
git commit -m "v3.1.1 button fix"
git push
pause
