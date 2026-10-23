@echo off
chcp 65001 >nul
title Build - Indeed downloader portable
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0build-indeed-portable.ps1"
echo.
pause
