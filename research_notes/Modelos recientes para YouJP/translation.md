# Modelos recientes de traducción de texto para YouJP

## ¿Cuál es el punto de partida y qué exige nuestro directo?

### Takeaway
Mantener por ahora Qwen3-4B-Instruct-2507 Q4_K_M. Hay candidatos nuevos y razonables, pero esta investigación no ha ejecutado inferencia y no prueba que alguno traduzca mejor japonés a español en YouJP.

### Cited Findings
- El proveedor predeterminado del código es `llm`, con `qwen3:4b-instruct-2507-q4_K_M` en Ollama. El código configura 2.048 tokens de contexto, tres frases japonesas anteriores, máximo 256 tokens de salida, `think:false`, temperatura 0,2 y residencia de 30 minutos. El sistema exige solo la traducción de la última línea, nombres por sonido, sujetos según contexto, registro correcto y no completar fragmentos. Son valores predeterminados del código; las variables de configuración podrían cambiarlos. — [config.py](D:/youJP-ESP/backend/youjp/config.py); [llm.py](D:/youJP-ESP/backend/youjp/mt/llm.py)
- La traducción procesa únicamente segmentos finales, en un trabajador separado de ASR. La cola admite 16 trabajos y descarta el más antiguo si se llena; existen métricas de duración, espera en cola y traducciones descartadas. Al cambiar la línea temporal se borra el contexto. — [translate.py](D:/youJP-ESP/backend/youjp/pipeline/translate.py)
- NLLB-200-distilled-600M convertido a CTranslate2 es una alternativa seleccionable, no un reemplazo automático si falla una respuesta de Ollama. Ignora el contexto. El proveedor LLM devuelve salida vacía ante error HTTP. — [factory](D:/youJP-ESP/backend/youjp/mt/__init__.py); [CT2 NLLB](D:/youJP-ESP/backend/youjp/mt/ct2_nllb.py); [LLM](D:/youJP-ESP/backend/youjp/mt/llm.py)
- El ADR registra mediciones históricas del 14-09-2026 sobre seis frases: Qwen3-4B 5/6 correctas frente a NLLB 2/6, aproximadamente 300 ms y 290 ms de mediana respectivamente; residencia atribuida al traductor 2.741 MiB y 1.117 MiB. README advierte que Whisper, traductor y navegador dejaban solo 400–900 MiB libres en la RTX 2060 de 6.144 MiB. Esto es evidencia histórica, pequeña y de otra ejecución, nunca una medida de esta investigación. — [ADR 0003](D:/youJP-ESP/docs/adr/0003-nmt-dedicado-frente-a-llm.md); [README](D:/youJP-ESP/README.md)
- Las regresiones locales cubren narración en tercera persona, aspirar a ser artista, comparación con interlocutor, apellidos no traducidos literalmente, 技術 según contexto, fragmentos sin completar, una sola línea e inglés básico. No constituyen un corpus representativo ni una revisión ciega; varias reglas están también en el prompt. — [tests de calidad](D:/youJP-ESP/backend/tests/test_translation_quality.py)
- Qwen confirma que el modelo Instruct-2507 solo funciona sin razonamiento y no genera bloques de pensamiento; una variante Qwen3 genérica puede comportarse de forma diferente. — [Qwen oficial](https://huggingface.co/Qwen/Qwen3-4B-Instruct-2507)

### Inferences
- El candidato más interesante debe ahorrar memoria y conservar el uso de contexto. La tarjeta comparte GPU con ASR y navegador, de modo que una mejora aislada de velocidad del traductor puede empeorar el retraso total.
- El historial de seis frases permite detectar errores graves, pero no basta para afirmar superioridad general ni para reemplazar el modelo seleccionado.
- Los nombres propios, sujetos omitidos, frases incompletas y el mandato de traducir solo la última línea son criterios principales, no detalles secundarios de fluidez.

### Gaps
- No medimos latencia, VRAM, calidad, consumo ni estabilidad de ninguno de los candidatos nuevos. No descargamos modelos ni iniciamos servicios.
- Los resultados locales son históricos; no verifiqué aquí el modelo efectivo de un proceso vivo ni posibles cambios de variables de configuración.

## ¿Qué candidatos recientes merecen una prueba local y cuáles descartaría del directo?

### Takeaway
Primera prueba: Hy-MT2-1.8B Q4_K_M oficial. Después, TranslateGemma-4B con su plantilla propia y Qwen3.5-2B/4B sin razonamiento. El orden expresa adecuación e interés para probar, no una clasificación demostrada de calidad japonés-español.

### Cited Findings

| Prioridad | Modelo y fecha verificada | Datos confirmados | Decisión para YouJP |
|---|---|---|---|
| 1 | Hy-MT2-1.8B, 21-05-2026 | Especializado; japonés, español e inglés en idiomas admitidos; contexto y restricciones de traducción en instrucciones oficiales. [Tencent](https://huggingface.co/tencent/Hy-MT2-1.8B) | Primer experimento; intención de reducir presión de memoria frente a 4B. Calidad ja→es y latencia compartida pendientes. |
| 2 | TranslateGemma-4B, 15-01-2026 | Familia especializada 4B/12B/27B. [Anuncio](https://blog.google/innovation-and-ai/technology/developers-tools/translategemma/) | Segundo experimento; cambios de plantilla y nombres propios necesitan atención especial. |
| 3 | Qwen3.5-2B y 4B, 02-03-2026 | Modelos compactos oficiales de nueva arquitectura; fecha en historial oficial. [Qwen](https://github.com/QwenLM/Qwen3.8/blob/main/README.md) | Comparación con generalista reciente; 2B interesa por memoria, 4B como sustituto de calidad. |
| Control | Qwen3-4B-Instruct-2507, generación julio 2025 | Ya integrado, exclusivamente sin razonamiento. [Card](https://huggingface.co/Qwen/Qwen3-4B-Instruct-2507) | Conservar hasta medir una mejora suficiente. |
| Fuera de prioridad | HY-MT1.5-1.8B, 30-12-2025; MADLAD-400-3B, generación 2023 | HY-MT1.5 sustituido por Hy-MT2; MADLAD es T5 multilingüe Apache-2.0. [Historial Tencent](https://github.com/Tencent-Hunyuan/Hy-MT2); [MADLAD](https://huggingface.co/google/madlad400-3b-mt) | HY-MT1.5 solo si MT2 presenta incompatibilidad; MADLAD como alternativa técnica para CT2, no candidato más reciente. |
| Excluidos de residencia conjunta | Hy-MT2-7B/30B-A3B; TranslateGemma-12B/27B; Qwen3.8-27B | Tamaños confirmados por autores; Qwen3.8-27B publicado 14-08-2026. [Tencent](https://github.com/Tencent-Hunyuan/Hy-MT2); [Google](https://blog.google/innovation-and-ai/technology/developers-tools/translategemma/); [Qwen](https://github.com/QwenLM/Qwen3.8/blob/main/README.md) | No priorizar en RTX 2060 6 GiB con ASR simultáneo; inferencia del presupuesto de memoria, no prueba de imposibilidad de descargar o ejecutar con CPU. |

- Hy-MT2 publica GGUF oficiales para llama.cpp y una invocación de Ollama mediante `hf.co/tencent/Hy-MT2-1.8B-GGUF:Q4_K_M`. El archivo Q4_K_M pesa 1,13 GB, Q6_K 1,47 GB y Q8_0 1,91 GB. Son tamaños de archivo, no VRAM total medida. El modelo no define un prompt de sistema predeterminado. — [GGUF y uso](https://huggingface.co/tencent/Hy-MT2-1.8B-GGUF); [archivos](https://huggingface.co/tencent/Hy-MT2-1.8B-GGUF/tree/main); [card](https://huggingface.co/tencent/Hy-MT2-1.8B)
- Verifiqué también el texto de licencia actual de Hy-MT2-1.8B: Apache License 2.0, no solamente la etiqueta de Hugging Face. — [LICENSE.txt](https://huggingface.co/tencent/Hy-MT2-1.8B/blob/main/LICENSE.txt)
- El tamaño de 440 MB de Hy-MT2 corresponde a cuantización extrema de 1,25 bits, no a Q4. La aceleración de 1,5× del artículo es sobre Apple A15 frente a HY-MT1.5 de 4 bits; no es una medición en la RTX 2060 ni con ASR. — [Informe Tencent](https://arxiv.org/html/2605.22064v1)
- TranslateGemma tiene una plantilla particular: solo roles user/assistant; el contenido incluye códigos de origen/destino y únicamente el texto a traducir; la card define contexto de entrada de 2K tokens. Prompts alternativos quedan fuera del soporte oficial. — [Card Google](https://huggingface.co/google/translategemma-4b-it)
- Ollama ofrece TranslateGemma-4B y documenta un prompt completo en un solo mensaje de usuario. El paquete 4B aparece de 3,3 GB, distinto del consumo GPU. Ollama anuncia arquitectura de 128K, mientras Google documenta uso de traducción de 2K: conservar un contexto corto y no deducir soporte efectivo de traducción larga de esa cifra. — [Ollama](https://ollama.com/library/translategemma); [Google](https://huggingface.co/google/translategemma-4b-it)
- TranslateGemma emplea términos Gemma específicos, con obligaciones de redistribución y restricciones de uso; no es Apache ni la misma licencia no comercial de NLLB. NLLB declara CC-BY-NC-4.0 y uso de investigación. — [Términos Gemma](https://ai.google.dev/gemma/terms); [NLLB oficial](https://huggingface.co/facebook/nllb-200-distilled-600M)
- Qwen3.5-4B tiene Apache-2.0 y razona por defecto. El fabricante permite desactivar el razonamiento por parámetros de API/plantilla, pero no mediante los comandos blandos `/think` y `/nothink`. La card advierte de diferencias de eficiencia entre motores. — [Qwen3.5 oficial](https://huggingface.co/Qwen/Qwen3.5-4B)
- Ollama dispone de Qwen3.5 0.8B, 2B y 4B: los paquetes publicados son 1,0 GB, 2,7 GB y 3,4 GB. No interpretar estos tamaños como memoria residente con YouJP; los paquetes incluyen capacidades multimodales. — [Ollama Qwen3.5](https://ollama.com/library/qwen3.5)
- El listado actual de conversión CTranslate2 incluye Gemma3 textual, Qwen3 y T5/MADLAD. Hy-MT2 y Qwen3.5 no figuran por nombre. Compatibilidad de arquitectura no prueba integración en el proveedor NLLB actual: cada modelo necesita su tokenización, plantilla y API correcta. — [Guía CT2](https://github.com/OpenNMT/CTranslate2/blob/master/docs/guides/transformers.md); [README CT2](https://github.com/OpenNMT/CTranslate2/blob/master/README.md)
- Qwen oficial tiene generaciones más recientes y grandes (Qwen3.8-27B, 2.4T-A95B y Flash-Next). No encontré un checkpoint compacto oficial Qwen3.8-4B en el listado del autor; resultados con ese nombre pueden ser destilaciones de terceros. — [Historial oficial](https://github.com/QwenLM/Qwen3.8/blob/main/README.md); [Modelos del autor](https://huggingface.co/Qwen/models)
- En modelos japoneses especializados, Sarashina2.2-3B-instruct-v0.1 anuncia japonés y licencia MIT; sus evaluaciones son conversación/generalismo japonés e inglés, sin evidencia publicada ja→es en la card. MT-Bench es una evaluación de chat de múltiples turnos, no una métrica de traducción automática. — [Sarashina](https://huggingface.co/sbintuitions/sarashina2.2-3b-instruct-v0.1); [MT-Bench original](https://github.com/lm-sys/FastChat#evaluation)

### Inferences
- Empezaría por GGUF Q4_K_M normal en Hy-MT2 para equilibrar calidad y memoria. La cuantización extrema es una investigación aparte y no debería sustituir el control inicial.
- Cambiar únicamente el nombre del modelo sería una comparación deficiente: Hy-MT2 usa instrucciones y antecedentes en un mensaje; TranslateGemma tiene contrato específico. Conservar las tres frases como contexto exige validar que el modelo no las traduzca ni las trate como instrucciones.
- Apache-2.0 de Hy-MT2 hace más fácil estudiar un eventual reemplazo distribuible de NLLB; su ventaja práctica debe confirmarse con calidad y latencia.
- No usaría un modelo japonés monolingüe como primera opción para producir español solamente porque destaque en preguntas en japonés.

### Gaps
- No existe en las fuentes examinadas una medida reproducible en RTX 2060 6 GiB de estos candidatos junto a Whisper turbo y Chrome.
- Falta confirmar versión mínima de Ollama instalada y soporte real de arquitectura/plantilla Hy-MT2. La documentación Hugging Face incluye instrucciones generadas de apps; eso no demuestra funcionamiento en nuestra instalación.
- Falta medir memoria GPU de texto de Qwen3.5 y TranslateGemma: ni parámetros, ni GB de descarga, ni contexto máximo anuncian el consumo conjunto.
- No se confirmó una fecha de publicación exacta de Sarashina2.2-3B en esta búsqueda; no presentarlo como lanzamiento reciente de 2026.

## ¿Qué pruebas y experiencias públicas justifican la selección?

### Takeaway
La evidencia pública justifica probar Hy-MT2-1.8B, pero no afirma que ya supere al modelo actual en nuestros subtítulos. TranslateGemma contiene una advertencia excepcionalmente pertinente para japonés: regresiones de entidades con nombre en evaluación humana, pese a mejoras agregadas.

### Cited Findings
- El informe de Hy-MT2 evalúa 1.056 direcciones entre 33 idiomas en FLORES y publica promedios ZH↔XX, EN↔XX y XX↔XX. Para 1.8B reporta XCOMET-XXL de 79,77 en XX↔XX. Ese promedio no da una puntuación separada japonés→español ni enfrenta nuestro Qwen3-4B-Instruct-2507 Q4 en subtítulos. Su IFMTBench incluye instrucciones japonesas y españolas, útil como evidencia de restricciones, no como prueba del par requerido. — [Informe, secciones 3.1–3.4](https://arxiv.org/html/2605.22064v1)
- Google evaluó humanamente ja→en con MQM en WMT25 para TranslateGemma-12B/27B. Obtuvieron 15,7 y 13,4 (menor es mejor), frente a 11,6 de Gemma3-27B. El artículo atribuye la regresión a entidades con nombre. No hay en esa tabla 4B ni japonés→español; el entrenamiento no inglés listado tampoco especifica ja↔es. — [Informe Google, páginas 5–6 y tabla 7](https://arxiv.org/pdf/2601.09012)
- Un usuario publicó el 13-07-2026 un caso Hy-MT2 de contexto inglés y destino español: al incluir corchetes y ciertas indentaciones, tradujo contexto adicional en vez de limitarse a `[stable]`; con otra indentación dejó `[stable]` sin traducir. Es un informe de primera mano con entrada/salida, pendiente de reproducir aquí y sin identificación clara de tamaño/cuantización. — [Issue #12](https://github.com/Tencent-Hunyuan/Hy-MT2/issues/12)
- El mismo autor abrió el 15-07-2026 otro issue indicando fallos de separación entre instrucciones y datos, y proponiendo etiquetas explícitas para fuente/contexto. La propuesta es de un usuario, no una solución confirmada por autores ni un hallazgo reproducido en YouJP. — [Issue #13](https://github.com/Tencent-Hunyuan/Hy-MT2/issues/13)
- En un hilo de Reddit sobre Hy-MT2, un usuario dice usar el 7B y preferirlo a TranslateGemma. No especifica par de idiomas ni corpus, hardware o latencia medidos; no convierte al 1.8B en ganador de ja→es. El navegador muestra fechas relativas de cuatro meses, por lo que no asignar día exacto a ese comentario. — [Hilo LocalLLaMA](https://www.reddit.com/r/LocalLLaMA/comments/1tjien7/tencent_hy_30b7b18b/)
- En otro hilo japonés→inglés, un usuario refiere que su esposa japonesa considera decente TranslateGemma-12B, pero explícitamente no sabe si 4B alcanza calidad suficiente. Es opinión doméstica sin evaluación reproducible; no prueba japonés→español ni adecuación al equipo. La página ofrece tiempos relativos, no día absoluto validado. — [Hilo LocalLLM](https://www.reddit.com/r/LocalLLM/comments/1wc003y/most_accurate_and_fast_jp_to_eng_translation_model/)

### Inferences
- Plan de comparación propuesto, no ejecutado: corpus ciego de al menos 150–300 segmentos reales (noticias, conversación, anime, juegos, voces sobre música), con referencias humanas bilingües y contexto de tres frases. Incluir los siete errores locales y más casos que no estén escritos en el prompt.
- Separar la calidad sobre japonés corregido de la calidad con errores ASR reales. El primer experimento compara traducción; el segundo mide el comportamiento end-to-end que recibe el usuario.
- Revisar por separado inversión de significado, negación, sujeto/persona, nombres propios, completado de fragmentos, términos, registro, omisiones y salida de contexto/notas/razonamiento. Una traducción fluida pero incorrecta no debe recibir buena calificación.
- Medir en misma sesión y con un solo traductor residente: p50/p95 de traducción, espera en cola, traducciones descartadas, latencia visible completa y pico GPU combinado con ASR y reproducción de Chrome. Exigir ausencia de crecimiento de cola y reserva real de VRAM.
- Comparar Qwen actual con prompt existente y candidatos con plantillas del autor más contexto adaptado; documentar modelo, hash, cuantización, motor, versión, parámetros, límites y número de repeticiones. Desactivar pensamiento y comprobar que no aparece ni consume latencia escondida.
- Criterio sugerido de adopción: reducción clara de errores graves de ja→es, sin empeorar las regresiones ni p95 total; alternativamente calidad estadísticamente comparable con ahorro de memoria que permita sostener el directo sin descartes. Validar ja→en por separado. Son criterios del investigador, no resultados publicados.

### Gaps
- No hallé evaluación pública sólida que compare directamente Hy-MT2-1.8B Q4, TranslateGemma4B Q4 y Qwen3-4B-Instruct-2507 Q4 sobre japonés→español hablado con contexto.
- Reddit ofrece entusiasmo y casos útiles, pero no aporta mediciones del hardware ni corpus del proyecto. Las fuentes con fecha absoluta más fiables de primera mano son los issues citados.
- Que una empresa patrocine una tarea de subtítulos WMT26 no prueba resultados ganadores, simultaneidad o baja latencia de un modelo particular.
