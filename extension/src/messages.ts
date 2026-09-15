/**
 * Mensajería interna de la extensión.
 *
 * Tres contextos que no pueden hablar entre sí libremente:
 *
 *   content script  --runtime.sendMessage-->  service worker + offscreen
 *   offscreen       --runtime.sendMessage-->  service worker
 *   service worker  --tabs.sendMessage---->   content script
 *
 * El offscreen no tiene acceso a `chrome.tabs`, así que todo lo que va hacia la
 * pestaña pasa por el service worker. Al revés no hace falta: un mensaje de un
 * content script llega a todas las páginas de la extensión, incluida la
 * offscreen, así que el tiempo del reproductor va directo.
 */

import type { AsrFinal, AsrPartial, MetricsTick, MtFinal, ServerError } from './protocol';

export type CaptureStatus =
  | 'idle'
  | 'starting'
  | 'connecting'
  | 'running'
  | 'reconnecting'
  | 'error';

/** content script -> offscreen (y service worker) */
export interface PlayerTick {
  type: 'player.tick';
  mediaTimeMs: number;
  paused: boolean;
  rate: number;
  videoId: string;
}

/** content script -> offscreen: seek, pausa o cambio de velocidad */
export interface PlayerFlush {
  type: 'player.flush';
  reason: 'seek' | 'pause' | 'rate';
  mediaTimeMs: number;
}

/** service worker -> offscreen */
export interface StartCapture {
  type: 'capture.start';
  streamId: string;
  tabId: number;
  videoId: string;
  url: string;
  isLive: boolean;
  mediaTimeMs: number;
  serverUrl: string;
}

export interface StopCapture {
  type: 'capture.stop';
}

/** offscreen -> service worker -> content script */
export interface StatusUpdate {
  type: 'status';
  status: CaptureStatus;
  detail?: string;
  model?: string;
}

export interface SubtitleUpdate {
  type: 'subtitle.partial';
  payload: AsrPartial;
}

export interface SubtitleFinal {
  type: 'subtitle.final';
  payload: AsrFinal;
}

export interface SubtitleTranslation {
  type: 'subtitle.translation';
  payload: MtFinal;
}

export interface MetricsUpdate {
  type: 'metrics';
  payload: MetricsTick;
}

export interface BackendError {
  type: 'backend.error';
  payload: ServerError;
}

export type ExtensionMessage =
  | PlayerTick
  | PlayerFlush
  | StartCapture
  | StopCapture
  | StatusUpdate
  | SubtitleUpdate
  | SubtitleFinal
  | SubtitleTranslation
  | MetricsUpdate
  | BackendError;

export const DEFAULT_SERVER_URL = 'ws://127.0.0.1:8770/stream';
