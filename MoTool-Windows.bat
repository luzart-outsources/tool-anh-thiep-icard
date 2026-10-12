@echo off
rem Bam dup de mo Ban lam viec thiep tren Windows. Cua so nay phai de mo trong luc dung tool.
chcp 65001 >nul
title Ban lam viec thiep - DUNG DONG cua so nay khi con dung tool
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0release\app\run.ps1" %*
if errorlevel 1 pause
