/**
 * Documento offscreen: audio y WebSocket.
 *
 * Aquí vive todo lo que tiene que sobrevivir a la sesión, porque el service
 * worker se termina por inactividad y el content script muere en cada
 * navegación.
 */

import {
  DEFAULT_SERVER_URL,
  type ExtensionMessage,
  type StartCapture,
} from '@/src/messages';
import {
  buildFrame,
  FLAG_DISCONTINUITY,
  FLAG_LIVE,
  FRAME_MS,
  FRAME_SAMPLES,
  SAMPLE_RATE,
  type ServerMessage,
} from '@/src/protocol';

interface Capture {
  stream: MediaStream;
  /** Contexto a 16 kHz que alimenta al worklet. */
  asrCtx: AudioContext;
  /** Contexto a la frecuencia nativa que devuelve el sonido al usuario. */
  playbackCtx: AudioContext;
  node: AudioWorkletNode;
  ws: WebSocket;
  startedAt: number;
  seq: number;
  mediaTimeMs: number;
  isLive: boolean;
  pendingDiscontinuity: boolean;
}

let current: Capture | null = null;
let reconnectTimer: number | undefined;

function report(message: ExtensionMessage): void {
  chrome.runtime.sendMessage(message).catch(() => {
    // El service worker puede estar dormido; volverá a arrancar solo.
  });
}

// ---------------------------------------------------------------------------
// audio
// ---------------------------------------------------------------------------

async function openStream(streamId: string): Promise<MediaStream> {
  // Las restricciones `mandatory` de tabCapture no están en los tipos estándar
  // de MediaTrackConstraints, pero son la única forma de consumir un streamId.
  return navigator.mediaDevices.getUserMedia({
    audio: {
      mandatory: {
        chromeMediaSource: 'tab',
        chromeMediaSourceId: streamId,
      },
    },
    video: false,
  } as unknown as MediaStreamConstraints);
}

/**
 * Dos contextos de audio, uno por cada trabajo, y no uno compartido.
 *
 * Whisper quiere 16 kHz, y pedir el `AudioContext` a esa frecuencia hace que
 * Chrome remuestree por nosotros — pero la reinyección del sonido tiene que
 * salir por otro sitio. Con un solo contexto a 16 kHz, lo que oye el usuario
 * queda limitado a 8 kHz de ancho de banda: suena apagado, como un teléfono.
 * Es audible y fue lo primero que se notó al probarlo en serio.
 *
 * El mismo `MediaStream` puede alimentar a los dos contextos a la vez, así que
 * cada camino trabaja a la frecuencia que le conviene:
 *
 *   stream ──> playbackCtx (nativa, 48 kHz) ──> altavoces
 *          └─> asrCtx (16 kHz) ──> worklet ──> WebSocket
 */
async function buildGraph(stream: MediaStream, onFrame: (pcm: ArrayBuffer) => void) {
  // --- reproducción: calidad intacta -------------------------------------
  // Sin esto la pestaña se queda muda. La documentación de tabCapture lo dice
  // explícitamente: mientras capturas, el audio deja de reproducirse para el
  // usuario. Es el fallo más fácil de cometer y el que más asusta.
  const playbackCtx = new AudioContext();
  playbackCtx.createMediaStreamSource(stream).connect(playbackCtx.destination);

  // --- análisis: 16 kHz, que es lo que quiere el modelo -------------------
  const asrCtx = new AudioContext({ sampleRate: SAMPLE_RATE });
  await asrCtx.audioWorklet.addModule(chrome.runtime.getURL('pcm-worklet.js'));

  const node = new AudioWorkletNode(asrCtx, 'pcm-collector', {
    processorOptions: { frameSamples: FRAME_SAMPLES },
    numberOfOutputs: 1,
  });
  asrCtx.createMediaStreamSource(stream).connect(node);

  // El worklet no escribe en su salida, así que esto no suena. Se conecta
  // igualmente porque Chrome solo procesa los nodos que llegan al destino: sin
  // esta arista, `process()` dejaría de llamarse y no llegaría ni una trama.
  node.connect(asrCtx.destination);

  node.port.onmessage = (event: MessageEvent<ArrayBuffer>) => onFrame(event.data);
  return { asrCtx, playbackCtx, node };
}

// ---------------------------------------------------------------------------
// transporte
// ---------------------------------------------------------------------------

function openSocket(url: string, params: StartCapture): Promise<WebSocket> {
  return new Promise((resolve, reject) => {
    const ws = new WebSocket(url);
    ws.binaryType = 'arraybuffer';

    ws.addEventListener('open', () => {
      ws.send(
        JSON.stringify({
          type: 'session.start',
          video_id: params.videoId,
          url: params.url,
          is_live: params.isLive,
          media_time_ms: Math.round(params.mediaTimeMs),
          source: 'ja',
          target: 'es',
          profile: 'n4',
        }),
      );
      resolve(ws);
    });

    ws.addEventListener('message', (event) => {
      if (typeof event.data !== 'string') return;
      const message = JSON.parse(event.data) as ServerMessage;
      switch (message.type) {
        case 'session.ready':
          report({
            type: 'status',
            status: 'running',
            model: `${message.asr_model} · ${message.device}/${message.compute_type}`,
          });
          break;
        case 'asr.partial':
          report({ type: 'subtitle.partial', payload: message });
          break;
        case 'asr.final':
          report({ type: 'subtitle.final', payload: message });
          break;
        case 'mt.final':
          report({ type: 'subtitle.translation', payload: message });
          break;
        case 'metrics.tick':
          report({ type: 'metrics', payload: message });
          break;
        case 'error':
          report({ type: 'backend.error', payload: message });
          break;
      }
    });

    ws.addEventListener('error', () => {
      reject(
        new Error(
          `No se pudo conectar con ${url}. ¿Está arrancado el backend? ` +
            '(cd backend && uv run uvicorn youjp.main:app --port 8770)',
        ),
      );
    });

    ws.addEventListener('close', () => {
      if (current?.ws === ws) {
        report({ type: 'status', status: 'reconnecting', detail: 'conexión perdida' });
      }
    });
  });
}

// ---------------------------------------------------------------------------
// ciclo de captura
// ---------------------------------------------------------------------------

async function start(params: StartCapture): Promise<void> {
  await stop();
  report({ type: 'status', status: 'connecting' });

  const stream = await openStream(params.streamId);
  let capture: Capture;

  const onFrame = (pcm: ArrayBuffer) => {
    if (!capture || capture.ws.readyState !== WebSocket.OPEN) return;

    // Esperar a que se vacíe el socket sería peor que descartar: el audio viejo
    // ya no sirve y la cola nunca se recupera. Con localhost no debería ocurrir.
    if (capture.ws.bufferedAmount > 1_000_000) return;

    let flags = capture.isLive ? FLAG_LIVE : 0;
    if (capture.pendingDiscontinuity) {
      flags |= FLAG_DISCONTINUITY;
      capture.pendingDiscontinuity = false;
    }

    capture.ws.send(
      buildFrame(pcm, {
        seq: capture.seq,
        // El tiempo del reproductor lo mantiene al día el content script. Se
        // avanza entre avisos con el propio ritmo de las tramas, que es exacto.
        mediaTimeMs: capture.mediaTimeMs,
        captureMs: performance.now() - capture.startedAt,
        flags,
      }),
    );
    capture.seq += 1;
    capture.mediaTimeMs += FRAME_MS;
  };

  const { asrCtx, playbackCtx, node } = await buildGraph(stream, onFrame);
  const ws = await openSocket(params.serverUrl || DEFAULT_SERVER_URL, params);

  capture = {
    stream,
    asrCtx,
    playbackCtx,
    node,
    ws,
    startedAt: performance.now(),
    seq: 0,
    mediaTimeMs: params.mediaTimeMs,
    isLive: params.isLive,
    pendingDiscontinuity: false,
  };
  current = capture;
}

async function stop(): Promise<void> {
  if (reconnectTimer) {
    clearTimeout(reconnectTimer);
    reconnectTimer = undefined;
  }
  const capture = current;
  current = null;
  if (!capture) return;

  try {
    if (capture.ws.readyState === WebSocket.OPEN) {
      capture.ws.send(JSON.stringify({ type: 'session.stop' }));
    }
    capture.ws.close();
  } catch {
    /* el socket ya estaba cerrado */
  }

  capture.node.port.onmessage = null;
  capture.node.disconnect();
  capture.stream.getTracks().forEach((track) => track.stop());
  await Promise.all([
    capture.asrCtx.close().catch(() => {}),
    capture.playbackCtx.close().catch(() => {}),
  ]);
  report({ type: 'status', status: 'idle' });
}

// ---------------------------------------------------------------------------
// mensajes
// ---------------------------------------------------------------------------

chrome.runtime.onMessage.addListener((message: ExtensionMessage) => {
  switch (message.type) {
    case 'capture.start':
      start(message).catch((error) => {
        console.error('[youjp] fallo al iniciar la captura', error);
        report({ type: 'status', status: 'error', detail: String(error.message ?? error) });
        void stop();
      });
      break;

    case 'capture.stop':
      void stop();
      break;

    case 'player.tick':
      // Reancla el reloj del vídeo. Entre avisos, las tramas avanzan solas.
      if (current) current.mediaTimeMs = message.mediaTimeMs;
      break;

    case 'player.flush':
      if (current?.ws.readyState === WebSocket.OPEN) {
        current.mediaTimeMs = message.mediaTimeMs;
        // Las dos mitades del mismo aviso: el mensaje descarta el buffer del
        // backend cuanto antes, y la bandera marca la primera trama nueva. El
        // reanclaje temporal lo hace la trama, no el mensaje.
        current.pendingDiscontinuity = true;
        current.ws.send(
          JSON.stringify({
            type: 'control.flush',
            reason: message.reason,
            media_time_ms: Math.round(message.mediaTimeMs),
          }),
        );
      }
      break;
  }
});
