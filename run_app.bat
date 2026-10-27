@echo off
chcp 65001 >nul
cd /d "%~dp0"
py -3 app.py
if errorlevel 1 (
  echo.
  echo Δεν ξεκίνησε η εφαρμογή. Βεβαιώσου ότι έχει εγκατασταθεί Python 3.10+.
  pause
)
