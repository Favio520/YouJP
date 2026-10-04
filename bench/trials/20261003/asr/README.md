# Ensayo ASR aislado

Fecha de corte: 3 de octubre de 2026. El ensayo no cambia el ASR configurado en YouJP.

Runtime Windows CUDA de NVIDIA NeMo-Speech.cpp v0.2.0 y modelo Nemotron 3.5 ASR 0.6B Q8_0 descargados en las carpetas `trials` del workspace. Tamaños y SHA256 comprobados en `assets.json`; compatibilidad de formato inspeccionada en `model-info.json`. Esto por sí solo no demuestra inferencia ni calidad.

## Repetir

Desde la raíz del repositorio:

```powershell
# Verificar las descargas existentes y extraer dentro del workspace.
& "$env:SystemRoot\System32\WindowsPowerShell\v1.0\powershell.exe" -NoProfile -ExecutionPolicy Bypass -File .\scripts\trials\asr-setup.ps1

$taskRuntime = 'D:\youJP-ESP\.youjp\trials\asr\runtime\nemo-speech-0.2.0-windows-x86_64-cuda\bin\nemo-speech.exe'
$taskModel = 'D:\youJP-ESP\models\trials\nemotron-3.5-asr\nemotron-3.5-asr-streaming-0.6b.q8_0.gguf'

# Prueba de streaming a ritmo real. Crea copias de los primeros 30 segundos.
& .\backend\.venv\Scripts\python.exe .\scripts\trials\asr_trial.py --provider nemotron --runtime $taskRuntime --model $taskModel --sample 10-noticias-apertura.wav --sample 20-anime-frieren.wav --limit-seconds 30 --output .\bench\trials\20261003\asr\nemotron-smoke-realtime.json
& .\backend\.venv\Scripts\python.exe .\scripts\trials\asr_trial.py --provider whisper --sample 10-noticias-apertura.wav --sample 20-anime-frieren.wav --limit-seconds 30 --output .\bench\trials\20261003\asr\whisper-smoke-realtime.json
```

Ejecutar las inferencias de forma secuencial. `--fast` mide procesamiento sin entrega a ritmo de reloj y no genera medidas de latencia de directo. Retirar `--limit-seconds` permite usar los clips completos. `--sample` se puede repetir para silencio, ruido y otros clips.

Los resultados publicados aquí usan las copias guardadas en `control-inputs`: noticias 30 s, anime 30 s, silencio 20 s. Para repetir exactamente esa selección, usar `--samples .\bench\trials\20261003\asr\control-inputs --sample 10-noticias-apertura.wav --sample 20-anime-frieren.wav --sample 00-silencio.wav` y retirar `--limit-seconds`. El ensayo de coexistencia usa solo noticias; el payload de calentamiento de Qwen y su comprobación antes/después figuran en `nemotron-with-qwen-residency.json`.

## Interpretación

- Whisper usa el pipeline existente de YouJP: Silero VAD + Whisper turbo + LocalAgreement + segmentador. Nemotron usa su servidor local y eventos WebSocket nativos con idioma `ja-JP`, contexto derecho 3 (320 ms), endpointing por ausencia de tokens a 500 ms y batching desactivado. Los límites de frase no son idénticos.
- Cada salida conserva finales, parciales, tiempos recibidos, palabras/fragmentos y el SHA256 exacto del audio. La validación de tiempos comprueba payloads reales, intervalos finitos, orden y límites. No mide la precisión de alineación contra anotación humana.
- La latencia de final usa su llegada al cliente menos el fin de audio estimado por ese ASR. Si los tiempos resultan inválidos, se omite el resumen de latencia. El RTF rápido de Nemotron descuenta el tiempo de espera del colector después del último evento.
- VRAM: muestreo NVML de toda la GPU a 10 Hz. El incremento sobre la línea base es aproximado porque otros procesos también pueden consumir memoria.
- No hay transcripciones humanas de referencia para estos clips: no se afirma CER/WER real ni mejor precisión a partir de la coincidencia entre modelos.
- Este banco evalúa ASR aislado. La traducción, captura del navegador y la latencia total del subtítulo no están medidas por él.
