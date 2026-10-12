@echo off
setlocal EnableExtensions
title PRINTFILM 一键部署
cd /d "%~dp0"

echo.
echo ========================================
echo   PRINTFILM 单机一键部署
echo ========================================
echo.
echo  本脚本会自动：
echo   0. 检测并生成 backend\.env（首次，从 .env.example）
echo   1. 检测依赖（Docker / Python 3.12+ / Node.js / FFmpeg）
echo   2. 启动 Postgres + Redis（Docker 容器）
echo   3. 初始化后端 venv + 前端依赖
echo   4. 启动 API(:8000) + 用户端(:5173) + 管理端(:5174)
echo   5. 自动打开浏览器
echo.
echo  前置安装（只需一次）：
echo   - Docker Desktop   https://www.docker.com/products/docker-desktop/
echo   - Python 3.12+     https://www.python.org/downloads/
echo   - Node.js 18+      https://nodejs.org/  （勾选 Add to PATH）
echo   - FFmpeg           https://ffmpeg.org/download.html （加入 PATH）
echo.
echo  三条能力（文本 / 图片 / 视频）默认走 Agnes 官方 API，
echo  启动后只需在「个人中心 → API」填一把 Agnes Key 即可使用。
echo.

REM 优先 PowerShell 7，回退 5.1
where pwsh >nul 2>&1
if %errorlevel%==0 (
    pwsh -NoProfile -ExecutionPolicy Bypass -File "%~dp0start_local.ps1"
) else (
    powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0start_local.ps1"
)

echo.
pause
