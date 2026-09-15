# ADR 0003 — Traductor dedicado en el camino caliente, LLM bajo demanda

- **Fecha:** 2026-09-14
- **Estado:** ⚠️ **parcialmente revocado el 2026-09-14 tras medir.** Ver la
  sección *Qué dijeron las medidas* al final. La separación en dos niveles se
  mantiene; la elección de NLLB para el camino caliente no.

## Contexto

La idea inicial era que un LLM local pequeño (clase Qwen3-4B) hiciera la
traducción japonés → español de cada frase, aprovechando que ya hace falta para
las explicaciones contextuales.

Dos restricciones lo impiden:

- **Ritmo.** Qwen3-4B en Q4_K_M sobre un Ryzen 7 da del orden de 8–14 tokens/s.
  Una frase traducida son 25–50 tokens: entre 2 y 6 s. Un directo produce una
  frase cada 2,5–4 s. La cola crece sin límite.
- **VRAM.** Subirlo a la GPU para acelerarlo no cabe: Whisper turbo (~1,6 GB)
  más Qwen3-4B Q4 (~3,1 GB) más el escritorio (~1,2 GB medidos) se salen de los
  6144 MiB. En Windows eso no da OOM, da una inferencia 5–10× más lenta sin
  ningún error visible.

## Decisión

Dos niveles, detrás de una interfaz `TranslationProvider`:

1. **Camino caliente:** NMT dedicado (NLLB-200-distilled-600M en CTranslate2
   `int8`, ~700 MiB en GPU), solo sobre frases finales, nunca sobre parciales.
2. **Bajo demanda:** el LLM re-traduce con contexto, desambigua acepciones y
   explica, únicamente cuando el estudiante pulsa. Respuesta en streaming y
   cacheada en SQLite por `(jmdict_id, hash de la frase)`.

Además, los dos modelos grandes **nunca coinciden en la GPU**: en modo directo la
GPU lleva ASR y NMT y el LLM está en CPU (`options.num_gpu = 0` en Ollama); en
modo estudio, con el vídeo pausado, el ASR se descarga y el LLM sube a la GPU.

## Motivos

- Mantiene la traducción dentro del presupuesto de latencia (~250 ms por frase
  frente a 2–6 s).
- Elimina la competencia por la VRAM por diseño, no por ajuste fino.
- Encaja con el principio del proyecto: no usar el LLM para lo que otra
  herramienta resuelve mejor y de forma determinista.

## Riesgos asumidos

- **La calidad de NLLB-600M en ja→es es mediana**, sobre todo en habla coloquial.
  Qwen3-4B traduce claramente mejor. Por eso la fase 3 compara los dos sobre los
  mismos clips y la decisión final se toma con datos, no aquí.
- **NLLB-200 es CC-BY-NC 4.0**, no comercial. Irrelevante para uso personal, pero
  si esto llegara a distribuirse habría que sustituirlo. La interfaz existe
  precisamente para que ese cambio sea de una línea.

## Alternativas descartadas

- **Pivote ja → en → es:** duplica la latencia y acumula errores.
- **API externa de traducción:** contradice el requisito de funcionamiento local.

---

## Qué dijeron las medidas — 2026-09-14

Las tres implementaciones, sobre las mismas seis frases sacadas de las
transcripciones reales de la fase 0.

| | NLLB-200-600M | Qwen3-1.7B | **Qwen3-4B-Instruct-2507** |
|---|---|---|---|
| Latencia p50 (GPU) | ~290 ms | ~130 ms | **~300 ms** |
| VRAM | 1 117 MiB | 1 398 MiB | 2 741 MiB |
| Frases correctas | 2 / 6 | 2 / 6 | **5 / 6** |

**La premisa de este ADR era falsa.** Suponía que un traductor dedicado sería
mucho más rápido que un LLM, y que por eso habría que aceptar su peor calidad en
el camino caliente. En GPU los dos tardan lo mismo, así que no había nada que
aceptar.

Los errores de NLLB además no son del tipo tolerable. Sobre
`魔力も技術もコントロールも私の方が遥かに上` («en magia, técnica y control yo
estoy muy por encima») escribió *«son mucho mejores que yo»* — **el significado
exactamente invertido**, con total fluidez. Para alguien que está aprendiendo
japonés eso es peor que no traducir, porque no tiene forma de detectarlo. También
convirtió `西山真さん` en *«Si-san-jin»* y cambió la persona de `自分の`
(«mis») a *«tenemos»*.

Qwen3-1.7B es peor todavía: se inventó un «¡Hola!» que no estaba en el original y
tradujo `西山真さん` como *«mujer de nombre Weston»*.

## Decisión revisada

- **Camino caliente: Qwen3-4B-Instruct-2507 en GPU.** Medido en el pipeline
  completo: 13 de 13 frases traducidas, p50 431 ms, y el subtítulo japonés sigue
  llegando a 1 514 ms — la traducción va en paralelo y no lo retrasa.
- **NLLB se conserva** detrás de la misma interfaz, como opción para cuando la
  VRAM no dé (`YOUJP_MT_PROVIDER=nllb`, 1 500 MiB menos) o si algún día hay que
  quitar la dependencia de Ollama.
- La separación en dos niveles **sigue en pie**: el LLM del camino caliente
  traduce y nada más. Las explicaciones de la fase 5 son otra petición, con otro
  prompt y probablemente otro modelo.

## El coste: ya no sobra VRAM

Con el navegador abierto quedan entre 400 y 900 MiB libres de los 6 144. Es
suficiente pero no hay margen para un juego. Consecuencias implementadas:

- El servidor mide la VRAM libre al arrancar y avisa por debajo de 500 MiB,
  indicando las dos salidas (`YOUJP_LLM_NUM_GPU=0` o `YOUJP_MT_PROVIDER=nllb`).
- El servidor avisa también si Ollama tiene **otros** modelos residentes. No es
  hipotético: durante estas pruebas un `qwen3:1.7b` olvidado de un experimento
  anterior ocupaba 1 398 MiB y hacía parecer que el traductor no cabía.
- `num_ctx` se acota a 2 048. Qwen3 declara 262 144 tokens de contexto y sin
  acotarlo Ollama reserva caché KV en consecuencia.
