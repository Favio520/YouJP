# ASR local japonés para YouJP — corte 3 de octubre de 2026

## 1. ¿Qué tenemos realmente y qué exige el directo?

### Takeaway
La base real es Whisper large-v3-turbo con CTranslate2 en una RTX 2060 de 6 GB. Cualquier sustituto debe medirse junto al traductor residente, preservar texto japonés y sincronización, y sostener habla continua; una cifra de throughput de servidor no demuestra eso.

### Cited Findings
- Verificación local de esta investigación, sin cargar modelos: `nvidia-smi --query-gpu=name,memory.total,memory.free,driver_version --format=csv,noheader` devolvió `NVIDIA GeForce RTX 2060, 6144 MiB, 4675 MiB, 591.74`. Los 4675 MiB libres son únicamente un snapshot de procesos actuales, NO una medición con ASR y MT activos. La consulta CIM de RAM fue denegada; no se afirma RAM total.
- Defaults y launcher coinciden: ASR `large-v3-turbo`, CUDA, `int8_float16`, japonés, beam 1. MT usa por defecto Ollama `qwen3:4b-instruct-2507-q4_K_M`, GPU y contexto 2048. — [config.py](</D:/youJP-ESP/backend/youjp/config.py>), [launcher.env](</D:/youJP-ESP/.youjp/launcher.env>)
- Audio mono 16 kHz; frames de 100 ms; Silero VAD con cierre tras 500 ms de silencio. Se redecodifica el buffer creciente cada 0,8 s, con recorte a 15 s. LocalAgreement-2 confirma el prefijo coincidente de dos pasadas. No es ASR incremental nativo. — [config.py](</D:/youJP-ESP/backend/youjp/config.py>), [hypothesis.py](</D:/youJP-ESP/backend/youjp/asr/hypothesis.py>)
- El motor devuelve tiempos absolutos y unidades finas. `word_timestamps=auto` consulta la capacidad; puede interpolar caracteres si el modelo carece de marcas. Eso mantiene el flujo a costa de precisión temporal. Cache: turbo sí admite marcas, Kotoba v2.0-faster no. Carpetas locales presentes: turbo, Kotoba v2.0-faster y tiny; presencia no implica que todos los snapshots estén completos. — [engine.py](</D:/youJP-ESP/backend/youjp/asr/engine.py>), [.asr_capabilities.json](</D:/youJP-ESP/models/.asr_capabilities.json>)
- Benchmark guardado del 14-09-2026, tres extractos de noticias, turbo: ASR p50 **362/440/383 ms**, p95 **543/625/567 ms**; latencia p50 **1440/1666/1421 ms**, p95 **3951/2673/2065 ms**. VRAM atribuible ASR **1315 MiB**, pico total **2495,8 MiB**, `contended=false`. Evidencia histórica releída, NO nuevo ensayo ni consumo conjunto con MT. — [resultado turbo](</D:/youJP-ESP/bench/results/20260914-181613-large-v3-turbo-realtime-fase0-final.json>)
- Kotoba local: latencia p95 **7301/4359/6740 ms**, `contended=true`; no constituye una comparación controlada frente a turbo. — [resultado Kotoba](</D:/youJP-ESP/bench/results/20260914-173106-kotoba-tech_kotoba-whisper-v2.0-faster-realtime-real-v3.json>)

### Inferences
- El presupuesto real debe incluir escritorio, ASR, MT, buffers y activaciones. Peso de archivo o parámetros no equivalen a VRAM pico.
- Al cambiar a streaming cacheado, el adaptador debe gestionar estados/parciales/finales y reset por cambio de vídeo; no basta con cambiar el nombre del modelo de Whisper.

### Gaps
- No se corrió inferencia, se descargaron pesos ni se iniciaron servicios. No hay comparación nueva de CER, latencia o VRAM conjunta. No se verificó RAM del equipo.

## 2. ¿Qué modelos recientes merecen una prueba?

### Takeaway
Nemotron 3.5 es el candidato reciente más alineado con menor latencia. Qwen3-ASR es interesante para reconocimiento, pero sus ventajas publicadas no equivalen a una mejora local automática, especialmente la variante pequeña.

### Cited Findings
- **Nemotron-3.5-ASR-Streaming-0.6B**: fecha oficial de publicación **04-06-2026**, indicada como `Release Date`, distinta de actualización de archivos. Japonés `ja-JP` en nivel transcription-ready; arquitectura RNNT/FastConformer con caché, chunks 80–1120 ms; licencia **OpenMDW-1.1**. Turing soportado; la integración NeMo de la ficha lista Linux. FLEURS japonés, CER autorreportado con idioma fijado: **12,22 % a 320 ms**, **11,91 % a 560 ms**, **11,48 % a 1120 ms**. Las pruebas de concurrencia son H100, no RTX 2060. — [ficha NVIDIA](https://huggingface.co/nvidia/nemotron-3.5-asr-streaming-0.6b)
- El runtime oficial **NVIDIA/NeMo-Speech.cpp** tiene versión **v0.1.0 de 19-08-2026** y **v0.2.0 de 02-10-2026**; ambas anteriores al corte. — [releases](https://github.com/NVIDIA/NeMo-Speech.cpp/releases)
- NeMo-Speech.cpp documenta builds Windows nativos con CPU/CUDA/Vulkan, Visual Studio 2022 y CUDA 12/13. — [builds oficiales](https://github.com/NVIDIA/NeMo-Speech.cpp/blob/main/docs/build.md)
- Su API WebSocket recibe PCM y entrega parciales/finales; `word_timestamps=true` agrega tiempos en los **eventos finales**. No se ha demostrado aquí alineación japonesa precisa ni tiempos de cada parcial. — [API oficial](https://github.com/NVIDIA/NeMo-Speech.cpp/blob/main/docs/api.md)
- **Qwen3-ASR-0.6B / 1.7B**: publicación oficial **29-01-2026**; soporte nativo Transformers anunciado **26-06-2026**; japonés, Apache-2.0. La interfaz oficial ofrece streaming solamente mediante vLLM y **sin timestamps**; para alineación palabra/carácter añade **Qwen3-ForcedAligner-0.6B**, que admite japonés. — [repositorio oficial Qwen](https://github.com/QwenLM/Qwen3-ASR)
- La tabla multilingüe autorreportada de Qwen distingue tamaños: FLEURS agregado **7,57 %** para 0.6B y **4,90 %** para 1.7B, frente a Whisper large-v3 **5,27 %**. Es promedio multilingüe offline, NO CER japonés de nuestros vídeos, ni comparación contra turbo. No respalda llamar a 0.6B universalmente superior. — [ficha Qwen 0.6B](https://huggingface.co/Qwen/Qwen3-ASR-0.6B)
- vLLM no soporta Windows nativo oficialmente; propone WSL o forks. El mínimo CUDA documentado es compute capability 7.5, incluyendo RTX20xx. Esto permite considerar la familia de GPU, pero no garantiza memoria ni kernels de cada modelo. — [instalación vLLM](https://docs.vllm.ai/en/latest/getting_started/installation/gpu/)
- **Kotoba-Whisper-v2.2** reutiliza v2.0 y agrega diarización/puntuación; no es una nueva arquitectura ASR incremental. Añade Transformers, pyannote/diarizers y modelos de diarización sujetos a acceso. No es un upgrade sencillo para nuestro directo. — [ficha oficial](https://huggingface.co/kotoba-tech/kotoba-whisper-v2.2)
- **SenseVoiceSmall** es una alternativa pequeña, no autoregresiva. La documentación de sherpa-onnx muestra reconocimiento offline con timestamps por token, y su ejemplo de directo declara explícitamente streaming **simulado** mediante VAD y SenseVoice no streaming. Considerarlo para liberar VRAM/CPU, no prometer menor demora en frases largas. — [API SenseVoice](https://github.com/k2-fsa/sherpa/blob/master/docs/source/onnx/sense-voice/python-api.rst), [ejemplo mantenedor](https://github.com/k2-fsa/sherpa-onnx/blob/master/python-api-examples/simulate-streaming-sense-voice-microphone.py)
- **Parakeet-tdt_ctc-0.6b-ja** existe y está especializado en japonés con licencia CC-BY-4.0 y benchmark CER. No confundirlo con Parakeet v3 europeo. La ficha consultada no demuestra el contrato de streaming cacheado y timestamps requerido aquí, así que no se prioriza. — [ficha NVIDIA](https://huggingface.co/nvidia/parakeet-tdt_ctc-0.6b-ja)

### Inferences
- Orden propuesto: **mantener turbo como base**, probar **Nemotron 3.5 + NeMo-Speech.cpp** para latencia; después **Qwen3-ASR 0.6B** para coste/calidad si cabe junto a MT. Qwen 1.7B y alineador en GPU suman un presupuesto más difícil en 6 GB.
- Nemotron exige proveedor/adaptador nuevo y mapeo de eventos finales al contrato YouJP. Puede conservar VAD, tokenización y traductor existentes. Qwen con Transformers por chunks exigiría estabilización y alineación/interpolación propias; su streaming oficial añade WSL/vLLM y no entrega timestamps.
- Los 320/560 ms de chunk son contextos algorítmicos, no promesas de latencia extremo a extremo del subtítulo traducido.

### Gaps
- VRAM/RTF Windows RTX2060 de Nemotron y Qwen no verificados. Calidad en anime, habla informal, música, nombres y mezclas de hablantes no establecida por estas cifras.
- La licencia OpenMDW se identifica, pero esta investigación no sustituye revisar las condiciones de redistribución antes de empaquetar pesos/runtime.
- No se encontró un benchmark controlado reciente con nuestros clips, ambos modelos residentes y métricas de traducción final.

## 3. ¿Qué dicen los usuarios y qué permitiría decidir?

### Takeaway
Los foros aportan señales para diseñar pruebas, no un ganador. Hay reportes favorables de Qwen y también fallos concretos de streaming/endpointing que justifican medir sesiones largas.

### Cited Findings
- Experiencia individual en Reddit: el autor comparó Whisper turbo, Voxtral y Qwen3-ASR1.7B, prefirió Qwen en su escenario, usó chunks con Transformers, pero reportó degradación acumulada al probar vLLM. No identifica una prueba japonesa/RTX2060 reproducible; es **anecdótico**. — [reporte de primera persona](https://www.reddit.com/r/LocalLLaMA/comments/1rq118c/qwen3_asr_seems_to_outperform_whisper_in_almost/)
- Issue del **21-09-2026**: Qwen-ASR en Windows falla al cargar cuando la ruta contiene caracteres no ASCII, ligado a nagisa/DyNet. Es reporte concreto, no demostración de que todas las instalaciones Windows fallen. — [issue Qwen #214](https://github.com/QwenLM/Qwen3-ASR/issues/214)
- Issue del **10-09-2026**: NeMo-Speech.cpp con endpointing activado y sin VAD puede cerrar a mitad de frase y resetear el decoder, corrompiendo continuidad. Reportado/reproducido por el autor; comprobar versión/fix y configuración en el piloto, no asumir que ocurre siempre. — [issue NVIDIA #40](https://github.com/NVIDIA/NeMo-Speech.cpp/issues/40)

### Inferences
- Piloto aislado sin sustituir defaults: mismos clips y transcripciones de referencia; japonés CER, nombres/negaciones, parciales estables, p50/p95 de texto japonés y traducción española final, sincronización, silencio/música y VRAM pico con MT activo.
- Agregar directo de 20–30 min para detectar deriva, acumulación, resets y contención. Comparar Nemotron 320/560 ms y Qwen0.6B frente al turbo existente; aprobación solo si conserva calidad y mejora la métrica objetivo.
- Con la evidencia disponible, afirmar «hay candidatos mejores para estudiar» es defendible; afirmar «ya encontramos un reemplazo superior probado» no lo es.

### Gaps
- No se instaló ni evaluó ningún candidato en esta investigación. Las fuentes/benchmarks publicados y los reportes individuales quedan separados de la prueba local pendiente.
