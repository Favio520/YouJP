# Ficha para Chrome Web Store y Edge Add-ons

Textos listos para pegar. Las capturas (1280×800) se hacen con la extensión sobre un vídeo
japonés de YouTube: subtítulos en vivo, panel de vocabulario, historial y ajustes.

## Nombre

YouJP: subtítulos japoneses

## Resumen (máx. 132 caracteres)

- ES: Subtítulos japoneses en vivo en YouTube, con traducción y vocabulario clicable. Todo se procesa en tu PC.
- EN: Live Japanese subtitles on YouTube with translation and clickable vocabulary. Everything runs on your PC.

## Descripción (ES)

YouJP muestra subtítulos en japonés en tiempo real sobre los vídeos de YouTube y los traduce al
español o al inglés, pensado para quien estudia japonés.

• Subtítulos en vivo con texto confirmado y provisional.
• Traducción japonés → español o inglés, que puedes cambiar mientras ves el vídeo.
• Palabras clicables con lectura, rōmaji, conjugación y definiciones de JMdict.
• Furigana automático en las palabras poco comunes, o en todos los kanji.
• Historial con marcas de tiempo que te devuelve a la frase correspondiente.
• Traducción de imágenes: selecciona una zona de cualquier página web.
• Para vídeos que no son en directo, traduce el vídeo entero por adelantado.

REQUIERE LA APLICACIÓN DE ESCRITORIO. YouJP reconoce el audio con Whisper en tu ordenador, así
que necesita instalar la aplicación gratuita para Windows (10 u 11; GPU NVIDIA recomendada).
Descárgala en: <URL de la página de descargas de GitHub>

PRIVACIDAD. El audio nunca sale de tu equipo: la extensión lo envía únicamente a la aplicación
que se ejecuta en 127.0.0.1. No hay cuentas, anuncios ni analítica.

## Description (EN)

YouJP shows live Japanese subtitles on YouTube videos and translates them into Spanish or
English, built for Japanese learners.

• Live subtitles with confirmed and tentative text.
• Japanese → Spanish or English translation you can switch while watching.
• Clickable words with readings, rōmaji, conjugations, and JMdict definitions.
• Automatic furigana for uncommon words, or for all kanji.
• Timestamped history that jumps back to the matching sentence.
• Image translation: select a region of any web page.
• For videos that are not live, translate the whole video in advance.

REQUIRES THE DESKTOP APP. YouJP recognizes audio with Whisper on your own computer, so it needs
the free Windows app (10 or 11; NVIDIA GPU recommended). Download it at: <GitHub releases URL>

PRIVACY. Audio never leaves your computer: the extension sends it only to the app running on
127.0.0.1. No accounts, ads, or analytics.

## Categoría

Educación (Education). Idioma de la ficha: español; añade la traducción al inglés.

## Justificación de permisos

| Permiso | Motivo |
| --- | --- |
| `tabCapture` | Capturar el audio de la pestaña de YouTube tras un clic del usuario, para transcribirlo localmente. |
| `offscreen` | Mantener el audio y la conexión local en un documento fuera de pantalla; el service worker se suspende por inactividad. |
| `scripting` | Reinyectar la interfaz de subtítulos en pestañas ya abiertas tras actualizar la extensión. |
| `activeTab` | Acceso temporal a la pestaña visible al usar el atajo de traducción de imágenes (Alt+Shift+S). |
| `storage` | Guardar las preferencias del usuario (idioma, tamaño y posición de los subtítulos). |
| `https://www.youtube.com/*` | Mostrar los subtítulos y controlar el reproductor. |
| `http://127.0.0.1/*`, `http://localhost/*` | Comunicarse con la aplicación local de YouJP. No se contacta con ningún servidor propio. |

## Uso de datos (formulario de la tienda)

- No recopila ni vende datos de usuario; no los transfiere a terceros.
- Datos que maneja localmente: audio de la pestaña (solo hacia `127.0.0.1`), preferencias.
- Política de privacidad: URL pública de `docs/privacy.md`.
