@echo off
chcp 65001 >nul
title Build - CV Screener portable
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0build-cv-screener-portable.ps1"
echo.
pause
