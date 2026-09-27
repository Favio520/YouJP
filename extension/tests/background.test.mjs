import assert from 'node:assert/strict';
import { test } from 'node:test';
import { fileURLToPath } from 'node:url';
import { runInNewContext } from 'node:vm';
import { buildSync } from 'esbuild';

const source = buildSync({
  entryPoints: [fileURLToPath(new URL('../entrypoints/background.ts', import.meta.url))],
  bundle: true, write: false, platform: 'node', format: 'cjs', external: ['#imports'],
  alias: { '@': fileURLToPath(new URL('..', import.meta.url)) },
}).outputFiles[0].text;

function harness({ capture = { tabId: 7, videoId: 'video' }, settings } = {}) {
  let receive, removed, settingsListener;
  let closes = 0;
  const routed = [], broadcasts = [], badges = [];
  const state = { capture };
  const chrome = {
    storage: {
      session: {
        get: async () => state,
        remove: async (key) => { delete state[key]; },
      },
      local: { get: async () => ({ overlaySettings: settings }) },
      onChanged: { addListener: (fn) => { settingsListener = fn; } },
    },
    runtime: {
      id: 'test',
      getURL: (path) => `chrome-extension://test/${path}`,
      onMessage: { addListener: (fn) => { receive = fn; } },
      sendMessage: async (msg) => { broadcasts.push(msg); },
    },
    action: {
      onClicked: { addListener() {} },
      setBadgeText: async (badge) => { badges.push(badge); },
      setTitle: async () => {},
    },
    tabs: {
      sendMessage: async (tabId, msg) => { routed.push({ tabId, msg }); },
      onRemoved: { addListener: (fn) => { removed = fn; } },
      onUpdated: { addListener() {} },
    },
    offscreen: { closeDocument: async () => { closes += 1; } },
  };
  runInNewContext(source, { chrome, console, module: { exports: {} },
    require: () => ({ defineBackground: (main) => main() }) });
  return { state, routed, broadcasts, badges, get closes() { return closes; },
    change: (...args) => settingsListener(...args),
    receive: (...args) => receive(...args), remove: (id) => removed(id) };
}

test('offscreen can request saved settings before capture starts', async () => {
  for (const [stored, expected] of [[{ targetLanguage: 'en', esSize: 30 }, 'en'], [undefined, 'es']]) {
    const h = harness({ capture: null, settings: stored });
    const settings = await new Promise((resolve) => {
      assert.equal(h.receive({ type: 'settings.get' }, { id: 'test' }, resolve), true);
    });
    assert.equal(settings.targetLanguage, expected);
    if (stored) assert.equal(settings.translationSize, 30);
  }
});

test('service worker relays normalized setting changes through runtime messages', async () => {
  const h = harness();
  const changes = { overlaySettings: { newValue: { targetLanguage: 'en' } } };
  h.change(changes, 'sync');
  assert.equal(h.broadcasts.length, 0);
  h.change(changes, 'local');
  assert.equal(h.broadcasts[0].type, 'settings.changed');
  assert.equal(h.broadcasts[0].settings.targetLanguage, 'en');
});

test('a restarted service worker restores routing and ignores other senders/tabs', async () => {
  const h = harness();
  const sender = { id: 'test' };
  h.receive({ type: 'status', tabId: 7, status: 'reconnecting' }, sender);
  await new Promise(setImmediate);
  assert.equal(h.routed[0].tabId, 7);
  assert.equal(h.badges[0].text, '...');
  h.receive({ type: 'status', tabId: 8, status: 'running' }, sender);
  h.receive({ type: 'status', tabId: 7, status: 'running' }, { id: 'test', tab: { id: 7 } });
  await new Promise(setImmediate);
  assert.equal(h.routed.length, 1);
});

test('fatal offscreen status clears stale capture state', async () => {
  const h = harness();
  h.receive({ type: 'status', tabId: 7, status: 'error', detail: 'fatal' }, { id: 'test' });
  await new Promise(setImmediate);
  assert.equal(h.state.capture, undefined);
  assert.equal(h.closes, 1);
});

test('closing captured tab after worker restart stops reconnects and removes stored state', async () => {
  const h = harness();
  h.remove(7);
  await new Promise(setImmediate);
  assert.equal(h.state.capture, undefined);
  assert.equal(h.broadcasts[0].type, 'capture.stop');
});
