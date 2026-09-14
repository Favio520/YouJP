# ADR 0001 — El WebSocket vive en el offscreen document

- **Fecha:** 2026-09-14
- **Estado:** aceptado
- **Fase:** 1 (pendiente de implementar)

## Contexto

En Manifest V3 no hay página de fondo persistente. Las tres piezas de la
extensión que podrían abrir el socket hacia el backend son el service worker, el
content script y el offscreen document.

`chrome.tabCapture.capture()` no existe en un service worker. La ruta válida es
`chrome.tabCapture.getMediaStreamId()` desde el service worker, tras un gesto del
usuario, y consumir ese ID con `getUserMedia()` en otro contexto. Desde Chrome
116 el ID puede usarse en cualquier frame del mismo origen y proceso, lo que
habilita el offscreen document. El ID caduca en pocos segundos si no se usa.

## Decisión

El audio, el `AudioWorklet` y el WebSocket viven en el **offscreen document**.
El service worker solo obtiene el `streamId`, crea el documento y coordina. El
content script no abre sockets: recibe los subtítulos por `chrome.runtime`.

## Motivos

1. **Ciclo de vida.** El service worker se termina por inactividad. El offscreen
   document vive mientras la captura esté activa, que es exactamente lo que dura
   la sesión.
2. **Contenido mixto.** Su origen es `chrome-extension://`, no `https://`. Abrir
   `ws://127.0.0.1` desde ahí no plantea ninguna duda; desde la página de YouTube
   sí la plantearía.
3. **Un solo salto para el audio.** El PCM se genera y se envía en el mismo
   contexto. No hay serialización entre procesos por cada trama de 100 ms.

## Consecuencias

- Solo puede haber un offscreen document por extensión: si en el futuro hay
  varias pestañas capturando, habrá que multiplexar dentro de él.
- El content script depende de mensajes del offscreen; si este muere, el overlay
  tiene que detectarlo y mostrar estado de desconexión en vez de quedarse con el
  último subtítulo congelado.
- **Hay que reconectar el audio a `ctx.destination`**, o la pestaña se queda
  muda. La documentación de `tabCapture` lo dice explícitamente y es el fallo más
  fácil de cometer.
