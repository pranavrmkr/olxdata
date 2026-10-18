@echo off
REM OLX Phone Data Pipeline - Windows Entry Point
REM This script installs dependencies and runs the pipeline

echo ========================================
echo OLX Phone Data Pipeline - Windows Runner
echo ========================================
echo.

REM Check if Python is available
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo ERROR: Python not found in PATH
    echo Please install Python 3.11+ and add it to PATH
    pause
    exit /b 1
)

echo [1/5] Checking Python version...
python -c "import sys; assert sys.version_info >= (3, 11), 'Python 3.11+ required'" 2>&1
if %errorlevel% neq 0 (
    echo ERROR: Python 3.11 or higher is required
    pause
    exit /b 1
)
echo OK - Python version check passed
echo.

echo [2/5] Installing dependencies...
pip install -e ".[dev]" --quiet
if %errorlevel% neq 0 (
    echo ERROR: Failed to install dependencies
    pause
    exit /b 1
)
echo OK - Dependencies installed
echo.

echo [3/5] Installing Playwright browsers...
playwright install chromium
if %errorlevel% neq 0 (
    echo WARNING: Playwright install failed, but continuing...
)
echo OK - Playwright ready
echo.

echo [4/5] Setting up environment...
if not exist .env (
    if exist .env.example (
        copy .env.example .env
        echo Created .env from .env.example - please edit it with your database URL
    ) else (
        echo WARNING: .env.example not found
    )
) else (
    echo .env already exists
)
echo.

echo [5/5] Running database migrations...
alembic upgrade head
if %errorlevel% neq 0 (
    echo ERROR: Database migration failed
    echo Make sure your DATABASE_URL in .env is correct and PostgreSQL is running
    pause
    exit /b 1
)
echo OK - Database ready
echo.

echo ========================================
echo Setup complete!
echo ========================================
echo.
echo Available commands:
echo   olx-data scrape --cities mumbai delhi --max-pages 5
echo   olx-data enrich --limit 1000
echo   olx-data fraud --limit 1000
echo   olx-data price
echo   olx-data report --output reports --days 30
echo   olx-data deals --city mumbai --days 7
echo   olx-data stats
echo   olx-data export --format csv --output data/exports
echo.
echo Run 'olx-data --help' for full command list
echo.
pause