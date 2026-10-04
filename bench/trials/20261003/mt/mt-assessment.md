# Evaluación inicial de Hy-MT2 frente al traductor actual

**Hy-MT2-1.8B Q4_K_M funciona localmente y usa menos memoria, pero esta prueba no justifica reemplazar Qwen3-4B.** Su mediana mejora y aparecen errores de significado, cifras y nombres. El traductor actual también presenta fallos que merecen otra tarea de mejora. No se cambiaron ajustes, prompts ni modelos predeterminados de YouJP.

Esta es una revisión inicial hecha por el asistente de las salidas completas, sin juez automático, puntuación global ni referencias de traducción revisadas por un evaluador bilingüe independiente. Hay seis casos españoles de regresión del repositorio, diez casos españoles escritos para esta prueba y tres casos ingleses de regresión. Varias frases y entidades del conjunto ya están enseñadas explícitamente en el prompt actual de Qwen; no es un banco ciego ni representativo de todo YouTube.

## Medidas observadas en la RTX 2060 de 6 GiB

Las cifras son traducción de texto, sin audio ni reconocimiento simultáneo. La primera tabla excluye las peticiones iniciales de carga. En la segunda fase, Whisper large-v3-turbo int8_float16 permaneció cargado sin ejecutar ASR.

| Condición | Qwen actual | Hy-MT2 candidato |
|---|---:|---:|
| Modelo solo: español, 32 peticiones calientes, p50 | 218.9 ms | 171.9 ms |
| Modelo solo: español, p95 | 386.3 ms | 302.1 ms |
| Modelo solo: máximo de 38 peticiones es/en | 391.9 ms | **9685.5 ms** |
| Modelo solo: máximo hasta el primer contenido | 191.8 ms | **9644.9 ms** |
| Con Whisper residente: español, 16 peticiones calientes, p50 | 223.1 ms | 164.1 ms |
| Con Whisper residente: español, p95 | 347.9 ms | 265.0 ms |
| Con Whisper residente: pico total de VRAM observado | 5391.0 MiB | 3912.7 MiB |
| Tamaño de MT residente según `/api/ps` | 2740.9 MiB | 1253.7 MiB |

Ollama confirmó residencia completa en GPU para ambos traductores, tanto solos como con Whisper. Los picos son muestras NVML a 4 Hz, incluyen el escritorio y pueden perder picos más cortos. La fase con Whisper confirma presupuesto de memoria compartido; no demuestra que ambos motores puedan inferir a la vez sin retraso.

El caso de 9.685 s fue `と言って` en la primera repetición de Hy-MT2. Ollama atribuyó **9611.7 ms a prompt_eval** y generó cinco tokens en 40.7 ms, con terminación normal. La segunda repetición tardó 55.3 ms y la fase con Whisper 81.0 ms. Es una cola observada de esta ejecución; su causa no se estableció y no debe ocultarse detrás del p95. No fue un bucle largo de generación ni un corte por el límite de tokens.

La primera carga más traducción tardó 27.177 s para Qwen y 2.653 s para Hy-MT2 en la fase individual. Los modelos estaban descargados de VRAM, pero no se limpió la caché del sistema operativo ni se reinició Ollama entre modelos; estas cifras no prueban una diferencia estable de arranque. Los dos modelos usaron prompts y parámetros apropiados diferentes: Qwen conserva su prompt actual y temperatura 0.2; Hy usa el prompt de Tencent y temperatura 0.7, top_p 0.6, top_k 20 y repeat_penalty 1.05. Ambos tuvieron contexto 2048 y límite de 256 tokens.

## Errores concretos revisados

| Japonés / significado a conservar | Qwen actual | Hy-MT2 candidato | Evaluación inicial |
|---|---|---|---|
| `一万二千五百円`: 12 500 yenes | «El precio incluye impuestos y no hay descuento», omite toda la cifra en ambas repeticiones | Dice 22 500 y 24 500 yenes | Ambos pierden información crítica; Hy altera la cifra. |
| `魔力も技術もコントロールも私の方が遥かに上`: el hablante es superior al otro en magia, técnica y control | Conserva hablante y comparación con «los tuyos», aunque la redacción es torpe | Usa «tecnología» y produce «son mucho mejores que los míos» en la segunda repetición | Hy pierde acepción y relación comparativa. Este caso está enseñado al baseline. |
| `本町から西梅田まで地下鉄で行きます`: de Honmachi a Nishi-Umeda por metro | Conserva ambas estaciones | Cambia destino a «Nishi-Medaka» en ambas repeticiones | Error de nombre propio en Hy; las entidades están enseñadas al baseline. |
| `昨日、退院しました` con tres frases sobre Misaki hospitalizada: alta hospitalaria ayer | «Se graduó ayer» en la primera repetición y en la fase residente; la segunda dice «Se retiró del hospital ayer» | «Ayer, se fue del hospital» en ambas repeticiones | Hy conserva mejor el dominio hospitalario; Qwen falla una interpretación importante. |
| `行かないわけではないけど、今日はやめておく`: no rechaza ir categóricamente, pero hoy lo deja | «Aunque no voy a dejar de ir…» cambia el matiz | Primera repetición afirma «No, no voy a ir»; segunda se aproxima con «No es que no iré…» | La doble negación es inestable en ambos. |
| `猫の手も借りたいくらい忙しい`: muy ocupado / cualquier ayuda vendría bien | Traduce literalmente ayuda de un gato | «Pedir la mano de un gato» | Ambos producen una expresión literal poco natural. |
| `毎朝ここで二時間勉強しています` con tres frases sobre Tanaka | Mantiene «Estudia» | Primera repetición «estudia»; segunda «estudio» | El sujeto dependiente del contexto varía en Hy. |

Ambos entregaron inglés coherente en las tres frases cortas probadas. No hubo errores HTTP, respuestas vacías, razonamiento visible, múltiples líneas, repeticiones detectadas ni truncamiento por límite en las 114 peticiones calientes. Eso prueba ejecución y formato en estos casos; no equivale a calidad semántica aprobada.

## Importación local y reproducción

El GGUF oficial tiene **1 133 080 448 bytes**. Se verificó el SHA256 local contra el [archivo oficial](https://huggingface.co/tencent/Hy-MT2-1.8B-GGUF/blob/main/Hy-MT2-1.8B-Q4_K_M.gguf): `dc5f44fcf1fa496ee7ad725982c0c8c553a4de00259b53af84c4b89fb0c06699`.

La ruta sugerida por Hugging Face, `ollama pull hf.co/tencent/Hy-MT2-1.8B-GGUF:Q4_K_M`, descargó e importó los pesos, pero Ollama 0.35.0 devolvió una plantilla defectuosa: faltaban `.Prompt` y `.Response`, y aparecía texto residual `onse }}`. Se preservó en `original-import-show.json`. Antes de inferir se creó el alias de prueba `youjp-trial-hymt2:1.8b-q4_k_m-20261003`, reutilizando el mismo blob y la rama exacta para un único mensaje de usuario de la [plantilla oficial de Tencent](https://huggingface.co/tencent/Hy-MT2-1.8B/blob/main/chat_template.jinja). La plantilla original se descargó en `official-chat-template.jinja`, y la adaptación Go está en `Modelfile.hymt2`. El alias tiene digest `fbcada38618b4438be212ada492e414bf2a392956868f5f36b70f36986ca3f13`.

Para repetir sin sobrescribir esta evidencia, desde la raíz del repositorio:

```powershell
ollama create youjp-trial-hymt2:1.8b-q4_k_m-20261003 -f bench\trials\20261003\mt\Modelfile.hymt2
.\backend\.venv\Scripts\python.exe scripts\trials\mt_trial.py --run --out bench\trials\mt-repeat
.\backend\.venv\Scripts\python.exe scripts\trials\mt_trial.py --run --with-whisper-resident --repetitions 1 --out bench\trials\mt-repeat-with-whisper
```

Las fases requieren que la GPU esté disponible y se ejecutan en serie. El script no descarga modelos ni cambia ajustes de producción. Conserva cada petición, sus roles, prompt, opciones, salida sin limpiar, salida de subtítulos y contadores de Ollama en JSONL/JSON. Los modelos de prueba y Whisper fueron descargados de VRAM al terminar; los pesos y el alias quedan instalados para futuras pruebas.

Los próximos cambios de prompts, quantización, motor o conjunto de frases deben tratarse como un experimento separado. La conclusión actual es conservar el modelo predeterminado, registrar los errores de ambos y evitar una sustitución basada únicamente en velocidad o memoria.
