/**
 * Vídeo completo traducido de antemano.
 *
 * El backend prepara todas las frases (transcript de YouTube o Whisper) y la
 * página las pinta según `currentTime`. El content script no habla con el
 * backend —YouTube no es un origen de confianza para él—: pasa por el service
 * worker, que sí tiene el origen de la extensión.
 */

import type { TargetLanguage, Token } from './protocol';
import type { Line } from './ui/types';

export type VideoAction = 'prepare' | 'poll' | 'cancel';

export interface VideoRequest {
  type: 'video.request';
  action: VideoAction;
  videoId: string;
  target: TargetLanguage;
  /** Frases ya recibidas: el backend solo devuelve las nuevas. */
  since: number;
}

export type VideoStatus =
  | 'none' | 'queued' | 'resolving' | 'downloading' | 'transcribing' | 'translating' | 'done' | 'error';

export interface VideoCue {
  i: number;
  start_ms: number;
  end_ms: number;
  ja: string;
  tr: string;
  tokens: Token[];
}

export interface VideoSnapshot {
  status: VideoStatus;
  error?: string;
  title?: string;
  channel?: string;
  source?: 'captions' | 'whisper' | '';
  progress?: number;
  total?: number;
  cues?: VideoCue[];
}

export type VideoResponse = { ok: true; data: VideoSnapshot } | { ok: false; error: string };

export function isVideoRequest(value: unknown): value is VideoRequest {
  if (typeof value !== 'object' || value === null) return false;
  const item = value as Record<string, unknown>;
  return item.type === 'video.request' &&
    (item.action === 'prepare' || item.action === 'poll' || item.action === 'cancel') &&
    typeof item.videoId === 'string' && /^[A-Za-z0-9_-]{11}$/.test(item.videoId) &&
    (item.target === 'es' || item.target === 'en') &&
    Number.isInteger(item.since) && (item.since as number) >= 0;
}

export function videoEndpoint(serverUrl: string, action: VideoAction): string {
  const url = new URL(serverUrl);
  if (!['ws:', 'wss:'].includes(url.protocol) ||
      !['127.0.0.1', 'localhost'].includes(url.hostname)) {
    throw new Error('La traducción de vídeos requiere el servidor local de YouJP');
  }
  url.protocol = url.protocol === 'wss:' ? 'https:' : 'http:';
  url.pathname = `/video/${action}`;
  url.search = '';
  url.hash = '';
  return url.toString();
}

/** Lo usa el service worker. */
export async function callVideoApi(serverUrl: string, request: VideoRequest): Promise<VideoSnapshot> {
  let response: Response;
  try {
    response = await fetch(videoEndpoint(serverUrl, request.action), {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ video_id: request.videoId, target: request.target, since: request.since }),
    });
  } catch {
    throw new Error('No se pudo conectar con YouJP. Comprueba que está iniciado.');
  }
  if (!response.ok) {
    const detail = await response.json().then((body) => body?.detail, () => null);
    throw new Error(typeof detail === 'string' ? detail : 'YouJP no pudo atender la petición');
  }
  return await response.json() as VideoSnapshot;
}

/** Lo usa el content script. */
export async function requestVideo(
  action: VideoAction, videoId: string, target: TargetLanguage, since = 0,
): Promise<VideoSnapshot> {
  const response = await chrome.runtime.sendMessage(
    { type: 'video.request', action, videoId, target, since } satisfies VideoRequest,
  ) as VideoResponse | undefined;
  if (!response) throw new Error('La extensión no respondió. Recarga la pestaña.');
  if (!response.ok) throw new Error(response.error);
  return response.data;
}

export function cueToLine(cue: VideoCue, target: TargetLanguage): Line {
  return {
    id: cue.i, ja: cue.ja, translation: cue.tr, target: cue.tr ? target : null,
    tokens: cue.tokens, mediaStartMs: cue.start_ms, mediaEndMs: cue.end_ms,
  };
}

/** Última frase que ya ha empezado; -1 antes de la primera. */
export function cueIndexAt(lines: readonly Line[], timeMs: number): number {
  let low = 0;
  let high = lines.length - 1;
  let found = -1;
  while (low <= high) {
    const middle = (low + high) >> 1;
    if ((lines[middle]?.mediaStartMs ?? Infinity) <= timeMs) { found = middle; low = middle + 1; } else high = middle - 1;
  }
  return found;
}
