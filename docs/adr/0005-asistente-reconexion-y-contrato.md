# 0005 — Asistente Windows, reconexión y contrato compartido

## Decisión

La aplicación se versiona desde `VERSION`. `protocol/schema.json` es el contrato
de mensajes, con metadatos de audio. `scripts/generate_contract.py` genera modelos
de Pydantic, interfaces de TypeScript y versiones de paquetes, sin dependencias
externas. `--check` y `test_contract.py` detectan cualquier divergencia. La versión
de audio y la de sesión se mantienen separadas: añadir negociación no cambia los
bytes PCM. Las versiones de release no son un requisito de compatibilidad entre
clientes; la versión del protocolo sí lo es.

La sesión v2 exige `protocol_version` en `session.start`. El servidor rechaza
clientes antiguos con `protocol_mismatch`, `fatal=true` y cierre WebSocket 1002
antes de crear workers. La extensión comprueba `session.ready`, versión y parámetros
de audio antes de enviar PCM. `app_version` permite diagnosticar instalaciones.

## Reconexión

`ReconnectingSession` posee un único socket y sus temporizadores. Solo acepta
eventos del socket vigente. Reintenta indefinidamente, hasta que el usuario pare,
con espera exponencial de 1 a 30 s; un handshake tiene plazo de 10 s. Un heartbeat
de 5 s detecta conexiones sin respuestas durante 15 s. Los errores fatales y la
incompatibilidad no se reintentan.

El documento offscreen conserva el MediaStream y la reproducción mientras está
desconectado. No almacena audio offline. El reloj, las pausas y el idioma siguen
actualizándose. Cada conexión confirmada reinicia la secuencia y marca discontinuidad.
Un mapeo acotado transforma identificadores de segmento de cada nueva sesión en
identificadores únicos durante la captura; así se conserva el historial sin que
una traducción nueva modifique una frase antigua. Los eventos de sockets anteriores
se ignoran. El service worker restaura la pestaña capturada desde `storage.session`.

## Asistente Windows

`YouJP.cmd` abre un panel WinForms con icono de bandeja, sin dependencias gráficas
adicionales. `Setup.ps1` prepara uv/Python 3.12, recursos y extensión. Puede usar
Node instalado o descargar Node 24 LTS portable, verificando su SHA-256. Las fuentes
de distribución son las oficiales: [uv](https://docs.astral.sh/uv/getting-started/installation/)
y [Node.js](https://nodejs.org/dist/). El asistente no instala Ollama; Auto elige
NLLB cuando Ollama no está disponible. El perfil CPU permite arrancar sin NVIDIA.

La configuración gestionada se carga antes de `.env`; entorno > `.env` > perfil
del asistente > valores del código. La instalación tiene bloqueo exclusivo,
comprueba el puerto y solo marca la versión instalada tras completar todos los pasos.
Una instalación incompleta puede repetirse; una base de diccionario existente no se
reconstruye. Las dependencias se sincronizan con el lockfile.

El panel crea directamente el proceso Python, comprueba `/health` asíncronamente
y conserva su objeto Process. La parada usa un archivo de señal único, observado
por `youjp.launcher`; Uvicorn cierra la sesión y descarga modelos. Tras 20 s sin
respuesta el panel termina exclusivamente su proceso. No expone un endpoint HTTP
de apagado ni termina servidores iniciados por otras aplicaciones.

## Verificación y límites

Pruebas con sockets y relojes simulados cubren backoff, heartbeat, handshake,
cancelación, cambio de idioma offline, reloj de vídeo y colisiones de identificadores.
Las pruebas de FastAPI verifican el rechazo antes de asignar workers. El asistente
tiene pruebas de perfiles, prioridad de configuración, handshake de salud, sintaxis
PowerShell y construcción de controles sin abrir una ventana.

El panel se entrega con el código fuente, no como un instalador MSI firmado. La
carga inicial de la extensión requiere el gesto del usuario en Chrome/Edge. Las
pruebas offline no sustituyen una instalación completa en un Windows x64 limpio,
con las descargas de varios GB y sus controladores reales.
