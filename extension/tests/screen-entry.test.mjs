import assert from 'node:assert/strict';
import { test } from 'node:test';
import { fileURLToPath } from 'node:url';
import { runInNewContext } from 'node:vm';
import { buildSync } from 'esbuild';

const source = buildSync({
  entryPoints: [fileURLToPath(new URL('../entrypoints/screen.content.ts', import.meta.url))],
  bundle: true, write: false, platform: 'node', format: 'cjs',
  external: ['#imports', '@/src/ui/ScreenTranslator', '@/src/settings'],
}).outputFiles[0].text;

test('on-demand selector responds once, cleans up on navigation and ignores foreign senders', () => {
  let definition, listener, cleanup;
  let selected = 0, disposed = 0, progress = 0;
  const events = new Map();
  const translator = {
    configureScreenTranslator() {},
    startScreenSelection() { selected++; },
    disposeScreenTranslator() { disposed++; },
    onScreenCaptureProgress() { progress++; },
  };
  runInNewContext(source, {
    module: { exports: {} }, window: {},
    require: (name) => name === '#imports'
      ? { defineContentScript(value) { definition = value; return value; } }
      : name === '@/src/settings' ? { loadSettings: async () => ({}), onSettingsChanged: () => () => {} } : translator,
    chrome: { runtime: { id: 'test', onMessage: {
      addListener(fn) { listener = fn; },
      removeListener(fn) { assert.equal(fn, listener); listener = null; },
    } } },
  });
  assert.equal(definition.registration, 'runtime');
  definition.main({
    addEventListener(_target, name, fn) { events.set(name, fn); },
    onInvalidated(fn) { cleanup = fn; },
  });
  let ready = false;
  listener({ type: 'screen.probe' }, { id: 'test' }, (value) => { ready = value.ready; });
  assert.equal(ready, true);
  listener({ type: 'screen.select' }, { id: 'other' });
  assert.equal(selected, 0);
  listener({ type: 'screen.select' }, { id: 'test' });
  listener({ type: 'screen.capture.progress' }, { id: 'test' });
  assert.equal(selected, 1);
  assert.equal(progress, 1);
  events.get('wxt:locationchange')();
  events.get('pagehide')();
  assert.equal(disposed, 2);
  cleanup();
  assert.equal(disposed, 3);
  assert.equal(listener, null);
});
