@echo off
chcp 65001 >nul
title Ban lam viec thiep - DUNG DONG cua so nay khi con dung tool
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0app\run.ps1"
if errorlevel 1 pause
