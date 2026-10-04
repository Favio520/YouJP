# Pruebas locales de modelos YouJP

**Mantener Qwen3-4B y Whisper turbo como predeterminados.** Las pruebas del 3 de octubre de 2026 en Windows y la RTX 2060 de 6 GiB confirmaron menor mediana y memoria en Hy-MT2-1.8B, pero errores de cifras, nombres y comparaciones. Nemotron funciona con CUDA y reduce el retraso observado de finales japoneses; falta resolver tiempos e integración. Ninguno demostró mejora completa del subtítulo español. Los ajustes de producción permanecieron intactos.

Ollama 0.35.0 importó Hy-MT2 con una plantilla defectuosa. Se corrigió mediante el alias aislado `youjp-trial-hymt2:1.8b-q4_k_m-20261003`, reutilizando pesos oficiales Q4_K_M con SHA256 verificado y la plantilla de Tencent para un mensaje. Qwen conservó sus parámetros; Hy usó los del fabricante. Se comparan configuraciones prácticas diferentes. ([Evaluación MT](</D:/youJP-ESP/bench/trials/20261003/mt/mt-assessment.md>), [Modelfile](</D:/youJP-ESP/bench/trials/20261003/mt/Modelfile.hymt2>))

| Traducción de texto | Qwen actual | Hy-MT2 |
|---|---:|---:|
| Español, modelo solo: p50 / p95, 32 peticiones calientes | 218,9 / 386,3 ms | 171,9 / 302,1 ms |
| Español, Whisper residente: p50 / p95, 16 peticiones calientes | 223,1 / 347,9 ms | 164,1 / 265,0 ms |
| Pico GPU con Whisper residente | 5.391,0 MiB | 3.912,7 MiB |
| MT residente según Ollama | 2.740,9 MiB | 1.253,7 MiB |
| Máximo individual en 38 peticiones es/en | 391,9 ms | **9.685,5 ms** |

La petición lenta de Hy, `と言って`, consumió 9.611,7 ms procesando el prompt y 40,7 ms generando; la repetición tardó 55,3 ms. Su causa no quedó establecida; debe conservarse junto al p95 favorable. Whisper estuvo cargado **sin ejecutar reconocimiento**: se acredita memoria compartida, no inferencia simultánea. ([MT individual](</D:/youJP-ESP/bench/trials/20261003/mt/mt-results.json>), [MT con Whisper residente](</D:/youJP-ESP/bench/trials/20261003/mt/with-whisper-resident/mt-results.json>))

La revisión encontró **12.500 yenes convertidos en 22.500 y 24.500** por Hy; Qwen omitió la cifra. Hy cambió Nishi-Umeda por Nishi-Medaka e invirtió una comparación. Qwen interpretó un alta hospitalaria como «Se graduó ayer»; Hy conservó el contexto hospitalario. Ambos fallaron en doble negación y expresiones idiomáticas. No hubo errores HTTP, salidas vacías ni truncamiento en las 114 peticiones calientes; las tres frases inglesas resultaron coherentes. La revisión del asistente usa un conjunto pequeño, parcialmente enseñado al prompt actual; no es una evaluación bilingüe ciega ni aprobación semántica.

ASR comparó los mismos WAV: 30 segundos de noticias, 30 de anime y 20 de silencio digital, enviados a ritmo real. Nemotron usó NeMo-Speech.cpp 0.2.0 y pesos Q8_0, idioma `ja-JP`, contexto derecho de 320 ms y endpointing de 500 ms. Whisper usó el pipeline existente. **El retraso siguiente es llegada del final menos fin de audio estimado por cada reconocedor**, no latencia del español visible. ([Entradas y hashes](</D:/youJP-ESP/bench/trials/20261003/asr/inputs.json>), [comparación ASR](</D:/youJP-ESP/bench/trials/20261003/asr/comparison.json>))

| Noticias, 30 segundos | Whisper turbo | Nemotron solo | Nemotron con Qwen residente |
|---|---:|---:|---:|
| Finales emitidos | 5 | 12 | 12 |
| Retraso final p50 / p95 | 1.411 / 3.729 ms | 834 / 1.045 ms | 822 / 943 ms |
| Primer parcial desde inicio del audio | 1.080 ms | 1.026 ms | 1.017 ms |

Los límites de frase y tamaños de muestra difieren: **12 finales frente a 5 confunden la comparación**, y estos percentiles son indicativos. Anime produjo un único final por motor, con 789 ms en Nemotron y 1.309 ms en Whisper. Ambos emitieron cero texto durante los 20 segundos de silencio. Se verificaron intervalos finitos, ordenados y dentro de límites; sin embargo, Nemotron entregó **una frase japonesa completa como un único elemento `word` en 13/13 finales**, frente a 0/6 en Whisper. Eso no acredita alineación fina de palabras ni precisión temporal humana, y afecta nuestro estudio de vocabulario.

Qwen permaneció completamente en GPU antes y después del reconocimiento, con contexto 2048. El pico conjunto fue **5.288,6 de 6.144 MiB**, aproximadamente 855 MiB libres; Nemotron añadió 1.087,7 MiB sobre la base con Qwen. No hubo traducción simultánea. Los picos incluyen escritorio y otros procesos, muestreados a 4 Hz en MT y 10 Hz en ASR. Se acredita residencia conjunta durante 30 segundos, no estabilidad prolongada. ([Ensayo conjunto](</D:/youJP-ESP/bench/trials/20261003/asr/nemotron-with-qwen-realtime.json>), [residencia y limpieza](</D:/youJP-ESP/bench/trials/20261003/asr/nemotron-with-qwen-residency.json>))

Faltan referencias humanas para CER, revisión bilingüe amplia, alineación fina y una sesión larga integrada con ASR y traducción simultáneos. Evaluar Nemotron como proveedor aislado exige resolver ese contrato antes de adoptarlo. Los servicios quedaron detenidos y los modelos descargados de VRAM; pesos y alias siguen disponibles. Soniox no se ejecutó: esta fase se limitó a modelos locales.

Para repetir las fases individuales en serie, desde `D:\youJP-ESP`, usando salidas nuevas y los audios exactos conservados:

```powershell
.\backend\.venv\Scripts\python.exe scripts\trials\mt_trial.py --run --out bench\trials\mt-repeat
.\backend\.venv\Scripts\python.exe scripts\trials\mt_trial.py --run --with-whisper-resident --repetitions 1 --out bench\trials\mt-repeat-with-whisper

$trialRuntime = 'D:\youJP-ESP\.youjp\trials\asr\runtime\nemo-speech-0.2.0-windows-x86_64-cuda\bin\nemo-speech.exe'
$trialModel = 'D:\youJP-ESP\models\trials\nemotron-3.5-asr\nemotron-3.5-asr-streaming-0.6b.q8_0.gguf'
.\backend\.venv\Scripts\python.exe scripts\trials\asr_trial.py --provider nemotron --runtime $trialRuntime --model $trialModel --samples bench\trials\20261003\asr\control-inputs --sample 10-noticias-apertura.wav --sample 20-anime-frieren.wav --sample 00-silencio.wav --output bench\trials\asr-repeat\nemotron.json
.\backend\.venv\Scripts\python.exe scripts\trials\asr_trial.py --provider whisper --samples bench\trials\20261003\asr\control-inputs --sample 10-noticias-apertura.wav --sample 20-anime-frieren.wav --sample 00-silencio.wav --output bench\trials\asr-repeat\whisper.json
```

Scripts: [MT](</D:/youJP-ESP/scripts/trials/mt_trial.py>), [ASR](</D:/youJP-ESP/scripts/trials/asr_trial.py>); preparación y condiciones del reconocimiento en [README ASR](</D:/youJP-ESP/bench/trials/20261003/asr/README.md>). Estos comandos repiten los componentes individuales; el ensayo con Qwen residente está documentado aparte en sus JSON.
