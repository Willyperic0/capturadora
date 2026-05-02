# StreamerSync Pro

StreamerSync Pro optimiza la captura de video y audio en Windows para reducir latencia y mantener sincronización de hardware precisa.

[![Python](https://img.shields.io/badge/Python-3.11-blue)](https://www.python.org/)
[![PySide6](https://img.shields.io/badge/PySide6-6.5.0-orange)](https://wiki.qt.io/PySide)
[![OpenCV](https://img.shields.io/badge/OpenCV-4.8.0-lightgrey)](https://opencv.org/)

## Key Technical Features

- HUD adaptativo con controles flotantes y auto-ocultado para mantener la visualización despejada.
- Motor multihilo desacoplado donde `VideoEngine` y `AudioEngine` ejecutan captura en `QThread` separados.
- Lógica de validación de hardware basada en identificadores `VID/PID` para emparejar dispositivo de video y dispositivo de audio.

## System Architecture

El pipeline de datos sigue esta secuencia:

1. Capture: `core/video_engine.py` captura frames de la capturadora DShow.
2. Process: `gui/main_window.py` redimensiona y convierte cada frame antes de renderizar.
3. Sync: `core/audio_sync.py` selecciona el dispositivo de audio correcto por `VID/PID` y `AudioEngine` aplica delay ajustable.
4. Render: la UI renderiza los frames en `QLabel` mediante `QImage` y `QPixmap`.

El procesamiento de video mantiene una complejidad temporal `O(n)` por frame, donde `n` es el número de píxeles del lienzo de salida. La aplicación utiliza un `Cached Canvas` de tamaño estático para la presentación del frame, minimizando al máximo la reasignación de memoria y evitando fugas durante ciclos continuos de renderizado.

## Logging System

StreamerSync Pro implementa un sistema de logging profesional para trazabilidad y monitoreo:

- **Archivo de Logs**: Los logs se guardan en `logs/osiris_YYYYMMDD_HHMMSS.log` con timestamp de inicio de aplicación.
- **Niveles de Registro**:
  - `INFO`: Hitos de sesión (inicio/detención, handshake completado).
  - `WARNING`: Eventos de degradación (FPS < 50, jitter > 20ms).
  - `ERROR`: Fallos críticos de hardware o sincronización.
  - `DEBUG`: Telemetría periódica (frames totales, métricas de rendimiento).
- **Resumen de Auditoría**: Al cerrar sesión, se genera automáticamente un resumen con duración total, FPS promedio y jitter máximo registrado.
- **Configuración**: Logger raíz configurado con formato timestamp + nivel + módulo + mensaje, salida a archivo y consola.

## Hardware Synchronization Logic

La lógica de sincronización utiliza identificadores únicos de hardware para mitigar drift de audio:

- `core/audio_sync.py` extrae `VID/PID` de los nombres de dispositivos.
- Se busca el audio asociado primero por coincidencia exacta de IDs, luego por coincidencia de fabricante y nombre.
- Ese enlace hardware reduce la probabilidad de emparejamientos incorrectos entre sesiones y soporta persistencia de dispositivo entre reinicios.
- `AudioEngine` mantiene un buffer circular interno y permite ajustar el delay en tiempo real sin recrear estructuras de almacenamiento.

## Deployment & Environment

1. Crear entorno virtual:

```powershell
python -m venv .venv
```

2. Activar entorno:

```powershell
.\.venv\Scripts\Activate.ps1
```

3. Instalar dependencias:

```powershell
python -m pip install -r requirements.txt
```

4. Ejecutar la aplicación:

```powershell
python main.py
```
