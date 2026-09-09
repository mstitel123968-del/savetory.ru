@echo off
cd /d "%~dp0"
python -m pip install -r requirements-build.txt
python -m PyInstaller --noconfirm --clean --onefile --windowed --name SKlad --icon NONE --add-data "assets;assets" --distpath release app.py
echo.
echo Готовое приложение: release\SKlad.exe
pause
