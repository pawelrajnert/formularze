@echo off
rem X-03: uruchomienie COI na Windowsie (Docker Desktop). Uzycie: start.bat   (zatrzymanie: start.bat stop)
setlocal
cd /d "%~dp0"

where docker >nul 2>nul
if errorlevel 1 (
  echo [BLAD] Nie znaleziono Dockera. Zainstaluj Docker Desktop: https://www.docker.com/products/docker-desktop/
  exit /b 1
)
docker info >nul 2>nul
if errorlevel 1 (
  echo [BLAD] Docker nie dziala. Uruchom Docker Desktop i sprobuj ponownie.
  exit /b 1
)

if /i "%~1"=="stop" (
  docker compose down
  exit /b %errorlevel%
)

if not exist ".env" (
  copy /y ".env.example" ".env" >nul
  echo [INFO] Utworzono plik .env z .env.example.
  echo        Uzupelnij w nim: LLM_API_KEY, AUTH_PASSWORD, JWT_SECRET  i uruchom start.bat ponownie.
  notepad ".env"
  exit /b 1
)

echo [INFO] Buduje i uruchamiam kontener (pierwszy raz trwa kilka minut)...
docker compose up --build -d
if errorlevel 1 (
  echo [BLAD] docker compose up nie powiodl sie.
  exit /b 1
)

echo [INFO] Czekam, az aplikacja odpowie na http://localhost:8000/health ...
for /l %%i in (1,1,60) do (
  powershell -NoProfile -Command "try { (Invoke-WebRequest -UseBasicParsing -TimeoutSec 2 http://localhost:8000/health).StatusCode } catch { exit 1 }" >nul 2>nul
  if not errorlevel 1 goto ready
  timeout /t 2 /nobreak >nul
)
echo [BLAD] Aplikacja nie odpowiada po 2 minutach. Logi: docker compose logs app
exit /b 1

:ready
echo [OK] Aplikacja dziala:
echo      frontend: http://localhost:8000
echo      API:      http://localhost:8000/docs
start "" http://localhost:8000
exit /b 0
