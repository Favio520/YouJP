/** Audio stays alive while a versioned WebSocket session reconnects. */
import { DEFAULT_SERVER_URL, type ExtensionMessage, type StartCapture } from '@/src/messages';
import type { OverlaySettings } from '@/src/settings';
import { ReconnectingSession } from '@/src/connection';
import {
  APP_VERSION, PROTOCOL_VERSION, buildFrame, FLAG_DISCONTINUITY, FLAG_LIVE,
  FRAME_MS, FRAME_SAMPLES, SAMPLE_RATE, type ServerMessage, type TargetLanguage,
} from '@/src/protocol';

interface Capture {
  tabId: number;
  params: StartCapture;
  stream: MediaStream;
  asrCtx: AudioContext;
  playbackCtx: AudioContext;
  node: AudioWorkletNode;
  connection: ReconnectingSession;
  startedAt: number;
  seq: number;
  mediaTimeMs: number;
  paused: boolean;
  rate: number;
  pendingDiscontinuity: boolean;
  target: TargetLanguage;
  nextSegment: number;
  segments: Map<number, number>;
}

let current: Capture | null = null;
let captureCommands: Promise<void> = Promise.resolve();

// Los documentos offscreen solo pueden usar chrome.runtime, no chrome.storage.
// El service worker lee y normaliza los ajustes guardados por el overlay.
function loadCaptureSettings(): Promise<OverlaySettings> {
  return chrome.runtime.sendMessage({ type: 'settings.get' } satisfies ExtensionMessage);
}

function report(message: ExtensionMessage, tabId = current?.tabId): void {
  chrome.runtime.sendMessage({ ...message, tabId }).catch(() => {});
}

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
  let asrCtx: AudioContext | undefined;
  try {
    playbackCtx.createMediaStreamSource(stream).connect(playbackCtx.destination);

    // --- análisis: 16 kHz, que es lo que quiere el modelo -------------------
    asrCtx = new AudioContext({ sampleRate: SAMPLE_RATE });
    await asrCtx.audioWorklet.addModule(chrome.runtime.getURL('pcm-worklet.js'));

    const node = new AudioWorkletNode(asrCtx, 'pcm-collector', {
      processorOptions: { frameSamples: FRAME_SAMPLES },
      numberOfOutputs: 1,
    });
    asrCtx.createMediaStreamSource(stream).connect(node);

    // El worklet no escribe en su salida, así que esto no suena. Se conecta
    // igualmente porque Chrome solo procesa los nodos que llegan al destino.
    node.connect(asrCtx.destination);

    node.port.onmessage = (event: MessageEvent<ArrayBuffer>) => onFrame(event.data);
    return { asrCtx, playbackCtx, node };
  } catch (error) {
    await Promise.all([
      playbackCtx.close().catch(() => {}),
      asrCtx?.close().catch(() => {}),
    ]);
    throw error;
  }
}


function forward(capture: Capture, message: ServerMessage): void {
  if (current !== capture) return;
  if (message.type === 'asr.final') {
    if (!capture.segments.has(message.segment_id)) {
      capture.segments.set(message.segment_id, ++capture.nextSegment);
      // La interfaz conserva pocas líneas; limitar también este índice.
      if (capture.segments.size > 512) capture.segments.delete(capture.segments.keys().next().value!);
    }
  }
  if (message.type === 'asr.final' || message.type === 'mt.final' || message.type === 'nlp.tokens') {
    const id = capture.segments.get(message.segment_id);
    if (id === undefined) return;
    message = { ...message, segment_id: id };
  }
  switch (message.type) {
    case 'asr.partial': report({ type: 'subtitle.partial', payload: message }); break;
    case 'asr.final': report({ type: 'subtitle.final', payload: message }); break;
    case 'mt.final': report({ type: 'subtitle.translation', payload: message }); break;
    case 'nlp.tokens': report({ type: 'subtitle.tokens', payload: message }); break;
    case 'metrics.tick': report({ type: 'metrics', payload: message }); break;
    case 'error': report({ type: 'backend.error', payload: message }); break;
  }
}

async function start(params: StartCapture): Promise<void> {
  await stop();
  report({ type: 'status', status: 'connecting' }, params.tabId);
  const settings = await loadCaptureSettings();
  const stream = await openStream(params.streamId);
  let capture: Capture | undefined;
  let graph: Awaited<ReturnType<typeof buildGraph>>;
  try {
    graph = await buildGraph(stream, (pcm) => {
      if (!capture || current !== capture || capture.paused || Math.abs(capture.rate - 1) > 0.01) return;
      const flags = (capture.params.isLive ? FLAG_LIVE : 0) |
        (capture.pendingDiscontinuity ? FLAG_DISCONTINUITY : 0);
      const sent = capture.connection.send(buildFrame(pcm, {
        seq: capture.seq, mediaTimeMs: capture.mediaTimeMs,
        captureMs: performance.now() - capture.startedAt, flags,
      }));
      capture.pendingDiscontinuity = !sent;
      if (sent) capture.seq += 1;
      // Advance even offline: old audio is deliberately discarded.
      capture.mediaTimeMs += FRAME_MS;
    });
  } catch (error) {
    stream.getTracks().forEach((track) => { track.stop(); });
    throw error;
  }

  const connection = new ReconnectingSession({
    url: params.serverUrl || DEFAULT_SERVER_URL,
    handshake: () => ({
      type: 'session.start', app_version: APP_VERSION, protocol_version: PROTOCOL_VERSION,
      video_id: capture!.params.videoId, url: capture!.params.url,
      is_live: capture!.params.isLive, media_time_ms: Math.round(capture!.mediaTimeMs),
      source: 'ja', target: capture!.target, profile: 'n4',
    }),
    onReady: (message) => {
      if (!capture || current !== capture) return;
      capture.seq = 0;
      capture.startedAt = performance.now();
      capture.pendingDiscontinuity = true;
      capture.segments.clear();
      // Apply settings changed while the handshake was in flight.
      connection.send({ type: 'session.configure', target: capture.target });
      report({ type: 'status', status: 'running',
        model: message.asr_model + ' · ' + message.device + '/' + message.compute_type });
    },
    onMessage: (message) => { if (capture) forward(capture, message); },
    onRetry: (attempt, delayMs) => {
      if (capture && current === capture) {
        capture.pendingDiscontinuity = true;
        report({ type: 'status', status: 'reconnecting',
          detail: 'Intento ' + attempt + ' en ' + delayMs / 1000 + ' s. Puedes detener la captura con el icono.' });
      }
    },
    onFatal: (detail) => {
      if (capture && current === capture) {
        current = null;
        void release(capture).then(() => report({ type: 'status', status: 'error', detail }, params.tabId));
      }
    },
  });
  capture = {
    ...graph, tabId: params.tabId, params, stream, connection,
    startedAt: performance.now(), seq: 0, mediaTimeMs: params.mediaTimeMs,
    paused: false, rate: 1, pendingDiscontinuity: true,
    target: settings.targetLanguage, nextSegment: 0, segments: new Map(),
  };
  current = capture;
  const latest = await loadCaptureSettings();
  capture.target = latest.targetLanguage;
  connection.start();
}

function updateTarget(target: TargetLanguage): void {
  if (!current || current.target === target) return;
  current.target = target;
  current.connection.send({ type: 'session.configure', target });
}

async function release(capture: Capture): Promise<void> {
  capture.connection.stop();
  capture.node.port.onmessage = null;
  capture.node.disconnect();
  capture.stream.getTracks().forEach((track) => { track.stop(); });
  await Promise.all([
    capture.asrCtx.close().catch(() => {}),
    capture.playbackCtx.close().catch(() => {}),
  ]);
}

async function stop(): Promise<void> {
  const capture = current;
  current = null;
  if (!capture) return;
  await release(capture);
  report({ type: 'status', status: 'idle' }, capture.tabId);
}

chrome.runtime.onMessage.addListener((message: ExtensionMessage, sender, respond) => {
  if (message.type === 'offscreen.ping') {
    respond({ ready: true });
    return true;
  }
  if ((message.type === 'player.tick' || message.type === 'player.flush') &&
      sender.tab?.id !== current?.tabId) return;
  switch (message.type) {
    case 'settings.changed':
      updateTarget(message.settings.targetLanguage);
      break;
    case 'capture.start':
      captureCommands = captureCommands.then(() => start(message)).catch(async (error) => {
        await stop();
        report({ type: 'status', status: 'error', detail: String(error.message ?? error) }, message.tabId);
      });
      break;
    case 'capture.stop':
      captureCommands = captureCommands.then(stop).catch(console.error);
      break;
    case 'player.tick':
      if (current) {
        current.mediaTimeMs = message.mediaTimeMs;
        current.paused = message.paused;
        current.rate = message.rate;
        current.params.videoId = message.videoId;
      }
      break;
    case 'player.flush':
      if (current) {
        current.mediaTimeMs = message.mediaTimeMs;
        current.pendingDiscontinuity = true;
        current.connection.send({ type: 'control.flush', reason: message.reason,
          media_time_ms: Math.round(message.mediaTimeMs) });
      }
      break;
  }
});
