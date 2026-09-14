# youjp

Subtítulos japoneses en tiempo real sobre YouTube, con análisis lingüístico local
y explicaciones adaptadas a nivel JLPT N4–N3.

El audio de la pestaña se captura, se transcribe con Whisper, se analiza con
Sudachi y JMdict y se traduce al español. Todo en local: la única pieza opcional
que sale de la máquina es la descarga inicial de modelos.

La revisión de arquitectura completa está en [`docs/arquitectura.html`](docs/arquitectura.html).

## Estado

**Fase 0 — banco de pruebas.** Todavía no hay extensión ni servidor: hay un
pipeline de streaming completo (VAD → Whisper → LocalAgreement → segmentador)
que se ejecuta sobre ficheros WAV para medir latencia, RTF y VRAM reales antes
de construir nada encima.

| Fase | Contenido | Estado |
|---|---|---|
| 0 | Banco de pruebas y línea base de medidas | **cerrada** |
| 1 | MVP: audio de la pestaña → japonés en pantalla | **en pruebas** |
| 2 | Sudachi + JMdict + tokens clicables | pendiente |
| 3 | Traducción al español | pendiente |
| 4 | Gramática por reglas | pendiente |
| 5 | LLM local y explicaciones contextuales | pendiente |
| 6 | Vocabulario, estadísticas y repaso espaciado | pendiente |

## Resultados de la Fase 0

Medido el 14-09-2026 en la máquina objetivo (RTX 2060 6 GB, faster-whisper 1.2.1,
CTranslate2 4.8.2) con la GPU en reposo. Detalle en [`docs/adr/`](docs/adr/).

| Muestra | Latencia p50 | p95 | Whisper p50 | Frases | Descartes |
|---|---|---|---|---|---|
| Silencio digital, 45 s | — | — | — | **0** | 0 pasadas |
| Ruido rosa, 45 s | — | — | — | **0** | 0 pasadas |
| Narración de estudio | 1 440 ms | 3 951 ms | 362 ms | 11 | 5 / 94 |
| Entrevistas en la calle | 1 666 ms | 2 673 ms | 440 ms | 14 | 3 / 94 |
| Reportaje, tramo final | 1 421 ms | 2 065 ms | 382 ms | 11 | 5 / 92 |
| Anime, escena de acción | 1 365 ms | 3 534 ms | 380 ms | 6 | 11 / 67 |

VRAM: base del escritorio 1 181 MiB, pico total 2 496, atribuible al modelo
**1 315 MiB** de 6 144. Los tres presupuestos de latencia del documento de
arquitectura se cumplen. Sobre silencio y ruido, Whisper no llega a ejecutarse
ni una vez.

**El anime es otro régimen.** Produce 87 caracteres en 62 s frente a los ~290 del
reportaje, y rechaza el 16 % de las pasadas frente al 3–5 % de las noticias. La
transcripción es utilizable para subtitular, pero pierde detalle
(お娘 por あの娘, フリーレ por フリーレン). A partir de la fase 2 habrá que
marcar la confianza por token: una lectura mal segmentada enseña japonés
incorrecto a quien todavía no puede detectarlo.

**Modelo elegido: `large-v3-turbo`.** Medido sobre tres tramos de 70 s de un
reportaje de televisión japonesa (narración de estudio, entrevistas en la calle,
voz sobre música).

| | large-v3-turbo | kotoba-whisper-v2.0-faster |
|---|---|---|
| Latencia p50 | **1 477 – 1 826 ms** | 1 514 – 3 276 ms |
| Latencia p95 | **2 096 – 4 307 ms** | 4 359 – 7 301 ms |
| Inferencia por pasada p50 | 408 – 482 ms | **317 – 338 ms** |
| Parciales emitidos por muestra | **73 – 77** | 36 – 41 |
| Pasadas que no emiten nada | **0** | 12 – 27 |
| VRAM atribuible | ~1 600 MiB | ~1 400 MiB |
| Marcas por palabra | **sí** | no — mata el proceso |

Kotoba infiere más rápido y ocupa menos, pero en streaming pierde: su
decodificador destilado de dos capas devuelve texto vacío en una de cada tres
ventanas parciales, y como LocalAgreement necesita dos pasadas coincidentes para
confirmar, cada vacío retrasa la frase entera. En calidad tampoco compensa —
escribió 大人の**自首**室 («sala de entrega a la policía») donde turbo escribió
大人の**自習**室 («sala de estudio»).

- **Línea base del escritorio: 825–1 060 MiB** de VRAM, sin Chrome reproduciendo.
- **`kotoba-whisper-v2.0-faster` no admite `word_timestamps`.** Lleva los
  `alignment_heads` de large-v3 (capas 7 a 25) sobre un decodificador destilado de
  2 capas; CTranslate2 indexa fuera de rango y el proceso muere con `0xC0000005`,
  que no es una excepción de Python y no se puede capturar. Se detecta con una
  sonda en subproceso, cacheada, y se cae a tiempos interpolados por carácter.
- **Los filtros estadísticos contra alucinaciones no funcionan.** Sobre silencio
  digital absoluto, turbo emite 「ご視聴ありがとうございました」 con
  `no_speech_prob = 0,000` y `avg_logprob = −0,143`. El VAD es la única defensa
  real; ver [ADR 0004](docs/adr/0004-el-vad-es-la-barrera.md).
- **Los bucles de repetición hay que cortarlos en el decodificador.** Sobre la
  apertura del reportaje (voz sobre música), turbo se enganchó repitiendo
  「私はサンドルオンを使って、」 hasta agotar la ventana: inferencia de 8 s y
  latencia p95 de 6,3 s. Con `no_repeat_ngram_size`, `repetition_penalty` y una
  cota de `max_new_tokens`, el p95 de inferencia bajó de 1 688 a 571 ms.

- **El umbral de confianza sirve, pero no para lo que parecía.** `avg_logprob < −1,0`
  rechaza 3–5 pasadas legítimas por muestra y no atrapa ni una alucinación, así que
  parecía coste puro. Al aflojarlo a −2,5 los descartes bajan de 5 a 2 pero el p95
  **empeora** de 3 951 a 7 811 ms: aceptar una pasada mala le da a LocalAgreement
  una hipótesis con la que la siguiente no coincide, y la confirmación se retrasa
  una ronda entera. Rechazar basura sale más barato que reconciliarla. Se queda
  en −1,0.

> **Al reproducir estas cifras, cierra juegos y navegadores con aceleración.**
> Con un juego abierto el pico de VRAM pasó de 2 496 a 5 392 MiB y la latencia p50
> casi se duplicó. El banco detecta la contención y lo avisa, pero no puede
> corregirla.

## Requisitos

- Windows 10/11 con GPU NVIDIA y driver reciente (**no** hace falta el CUDA Toolkit:
  las bibliotecas llegan como ruedas de pip).
- [`uv`](https://docs.astral.sh/uv/) para el entorno de Python.
- `ffmpeg` en el `PATH`, para preparar las muestras de audio.

## Puesta en marcha

```powershell
git clone <este repo> ; cd youJP-ESP
.\tasks.ps1 setup       # entorno + bibliotecas CUDA + modelos
.\tasks.ps1 doctor      # comprueba que todo está en su sitio
.\tasks.ps1 test        # tests del backend
```

Prepara una o varias muestras de audio japonés (60 segundos bastan) y lanza el banco:

```powershell
# desde un fichero local
.\scripts\prepare_sample.ps1 -Source "D:\clips\noticias.mp4" -Name noticias -Duration 60

# o directamente desde YouTube (solo el tramo pedido, solo el audio)
.\scripts\fetch_sample.ps1 -Url "https://youtu.be/XXXX" -Name noticias -Start 00:01:30 -Duration 60

.\tasks.ps1 bench
```

Conviene tener cinco muestras de tipos distintos, porque se comportan muy
diferente: informativo (habla clara y pausada), conversación o charla, anime o
drama (habla rápida y coloquial), un tramo con música de fondo, y un tramo de
**silencio puro** — este último es la prueba que de verdad importa, porque es
donde Whisper en japonés inventa frases.

## Usar la extensión

```powershell
# 1. Arranca el backend y déjalo corriendo
cd backend
uv run uvicorn youjp.main:app --host 127.0.0.1 --port 8770

# 2. En otra consola, construye la extensión
cd extension
npm install
npm run build          # deja el resultado en extension/.output/chrome-mv3
```

En Chrome o Edge: `chrome://extensions` → activa **Modo de desarrollador** →
**Cargar descomprimida** → elige `extension/.output/chrome-mv3`.

Abre un vídeo japonés de YouTube y **haz clic en el icono de la extensión**. Ese
clic es obligatorio: `tabCapture` solo concede el permiso tras un gesto del
usuario, y por eso la extensión no tiene popup — con popup, `action.onClicked`
no se dispararía.

- El icono muestra `ON` mientras captura. Otro clic la detiene.
- **Alt+M** abre el panel de métricas sobre el vídeo.
- El texto blanco está confirmado y ya no cambiará; el gris en cursiva todavía
  puede reescribirse.

Durante el desarrollo, `npm run dev` levanta un Chrome aparte con recarga en
caliente.

### Si algo no funciona

| Síntoma | Causa probable |
|---|---|
| «conectando con el backend…» y no avanza | El backend no está arrancado, o está en otro puerto. |
| La pestaña se queda muda | No debería ocurrir: el audio se reinyecta en `offscreen/main.ts`. Si pasa, mira ahí. |
| El audio suena apagado, como un teléfono | Alguien ha vuelto a juntar los dos contextos de audio en uno. El de reproducción tiene que ir a la frecuencia nativa; solo el del ASR va a 16 kHz. |
| No aparece nada y el vídeo no es japonés | Normal: el VAD y los filtros descartan lo que no es habla japonesa. |
| Nada tras un `seek` | Mira el log del backend, debe aparecer `flush del pipeline`. |

Los tres contextos depuran por separado: el service worker y el offscreen en
`chrome://extensions` → *service worker* / *offscreen*, y el content script en la
consola de la propia pestaña de YouTube.

## Probar sin navegador

El backend se puede ejercitar entero sin extensión, que es como se desarrolló:

```powershell
cd backend
uv run python ../scripts/replay_client.py ../bench/samples/11-noticias-entrevista.wav
uv run python ../scripts/replay_client.py <wav> --seek-at 20    # simula un salto
```

Hace exactamente lo que hace la extensión —abrir el WebSocket, anunciar la
sesión y enviar PCM de 16 kHz en tramas de 100 ms al ritmo del reloj— pero
leyendo de un fichero. Cuando algo falle, es la forma rápida de saber de qué
lado está.

Y para comprobar que los dos codecs siguen de acuerdo:

```powershell
cd backend
uv run python ../scripts/check_frame_conformance.py
```

## Los dos modos del banco

```powershell
.\tasks.ps1 bench            # ritmo real: mide LATENCIA
.\tasks.ps1 bench -Fast      # sin pacing: mide RTF
```

- **Latencia** es lo que notarás al usarlo: milisegundos entre que se pronuncia
  una frase y aparece en pantalla. Se mide en `speech_latency_ms`.
- **RTF** (*real-time factor*) dice si el modelo aguanta el ritmo en esta
  máquina. Un RTF de 0,3 significa que procesa 1 s de audio en 0,3 s. Por encima
  de 1,0 el sistema se queda atrás y empieza a descartar pasadas.

Cada ejecución escribe un JSON en `bench/results/`, con la configuración usada
dentro, para que dos ejecuciones se puedan comparar sin adivinar qué cambió.

## Comparar modelos

```powershell
.\tasks.ps1 bench -Model large-v3-turbo
.\tasks.ps1 bench -Model kotoba-tech/kotoba-whisper-v2.0-faster
.\tasks.ps1 bench -Model small
```

## Estructura

```
backend/youjp/
  audio/      captura, buffer circular, VAD
  asr/        Whisper, LocalAgreement, segmentador, filtros de alucinación
  pipeline/   el bucle que lo une todo
  obs/        métricas, GPU, registro
scripts/      descarga de modelos, preparación de muestras, banco de pruebas
bench/        muestras de audio y resultados
docs/         arquitectura y decisiones
```

## Problemas de Windows ya encontrados

### Reserva de memoria del sistema (el importante)

En el panel de control de NVIDIA, en **Administrar configuración 3D →
Configuración del programa**, añade `python.exe` del entorno
(`backend\.venv\Scripts\python.exe`) y pon **CUDA - Política de reserva de
memoria del sistema** en *Preferir que no haya reserva de memoria del sistema*.

Por defecto, cuando se agota la VRAM el controlador WDDM desborda a RAM del
sistema sin avisar: no hay error, solo una inferencia entre 5 y 10 veces más
lenta. Con este ajuste falla de forma ruidosa, que es lo que se quiere al
depurar.

### La descarga de modelos se queda a cero bytes

El backend de almacenamiento *xet* de Hugging Face puede quedarse reconstruyendo
en memoria sin escribir nada en disco durante mucho tiempo. Si `models/whisper`
no crece, usa el descargador clásico, que escribe de forma incremental:

```powershell
$env:HF_HUB_DISABLE_XET = '1'
uv run python ../scripts/fetch_models.py --whisper large-v3-turbo
```

### Los modelos ocupan el doble de lo esperado

Sin *modo de desarrollador* activado, Windows no permite enlaces simbólicos y la
caché de Hugging Face copia cada fichero en lugar de enlazarlo. Un modelo de
1,6 GB pasa a ocupar 3,2 GB. Se arregla activando **Configuración → Sistema →
Para programadores → Modo de desarrollador**, o se ignora si sobra disco.

## Licencias de terceros

JMdict y KANJIDIC2 son del [EDRDG](https://www.edrdg.org/) bajo CC BY-SA 4.0.
Whisper es MIT, Sudachi Apache-2.0. Si en algún momento esto se distribuye,
revisar la licencia no comercial de NLLB-200.
