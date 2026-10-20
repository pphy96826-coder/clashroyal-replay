@echo off
setlocal
chcp 65001 >nul
set "RR_TARGET=%~1"
if not defined RR_TARGET set /p "RR_TARGET=请输入已有 Windows 完整环境根目录（不要加引号）："
if not exist "%RR_TARGET%\tools\python\python.exe" (
  echo 未找到完整环境自带的 Python，没有修改任何文件。
  pause
  exit /b 1
)
"%RR_TARGET%\tools\python\python.exe" -X utf8 "%~dp0scripts\apply_update.py" --target "%RR_TARGET%"
if errorlevel 1 (echo 更新未完成，请查看上方提示。) else (echo 更新完成。请使用原来的入口打开控制台；实例配置及运行时均保留。)
pause
