@echo off
setlocal

set "ROOT=%~dp0"

set "PYTHON_EXE="
set "PYTHON_ARGS="
if exist "%ROOT%.venv\Scripts\python.exe" set "PYTHON_EXE=%ROOT%.venv\Scripts\python.exe"
if not defined PYTHON_EXE if exist "%USERPROFILE%\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe" set "PYTHON_EXE=%USERPROFILE%\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"
if not defined PYTHON_EXE where python >nul 2>nul && set "PYTHON_EXE=python"
if not defined PYTHON_EXE where py >nul 2>nul && set "PYTHON_EXE=py" && set "PYTHON_ARGS=-3"

if not defined PYTHON_EXE (
  echo Python bulunamadi. Lutfen Python 3.10+ kurun veya proje kokunde .venv olusturun.
  pause
  exit /b 1
)

if /I "%~1"=="--check" (
  echo ROOT=%ROOT%
  echo PYTHON="%PYTHON_EXE%" %PYTHON_ARGS%
  "%PYTHON_EXE%" %PYTHON_ARGS% --version
  exit /b %ERRORLEVEL%
)

echo Starting ThermaIQ backend on http://127.0.0.1:8001
start "ThermaIQ Backend" cmd /k "cd /d ""%ROOT%backend"" && ""%PYTHON_EXE%"" %PYTHON_ARGS% -m uvicorn main:app --host 127.0.0.1 --port 8001 --reload"

echo Starting ThermaIQ frontend on http://127.0.0.1:3000
start "ThermaIQ Frontend" cmd /k "cd /d ""%ROOT%"" && ""%PYTHON_EXE%"" %PYTHON_ARGS% -m http.server 3000 -d frontend"

timeout /t 3 /nobreak >nul
start http://127.0.0.1:3000

echo.
echo ThermaIQ demo is running.
echo Frontend: http://127.0.0.1:3000
echo Backend docs: http://127.0.0.1:8001/docs
echo.
echo Keep the two opened terminal windows running during the demo.
pause
