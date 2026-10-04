/** Selección de una zona visible y resultado OCR, ajenos al overlay de audio. */

import type { ScreenSelection, ScreenTranslation } from '../screenCapture';
import { uiText } from '../i18n';
import { DEFAULT_SETTINGS, type OverlaySettings } from '../settings';

let selector: HTMLElement | null = null;
let resultPanel: HTMLElement | null = null;
let restoreOverlay: (() => void) | null = null;
let cancelSelection: (() => void) | null = null;
let capturePending = false;
let generation = 0;
let resultDismissed = false;
let closeResult: (() => void) | null = null;
let settings = DEFAULT_SETTINGS;

export function configureScreenTranslator(value: OverlaySettings): void { settings = value; }
const t = (value: string) => uiText(settings.settingsLanguage, value);

const STYLE = `
  :host { font-family: system-ui, 'Yu Gothic UI', sans-serif; color-scheme:light; }
  .veil { position:fixed; inset:0; cursor:crosshair; background:rgba(5,10,18,.38);
    touch-action:none; user-select:none; }
  .hint { position:fixed; top:18px; left:50%; transform:translateX(-50%);
    padding:12px 18px; border-radius:16px; background:#fff9f2; color:#25364a;
    border:1px solid #dfd2f5; font-size:13px; box-shadow:0 8px 30px #25364a20;
    pointer-events:none; width:max-content; max-width:calc(100vw - 32px); box-sizing:border-box; text-align:center; }
  .box { position:fixed; display:none; border:2px solid #6450a4;
    background:rgba(185,162,244,.18); box-shadow:0 0 0 1px #fff9f2;
    pointer-events:none; }
  .panel { pointer-events:auto; width:min(370px,calc(100vw - 28px)); max-height:72vh;
    overflow:auto; border:1px solid #eadfd4; border-radius:22px;
    background:#fff9f2; color:#25364a; box-shadow:0 16px 44px #25364a20;
    scrollbar-width:thin; scrollbar-color:#b6a6ce transparent; }
  .head { display:flex; align-items:center; gap:10px; padding:14px 16px;
    border-bottom:1px solid #eadfd4; background:#f1ecfd; font-size:14px; font-weight:600; }
  .badge { color:#6450a4; font-size:11px; letter-spacing:.1em; }
  .title { flex:1; }
  button { font:inherit; cursor:pointer; border:1px solid #eadfd4; border-radius:12px;
    background:#eee5ff; color:#25364a; padding:7px 10px; min-height:32px; }
  button:hover { background:#e4d8fc; }
  button:focus-visible { outline:2px solid #ae3b2c; outline-offset:2px; }
  .close { background:transparent; font-size:18px; line-height:1; }
  .body { padding:18px; font-size:14px; line-height:1.65; }
  .label { color:#ae3b2c; font-size:10px; font-weight:600; text-transform:uppercase;
    letter-spacing:.12em; margin:0 0 5px; }
  .text { white-space:pre-wrap; overflow-wrap:anywhere; margin:0 0 15px; }
  .empty { color:#5c6b7e; }
  .actions { display:flex; justify-content:flex-end; }
`;

function makeHost(): { host: HTMLElement; root: ShadowRoot } {
  const host = document.createElement('youjp-screen-translate');
  const root = host.attachShadow({ mode: 'closed' });
  const style = document.createElement('style');
  style.textContent = STYLE;
  root.append(style);
  // Solo los descendientes del elemento fullscreen son visibles sobre él.
  (document.fullscreenElement ?? document.documentElement).append(host);
  return { host, root };
}

function addText(parent: Element, className: string, value: string): HTMLElement {
  const node = document.createElement('div');
  node.className = className;
  node.textContent = value;
  parent.append(node);
  return node;
}

function showResult(translation?: ScreenTranslation, error?: string): void {
  if (resultDismissed) return;
  closeResult?.();
  const { host, root } = makeHost();
  resultPanel = host;
  host.style.cssText = 'position:fixed;top:16px;right:16px;z-index:2147483647;pointer-events:none;';
  const panel = document.createElement('div');
  panel.className = 'panel';
  panel.setAttribute('role', 'dialog');
  panel.setAttribute('aria-label', t('Traducción de captura'));
  root.append(panel);
  const head = document.createElement('div');
  head.className = 'head';
  panel.append(head);
  addText(head, 'badge', '画');
  addText(head, 'title', `${t('Captura')} · ${t('japonés')} → ${t((translation?.target ?? settings.targetLanguage) === 'en' ? 'inglés' : 'español')}`);
  const close = document.createElement('button');
  close.className = 'close';
  close.type = 'button';
  close.textContent = '×';
  close.setAttribute('aria-label', t('Cerrar traducción'));
  const dismiss = () => { resultDismissed = true; disposeScreenTranslator(); };
  const onKey = (event: KeyboardEvent) => {
    if (event.key === 'Escape') { event.preventDefault(); dismiss(); }
  };
  const cleanup = () => {
    window.removeEventListener('keydown', onKey, true);
    host.remove();
    if (resultPanel === host) resultPanel = null;
    if (closeResult === cleanup) closeResult = null;
  };
  closeResult = cleanup;
  window.addEventListener('keydown', onKey, true);
  close.onclick = dismiss;
  head.append(close);
  const body = document.createElement('div');
  body.className = 'body';
  panel.append(body);

  if (error && !translation) {
    addText(body, 'text empty', t(error));
  } else if (!translation) {
    addText(body, 'text empty', t('Leyendo y traduciendo el recorte…'));
  } else if (!translation.japanese) {
    addText(body, 'text empty', t('No encontré texto japonés en la zona seleccionada.'));
  } else {
    addText(body, 'label', t('Texto reconocido'));
    addText(body, 'text', translation.japanese).lang = 'ja';
    addText(body, 'label', t('Traducción'));
    if (error) addText(body, 'text empty', t(error));
    const translated = translation.translation;
    addText(body, translated ? 'text' : 'text empty', translated || t(capturePending ? 'Reintentando…'
      : translation.translation_error ? 'Falló la traducción. Comprueba Ollama o el servidor y vuelve a intentarlo.'
        : 'No hay traductor activo en el servidor local.'));
    if (translation.translation_error) {
      const retry = document.createElement('button');
      retry.type = 'button';
      retry.disabled = capturePending;
      retry.textContent = t(capturePending ? 'Reintentando…' : 'Reintentar traducción');
      retry.onclick = () => { void retryTranslation(translation); };
      body.append(retry);
    }
    if (translated) {
      const actions = document.createElement('div');
      actions.className = 'actions';
      const copy = document.createElement('button');
      copy.type = 'button';
      copy.textContent = t('Copiar traducción');
      copy.onclick = () => {
        void navigator.clipboard.writeText(translated).then(() => {
          copy.textContent = t('Copiado');
        }).catch(() => {
          copy.textContent = t('No se pudo copiar');
        });
      };
      actions.append(copy);
      body.append(actions);
    }
  }
}

function twoFrames(): Promise<void> {
  return new Promise((resolve) => requestAnimationFrame(() => requestAnimationFrame(() => resolve())));
}

export function onScreenCaptureProgress(requestId?: number): void {
  if (requestId !== undefined && requestId !== generation) return;
  restoreOverlay?.();
  restoreOverlay = null;
  if (capturePending) showResult();
}

export function disposeScreenTranslator(): void {
  if (capturePending) {
    void chrome.runtime.sendMessage({ type: 'screen.cancel', requestId: generation }).catch(() => {});
  }
  generation += 1;
  cancelSelection?.();
  closeResult?.();
  resultPanel = null;
  restoreOverlay?.();
  restoreOverlay = null;
  capturePending = false;
}

function validResult(value: unknown): value is ScreenTranslation {
  return !!value && typeof value === 'object' && 'japanese' in value && typeof value.japanese === 'string' &&
    'translation' in value && typeof value.translation === 'string' && 'target' in value &&
    (value.target === 'es' || value.target === 'en') && 'translation_error' in value &&
    (value.translation_error === null || typeof value.translation_error === 'string');
}

async function retryTranslation(previous: ScreenTranslation): Promise<void> {
  if (capturePending) return;
  capturePending = true;
  const currentGeneration = ++generation;
  showResult(previous);
  try {
    const response = await chrome.runtime.sendMessage({ type: 'screen.retry',
      japanese: previous.japanese, requestId: currentGeneration });
    if (currentGeneration !== generation) return;
    capturePending = false;
    if (response?.ok && validResult(response.result)) showResult(response.result);
    else showResult(previous, response?.error ?? 'El servidor devolvió una respuesta no válida');
  } catch (error) {
    if (currentGeneration === generation) {
      capturePending = false;
      showResult(previous, error instanceof Error ? error.message : String(error));
    }
  } finally { if (currentGeneration === generation) capturePending = false; }
}

export function startScreenSelection(): void {
  if (capturePending) return;
  cancelSelection?.();
  closeResult?.();
  resultPanel = null;
  resultDismissed = false;
  const { host, root } = makeHost();
  selector = host;
  host.style.cssText = 'position:fixed;inset:0;z-index:2147483647;';
  const veil = document.createElement('div');
  veil.className = 'veil';
  root.append(veil);
  addText(veil, 'hint', t('Arrastra sobre el texto japonés · Esc para cancelar'));
  const box = document.createElement('div');
  box.className = 'box';
  root.append(box);

  let start: { x: number; y: number } | null = null;
  const clamp = (n: number, max: number) => Math.max(0, Math.min(max, n));
  const draw = (x: number, y: number) => {
    if (!start) return;
    const left = Math.min(start.x, x);
    const top = Math.min(start.y, y);
    box.style.cssText = `display:block;left:${left}px;top:${top}px;width:${Math.abs(x - start.x)}px;height:${Math.abs(y - start.y)}px;`;
  };
  const cleanup = () => {
    window.removeEventListener('pointermove', move, true);
    window.removeEventListener('pointerup', up, true);
    window.removeEventListener('pointercancel', cleanup, true);
    window.removeEventListener('blur', cleanup);
    document.removeEventListener('fullscreenchange', cleanup);
    window.removeEventListener('resize', cleanup);
    window.removeEventListener('scroll', cleanup, true);
    window.removeEventListener('keydown', key, true);
    host.remove();
    if (selector === host) selector = null;
    if (cancelSelection === cleanup) cancelSelection = null;
  };
  const move = (event: PointerEvent) => {
    draw(clamp(event.clientX, innerWidth), clamp(event.clientY, innerHeight));
  };
  const key = (event: KeyboardEvent) => {
    if (event.key === 'Escape') { event.preventDefault(); cleanup(); }
  };
  const up = (event: PointerEvent) => {
    if (!start) return;
    const endX = clamp(event.clientX, innerWidth);
    const endY = clamp(event.clientY, innerHeight);
    const selection: ScreenSelection = {
      rect: { x: Math.min(start.x, endX), y: Math.min(start.y, endY),
        width: Math.abs(endX - start.x), height: Math.abs(endY - start.y) },
      viewport: { width: innerWidth, height: innerHeight },
    };
    cleanup();
    if (selection.rect.width < 12 || selection.rect.height < 12) return;
    capturePending = true;
    const currentGeneration = ++generation;
    void (async () => {
      const overlay = document.querySelector<HTMLElement>('youjp-overlay');
      if (overlay) {
        const previous = overlay.style.visibility;
        overlay.style.visibility = 'hidden';
        restoreOverlay = () => { overlay.style.visibility = previous; };
      }
      try {
        await twoFrames();
        if (currentGeneration !== generation) return;
        const response: unknown = await chrome.runtime.sendMessage({ type: 'screen.capture', selection, requestId: currentGeneration });
        if (currentGeneration !== generation) return;
        if (!response || typeof response !== 'object' || !('ok' in response) || !response.ok) {
          const message = response && typeof response === 'object' && 'error' in response
            ? String(response.error) : 'No se pudo capturar la pestaña';
          showResult(undefined, message);
        } else if ('result' in response && validResult(response.result)) {
          capturePending = false;
          showResult(response.result);
        } else {
          showResult(undefined, 'El servidor devolvió una respuesta no válida');
        }
      } catch (error) {
        if (currentGeneration === generation) {
          showResult(undefined, error instanceof Error ? error.message : String(error));
        }
      } finally {
        if (currentGeneration === generation) {
          restoreOverlay?.();
          restoreOverlay = null;
          capturePending = false;
        }
      }
    })();
  };
  veil.addEventListener('pointerdown', (event) => {
    if (event.button !== 0) return;
    event.preventDefault();
    start = { x: clamp(event.clientX, innerWidth), y: clamp(event.clientY, innerHeight) };
    window.addEventListener('pointermove', move, true);
    window.addEventListener('pointerup', up, true);
  });
  window.addEventListener('keydown', key, true);
  window.addEventListener('pointercancel', cleanup, true);
  window.addEventListener('blur', cleanup);
  document.addEventListener('fullscreenchange', cleanup);
  window.addEventListener('resize', cleanup);
  window.addEventListener('scroll', cleanup, true);
  cancelSelection = cleanup;
}
