/** Captura y recorta en el service worker: solo el recorte llega al backend. */
import type { TargetLanguage } from './protocol';

export interface ScreenRect {
  x: number;
  y: number;
  width: number;
  height: number;
}

export interface ScreenSelection {
  rect: ScreenRect;
  viewport: { width: number; height: number };
}

export interface ScreenTranslation {
  japanese: string;
  translation: string;
  target: TargetLanguage;
  translation_error: string | null;
  provider: string;
  /** Compatibility with older Spanish-only clients. */
  spanish: string;
}

export function supportsScreenCapture(url: string | undefined): boolean {
  try {
    return !!url && ['http:', 'https:'].includes(new URL(url).protocol);
  } catch {
    return false;
  }
}

export function validSelection(value: unknown): value is ScreenSelection {
  if (!value || typeof value !== 'object') return false;
  const item = value as Partial<ScreenSelection>;
  const r = item.rect;
  const v = item.viewport;
  if (!r || !v) return false;
  if (![r.x, r.y, r.width, r.height, v.width, v.height]
    .every((n) => typeof n === 'number' && Number.isFinite(n))) return false;
  return r.x >= 0 && r.y >= 0 && r.width >= 12 && r.height >= 12 &&
    v.width >= 12 && v.height >= 12 &&
    r.x + r.width <= v.width + 1 && r.y + r.height <= v.height + 1;
}

export function cropBounds(selection: ScreenSelection, imageWidth: number, imageHeight: number) {
  const scaleX = imageWidth / selection.viewport.width;
  const scaleY = imageHeight / selection.viewport.height;
  const x = Math.max(0, Math.floor(selection.rect.x * scaleX));
  const y = Math.max(0, Math.floor(selection.rect.y * scaleY));
  const width = Math.min(imageWidth - x, Math.ceil(selection.rect.width * scaleX));
  const height = Math.min(imageHeight - y, Math.ceil(selection.rect.height * scaleY));
  if (width < 1 || height < 1 || width * height > 6_000_000) {
    throw new Error('La selección es demasiado grande');
  }
  return { x, y, width, height };
}

export function ocrEndpoint(serverUrl: string): string {
  const url = new URL(serverUrl);
  if (!['ws:', 'wss:'].includes(url.protocol) ||
      !['127.0.0.1', 'localhost'].includes(url.hostname)) {
    throw new Error('La traducción de capturas requiere el servidor local de YouJP');
  }
  url.protocol = url.protocol === 'wss:' ? 'https:' : 'http:';
  url.pathname = '/ocr/translate';
  url.search = '';
  url.hash = '';
  return url.toString();
}

export async function captureAndTranslate(
  tab: chrome.tabs.Tab,
  selection: ScreenSelection,
  serverUrl: string,
  onCaptured?: () => void | Promise<void>,
  target: TargetLanguage = 'es',
  signal?: AbortSignal,
): Promise<ScreenTranslation> {
  if (!tab.active || tab.id === undefined || tab.windowId === undefined ||
      !supportsScreenCapture(tab.url)) {
    throw new Error('Abre una página web HTTP o HTTPS en la pestaña activa para usar el recorte');
  }
  if (!validSelection(selection)) throw new Error('Selección no válida');
  const endpoint = ocrEndpoint(serverUrl);
  signal?.throwIfAborted();

  const [active] = await chrome.tabs.query({ active: true, windowId: tab.windowId });
  if (active?.id !== tab.id || (active.url && active.url !== tab.url)) {
    throw new Error('La pestaña cambió antes de capturar');
  }

  signal?.throwIfAborted();
  const dataUrl = await chrome.tabs.captureVisibleTab(tab.windowId, { format: 'png' });
  // captureVisibleTab resuelve de forma asíncrona. Si la pestaña activa cambió
  // durante la captura, descartar la imagen antes de procesarla o enviarla.
  const [capturedTab] = await chrome.tabs.query({ active: true, windowId: tab.windowId });
  if (capturedTab?.id !== tab.id || (capturedTab.url && capturedTab.url !== tab.url)) {
    throw new Error('La pestaña cambió durante la captura. Vuelve a seleccionar el texto.');
  }
  signal?.throwIfAborted();
  const bitmap = await createImageBitmap(await (await fetch(dataUrl)).blob());
  let png: Blob;
  try {
    const bounds = cropBounds(selection, bitmap.width, bitmap.height);
    const canvas = new OffscreenCanvas(bounds.width, bounds.height);
    const context = canvas.getContext('2d');
    if (!context) throw new Error('No se pudo preparar el recorte');
    context.drawImage(bitmap, bounds.x, bounds.y, bounds.width, bounds.height,
      0, 0, bounds.width, bounds.height);
    png = await canvas.convertToBlob({ type: 'image/png' });
  } finally {
    bitmap.close();
  }

  await onCaptured?.();
  signal?.throwIfAborted();

  const url = new URL(endpoint);
  url.searchParams.set('target', target);
  return requestTranslation(url.toString(), png, 'image/png', target, signal);
}

export async function retryScreenTranslation(
  japanese: string, serverUrl: string, target: TargetLanguage, signal?: AbortSignal,
): Promise<ScreenTranslation> {
  const url = new URL(ocrEndpoint(serverUrl));
  url.pathname = '/ocr/translate-text';
  return requestTranslation(url.toString(), JSON.stringify({ japanese, target }),
    'application/json', target, signal);
}

async function requestTranslation(endpoint: string, body: BodyInit, contentType: string,
  target: TargetLanguage, signal?: AbortSignal): Promise<ScreenTranslation> {
  let response: Response;
  try {
    response = await fetch(endpoint, {
      method: 'POST',
      headers: { 'Content-Type': contentType },
      body,
      redirect: 'error',
      signal: signal ? AbortSignal.any([signal, AbortSignal.timeout(150_000)]) : AbortSignal.timeout(150_000),
    });
  } catch (error) {
    if (signal?.aborted) throw error;
    throw new Error('No se pudo conectar con el OCR. Reinicia YouJP e inténtalo de nuevo.');
  }
  if (response.status === 404) {
    throw new Error('El servidor abierto aún no tiene OCR. Cierra y vuelve a iniciar YouJP.');
  }
  const payload: unknown = await response.json().catch(() => null);
  if (!response.ok) {
    const detail = payload && typeof payload === 'object' && 'detail' in payload
      ? String(payload.detail) : `Error del servidor (${response.status})`;
    throw new Error(detail);
  }
  if (!payload || typeof payload !== 'object' ||
      !('japanese' in payload) || typeof payload.japanese !== 'string' ||
      !('spanish' in payload) || typeof payload.spanish !== 'string') {
    throw new Error('Respuesta de OCR no válida');
  }
  if (!('translation' in payload) || typeof payload.translation !== 'string' ||
      !('target' in payload) || payload.target !== target ||
      !('translation_error' in payload) ||
      (payload.translation_error !== null && typeof payload.translation_error !== 'string') ||
      !('provider' in payload) || typeof payload.provider !== 'string') {
    throw new Error('El servidor OCR es antiguo. Reinicia YouJP para actualizarlo.');
  }
  return { japanese: payload.japanese, spanish: payload.spanish, translation: payload.translation,
    target, translation_error: payload.translation_error, provider: payload.provider };
}
