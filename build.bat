@echo off
rem Сборка CloudSaveManager.exe (нужен Python 3.9+ в PATH)
python -m pip install -r requirements.txt pyinstaller
python -m PyInstaller --noconfirm CloudSaveManager.spec
echo.
echo Готово: dist\CloudSaveManager.exe
pause
