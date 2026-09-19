import assert from 'node:assert/strict';
import { test } from 'node:test';
import { fileURLToPath } from 'node:url';
import { runInNewContext } from 'node:vm';
import { buildSync } from 'esbuild';

const source = buildSync({
  entryPoints: [fileURLToPath(new URL('../entrypoints/offscreen/main.ts', import.meta.url))],
  bundle: true, write: false, platform: 'browser', format: 'iife',
  alias: { '@': fileURLToPath(new URL('..', import.meta.url)) },
}).outputFiles[0].text;

function harness({ target = 'en', socketFails = false, workletFails = false } = {}) {
  const reports = [], sockets = [], contexts = [], tracks = [], nodes = [];
  let listener, settingsListener;
  const chrome = {
    runtime: {
      sendMessage: async (message) => { reports.push(message); },
      getURL: (path) => path,
      onMessage: { addListener: (fn) => { listener = fn; } },
    },
    storage: {
      local: { get: async () => ({ overlaySettings: { targetLanguage: target } }) },
      onChanged: { addListener: (fn) => { settingsListener = fn; } },
    },
  };
  class AudioContext {
    constructor() {
      this.closed = false;
      this.destination = {};
      this.audioWorklet = { addModule: async () => { if (workletFails) throw new Error('worklet failed'); } };
      contexts.push(this);
    }
    createMediaStreamSource() { return { connect() {} }; }
    async close() { this.closed = true; }
  }
  class AudioWorkletNode {
    constructor() { this.port = {}; nodes.push(this); }
    connect() {}
    disconnect() { this.disconnected = true; }
  }
  class WebSocket {
    static OPEN = 1;
    constructor() {
      this.readyState = 0;
      this.bufferedAmount = 0;
      this.handlers = {};
      this.sent = [];
      sockets.push(this);
      queueMicrotask(() => {
        if (socketFails) this.close();
        else { this.readyState = 1; this.emit('open'); }
      });
    }
    addEventListener(type, fn) { this.handlers[type] = fn; }
    emit(type, event = {}) { this.handlers[type]?.(event); }
    send(message) { this.sent.push(typeof message === 'string' ? JSON.parse(message) : message); }
    close() { this.readyState = 3; this.emit('close'); }
  }
  runInNewContext(source, {
    chrome, AudioContext, AudioWorkletNode, WebSocket, setTimeout, clearTimeout, performance,
    console: { error() {}, warn() {} },
    navigator: { mediaDevices: { getUserMedia: async () => {
      const track = { stopped: false, stop() { this.stopped = true; } };
      tracks.push(track);
      return { getTracks: () => [track] };
    } } },
  });
  return {
    reports, sockets, contexts, tracks, nodes,
    send: (message, tabId = 7) => listener(message, { tab: { id: tabId } }),
    change: (next) => { target = next; settingsListener({ overlaySettings: { newValue: { targetLanguage: next } } }, 'local'); },
  };
}

async function waitFor(predicate) {
  for (let i = 0; i < 100; i++) {
    if (predicate()) return;
    await new Promise(setImmediate);
  }
  assert.ok(predicate(), 'asynchronous capture did not reach expected state');
}

const start = { type: 'capture.start', tabId: 7, streamId: 'test', videoId: 'video',
  url: 'https://www.youtube.com/watch?v=video', isLive: false, mediaTimeMs: 1200,
  serverUrl: 'ws://localhost:8770/stream' };

test('saved target reaches handshake and a live switch reuses the socket', async () => {
  const h = harness();
  h.send(start);
  try {
    await waitFor(() => h.sockets[0]?.sent.length > 0);
    await new Promise(setImmediate);
    assert.equal(h.sockets[0].sent[0].target, 'en');
    h.change('es');
    assert.equal(h.sockets[0].sent.at(-1).type, 'session.configure');
    assert.equal(h.sockets[0].sent.at(-1).target, 'es');
    assert.equal(h.sockets.length, 1);
    h.sockets[0].emit('message', { data: '{bad json' });
    h.sockets[0].emit('message', { data: JSON.stringify({ type: 'mt.final', target: 'es', text: 'hola' }) });
    assert.equal(h.reports.at(-1).payload.text, 'hola');
  } finally {
    h.send({ type: 'capture.stop' });
    await waitFor(() => h.contexts.every((ctx) => ctx.closed));
  }
});

test('other YouTube tabs cannot change the captured clock or flush', async () => {
  const h = harness();
  h.send(start);
  try {
    await waitFor(() => h.sockets[0]?.sent.length > 0);
    await new Promise(setImmediate);
    h.send({ type: 'player.tick', mediaTimeMs: 99999 }, 8);
    h.send({ type: 'player.flush', reason: 'seek', mediaTimeMs: 99999 }, 8);
    h.nodes[0].port.onmessage({ data: new ArrayBuffer(3200) });
    assert.equal(h.sockets[0].sent.length, 2);
    const frame = new DataView(h.sockets[0].sent[1]);
    assert.equal(frame.getUint32(8, true), 1200);
    h.send({ type: 'player.flush', reason: 'seek', mediaTimeMs: 5000 }, 7);
    assert.equal(h.sockets[0].sent.at(-1).type, 'control.flush');
  } finally {
    h.send({ type: 'capture.stop' });
    await waitFor(() => h.contexts.every((ctx) => ctx.closed));
  }
});

for (const failure of ['socketFails', 'workletFails']) {
  test(`${failure}: release captured audio and both contexts`, async () => {
    const h = harness({ [failure]: true });
    h.send(start);
    await waitFor(() => h.reports.some((message) => message.status === 'error'));
    assert.ok(h.tracks.every((track) => track.stopped));
    assert.ok(h.contexts.every((ctx) => ctx.closed));
    assert.equal(h.reports.at(-1).status, 'error');
  });
}
