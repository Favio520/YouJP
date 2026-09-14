# ADR 0003 — Traductor dedicado en el camino caliente, LLM bajo demanda

- **Fecha:** 2026-09-14
- **Estado:** aceptado, pendiente de validar con medidas (fase 3)

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
- **Qwen3-1.7B en GPU como traductor:** cabe (~1,5 GB) pero su japonés no da la
  talla, y si hay que revisar cada frase el sistema pierde su propósito.
- **API externa de traducción:** contradice el requisito de funcionamiento local.
