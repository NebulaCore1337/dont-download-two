@echo off
echo Starting AI Auto-Reply...

:: Запускаем xRay прокси (фоном)
start /B "" "D:\mcptg\telegram-mcp\xray.exe" run -c "D:\mcptg\telegram-mcp\config.json"

:: Ждём пока прокся поднимется
timeout /t 3 /nobreak >nul

:: Запускаем автоответчик
set TG_API_ID=29865278
set TG_API_HASH=1f2c2ec9ea3ad91acbce408c0205b51e
set TG_SESSION_STRING=1ApWapzMBu727TNMUB8wvybYhdzXOqf_Je3Ng8S1XsHW-nt_bl_sktYAdXhKiJ1v9SWbbaAmGGSuiAnc0HJ1eowilTN1ZaLaXo-uxVZRaEvndA396br9RZ0JTMP_4ANBn3-63MRBapibzqOxozlHXY8LQCBufrqVJ26sPq9HS8wmH4gHgOJ0JnzZsnYrQLK95uaFcbjYIuQxdW5EpNAYVUFNLzJI5DWrNrlY03ErIquDjQnn7GhzrVcgr2Vi10KaK2O3rrEMcywLVhOAuHEoNv8OFisCpHBOa5wogIksVVVhwxy9q0zBeGznlb6ai4icM_fU6NRFpMVU5o7Uov0FPGWGY1YU8ugo=

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
