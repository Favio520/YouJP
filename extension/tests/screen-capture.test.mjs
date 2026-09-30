import assert from 'node:assert/strict';
import { test } from 'node:test';
import { createRequire } from 'node:module';
import { fileURLToPath } from 'node:url';
import { buildSync } from 'esbuild';

const file = fileURLToPath(new URL('../src/screenCapture.ts', import.meta.url));
const bundle = buildSync({ entryPoints: [file], bundle: true, write: false,
  platform: 'node', format: 'cjs' }).outputFiles[0].text;
const module = { exports: {} };
new Function('require', 'module', 'exports', bundle)(createRequire(import.meta.url), module, module.exports);
const { validSelection, cropBounds, ocrEndpoint, captureAndTranslate, supportsScreenCapture, retryScreenTranslation } = module.exports;

const selection = {
  rect: { x: 100, y: 50, width: 200, height: 100 },
  viewport: { width: 1000, height: 500 },
};

test('crop follows screenshot scale and excludes everything outside the selection', () => {
  assert.equal(validSelection(selection), true);
  assert.deepEqual(cropBounds(selection, 2000, 1000), { x: 200, y: 100, width: 400, height: 200 });
  assert.equal(validSelection({ ...selection, rect: { ...selection.rect, x: -1 } }), false);
  assert.equal(validSelection({ ...selection, rect: { ...selection.rect, width: 2000 } }), false);
});

test('screenshot requests stay on the configured local backend', () => {
  assert.equal(ocrEndpoint('ws://127.0.0.1:8770/stream'), 'http://127.0.0.1:8770/ocr/translate');
  assert.equal(ocrEndpoint('ws://localhost:8770/stream'), 'http://localhost:8770/ocr/translate');
  assert.throws(() => ocrEndpoint('wss://remote.example/stream'), /servidor local/);
});

test('OCR accepts ordinary web pages and rejects non-web URLs', async () => {
  for (const url of ['https://example.org/manga', 'http://example.net/']) {
    assert.equal(supportsScreenCapture(url), true);
  }
  for (const url of [undefined, 'not a URL', 'chrome://settings', 'edge://extensions', 'file:///book.png']) {
    assert.equal(supportsScreenCapture(url), false);
    await assert.rejects(captureAndTranslate({ id: 7, windowId: 4, active: true, url },
      selection, 'ws://127.0.0.1:8770/stream'), /HTTP o HTTPS/);
  }
});

test('captured selection is cropped and a stale server reports how to fix OCR', async () => {
  const originals = {
    chrome: globalThis.chrome,
    fetch: globalThis.fetch,
    createImageBitmap: globalThis.createImageBitmap,
    OffscreenCanvas: globalThis.OffscreenCanvas,
  };
  const draws = [];
  const requests = [];
  let captured = false;
  globalThis.chrome = {
    tabs: {
      query: async () => [{ id: 7 }],
      captureVisibleTab: async () => 'data:image/png;base64,AA==',
    },
  };
  globalThis.createImageBitmap = async () => ({ width: 2000, height: 1000, close() {} });
  globalThis.OffscreenCanvas = class {
    getContext() { return { drawImage: (...args) => draws.push(args) }; }
    async convertToBlob() { return new Blob(['png'], { type: 'image/png' }); }
  };
  globalThis.fetch = async (url, options) => {
    requests.push({ url, options });
    if (requests.length === 1) return { blob: async () => new Blob() };
    return { status: 404, ok: false, json: async () => ({ detail: 'Not Found' }) };
  };
  try {
    await assert.rejects(
      captureAndTranslate(
        { id: 7, windowId: 4, active: true, url: 'https://example.org/manga/chapter-1' },
        selection, 'ws://127.0.0.1:8770/stream', () => { captured = true; },
      ),
      /servidor abierto aún no tiene OCR.*vuelve a iniciar YouJP/,
    );
    assert.equal(captured, true);
    assert.deepEqual(draws[0].slice(1), [200, 100, 400, 200, 0, 0, 400, 200]);
    assert.equal(requests[1].url, 'http://127.0.0.1:8770/ocr/translate?target=es');
    assert.equal(requests[1].options.body.type, 'image/png');
    assert.equal(requests[1].options.redirect, 'error');
  } finally {
    Object.assign(globalThis, originals);
  }
});

test('retry sends recognized text and English target without a screenshot', async () => {
  const previous = globalThis.fetch;
  const requests = [];
  globalThis.fetch = async (url, options) => {
    requests.push({ url, options });
    return { ok: true, status: 200, json: async () => ({ japanese: '猫', translation: 'cat',
      spanish: '', target: 'en', translation_error: null, provider: 'test' }) };
  };
  try {
    const result = await retryScreenTranslation('猫', 'ws://127.0.0.1:8770/stream', 'en');
    assert.equal(result.translation, 'cat');
    assert.equal(requests.length, 1);
    assert.equal(requests[0].url, 'http://127.0.0.1:8770/ocr/translate-text');
    assert.deepEqual(JSON.parse(requests[0].options.body), { japanese: '猫', target: 'en' });
  } finally { globalThis.fetch = previous; }
});

for (const capturedTab of [{ id: 8 }, { id: 7, url: 'https://www.youtube.com/watch?v=other' }]) {
  test(`tab change during capture discards image before any upload (${capturedTab.id})`, async () => {
    const originalChrome = globalThis.chrome;
    const originalFetch = globalThis.fetch;
    let queries = 0;
    let requests = 0;
    globalThis.chrome = { tabs: {
      query: async () => [++queries === 1 ? { id: 7 } : capturedTab],
      captureVisibleTab: async () => 'data:image/png;base64,AA==',
    } };
    globalThis.fetch = async () => { requests += 1; throw new Error('must not fetch'); };
    try {
      await assert.rejects(captureAndTranslate(
        { id: 7, windowId: 4, active: true, url: 'https://www.youtube.com/watch?v=abc' },
        selection, 'ws://127.0.0.1:8770/stream',
      ), /durante la captura/);
      assert.equal(requests, 0);
    } finally {
      globalThis.chrome = originalChrome;
      globalThis.fetch = originalFetch;
    }
  });
}
