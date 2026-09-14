# ADR 0004 — El VAD es la barrera, no una optimización

- **Fecha:** 2026-09-14
- **Estado:** aceptado e implementado (fase 0)
- **Código:** `backend/youjp/pipeline/streaming.py` (`_window_has_speech`)
- **Sustituye a:** la mitigación de alucinaciones descrita en el documento de
  arquitectura v1, que proponía cuatro filtros «los cuatro juntos, no uno».

## Contexto

El diseño original trataba el VAD como un ahorro de GPU, y ponía la defensa real
contra las alucinaciones en cuatro filtros posteriores: `no_speech_prob`,
`avg_logprob`, detección de repetición y lista negra.

Al medirlo con audio de control (30 s de silencio digital absoluto, generado con
`anullsrc`, sin una sola muestra distinta de cero):

| Modelo | Emite | `no_speech_prob` | `avg_logprob` | Repetición |
|---|---|---|---|---|
| large-v3-turbo | ご視聴ありがとうございました | **0,000** | **−0,143** | 0,00 |
| kotoba-whisper-v2.0-faster | ごめん | 0,128 | −0,527 | 0,00 |

Tres de los cuatro filtros no sirven:

- **`no_speech_prob`** da exactamente `0,000` sobre silencio puro con turbo.
  Ningún umbral distingue eso del habla.
- **`avg_logprob`** da `−0,143`, mejor confianza que la que produce sobre habla
  real. Usarlo como filtro descartaría antes el habla buena que la alucinación.
- **La repetición** no aparece: estas alucinaciones son cortas y no repiten. Solo
  sirve contra los bucles largos del decodificador, que son otro fenómeno.
- **La lista negra** paró a turbo, pero es incompleta por construcción: ごめん es
  una palabra perfectamente normal que nadie pondría en una lista negra.

## Decisión

El VAD de Silero es la barrera. **Ninguna pasada de Whisper puede ejecutarse
sobre una ventana sin voz detectada**, incluidas las pasadas forzadas por cierre
de frase o por fin de sesión, que antes se lo saltaban con `force=True`.

`force` pasa a significar solo «adelanta la cadencia», nunca «transcribe
igualmente».

Se implementa con `_last_speech_at`, el instante absoluto de la última voz
detectada, comparado contra el inicio de la ventana actual. Los cuatro filtros se
conservan como segunda línea, por si el VAD deja pasar ruido parecido a voz.

## Consecuencias

- El banco pasa de una pasada con alucinación aceptada por muestra a **cero
  pasadas** sobre silencio y ruido rosa. El modelo no ve ese audio.
- La calidad del VAD pasa a ser crítica: un falso negativo ya no es «se pierde
  una frase», es «se pierde una frase». Un falso positivo sí puede colar una
  alucinación. Los umbrales (`vad_threshold`, `vad_release_threshold`) hay que
  ajustarlos con audio real, no con los valores por defecto.
- Hay un test de regresión: `test_ni_una_pasada_forzada_transcribe_silencio`.
- Queda pendiente para la fase 1 el caso que este audio de control no cubre:
  **música con voz cantada**, donde el VAD sí detectará voz y Whisper transcribirá
  letras de canciones como si fueran diálogo.
