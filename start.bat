@echo off
chcp 65001 >nul
title AIRA - 启动器
cd /d "%~dp0"

echo ============================================
echo   Academic-information-report-agent v2.0
echo   Trying to start all services...
echo ============================================
echo.

:: 检查 venv 是否存在
if not exist "venv\Scripts\activate.bat" (
    echo [ERROR] venv not found: venv\Scripts\activate.bat
    echo         Please run first: python -m venv venv
    echo         then:            venv\Scripts\pip install -r requirements.txt
    pause
    exit /b 1
)

:: 后端 (FastAPI, port 8138) — 先激活 venv 再启动
echo [1/3] start backend...
start "AIRA - 后端 :8138" /d "%~dp0" cmd /k "title AIRA - 后端 :8138 && call venv\Scripts\activate.bat && python -m uvicorn backend.main:app --host 0.0.0.0 --port 8138 --reload"

echo    wait for backend (5s)...
timeout /t 5 /nobreak >nul

:: 前端 (Vite, port 7860) — 绕过 npm（npm 会重置窗口标题），直接用 node 启动 vite
echo [2/3] start frontend...
if not exist "frontend\node_modules\vite\bin\vite.js" (
    echo [ERROR] frontend dependencies not installed.
    echo         Please run first: cd frontend ^& npm install
    pause
    exit /b 1
)
start "AIRA - 前端 :7860" /d "%~dp0frontend" cmd /k "title AIRA - 前端 :7860 && node node_modules\vite\bin\vite.js --host 0.0.0.0 --port 7860"

echo    wait for frontend...
timeout /t 3 /nobreak >nul

:: 打开浏览器
echo [3/3] open browser...
start msedge http://localhost:7860

echo.
echo ============================================
echo   All started!
echo   frontend:     http://localhost:7860
echo   API document: http://localhost:8138/docs
echo ============================================
echo.
echo Close this window will NOT stop the services.