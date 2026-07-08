@echo off
title BotTelegram

:: Verifica se já existe uma instância rodando
tasklist /fi "imagename eq python.exe" | find "python.exe" >nul
if errorlevel 0 (
    echo [%date% %time%] Bot já está rodando. Saindo...
    exit
)

:loop
echo [%date% %time%] Iniciando bot...
python bot_telegram.py
echo [%date% %time%] Bot caiu. Reiniciando em 10 segundos...
timeout /t 10
goto loop