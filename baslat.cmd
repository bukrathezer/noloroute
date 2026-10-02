@echo off
chcp 65001 >nul
rem NoloRoute yerel geliştirme: çift tıklayınca veritabanı, API ve arayüz açılır.
rem Durdurmak için "NoloRoute API" ve "NoloRoute Web" pencerelerini kapat.
cd /d "%~dp0"

rem 1) Docker Desktop (veritabanı konteyneri onunla birlikte kendiliğinden başlar)
tasklist /fi "imagename eq Docker Desktop.exe" | find /i "Docker Desktop.exe" >nul
if errorlevel 1 (
    echo Docker Desktop aciliyor...
    start "" "%LOCALAPPDATA%\Programs\DockerDesktop\Docker Desktop.exe"
) else (
    echo Docker Desktop zaten acik.
)

rem 2) API: http://localhost:8000 (zaten çalışıyorsa ikinci kez başlatma)
netstat -ano | findstr /r /c:":8000 .*LISTENING" >nul
if errorlevel 1 (
    echo API baslatiliyor...
    start "NoloRoute API" cmd /k ".venv\Scripts\python.exe -m uvicorn app.main:app --port 8000 --reload"
) else (
    echo API zaten calisiyor.
)

rem 3) Arayüz: http://localhost:5173
netstat -ano | findstr /r /c:":5173 .*LISTENING" >nul
if errorlevel 1 (
    echo Arayuz baslatiliyor...
    start "NoloRoute Web" cmd /k "cd /d frontend && npm run dev"
) else (
    echo Arayuz zaten calisiyor.
)

rem 4) Arayüz cevap verince tarayıcıyı aç (en fazla ~30 sn bekle)
set /a tries=0
:wait_web
curl -s -o nul http://localhost:5173 && goto open_browser
set /a tries+=1
if %tries% geq 30 goto open_browser
timeout /t 1 /nobreak >nul
goto wait_web

:open_browser
start "" http://localhost:5173
echo.
echo Hazir: http://localhost:5173
echo Veritabani Docker ile birlikte acilir; ilk acilista sehirlerin gelmesi biraz surebilir.
timeout /t 5 >nul
