@echo off
chcp 65001 >nul
setlocal

for %%I in ("%~dp0.") do set "PROJECT_DIR=%%~fI"
set "BACKEND_DIR=%PROJECT_DIR%\backend"
set "FRONTEND_DIR=%PROJECT_DIR%\frontend"
set "FRONTEND_URL=http://localhost:5173"

echo ========================================
echo STrans one-click starter
echo Project: %PROJECT_DIR%
echo Backend: http://localhost:8000
echo Frontend: %FRONTEND_URL%
echo ========================================
echo.

if not exist "%BACKEND_DIR%\app\main.py" (
  echo [ERROR] Backend not found: %BACKEND_DIR%
  pause
  exit /b 1
)

if not exist "%FRONTEND_DIR%\package.json" (
  echo [ERROR] Frontend not found: %FRONTEND_DIR%
  pause
  exit /b 1
)

if not exist "%BACKEND_DIR%\data\traffic_analysis.db" if "%STRANS_ADMIN_PASSWORD%"=="" (
  echo [ERROR] First boot requires STRANS_ADMIN_PASSWORD with at least 12 characters.
  echo Run this starter from a PowerShell session where the variable is set.
  pause
  exit /b 1
)

where python >nul 2>nul
if errorlevel 1 (
  echo [ERROR] Python is not installed or not in PATH.
  pause
  exit /b 1
)

where node >nul 2>nul
if errorlevel 1 (
  echo [ERROR] Node.js is not installed or not in PATH.
  pause
  exit /b 1
)

echo [1/4] Checking backend dependencies...
cd /d "%BACKEND_DIR%"
python -c "import fastapi, uvicorn, cv2, pydantic, psutil" >nul 2>nul
if errorlevel 1 (
  echo Backend dependencies are missing. Installing from requirements.txt...
  python -m pip install -r requirements.txt
  if errorlevel 1 (
    echo [ERROR] Backend dependency installation failed.
    pause
    exit /b 1
  )
) else (
  echo Backend dependencies are ready.
)

echo.
echo [2/4] Checking frontend dependencies...
cd /d "%FRONTEND_DIR%"
if not exist "%FRONTEND_DIR%\node_modules" (
  where pnpm >nul 2>nul
  if errorlevel 1 (
    echo pnpm not found. Installing frontend dependencies with npm...
    npm install
  ) else (
    echo Installing frontend dependencies with pnpm...
    pnpm install
  )
  if errorlevel 1 (
    echo [ERROR] Frontend dependency installation failed.
    pause
    exit /b 1
  )
) else (
  echo Frontend dependencies are ready.
)

echo.
echo [3/4] Starting backend server...
powershell -NoProfile -Command "if (Get-NetTCPConnection -LocalPort 8000 -State Listen -ErrorAction SilentlyContinue) { exit 0 } else { exit 1 }" >nul 2>nul
if errorlevel 1 (
  start "STrans Backend Watchdog - FastAPI 8000" powershell -NoExit -ExecutionPolicy Bypass -File "%BACKEND_DIR%\run_backend_watchdog.ps1"
) else (
  echo Backend port 8000 is already running. Skip starting backend.
)

echo [4/4] Starting frontend dev server...
where pnpm >nul 2>nul
if errorlevel 1 (
  start "STrans Frontend - Vite 5173" powershell -NoExit -ExecutionPolicy Bypass -Command "Set-Location -LiteralPath '%FRONTEND_DIR%'; npm run dev"
) else (
  start "STrans Frontend - Vite 5173" powershell -NoExit -ExecutionPolicy Bypass -Command "Set-Location -LiteralPath '%FRONTEND_DIR%'; pnpm dev"
)

echo.
echo Waiting for services to start...
timeout /t 5 /nobreak >nul
start "" "%FRONTEND_URL%"

echo.
echo Done. Keep the two opened terminal windows running.
echo Close those windows or press Ctrl+C inside them to stop the project.
pause
