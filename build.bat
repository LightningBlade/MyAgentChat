@echo off
cd /d "%~dp0"
echo Installing PyInstaller...
py -m pip install --upgrade pyinstaller
if errorlevel 1 goto fail
echo Building MyAgentChat.exe ...
py -m PyInstaller --clean --noconsole --onefile --name MyAgentChat chat_app.py
if errorlevel 1 goto fail
echo.
echo Done. Your program is in the dist folder.
pause
exit /b 0
:fail
echo.
echo Something went wrong. Check that Python is installed and "py" works.
pause
exit /b 1
