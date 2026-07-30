@echo off
setlocal
cd /d "%~dp0"

where py >nul 2>nul
if %errorlevel% equ 0 (
  py -3 run.py
  goto :end
)

where python >nul 2>nul
if %errorlevel% equ 0 (
  python run.py
  goto :end
)

echo.
echo A programhoz Python 3.11 vagy ujabb szukseges.
echo Letoltes: https://www.python.org/downloads/
echo.
pause

:end
endlocal
