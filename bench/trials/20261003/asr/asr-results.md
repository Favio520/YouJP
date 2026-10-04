# Resultado ASR: Nemotron 3.5 frente a Whisper turbo

Pruebas reales del 3 de octubre de 2026 en Windows y RTX 2060 de 6 GiB. Los dos modelos procesaron secuencialmente **los mismos primeros 30 s de noticias, 30 s de anime y 20 s de silencio digital**, enviados a ritmo de reloj. Los SHA256 de entrada coinciden; procedencia en `inputs.json`.

Nemotron 3.5 ASR 0.6B Q8_0 funciona con CUDA en este equipo mediante el binario Windows oficial NeMo-Speech.cpp v0.2.0. No se instalaron componentes globales ni se cambiaron defaults de YouJP.

| Medida | Nemotron | Whisper large-v3-turbo |
|---|---:|---:|
| Noticias: finales con texto | 12 | 5 |
| Noticias: llegada final menos fin estimado, p50 | 834 ms | 1411 ms |
| Noticias: misma medida, p95 | 1045 ms | 3729 ms |
| Noticias: primer parcial desde inicio del archivo | 1026 ms | 1080 ms |
| Anime: llegada final menos fin estimado | 789 ms, n=1 | 1309 ms, n=1 |
| Anime: primer parcial desde inicio del archivo | 4994 ms | 5920 ms |
| Silencio digital, 20 s | 0 caracteres y 0 parciales | 0 caracteres y 0 parciales |
| Pico total de VRAM, NVML a 10 Hz | 2436 MiB | 2757 MiB |
| VRAM por encima de su propia línea base | 1029 MiB | 1406 MiB |

**Los tiempos son indicativos.** Cada modelo estima sus propios límites de audio y Nemotron cerró 12 segmentos de noticias frente a 5 del pipeline actual; una segmentación más corta también reduce demora. Hay pocos finales y solamente una frase de anime. Los parciales de ambos proveedores tienen semánticas diferentes. El tiempo total del WAV con pacing no es una medida de RTF de inferencia ni de la latencia del subtítulo traducido.

La salida del anime conserva la misma frase en ambos modelos, con la variante ortográfica `はるか` / `遥か`: `魔力も技術もコントロールも私の方がはるかに上`. En noticias los textos difieren y contienen reconocimientos dudosos; sin transcripción humana no hay CER/WER ni ganador de precisión demostrado. Las salidas japonesas completas están en los JSON para revisión.

## Limitación material de los timestamps

Los intervalos finales recibidos son finitos, están ordenados y dentro del audio, con tolerancia de 0,5 s al final. Sin embargo, **Nemotron devolvió un solo elemento `words[]` con toda la frase japonesa en cada final**: 12 unidades en noticias y 1 en anime. Whisper devolvió 78 y 19 unidades respectivamente. Validar estos intervalos no demuestra alineación por palabra o carácter. La integración con YouJP necesita gestionar parciales/finales y usar interpolación o alineación adicional si requiere marcas finas; no basta cambiar el nombre del modelo de Whisper.

## Coexistencia con el traductor actual

Una prueba adicional y acotada de **30 s de noticias con Qwen3 4B Q4_K_M residente en GPU**, contexto 2048, también terminó correctamente. Ollama `/api/ps` comprobó residencia antes y después. Pico total observado: **5289/6144 MiB**, unos **855 MiB libres**. El texto japonés coincide con Nemotron aislado; p50 de llegada final menos fin estimado: 822 ms, p95: 943 ms, 12 finales. El traductor se calentó antes y no realizó inferencia durante el reconocimiento. Esto verifica coexistencia de memoria en esa prueba; **no es una prueba de traducción simultánea ni del flujo completo de la aplicación**.

Los modelos que cargó el ensayo se descargaron de memoria al terminar; `/api/ps` quedó vacío y el proceso nativo terminó. Los pesos y runtime aislados quedan disponibles para repetir la prueba.

## Decisión respaldada

Nemotron merece un adaptador experimental por su funcionamiento real en esta GPU, menor demora observada y espacio junto a Qwen. Mantener Whisper turbo como default hasta revisar precisión japonesa con referencias y medir una sesión con ASR y MT trabajando simultáneamente. No se ensayaron clips completos, sesiones largas, navegador ni captura real.

Evidencia: `nemotron-controlled-realtime.json`, `whisper-controlled-realtime.json`, `comparison.json`, `nemotron-with-qwen-realtime.json` y `nemotron-with-qwen-residency.json`. Reproducción y configuración en `README.md`; assets y hashes en `assets.json`.
