@echo off
title Push to GitHub

echo.
echo === AIRA - Push to GitHub ===
echo.

:: [0/5] Safety check
echo [0/5] Safety check...
git check-ignore .env >nul 2>&1
if %errorlevel% neq 0 (
    echo [WARN] .env is NOT ignored by .gitignore!
)

git check-ignore configs/ >nul 2>&1
if %errorlevel% neq 0 (
    echo [WARN] configs/ is NOT ignored by .gitignore! Aborting.
    pause
    exit /b 1
)

for /f "delims=" %%f in ('git ls-files --cached configs\ 2^>nul') do (
    echo [WARN] configs\ file staged: %%f, unstaging...
    git rm --cached "%%f" >nul 2>&1
)

echo [OK] Safety check passed.
echo.

:: [1/5] Show changes
echo [1/5] Changes preview:
echo -------------------------------------------
git status --short
echo -------------------------------------------
echo.

set /p confirm="Confirm push? (Y/N): "
if /i not "%confirm%"=="Y" (
    echo Cancelled.
    exit /b 0
)
echo.

:: [2/5] Add files
echo [2/5] Adding files...
git add -A
if %errorlevel% neq 0 (
    echo [ERROR] git add failed.
    pause
    exit /b 1
)
echo [OK] Files added.
echo.

:: [3/5] Commit message
for /f "tokens=1-3 delims=/- " %%a in ('date /t') do (
    set YY=%%a
    set MM=%%b
    set DD=%%c
)

set /p desc="[3/5] Brief description (enter to skip): "
if "%desc%"=="" (
    set commit_msg="[%YY%-%MM%-%DD%] Routine update"
) else (
    set commit_msg="[%YY%-%MM%-%DD%] %desc%"
)

echo Commit message: %commit_msg%

set /p ver="[3/5] Release version (e.g. 2.0.1, enter to skip tag): "
echo.

:: [4/5] Commit
echo [4/5] Committing...
git commit -m %commit_msg%
if %errorlevel% neq 0 (
    echo [INFO] Nothing to commit or commit failed. Proceeding to push...
    goto :push
)
echo [OK] Committed.
echo.

:: [5/5] Push
:push
echo [5/5] Pushing to origin/main...
git pull --rebase origin main >nul 2>&1
git push origin main
if %errorlevel% neq 0 (
    echo.
    echo [ERROR] Push failed! Possible reasons:
    echo   1. Remote URL not configured
    echo   2. Network issue
    echo   3. No push permission
    echo.
    pause
    exit /b 1
)

echo.

:: Tag if version provided
if not "%ver%"=="" (
    echo Tagging: v%ver%
    git tag -a v%ver% -m "Release v%ver%"
    if errorlevel 1 (
        echo [WARN] Tag v%ver% already exists, skipping.
    ) else (
        git push origin v%ver%
        echo [OK] Tag v%ver% pushed.
    )
    echo.
)

echo === [OK] Push successful! ===
echo.
timeout /t 3 >nul
exit /b 0
