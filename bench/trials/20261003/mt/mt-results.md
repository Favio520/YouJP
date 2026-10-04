# Prueba aislada de traducción YouJP — 3 de octubre de 2026

La prueba mide traducción de texto japonés a subtítulos en español y un subconjunto en inglés. No mide ASR, audio a subtítulo, captura de navegador ni contención durante inferencia concurrente. No modifica el proveedor ni el modelo predeterminado.

Whisper no está cargado por esta prueba.

Las traducciones y las preguntas de revisión permiten una revisión semántica; las coincidencias de palabras y el éxito de la API no prueban calidad. Los casos escritos a mano están identificados. Varias frases de regresión ya están enseñadas explícitamente en el prompt de Qwen; no son una prueba ciega.

## Condiciones

- Ollama: `{'version': '0.35.0'}`.
- Semilla base: 20261003; 2 repeticiones por caso.
- Modelo baseline: `qwen3:4b-instruct-2507-q4_K_M`.
- Modelo candidato: `youjp-trial-hymt2:1.8b-q4_k_m-20261003`.
- Baseline: prompt y limpieza actuales de `backend/youjp/mt/llm.py`, temperatura 0.2.
- Candidato: prompt de traducción de Tencent sin system prompt; para contexto usa el ejemplo de información de fondo con la instrucción explícita de traducir solo la última línea.
- La importación directa de Hugging Face en Ollama 0.35.0 devolvió una plantilla sin `.Prompt` ni `.Response` y con texto residual `onse }}`. Se creó un alias aislado con los mismos pesos y la plantilla exacta del caso de un único mensaje de usuario de Tencent. La importación original y la plantilla oficial se preservan en los artefactos de esta prueba.
- Candidato: temperatura 0.7, top_p 0.6, top_k 20, repeat_penalty 1.05. Se mantiene el límite de 256 tokens / contexto 2048 del caso en vivo, frente a 4096 tokens sugeridos por Tencent.
- Comparación de dos configuraciones apropiadas a cada modelo, con prompts y parámetros diferentes; no permite atribuir todas las diferencias únicamente a los pesos.
- Primera petición con el modelo descargado de VRAM; caché de archivos del SO sin limpiar. Las mediciones calientes siguen a esa petición y reutilizan el mismo modelo.
- Streaming de la API para medir primer contenido; YouJP actualmente consume la traducción completa.
- Timeout de socket/inactividad de 120 s y comprobación de plazo al recibir cada bloque; un read bloqueado puede consumir su timeout aunque el plazo global ya haya vencido. No es una garantía de cancelación global exacta.
- p95 interpolado sobre una muestra pequeña; es descriptivo, sin intervalo de confianza.

## Tiempos

| Configuración | Peticiones calientes | Errores API | Primera carga y traducción (ms) | Español p50 (ms) | Español p95 (ms) | Todos p50 (ms) | Todos p95 (ms) | Máximo (ms) | Primer contenido p50 (ms) | Primer contenido máximo (ms) |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| baseline | 38 | 0 | 27177.221 | 218.921 | 386.328 | 215.928 | 384.15 | 391.881 | 69.502 | 191.848 |
| candidate | 38 | 0 | 2653.238 | 171.933 | 302.144 | 159.913 | 293.67 | 9685.451 | 35.42 | 9644.912 |

## VRAM observada

Muestreo NVML a 4 Hz de VRAM total usada, incluido escritorio y Whisper cuando está residente. Un pico corto puede quedar entre muestras; `/api/ps` registra además el tamaño residente de cada traductor.

| Configuración | Base antes de cargar MT (MiB) | Pico observado (MiB) | MT residente según Ollama (MiB) |
|---|---:|---:|---:|
| baseline | 1436.4 | 4283.4 | 2740.9 |
| candidate | 1436.4 | 2804.7 | 1253.7 |

Caso de mayor tiempo: `candidate` `reg_fragment` r1, 9685.5 ms, primer contenido 9644.912 ms, prefill/prompt_eval 9611.7 ms, 5 tokens generados, terminación `stop`.


## Traducciones completas para revisión

### reg_aspiration (es)

Procedencia: backend/tests/test_translation_quality.py; real transcript regression, reviewed 2026-09-14

Japonés: 漫画家を目指して10年以上になるという田中さん

Revisión: Keep third-person Tanaka and over ten years of trying/aspiring to become a manga artist; do not claim that he already is one.

- baseline r1 (360 ms): Señor Tanaka lleva más de 10 años aspirando a ser dibujante de manga.
- baseline r2 (390 ms): Señor Tanaka ha estado intentando ser dibujante de manga durante más de 10 años.
- candidate r1 (209 ms): Señor Tanaka, que lleva más de 10 años aspirando ser mangaká.
- candidate r2 (223 ms): La señora Tanaka lleva más de 10 años intentando convertirse en dibujante de manga.

### reg_subject_context (es)

Procedencia: backend/tests/test_translation_quality.py; real transcript regression, reviewed 2026-09-14

Japonés: ここで毎朝2時間勉強しています

Contexto previo:

> 一方西梅田店は朝5時から営業
> 証券会社でお客様対応をしている35歳の西山さん

Revisión: Use third-person studies; translate only the last line, without adding Nishiyama's age, job or the shop opening time.

- baseline r1 (197 ms): Estudia aquí dos horas cada mañana.
- baseline r2 (209 ms): Estudia aquí dos horas cada mañana.
- candidate r1 (164 ms): Aquí estudia 2 horas cada mañana.
- candidate r2 (136 ms): Aquí estudia 2 horas cada mañana.

### reg_comparison_skill (es)

Procedencia: backend/tests/test_translation_quality.py; real transcript regression, reviewed 2026-09-14

Japonés: 魔力も技術もコントロールも私の方が遥かに上

Revisión: The speaker is far above the other person in magical power, skill/technique and control. Do not invert comparison, use 'los míos', or translate skill as industrial technology.

- baseline r1 (297 ms): Mi magia, mi técnica y mi control son mucho más superiores que los tuyos.
- baseline r2 (290 ms): Mi magia, mi técnica y mi control son mucho más superiores que los tuyos.
- candidate r1 (235 ms): Tanto el poder mágico, como la tecnología y el control, son mucho más superiores los míos.
- candidate r2 (237 ms): Tanto el poder mágico, como la tecnología y el control, son mucho mejores que los míos.

### reg_proper_name (es)

Procedencia: backend/tests/test_translation_quality.py; real transcript regression, reviewed 2026-09-14

Japonés: 証券会社でお客様対応をしている35歳の西山真さん

Revisión: Preserve age 35, customer-facing securities job and Nishiyama by sound. Given-name reading 真 is not established in this isolated line; do not score one reading as certain.

- baseline r1 (392 ms): Nishiyama Shin, de 35 años, que trabaja en una compañía de valores atendiendo a clientes.
- baseline r2 (383 ms): Nishiyama Shin, de 35 años, que trabaja en una compañía de valores atendiendo a clientes.
- candidate r1 (282 ms): Shin Nishi, de 35 años, que trabaja en una compañía de valores y se encarga del servicio al cliente
- candidate r2 (318 ms): La señora Nishiyama Makiko, de 35 años, que trabaja en una compañía de valores y se encarga del servicio al cliente.

### reg_fragment (es)

Procedencia: backend/tests/test_translation_quality.py; real transcript regression, reviewed 2026-09-14

Japonés: と言って

Revisión: Translate the short quoted-speech fragment without inventing a completed event.

- baseline r1 (113 ms): Y diciendo que
- baseline r2 (120 ms): Y diciendo que
- candidate r1 (9685 ms): Y dijo eso
- candidate r2 (55 ms): Y dijo eso

### reg_one_line (es)

Procedencia: backend/tests/test_translation_quality.py; real transcript regression, reviewed 2026-09-14

Japonés: 今日は経済への影響について話します。

Revisión: A natural subtitle about discussing effects on the economy today; no commentary or extra lines.

- baseline r1 (224 ms): Hoy hablaré sobre su influencia en la economía.
- baseline r2 (217 ms): Hoy hablaré sobre su influencia en la economía.
- candidate r1 (180 ms): Hoy hablaremos sobre las repercusiones en la economía.
- candidate r2 (156 ms): Hoy hablaremos sobre los efectos en la economía.

### edge_negation (es)

Procedencia: manually authored edge case; not a recording

Japonés: 行かないわけではないけど、今日はやめておく。

Revisión: The speaker does not flatly refuse to go; today they choose to leave it. Preserve the double-negation nuance without reversing the decision.

- baseline r1 (222 ms): Aunque no voy a dejar de ir, hoy lo dejaré.
- baseline r2 (225 ms): Aunque no voy a dejar de ir, hoy lo dejo.
- candidate r1 (185 ms): No, no voy a ir, pero hoy me decido a no hacerlo.
- candidate r2 (171 ms): No es que no iré, pero hoy me decido a dejarlo.

### edge_numbers (es)

Procedencia: manually authored edge case; not a recording

Japonés: 料金は税込みで一万二千五百円、割引はありません。

Revisión: Preserve 12,500 yen, taxes included, and no discount.

- baseline r1 (224 ms): El precio incluye impuestos y no hay descuento.
- baseline r2 (205 ms): El precio incluye impuestos y no hay descuento.
- candidate r1 (260 ms): El costo, incluyendo impuestos, es de veintidós mil quinientos yenes; no hay descuentos.
- candidate r2 (289 ms): El costo, incluyendo impuestos, es de veinticuatro mil quinientas yenes; no hay descuentos.

### edge_politeness (es)

Procedencia: manually authored edge case; not a recording

Japonés: 恐れ入りますが、少々お待ちいただけますか。

Revisión: A polite request to wait a moment, maintaining polite register without a long cultural explanation.

- baseline r1 (214 ms): Perdón, ¿podría esperar un momento?
- baseline r2 (217 ms): Perdón, ¿podría esperar un momento?
- candidate r1 (149 ms): Lamento molestarlo, pero ¿podría esperar un poco?
- candidate r2 (133 ms): Perdóneme, ¿podría esperar un poco?

### edge_colloquial (es)

Procedencia: manually authored edge case; not a recording

Japonés: マジで？めっちゃすごいじゃん。

Revisión: Natural informal surprise and praise; preserve questions and colloquial register.

- baseline r1 (181 ms): Serio? ¡Es impresionante!
- baseline r2 (191 ms): En serio? ¡Es impresionante!
- candidate r1 (142 ms): ¿En serio? Es realmente impresionante.
- candidate r2 (141 ms): ¿En serio? Es realmente impresionante.

### edge_unfinished_condition (es)

Procedencia: manually authored edge case; not a recording

Japonés: もし明日までに返事がなかったら

Revisión: Preserve the unfinished condition 'if there is no reply by tomorrow'; do not invent what happens next.

- baseline r1 (153 ms): Si no me respondieran antes de mañana
- baseline r2 (161 ms): Si no me respondieran antes de mañana
- candidate r1 (140 ms): Si no recibo respuesta hasta mañana,
- candidate r2 (116 ms): Si no recibo respuesta hasta mañana,

### edge_idiom (es)

Procedencia: manually authored edge case; not a recording

Japonés: 猫の手も借りたいくらい忙しい。

Revisión: Express being extremely busy / needing any help, without presenting literal cat labor as the intended meaning.

- baseline r1 (274 ms): Estoy tan ocupado que incluso me haría falta un gato para ayudarme.
- baseline r2 (259 ms): Estoy tan ocupado que incluso me haría falta ayuda de un gato.
- candidate r1 (176 ms): Estoy tan ocupado que hasta quiero pedir la mano de un gato.
- candidate r2 (180 ms): Estoy tan ocupado que quiero pedir la mano de un gato.

### edge_terms_places (es)

Procedencia: manually authored edge case; not a recording

Japonés: 本町から西梅田まで地下鉄で行きます。

Revisión: Travel by subway from Honmachi to Nishi-Umeda, preserving both place names by sound.

- baseline r1 (272 ms): Voy desde Honmachi hasta Nishi-Umeda en el metro.
- baseline r2 (254 ms): Voy desde Honmachi hasta Nishi-Umeda en el metro.
- candidate r1 (184 ms): Desde Honmachi hasta Nishi-Medaka, se puede ir en metro.
- candidate r2 (173 ms): Desde Honmachi hasta Nishi-Medaka, se puede ir en metro.

### ctx_subject_three (es)

Procedencia: manually authored edge case; not a recording

Japonés: 毎朝ここで二時間勉強しています。

Contexto previo:

> これは田中さんです。
> 田中さんは試験に向けて準備しています。
> 勉強場所は図書館です。

Revisión: Third-person studies for two hours every morning; preceding Tanaka/library/exam information must only resolve context, without being translated again.

- baseline r1 (209 ms): Estudia aquí dos horas cada mañana.
- baseline r2 (215 ms): Estudia aquí dos horas cada mañana.
- candidate r1 (166 ms): Cada mañana estudia aquí durante dos horas.
- candidate r2 (173 ms): Todos los días por la mañana estudio aquí durante dos horas.

### ctx_person_three (es)

Procedencia: manually authored edge case; not a recording

Japonés: 昨日、退院しました。

Contexto previo:

> 山田さんには娘がいます。
> 娘の名前は美咲です。
> 美咲は先週、病院に入院しました。

Revisión: Context identifies Misaki as the discharged person; preserve yesterday and discharge rather than admission, without repeating the family/intake history.

- baseline r1 (171 ms): Se graduó ayer.
- baseline r2 (171 ms): Se retiró del hospital ayer.
- candidate r1 (130 ms): Ayer, se fue del hospital.
- candidate r2 (110 ms): Ayer, se fue del hospital.

### ctx_no_repetition_three (es)

Procedencia: manually authored edge case; not a recording

Japonés: 会議は午後三時からです。

Contexto previo:

> 昨日は東京へ行きました。
> 西山さんと寿司を食べました。
> 新幹線で帰ってきました。

Revisión: Only the meeting starting at 3 p.m.; prior Tokyo/Nishiyama/sushi/train sentences must not reappear.

- baseline r1 (221 ms): La reunión comienza a las tres de la tarde.
- baseline r2 (237 ms): La reunión comienza a las tres de la tarde.
- candidate r1 (145 ms): La reunión es a las tres de la tarde.
- candidate r2 (109 ms): La reunión es a las tres de la tarde.

### en_economy (en)

Procedencia: backend/tests/test_translation_quality.py; real transcript regression, reviewed 2026-09-14

Japonés: 今日は経済について話します。

Revisión: Discuss the economy today in English.

- baseline r1 (281 ms): Today I'll talk about economics.
- baseline r2 (174 ms): Today I'll talk about economics.
- candidate r1 (118 ms): Today, we will talk about economics.
- candidate r2 (115 ms): Today, we will talk about economics.

### en_name (en)

Procedencia: backend/tests/test_translation_quality.py; real transcript regression, reviewed 2026-09-14

Japonés: 私の名前は田中です。

Revisión: The speaker's name is Tanaka, in English.

- baseline r1 (143 ms): My name is Tanaka.
- baseline r2 (148 ms): My name is Tanaka.
- candidate r1 (76 ms): My name is Tanaka.
- candidate r2 (73 ms): My name is Tanaka.

### en_thanks (en)

Procedencia: backend/tests/test_translation_quality.py; real transcript regression, reviewed 2026-09-14

Japonés: ありがとうございます。

Revisión: A polite thank-you in English.

- baseline r1 (95 ms): Thank you.
- baseline r2 (120 ms): Thank you.
- candidate r1 (64 ms): Thank you.
- candidate r2 (66 ms): Thank you.

## Fuentes primarias verificadas

- [Ficha oficial y prompts de Hy-MT2](https://huggingface.co/tencent/Hy-MT2-1.8B-GGUF)
- [Archivo Q4_K_M oficial y SHA256](https://huggingface.co/tencent/Hy-MT2-1.8B-GGUF/blob/main/Hy-MT2-1.8B-Q4_K_M.gguf)
- [Importación GGUF de Ollama](https://docs.ollama.com/import)

- [Plantilla oficial del tokenizer](https://huggingface.co/tencent/Hy-MT2-1.8B/blob/main/chat_template.jinja)

Los detalles de plantilla, parámetros, contadores de evaluación, tiempos, versión, VRAM y errores están en `mt-results.json`; `mt-runs.jsonl` preserva cada petición inmediatamente.
