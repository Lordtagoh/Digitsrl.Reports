@echo off
rem Genera il report e lo pubblica su GitHub Pages SOLO se i dati sono cambiati.
rem Uso: publish.bat [argomenti per generate_report.py, es. --force]
setlocal
cd /d "%~dp0"

if not exist password.local.txt (
    type nul > password.local.txt
    echo password.local.txt non trovato: creato vuoto e aperto per la modifica.
    echo Inserisci la password, salva, chiudi l'editor e rilancia publish.bat.
    start "" "password.local.txt"
    pause
    exit /b 1
)

python -X utf8 generate_report.py %*
if errorlevel 1 (
    echo.
    echo Generazione fallita: niente commit.
    pause
    exit /b 1
)

git add docs/data/report.enc.json
git diff --cached --quiet
if not errorlevel 1 (
    echo.
    echo Nessuna modifica da pubblicare.
    pause
    exit /b 0
)

for /f %%d in ('powershell -NoProfile -Command "Get-Date -Format yyyy-MM-dd"') do set TODAY=%%d
git commit -m "Daily report %TODAY%"
if errorlevel 1 (
    echo.
    echo Commit fallito.
    pause
    exit /b 1
)
git push
if errorlevel 1 (
    echo.
    echo Push fallito: il commit locale e' stato creato ma non pubblicato.
    pause
    exit /b 1
)
echo.
echo Report pubblicato.
pause
