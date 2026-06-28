@echo off
chcp 65001 >nul
title AIRA - 启动器

echo ============================================
echo   Academic-information-report-agent v2.0
echo   Trying to start all services...
echo ============================================
echo.

:: 后端 (FastAPI, port 8138)
echo [1/3] start backend...
start "AIRA - 后端 :8138" cmd /k "cd /d %~dp0 && start /b cmd /c call %~dp0_title_keep.bat AIRA - 后端 :8138 && python -m uvicorn backend.main:app --host 0.0.0.0 --port 8138 --reload"

echo    wait for backend (5s)...
timeout /t 5 /nobreak >nul

:: 前端 (Vite, port 7860)
echo [2/3] start frontend...
start "AIRA - 前端 :7860" cmd /k "cd /d %~dp0frontend && start /b cmd /c call %~dp0_title_keep.bat AIRA - 前端 :7860 && npm run dev -- --host 0.0.0.0 --port 7860"

echo    wait for frontend...
timeout /t 3 /nobreak >nul

:: 打开浏览器
echo [3/3] open browser...
start msedge http://localhost:7860

echo.
echo ============================================
echo   All starts up！
echo   frontend: http://localhost:7860
echo   API document:  http://localhost:8138/docs
echo ============================================
echo.
echo shut down this window will not stop the service.
echo.

pause
