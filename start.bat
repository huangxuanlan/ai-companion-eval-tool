@echo off
chcp 65001 >nul 2>&1
title 长文模式多轮对话验证工具

echo ============================================================
echo   长文模式多轮对话验证工具 - 一键启动
echo ============================================================
echo.

cd /d "%~dp0"

echo [1/2] 检查 Python 环境并准备虚拟环境...
py -3 --version >nul 2>&1
if not errorlevel 1 (
    py -3 launcher.py
    if errorlevel 1 pause
    exit /b %errorlevel%
)

python --version >nul 2>&1
if errorlevel 1 (
    echo [ERROR] 未找到 Python，请安装 Python 3.11+ 并添加到 PATH
    pause
    exit /b 1
)

python launcher.py
if errorlevel 1 pause
