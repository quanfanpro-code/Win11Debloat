@echo off
chcp 65001 >nul
cd /d "%~dp0"
"%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe" -NoProfile -ExecutionPolicy Bypass -File "%~dp0Win11Debloat.ps1" -Language zh-CN
echo 按任意键关闭此窗口。
pause >nul
