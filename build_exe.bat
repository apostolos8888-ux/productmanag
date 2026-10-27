@echo off
chcp 65001 >nul
cd /d "%~dp0"
py -3 -m pip install --upgrade pyinstaller
if errorlevel 1 goto error
py -3 -m PyInstaller --noconfirm --clean --onefile --windowed --name "ΔιαχείρισηΠροϊόντων" app.py
if errorlevel 1 goto error
echo.
echo Έτοιμο: dist\ΔιαχείρισηΠροϊόντων.exe
pause
goto end
:error
echo.
echo Η δημιουργία EXE απέτυχε. Έλεγξε την εγκατάσταση Python και τη σύνδεση internet.
pause
:end
