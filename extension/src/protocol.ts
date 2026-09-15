/**
 * Protocolo del WebSocket. Espejo de `backend/youjp/ws/protocol.py` y
 * `codec.py`.
 *
 * Mientras no haya generación automática de tipos, cualquier cambio aquí hay
 * que hacerlo también allí. El test `test_ws_codec.py` del backend cubre el
 * lado binario, que es donde un desajuste no da un error claro sino audio que
 * suena a ruido blanco.
 */

export const PROTOCOL_VERSION = 1;
export const SAMPLE_RATE = 16_000;
export const FRAME_MS = 100;
export const FRAME_SAMPLES = (SAMPLE_RATE * FRAME_MS) / 1000; // 1600
export const HEADER_SIZE = 16;

const MAGIC = 0xa5;
export const FLAG_LIVE = 1 << 0;
export const FLAG_DISCONTINUITY = 1 << 1;

// ---------------------------------------------------------------------------
// trama binaria
// ---------------------------------------------------------------------------

export interface FrameHeader {
  seq: number;
  mediaTimeMs: number;
  captureMs: number;
  flags: number;
}

/**
 * Antepone la cabecera de 16 B al PCM ya convertido a Int16 por el worklet.
 *
 * `setUint32(..., true)` en todos los campos: little endian. Sin ese `true`,
 * JavaScript escribe big endian por defecto y Python lee números absurdos —
 * el error más fácil de cometer en esta frontera.
 */
export function buildFrame(pcm: ArrayBuffer, header: FrameHeader): ArrayBuffer {
  const out = new ArrayBuffer(HEADER_SIZE + pcm.byteLength);
  const view = new DataView(out);

  view.setUint8(0, MAGIC);
  view.setUint8(1, PROTOCOL_VERSION);
  view.setUint8(2, header.flags);
  view.setUint8(3, 0); // reservado
  view.setUint32(4, header.seq >>> 0, true);
  view.setUint32(8, Math.max(0, Math.round(header.mediaTimeMs)) >>> 0, true);
  view.setUint32(12, Math.max(0, Math.round(header.captureMs)) >>> 0, true);

  new Uint8Array(out, HEADER_SIZE).set(new Uint8Array(pcm));
  return out;
}

// ---------------------------------------------------------------------------
// mensajes de texto
// ---------------------------------------------------------------------------

export interface SessionStart {
  type: 'session.start';
  video_id: string;
  url: string;
  is_live: boolean;
  media_time_ms: number;
  source: string;
  target: string;
  profile: string;
}

export interface SessionStop {
  type: 'session.stop';
}

export interface ControlFlush {
  type: 'control.flush';
  reason: 'seek' | 'pause' | 'rate' | 'manual';
  media_time_ms: number;
}

export type ClientMessage = SessionStart | SessionStop | ControlFlush | { type: 'ping'; t: number };

export interface SessionReady {
  type: 'session.ready';
  session_id: string;
  asr_model: string;
  device: string;
  compute_type: string;
  sample_rate: number;
  frame_ms: number;
  protocol_version: number;
}

/**
 * `committed` ya no cambiará nunca: es lo que LocalAgreement ha confirmado y se
 * puede pintar en firme. `tentative` se reemplaza entera en cada actualización,
 * así que va en gris y sin interacciones encima.
 */
export interface AsrPartial {
  type: 'asr.partial';
  committed: string;
  tentative: string;
  media_start_ms: number;
}

export interface AsrFinal {
  type: 'asr.final';
  segment_id: number;
  text: string;
  media_start_ms: number;
  media_end_ms: number;
  reason: string;
  latency_ms: number;
}

/**
 * Traducción de una frase ya cerrada.
 *
 * Llega por separado y después del `asr.final` correspondiente, enlazada por
 * `segment_id`. Así el japonés aparece en cuanto está listo sin esperar al
 * traductor: son dos trabajos en paralelo, no una cadena.
 */
export interface MtFinal {
  type: 'mt.final';
  segment_id: number;
  text_es: string;
  provider: string;
  media_start_ms: number;
  media_end_ms: number;
  latency_ms: number;
}

export interface Sense {
  /** Etiquetas de JMdict: `n`, `vs`, `adj-i`... */
  pos: string[];
  glosses_es: string[];
  glosses_en: string[];
}

export interface DictEntry {
  id: number;
  headword: string;
  readings: string[];
  common: boolean;
  freq_rank: number | null;
  senses: Sense[];
}

/**
 * Una unidad clicable del subtítulo.
 *
 * La entrada de diccionario viene incrustada en vez de un identificador para
 * pedirla después: una frase son unos pocos kilobytes por localhost, y a cambio
 * la tarjeta aparece en el mismo fotograma del clic.
 */
export interface Token {
  i: number;
  /** Índices sobre el texto de `asr.final`. */
  span: [number, number];
  surface: string;
  lemma: string;
  kana: string;
  romaji: string;
  pos: string[];
  pos_label: string;
  /** Cadena de conjugación: `["causativo", "formal", "pasado"]`. */
  chain: string[];
  clickable: boolean;
  entry: DictEntry | null;
}

export interface NlpTokens {
  type: 'nlp.tokens';
  segment_id: number;
  tokens: Token[];
  analysis_ms: number;
}

export interface MetricsTick {
  type: 'metrics.tick';
  end_to_end_ms_p50: number;
  end_to_end_ms_p95: number;
  whisper_processing_ms_p50: number;
  audio_buffer_ms: number;
  dropped_audio_chunks: number;
  partial_transcripts: number;
  final_transcripts: number;
  passes: number;
  skipped_silent: number;
  rejected: Record<string, number>;
  nlp_ms_p50: number;
  translation_latency_ms_p50: number;
  translations: number;
  dropped_translations: number;
  mt_provider: string;
  gpu_used_mb: number;
  gpu_total_mb: number;
  cpu_pct: number;
  ram_mb: number;
}

export interface ServerError {
  type: 'error';
  code: string;
  message: string;
  fatal: boolean;
}

export type ServerMessage =
  | SessionReady
  | AsrPartial
  | AsrFinal
  | MtFinal
  | NlpTokens
  | MetricsTick
  | ServerError
  | { type: 'pong'; t: number };
