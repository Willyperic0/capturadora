@echo off
REM Construye un ejecutable .exe de la aplicación usando PyInstaller.
REM Ejecuta este archivo desde la carpeta del proyecto: d:\capturadora

REM Instala PyInstaller si no está disponible
python -m pip install --upgrade pyinstaller

REM Borra builds anteriores
rmdir /s /q build 2>nul
rmdir /s /q dist 2>nul
if exist main.spec del /q main.spec

REM Construcción de un solo ejecutable sin consola
pyinstaller --noconfirm --clean --onefile --windowed --add-data "config.json;." main.py

echo.
echo Construcción completada.
echo El ejecutable estará en dist\main.exe
echo Si quieres cambiar el nombre del exe, edita este archivo y agrega --name "Nombre" a pyinstaller.
pause