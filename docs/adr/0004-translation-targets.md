# 0004 — Idioma de traducción por sesión y separación de presentación

Estado: implementado.

## Problema

El protocolo aceptaba `target`, pero el servidor lo ignoraba. Ollama siempre
recibía instrucciones en español, NLLB usaba una configuración global y tanto
el historial como el mensaje de traducción asumían `text_es`.

## Decisión

- Admitir `es` y `en`, manteniendo `ja` como origen. Validar estos códigos al
  recibir mensajes, antes de llamar a los modelos.
- Pasar el destino a cada llamada al proveedor. El modelo se comparte entre
  sesiones, pero no se modifica su configuración global al cambiar de idioma.
- Usar prompts separados para Ollama y los prefijos `spa_Latn` / `eng_Latn` para
  NLLB. Cambiar el destino no requiere descargar otro modelo.
- Separar `targetLanguage` (es/en) de `languages` (ambos/japonés/traducción).
  Migrar `esSize` y el antiguo modo `es` al cargar ajustes guardados.
- Aplicar `session.configure` sin reiniciar ASR ni capturar otra vez la pestaña.
  El trabajador invalida los trabajos pendientes y las respuestas en curso de
  la generación anterior. El contexto japonés válido sigue disponible; un salto
  en el vídeo limpia el contexto.
- Conservar el idioma original en el historial. El cambio solo afecta a frases
  futuras; no retraduce automáticamente toda la sesión.

## Protocolo

Inicio: `{"type":"session.start","source":"ja","target":"en"}`.

Cambio en vivo: `{"type":"session.configure","target":"es"}`.

`mt.final` añade `text` y `target`, además de los identificadores, tiempos y
proveedor existentes. Mantiene `text_es` para clientes anteriores únicamente
cuando la traducción es española; para inglés es una cadena vacía. El formato
binario de audio permanece en versión 1. El nuevo cliente puede leer respuestas
españolas antiguas, pero necesita el backend actualizado para seleccionar inglés.

## Correcciones relacionadas de estabilidad

- El cierre de trabajadores se ejecuta fuera del bucle asíncrono y no espera
  indefinidamente para insertar una señal en una cola llena.
- Reiniciar una sesión cancela el recolector de métricas anterior e invalida
  sus emisores, para impedir que respuestas tardías reutilicen IDs nuevos.
- Un cliente lento puede perder mensajes cuando llena la cola de salida; esa
  condición se registra sin producir excepciones asíncronas no controladas.
- Un fallo de conexión o de AudioWorklet libera los recursos de audio adquiridos.
- Los eventos del reproductor solo afectan a la pestaña capturada.

## Verificación y límites

Pruebas con proveedores simulados comprueban prompts, prefijos, aislamiento de
sesiones y carreras al cambiar idioma. Pruebas de WebSocket verifican cambios en
vivo y reinicios. Las pruebas de Ollama ejercitan frases reales si el modelo está
disponible; las de extensión cubren migración, componentes y captura simulada.

Los controles y las etiquetas gramaticales siguen en español. Las traducciones
pueden contener errores y las pruebas de frases no certifican la calidad de todos
los contenidos. Una inferencia iniciada no se cancela dentro del modelo: se
descarta su resultado si dejó de pertenecer a la generación activa. Una conexión
perdida requiere reiniciar la captura desde el icono de la extensión.
