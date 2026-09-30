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

function harness({ capture = { tabId: 7, videoId: 'video' }, settings, beforeProbe,
    failStream = false, screenReady = true, failInjection = false, fetchImpl } = {}) {
  let receive, removed, updated, settingsListener, command, click;
  const receivers = [];
  let closes = 0;
  const routed = [], broadcasts = [], badges = [], events = [], injected = [], titles = [];
  const state = { capture };
  const chrome = {
    storage: {
      session: {
        get: async () => state,
        set: async (value) => { Object.assign(state, value); },
        remove: async (key) => { delete state[key]; },
      },
      local: { get: async () => ({ overlaySettings: settings }) },
      onChanged: { addListener: (fn) => { settingsListener = fn; } },
    },
    runtime: {
      id: 'test',
      ContextType: { OFFSCREEN_DOCUMENT: 'OFFSCREEN_DOCUMENT' },
      getContexts: async () => [],
      getManifest: () => ({ content_scripts: [] }),
      getURL: (path) => `chrome-extension://test/${path}`,
      onMessage: { addListener: (fn) => { receivers.push(fn); receive = fn; } },
      sendMessage: async (msg) => {
        broadcasts.push(msg);
        events.push(msg.type);
        if (msg.type === 'offscreen.ping') return { ready: true };
      },
    },
    action: {
      onClicked: { addListener: (fn) => { click = fn; } },
      setBadgeText: async (badge) => { badges.push(badge); },
      setBadgeBackgroundColor: async () => {},
      setTitle: async (value) => { titles.push(value); },
    },
    commands: { onCommand: { addListener: (fn) => { command = fn; } } },
    scripting: { executeScript: async (options) => {
      injected.push(options);
      if (failInjection) throw new Error('Cannot access contents of this page');
      screenReady = true;
    } },
    tabs: {
      get: async (id) => ({ id, url: 'https://example.org/' }),
      sendMessage: async (tabId, msg) => {
        routed.push({ tabId, msg });
        if (msg.type === 'screen.probe') return { ready: screenReady };
        if (msg.type === 'player.probe') {
          events.push('player.probe');
          await beforeProbe?.();
          return { videoId: 'video', mediaTimeMs: 0, paused: false, rate: 1, isLive: false };
        }
        return undefined;
      },
      onRemoved: { addListener: (fn) => { removed = fn; } },
      onUpdated: { addListener: (fn) => { updated = fn; } },
    },
    offscreen: {
      Reason: { USER_MEDIA: 'USER_MEDIA' },
      createDocument: async () => { events.push('createDocument'); },
      closeDocument: async () => { closes += 1; },
    },
    tabCapture: { getMediaStreamId: (_, callback) => {
      events.push('streamId');
      callback(failStream ? '' : 'stream');
    } },
  };
  runInNewContext(source, { chrome, console, URL, AbortController, AbortSignal, fetch: fetchImpl,
    module: { exports: {} },
    require: () => ({ defineBackground: (main) => main() }) });
  return { state, routed, broadcasts, badges, events, injected, titles, get closes() { return closes; },
    click: (...args) => click(...args),
    screen: (...args) => receivers[0](...args), update: (...args) => updated(...args),
    change: (...args) => settingsListener(...args),
    receive: (...args) => receive(...args), remove: (id) => removed(id),
    command: (...args) => command(...args) };
}

test('OCR retry uses saved target and rejects messages from subframes', async () => {
  const calls = [];
  const h = harness({ settings: { targetLanguage: 'en' }, fetchImpl: async (url, options) => {
    calls.push({ url, options });
    return { ok: true, status: 200, json: async () => ({ japanese: '猫', translation: 'cat',
      spanish: '', target: 'en', translation_error: null, provider: 'test' }) };
  } });
  const sender = { id: 'test', tab: { id: 8 }, frameId: 0, documentId: 'doc', url: 'https://example.org/' };
  assert.equal(h.screen({ type: 'screen.retry', japanese: '猫' }, { ...sender, frameId: 1 }, () => {}), undefined);
  const reply = await new Promise((resolve) => h.screen({ type: 'screen.retry', japanese: '猫', requestId: 1 }, sender, resolve));
  assert.equal(reply.ok, true);
  assert.equal(reply.result.translation, 'cat');
  assert.equal(calls.length, 1);
  assert.deepEqual(JSON.parse(calls[0].options.body), { japanese: '猫', target: 'en' });
});

for (const cancel of ['close', 'navigate', 'remove']) {
  test(`OCR pending request aborts on ${cancel}`, async () => {
    let signal;
    const h = harness({ fetchImpl: async (_url, options) => {
      signal = options.signal;
      return new Promise((_resolve, reject) => signal.addEventListener('abort', () => reject(signal.reason), { once: true }));
    } });
    const sender = { id: 'test', tab: { id: 8 }, frameId: 0, documentId: 'doc', url: 'https://example.org/' };
    const reply = new Promise((resolve) => h.screen({ type: 'screen.retry', japanese: '猫', requestId: 5 }, sender, resolve));
    await new Promise(setImmediate);
    assert.ok(signal);
    if (cancel === 'close') {
      h.screen({ type: 'screen.cancel', requestId: 4 }, sender, () => {});
      assert.equal(signal.aborted, false, 'old close must not cancel a newer request');
      h.screen({ type: 'screen.cancel', requestId: 5 }, sender, () => {});
    } else if (cancel === 'navigate') h.update(8, { status: 'loading' });
    else h.remove(8);
    assert.equal(signal.aborted, true);
    assert.equal((await reply).ok, false);
  });
}

test('capture shortcut opens the selector on the current YouTube tab', async () => {
  const h = harness();
  h.command('translate-selection', { id: 7, url: 'https://www.youtube.com/watch?v=video' });
  await new Promise(setImmediate);
  assert.equal(h.routed.at(-1).msg.type, 'screen.select');
  assert.equal(h.routed.at(-1).tabId, 7);
});

for (const url of ['https://example.org/manga', 'http://example.org/article']) {
  test(`OCR shortcut injects only the selector on ${url}`, async () => {
    const h = harness({ screenReady: false });
    h.command('translate-selection', { id: 8, url });
    await new Promise(setImmediate);
    assert.deepEqual(JSON.parse(JSON.stringify(h.injected)), [
      { target: { tabId: 8 }, files: ['content-scripts/screen.js'] },
    ]);
    assert.equal(h.routed.at(-1).msg.type, 'screen.select');
    assert.equal(h.routed.some(({ msg }) => msg.type === 'player.probe'), false);
    assert.equal(h.broadcasts.length, 0);
    assert.equal(h.state.capture.tabId, 7);
    h.command('translate-selection', { id: 8, url });
    await new Promise(setImmediate);
    assert.equal(h.injected.length, 1);
  });
}

test('toolbar OCR leaves audio capture in another tab running', async () => {
  const h = harness({ screenReady: false });
  await h.click({ id: 8, url: 'https://example.org/' });
  assert.equal(h.routed.at(-1).msg.type, 'screen.select');
  assert.equal(h.state.capture.tabId, 7);
  assert.equal(h.closes, 0);
  assert.equal(h.broadcasts.length, 0);
});

test('restricted pages and failed injection report an error without starting capture', async () => {
  for (const url of ['chrome://extensions', 'https://chromewebstore.google.com/']) {
    const h = harness({ screenReady: false, failInjection: true });
    h.command('translate-selection', { id: 8, url });
    await new Promise(setImmediate);
    assert.equal(h.routed.some(({ msg }) => msg.type === 'screen.select'), false);
    assert.equal(h.badges.at(-1).text, '!');
    assert.equal(h.state.capture.tabId, 7);
    assert.equal(h.broadcasts.length, 0);
  }
});

test('rapid double click serializes startup and stop without leaving capture active', async () => {
  let resume;
  const probe = new Promise((resolve) => { resume = resolve; });
  const h = harness({ capture: null, beforeProbe: () => probe });
  const tab = { id: 7, url: 'https://www.youtube.com/watch?v=video' };
  const first = h.click(tab);
  const second = h.click(tab);
  await new Promise(setImmediate);
  assert.equal(h.events.filter((event) => event === 'player.probe').length, 1);
  resume();
  await Promise.all([first, second]);
  assert.equal(h.state.capture, undefined);
  assert.equal(h.broadcasts.filter((msg) => msg.type === 'capture.start').length, 1);
  assert.equal(h.broadcasts.at(-1).type, 'capture.stop');
  assert.equal(h.closes, 1);
  assert.ok(h.events.indexOf('player.probe') < h.events.indexOf('streamId'));
  assert.equal(h.events[h.events.indexOf('streamId') + 1], 'capture.start');
  const message = h.broadcasts.find((msg) => msg.type === 'capture.start');
  assert.equal(message.paused, false);
  assert.equal(message.rate, 1);
});

test('failure to obtain a stream cleans up the offscreen document and capture state', async () => {
  const h = harness({ capture: null, failStream: true });
  await h.click({ id: 7, url: 'https://www.youtube.com/watch?v=video' });
  assert.equal(h.state.capture, undefined);
  assert.equal(h.closes, 1);
  assert.equal(h.badges.at(-1).text, '!');
  assert.equal(h.broadcasts.some((msg) => msg.type === 'capture.start'), false);
});

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
