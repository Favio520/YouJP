# Política de privacidad de YouJP

Última actualización: 4 de octubre de 2026.

YouJP (la aplicación de escritorio y su extensión de Chrome/Edge) procesa todo en tu propio
ordenador. No tiene servidores propios, cuentas de usuario, anuncios ni analítica.

## Qué datos maneja y dónde

- **Audio de la pestaña.** Cuando haces clic en el icono de la extensión, esta captura el audio
  de la pestaña actual y lo envía únicamente a la aplicación de YouJP que se ejecuta en tu
  equipo (`127.0.0.1`). Whisper lo transcribe allí. El audio no se envía a Internet ni se guarda.
  Al traducir un vídeo por adelantado, su audio se descarga a una carpeta temporal que se borra al terminar.
- **Texto reconocido y traducciones.** Se muestran en pantalla y se guardan en tu equipo, en
  `.youjp/history` (historial) y `.youjp/library` (vídeos traducidos por adelantado). Puedes
  borrar esas carpetas cuando quieras.
- **Traducción de imágenes.** La región que seleccionas se envía a la aplicación local, que
  reconoce el texto con OCR en tu equipo.
- **Preferencias.** Idioma, tamaño y posición de los subtítulos se guardan con
  `chrome.storage` en tu navegador.

## Conexiones a Internet

La aplicación solo se conecta para:

- Descargar, durante la preparación, Python y sus bibliotecas, los modelos de reconocimiento y
  traducción, y los diccionarios (Hugging Face, PyPI, GitHub y sitios de los diccionarios).
- Descargar el modelo de traducción de Ollama, si lo usas.
- Traducir un vídeo por adelantado: se pide a YouTube el vídeo con `yt-dlp`, igual que lo haría
  tu navegador. Solo se comunica a YouTube el identificador del vídeo.

La reproducción de YouTube sigue usando su conexión habitual y sus propias políticas.

## Lo que no hacemos

No vendemos, compartimos ni transferimos datos de usuario a terceros, ni los usamos para
publicidad, perfiles o fines ajenos al funcionamiento de la función que ves.

## Contacto

Abre una incidencia en el repositorio del proyecto en GitHub.
