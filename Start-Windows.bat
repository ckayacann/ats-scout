@echo off
rem Double-click launcher for Windows. First run sets everything up, later runs just open the app.
cd /d "%~dp0"

if not exist venv (
  echo First run: setting up (needs internet, takes about a minute)...
  python -m venv venv || goto :fail
  call venv\Scripts\activate.bat
  pip install -q -r requirements.txt || goto :fail
) else (
  call venv\Scripts\activate.bat
)

python main.py
if errorlevel 1 goto :fail
exit /b 0

:fail
echo.
echo Something went wrong (see above). Make sure Python 3.10+ is installed with "Add python.exe to PATH" ticked.
pause
