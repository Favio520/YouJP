# ADR 0002 — LocalAgreement-2 en lugar de transcribir por segmento de VAD

- **Fecha:** 2026-09-14
- **Estado:** aceptado e implementado (fase 0)
- **Código:** `backend/youjp/asr/hypothesis.py`, `backend/youjp/pipeline/streaming.py`

## Contexto

Whisper es un modelo codificador-decodificador sobre ventanas de 30 s. No es un
modelo de streaming y no tiene noción de salida incremental.

El diseño evidente es: el VAD detecta el final de una intervención, se pasa ese
audio a Whisper, se muestra el resultado. La latencia resultante es *duración de
la frase + inferencia*, entre 4 y 10 s en habla continua, y sin nada en pantalla
mientras tanto.

## Decisión

Reejecutar Whisper sobre un buffer creciente cada `min_chunk_s` (0,8 s por
defecto) y **confirmar solo el prefijo en el que coinciden dos pasadas
consecutivas**. Lo confirmado es inmutable; lo que va detrás se muestra en gris y
se reescribe libremente.

Es la política LocalAgreement-2 de Macháček, Dabre y Bojar, *Turning Whisper into
Real-Time Transcription System* (arXiv:2307.14743), reimplementada aquí.

## Motivos

- Da parciales a ~0,8 s y texto firme a ~1,9 s, frente a los 4–10 s del diseño
  por segmento.
- La garantía de inmutabilidad es lo que permite montar tokens clicables sobre el
  texto confirmado sin que se muevan bajo el cursor.
- El coste es una pasada adicional de espera antes de dar por buena una palabra.
  Es el precio de tener parciales estables en vez de texto que baila.

## Consecuencias

- **Se paga inferencia repetida** sobre el mismo audio. Con turbo en `int8_float16`
  y beam 1 sale a cuenta; con un modelo más lento dejaría de salir.
- **Hay que recortar la ventana** por el último punto confirmado. Sin recorte
  crece hasta los 30 s y el tiempo de inferencia sube con ella hasta romper el
  presupuesto de latencia.
- El intervalo entre pasadas **se cuenta en muestras enteras, no en segundos**:
  en coma flotante `0.6 - 0.4` no da `0.2` y la cadencia alterna entre dos
  valores, añadiendo ~100 ms de jitter aleatorio a la latencia. Hay un test de
  regresión para esto (`test_cadencia_de_pasadas_regular`).
- El VAD sigue siendo necesario, pero para otras tres cosas: no ejecutar sobre
  silencio, cerrar frases sin puntuación, y frenar las alucinaciones.
