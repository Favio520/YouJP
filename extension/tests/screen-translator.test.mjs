import assert from 'node:assert/strict';
import { test } from 'node:test';
import { fileURLToPath } from 'node:url';
import { runInNewContext } from 'node:vm';
import { buildSync } from 'esbuild';

const source = buildSync({
  entryPoints: [fileURLToPath(new URL('../src/ui/ScreenTranslator.ts', import.meta.url))],
  bundle: true, write: false, platform: 'browser', format: 'iife', globalName: 'screen',
}).outputFiles[0].text;

class Events {
  listeners = new Map();
  addEventListener(type, fn) {
    if (!this.listeners.has(type)) this.listeners.set(type, new Set());
    this.listeners.get(type).add(fn);
  }
  removeEventListener(type, fn) { this.listeners.get(type)?.delete(fn); }
  emit(type, event = {}) {
    for (const fn of [...(this.listeners.get(type) ?? [])]) fn({ preventDefault() {}, ...event });
  }
}
class Element extends Events {
  children = [];
  style = {};
  append(node) { this.children.push(node); node.parent = this; }
  remove() { if (this.parent) this.parent.children = this.parent.children.filter((node) => node !== this); }
  attachShadow() { this.root = new Element(); return this.root; }
  setAttribute() {}
}

function harness({ plainPage = false } = {}) {
  const window = new Events(), document = new Events();
  document.documentElement = new Element();
  document.fullscreenElement = plainPage ? null : new Element();
  document.createElement = () => new Element();
  const overlay = { style: { visibility: '' } };
  document.querySelector = () => plainPage ? null : overlay;
  const frames = [], requests = [], cancellations = [];
  const context = { window, document, innerWidth: 1000, innerHeight: 600,
    requestAnimationFrame: (fn) => frames.push(fn),
    navigator: { clipboard: { writeText: async () => { throw new Error('denied'); } } },
    chrome: { runtime: { sendMessage: (message) => {
      if (message.type === 'screen.cancel') { cancellations.push(message); return Promise.resolve({ ok: true }); }
      return new Promise((resolve) => requests.push({ message, resolve }));
    } } },
  };
  runInNewContext(source, context);
  return { api: context.screen, window, document, overlay, requests, cancellations,
    select() {
      context.screen.startScreenSelection();
      const host = (document.fullscreenElement ?? document.documentElement).children.at(-1);
      host.root.children.find((node) => node.className === 'veil').emit('pointerdown', {
        button: 0, clientX: 10, clientY: 20,
      });
      window.emit('pointerup', { clientX: 100, clientY: 200 });
    },
    async paint() { while (frames.length) frames.shift()(); await new Promise(setImmediate); },
  };
}
const response = { ok: true, result: { japanese: '猫', spanish: 'gato', translation: 'gato',
  target: 'es', translation_error: null, provider: 'test' } };

test('OCR selects and displays results on a normal page without a video or subtitle overlay', async () => {
  const h = harness({ plainPage: true });
  h.select();
  await h.paint();
  assert.equal(h.requests.length, 1);
  h.api.onScreenCaptureProgress();
  h.requests[0].resolve(response);
  await new Promise(setImmediate);
  assert.equal(h.document.documentElement.children.length, 1);
  assert.ok(findByText(h.document.documentElement.children[0].root, 'gato'));
  h.api.disposeScreenTranslator();
  assert.equal(h.document.documentElement.children.length, 0);
});

function findByText(element, value) {
  if (element.textContent === value) return element;
  for (const child of element.children) {
    const found = findByText(child, value);
    if (found) return found;
  }
}

test('OCR selection and results are visible inside the fullscreen player', async () => {
  const h = harness();
  h.select();
  assert.equal(h.overlay.style.visibility, 'hidden');
  await h.paint();
  assert.equal(h.requests.length, 1);
  h.api.onScreenCaptureProgress();
  assert.equal(h.overlay.style.visibility, '');
  assert.equal(h.document.fullscreenElement.children.length, 1);
  assert.equal(h.document.documentElement.children.length, 0);
  h.requests[0].resolve(response);
  await new Promise(setImmediate);
  const panel = h.document.fullscreenElement.children[0].root;
  const copy = findByText(panel, 'Copiar traducción');
  copy.onclick();
  await new Promise(setImmediate);
  assert.equal(copy.textContent, 'No se pudo copiar');
  h.api.disposeScreenTranslator();
  assert.equal(h.window.listeners.get('keydown').size, 0);
});

test('closing an OCR progress panel prevents the late response reopening it', async () => {
  const h = harness();
  h.select();
  await h.paint();
  h.api.onScreenCaptureProgress();
  h.window.emit('keydown', { key: 'Escape' });
  assert.equal(h.cancellations.length, 1);
  assert.equal(h.document.fullscreenElement.children.length, 0);
  h.requests[0].resolve(response);
  await new Promise(setImmediate);
  assert.equal(h.document.fullscreenElement.children.length, 0);
});

test('English OCR retains recognized text and retries translation without recapturing', async () => {
  const h = harness({ plainPage: true });
  h.api.configureScreenTranslator({ settingsLanguage: 'en', targetLanguage: 'en' });
  h.select();
  await h.paint();
  h.requests[0].resolve({ ok: true, result: { ...response.result, translation: '', spanish: '',
    target: 'en', translation_error: 'translation_failed' } });
  await new Promise(setImmediate);
  let panel = h.document.documentElement.children[0].root;
  assert.ok(findByText(panel, '猫'));
  const retry = findByText(panel, 'Retry translation');
  assert.ok(retry);
  retry.onclick();
  assert.equal(h.requests[1].message.type, 'screen.retry');
  assert.equal(h.requests[1].message.japanese, '猫');
  h.requests[1].resolve({ ok: true, result: { ...response.result, target: 'en', translation: 'cat', spanish: '' } });
  await new Promise(setImmediate);
  panel = h.document.documentElement.children[0].root;
  assert.ok(findByText(panel, 'cat'));
  assert.ok(findByText(panel, 'Copy translation'));
  assert.equal(h.requests.filter(({ message }) => message.type === 'screen.capture').length, 1);
});

test('navigation before painting cancels the screenshot request and restores subtitles', async () => {
  const h = harness();
  h.select();
  h.api.disposeScreenTranslator();
  await h.paint();
  assert.equal(h.requests.length, 0);
  assert.equal(h.overlay.style.visibility, '');
});

test('an old request cannot release the overlay or pending state of a new selection', async () => {
  const h = harness();
  h.select();
  await h.paint();
  h.api.disposeScreenTranslator();
  h.select();
  await h.paint();
  h.requests[0].resolve(response);
  await new Promise(setImmediate);
  assert.equal(h.overlay.style.visibility, 'hidden');
  h.api.startScreenSelection();
  assert.equal(h.document.fullscreenElement.children.length, 0, 'new capture is still pending');
  h.requests[1].resolve(response);
  await new Promise(setImmediate);
  assert.equal(h.overlay.style.visibility, '');
  assert.equal(h.document.fullscreenElement.children.length, 1);
  h.api.disposeScreenTranslator();
});

test('changing fullscreen while selecting cancels the stale crop rectangle', () => {
  const h = harness();
  h.api.startScreenSelection();
  h.document.emit('fullscreenchange');
  assert.equal(h.document.fullscreenElement.children.length, 0);
  assert.equal(h.window.listeners.get('pointermove')?.size ?? 0, 0);
  assert.equal(h.window.listeners.get('keydown').size, 0);
});
