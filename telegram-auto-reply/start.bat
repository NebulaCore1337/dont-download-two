@echo off
echo Starting AI Auto-Reply...

:: Запускаем xRay прокси (фоном)
start /B "" "D:\mcptg\telegram-mcp\xray.exe" run -c "D:\mcptg\telegram-mcp\config.json"

:: Ждём пока прокся поднимется
timeout /t 3 /nobreak >nul

:: Запускаем автоответчик
set TG_API_ID=ВАШ АЙДИ
set TG_API_HASH=ВАШ ХЭШ
set TG_SESSION_STRING=

cd /d "C:\Users\sanya\telegram-auto-reply"

:: Запускаем локальный сервер для дашборда (фоном)
start /B python server.py

:: Ждём пока сервер поднимется
timeout /t 1 /nobreak >nul

:: Открываем дашборд в браузере
start "" "http://localhost:8080/dashboard.html"

:: Запускаем автоответчик
python auto_reply.py

:: Если auto_reply упал — убиваем xRay
taskkill /f /im xray.exe >nul 2>&1
pause
