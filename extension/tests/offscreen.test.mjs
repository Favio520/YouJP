import assert from 'node:assert/strict';
import { test } from 'node:test';
import { fileURLToPath } from 'node:url';
import { runInNewContext } from 'node:vm';
import { buildSync } from 'esbuild';
import { readFileSync } from 'node:fs';

const protocol = JSON.parse(readFileSync(new URL('../../protocol/schema.json', import.meta.url)))['x-youjp'];
const source = buildSync({
  entryPoints: [fileURLToPath(new URL('../entrypoints/offscreen/main.ts', import.meta.url))],
  bundle: true, write: false, platform: 'browser', format: 'iife',
  alias: { '@': fileURLToPath(new URL('..', import.meta.url)) },
}).outputFiles[0].text;

function harness({ target = 'en', socketFails = false, workletFails = false,
    readyVersion = protocol.protocol_version, autoReady = true, beforeWorkletReady,
    beforeStreamReady } = {}) {
  const reports = [], sockets = [], contexts = [], tracks = [], nodes = [];
  let listener, now = 0, timerId = 0;
  const timers = new Map();
  const schedule = (fn, delay) => {
    const id = ++timerId;
    timers.set(id, { at: now + delay, fn });
    return id;
  };
  const chrome = {
    runtime: {
      id: 'maigpfdicmnmilihmhnfalbcchkpobab',
      sendMessage: async (message) => {
        if (message.type === 'settings.get') return { targetLanguage: target };
        reports.push(message);
      },
      getURL: (path) => path,
      onMessage: { addListener: (fn) => { listener = fn; } },
    },
  };
  class AudioContext {
    constructor() {
      this.closed = false;
      this.destination = {};
      this.audioWorklet = { addModule: async () => {
        if (workletFails) throw new Error('worklet failed');
        await beforeWorkletReady?.();
      } };
      contexts.push(this);
    }
    createMediaStreamSource() { return { connect() {} }; }
    async close() { this.closed = true; }
    async resume() { this.resumed = true; }
  }
  class AudioWorkletNode {
    constructor() { this.port = { messages: [], postMessage(message) { this.messages.push(message); } }; nodes.push(this); }
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
      this.createdAt = now;
      sockets.push(this);
      queueMicrotask(() => {
        if (this.readyState === 3) return;
        if (socketFails) this.close();
        else { this.readyState = 1; this.emit('open'); }
      });
    }
    addEventListener(type, fn) { this.handlers[type] = fn; }
    emit(type, event = {}) { this.handlers[type]?.(event); }
    message(message) { this.emit('message', { data: JSON.stringify(message) }); }
    send(message) {
      const parsed = typeof message === 'string' ? JSON.parse(message) : message;
      this.sent.push(parsed);
      if (parsed.type === 'session.start' && autoReady) {
        queueMicrotask(() => this.message({
          type: 'session.ready', protocol_version: readyVersion, app_version: '1.3.0',
          session_id: `session-${sockets.length}`, sample_rate: 16000, frame_ms: 100,
          asr_model: 'test', device: 'cpu', compute_type: 'int8', target: parsed.target,
        }));
      }
    }
    close() { this.readyState = 3; this.emit('close'); }
  }
  class FakeDate extends Date { static now() { return now; } }
  runInNewContext(source, {
    chrome, AudioContext, AudioWorkletNode, WebSocket,
    setTimeout: schedule, clearTimeout: (id) => timers.delete(id), Date: FakeDate,
    performance: { now: () => now }, console: { error() {}, warn() {} },
    navigator: { mediaDevices: { getUserMedia: async () => {
      await beforeStreamReady?.();
      const track = { stopped: false, handlers: {}, stop() { this.stopped = true; },
        addEventListener(type, handler) { this.handlers[type] = handler; } };
      tracks.push(track);
      return { getTracks: () => [track] };
    } } },
  });
  const send = (message, tabId = 7) => listener(message, {
    id: chrome.runtime.id,
    ...(message.type.startsWith('player.') ? { tab: { id: tabId } } : {}),
  }, () => {});
  const ping = () => new Promise((resolve) => {
    listener({ type: 'offscreen.ping' }, { id: chrome.runtime.id }, resolve);
  });
  return {
    reports, sockets, contexts, tracks, nodes, timers, send, ping,
    receive: (...args) => listener(...args),
    frame: () => nodes[0].port.onmessage({ data: new ArrayBuffer(3200) }),
    change: (next) => {
      target = next;
      listener({ type: 'settings.changed', settings: { targetLanguage: next } }, { id: chrome.runtime.id }, () => {});
    },
    async advance(ms) {
      const until = now + ms;
      for (;;) {
        const next = [...timers.entries()].filter(([, t]) => t.at <= until).sort((a, b) => a[1].at - b[1].at)[0];
        if (!next) break;
        timers.delete(next[0]);
        now = next[1].at;
        next[1].fn();
        await new Promise(setImmediate);
      }
      now = until;
      await new Promise(setImmediate);
    },
    async stop() {
      send({ type: 'capture.stop' });
      await waitFor(() => contexts.every((ctx) => ctx.closed));
      assert.equal(timers.size, 0, 'stop must cancel retry and heartbeat timers');
    },
  };
}

test('offscreen announces readiness with only chrome.runtime available', async () => {
  const h = harness();
  assert.equal((await h.ping()).ready, true);
});

async function waitFor(predicate) {
  for (let i = 0; i < 100; i++) {
    if (predicate()) return;
    await new Promise(setImmediate);
  }
  assert.ok(predicate(), 'asynchronous capture did not reach expected state');
}
async function started(h) {
  h.send(start);
  await waitFor(() => h.reports.some((r) => r.status === 'running'));
}
const start = { type: 'capture.start', tabId: 7, streamId: 'test', videoId: 'video',
  url: 'https://www.youtube.com/watch?v=video', isLive: false, mediaTimeMs: 1200,
  serverUrl: 'ws://localhost:8770/stream' };
const final = { type: 'asr.final', segment_id: 1, text: '猫', media_start_ms: 1000,
  media_end_ms: 1200, reason: 'punctuation', latency_ms: 100 };

test('saved target and protocol reach handshake; settings reuse the socket', async () => {
  const h = harness();
  try {
    await started(h);
    const ws = h.sockets[0];
    assert.equal(ws.sent[0].target, 'en');
    assert.equal(ws.sent[0].protocol_version, protocol.protocol_version);
    h.change('es');
    assert.equal(ws.sent.at(-1).type, 'session.configure');
    assert.equal(ws.sent.at(-1).target, 'es');
    assert.equal(h.sockets.length, 1);
    ws.emit('message', { data: '{bad json' });
    ws.message(final);
    ws.message({ type: 'mt.final', segment_id: 1, target: 'es', text: 'gato' });
    assert.equal(h.reports.at(-1).payload.text, 'gato');
  } finally { await h.stop(); }
});

test('target changed while audio initializes is included in the handshake', async () => {
  const h = harness({ beforeWorkletReady: () => h.change('es') });
  try {
    await started(h);
    assert.equal(h.sockets[0].sent[0].target, 'es');
  } finally { await h.stop(); }
});

test('target changed during handshake is applied once the backend is ready', async () => {
  const h = harness({ autoReady: false });
  try {
    h.send(start);
    await waitFor(() => h.sockets[0]?.sent.length > 0);
    h.change('es');
    h.sockets[0].message({ type: 'session.ready', protocol_version: protocol.protocol_version,
      session_id: 'test', sample_rate: 16000, frame_ms: 100 });
    assert.equal(h.sockets[0].sent.at(-1).type, 'session.configure');
    assert.equal(h.sockets[0].sent.at(-1).target, 'es');
  } finally { await h.stop(); }
});

test('other tabs cannot move the clock; paused or accelerated audio is not sent', async () => {
  const h = harness();
  try {
    await started(h);
    h.send({ type: 'player.tick', mediaTimeMs: 99999, paused: false, rate: 1, videoId: 'video' }, 8);
    h.send({ type: 'player.flush', reason: 'seek', mediaTimeMs: 99999 }, 8);
    h.frame();
    const frame = new DataView(h.sockets[0].sent.at(-1));
    assert.equal(frame.getUint32(8, true), 1200);
    h.send({ type: 'player.flush', reason: 'seek', mediaTimeMs: 5000 });
    assert.equal(h.sockets[0].sent.at(-1).type, 'control.flush');
    assert.equal(h.nodes[0].port.messages.at(-1).type, 'reset');
    for (const state of [{ paused: true, rate: 1 }, { paused: false, rate: 1.5 }]) {
      h.send({ type: 'player.tick', mediaTimeMs: 5000, videoId: 'video', ...state });
      const before = h.sockets[0].sent.length;
      h.frame();
      assert.equal(h.sockets[0].sent.length, before);
    }
  } finally { await h.stop(); }
});

test('restart restores clock/target, discards offline audio and separates segment IDs', async () => {
  const h = harness();
  try {
    await started(h);
    const first = h.sockets[0];
    first.message(final);
    const oldId = h.reports.at(-1).payload.segment_id;
    first.close();
    assert.equal(h.reports.at(-1).status, 'reconnecting');
    const before = first.sent.length;
    h.frame();
    assert.equal(first.sent.length, before);
    assert.ok(h.contexts.every((ctx) => !ctx.closed));
    h.send({ type: 'player.tick', mediaTimeMs: 9000, paused: false, rate: 1, videoId: 'video' });
    h.change('es');
    await h.advance(1000);
    const second = h.sockets[1];
    assert.equal(second.sent[0].media_time_ms, 9000);
    assert.equal(second.sent[0].target, 'es');
    assert.equal(h.tracks.length, 1, 'reconnect does not recapture tab audio');
    const reportCount = h.reports.length;
    first.message({ type: 'mt.final', segment_id: 1, text: 'stale' });
    assert.equal(h.reports.length, reportCount);
    second.message(final);
    const newId = h.reports.at(-1).payload.segment_id;
    assert.notEqual(newId, oldId);
    second.message({ type: 'mt.final', segment_id: 1, text: 'nuevo', target: 'es' });
    assert.equal(h.reports.at(-1).payload.segment_id, newId);
    h.frame();
    const frame = new DataView(second.sent.at(-1));
    assert.equal(frame.getUint32(4, true), 0);
    assert.equal(frame.getUint32(8, true), 9000);
    assert.equal(frame.getUint8(2) & 2, 2);
  } finally { await h.stop(); }
});

test('offline initial start backs off to 30 seconds and stop cancels reconnects', async () => {
  const h = harness({ socketFails: true });
  h.send(start);
  try {
    await waitFor(() => h.reports.some((m) => m.status === 'reconnecting'));
    await h.advance(61_000);
    assert.deepEqual(h.sockets.map((s) => s.createdAt), [0, 1000, 3000, 7000, 15000, 31000, 61000]);
  } finally { await h.stop(); }
  const count = h.sockets.length;
  await h.advance(120_000);
  assert.equal(h.sockets.length, count);
  assert.ok(h.tracks.every((track) => track.stopped));
});

test('socket open without session.ready cannot send audio and times out', async () => {
  const h = harness({ autoReady: false });
  h.send(start);
  try {
    await waitFor(() => h.sockets[0]?.sent.length > 0);
    h.frame();
    assert.equal(h.sockets[0].sent.length, 1);
    await h.advance(10_000);
    assert.equal(h.reports.at(-1).status, 'reconnecting');
  } finally { await h.stop(); }
});

test('silent half-open connection is detected by heartbeat', async () => {
  const h = harness();
  try {
    await started(h);
    await h.advance(15_000);
    assert.equal(h.reports.at(-1).status, 'reconnecting');
    assert.ok(h.sockets[0].sent.some((m) => m.type === 'ping'));
    await h.advance(1000);
    assert.equal(h.sockets.length, 2);
  } finally { await h.stop(); }
});

test('stop during handshake ignores a late ready and leaves no resources or retries', async () => {
  const h = harness({ autoReady: false });
  h.send(start);
  await waitFor(() => h.sockets[0]?.sent.length > 0);
  await h.stop();
  h.sockets[0].message({ type: 'session.ready', protocol_version: protocol.protocol_version,
    session_id: 'late', sample_rate: 16000, frame_ms: 100 });
  await h.advance(60_000);
  assert.equal(h.sockets.length, 1);
  assert.ok(!h.reports.some((m) => m.status === 'running'));
});

test('backend fatal error closes capture without retrying', async () => {
  const h = harness({ autoReady: false });
  h.send(start);
  await waitFor(() => h.sockets[0]?.sent.length > 0);
  h.sockets[0].message({ type: 'error', code: 'protocol_mismatch', fatal: true, message: 'Actualiza YouJP' });
  await waitFor(() => h.reports.some((m) => m.status === 'error'));
  assert.equal(h.reports.at(-1).detail, 'Actualiza YouJP');
  assert.ok(h.tracks.every((track) => track.stopped));
  assert.equal(h.timers.size, 0);
});

test('rejected origin explains the extension ID and never retries', async () => {
  const h = harness({ autoReady: false });
  h.send(start);
  await waitFor(() => h.sockets[0]?.sent.length > 0);
  h.sockets[0].readyState = 3;
  h.sockets[0].emit('close', { code: 1008 });
  await waitFor(() => h.reports.some((m) => m.status === 'error'));
  const { detail } = h.reports.at(-1);
  assert.match(detail, /maigpfdicmnmilihmhnfalbcchkpobab/);
  assert.match(detail, /YOUJP_ALLOWED_EXTENSION_IDS/);
  assert.ok(h.tracks.every((track) => track.stopped));
  assert.equal(h.timers.size, 0);
  await h.advance(120_000);
  assert.equal(h.sockets.length, 1);
});

for (const readyVersion of [1, 999, null]) {
  test(`incompatible server ${readyVersion} releases audio and never retries`, async () => {
    const h = harness({ readyVersion });
    h.send(start);
    await waitFor(() => h.reports.some((m) => m.status === 'error'));
    assert.ok(h.contexts.every((ctx) => ctx.closed));
    assert.ok(h.tracks.every((track) => track.stopped));
    assert.equal(h.timers.size, 0);
    await h.advance(120_000);
    assert.equal(h.sockets.length, 1);
  });
}

test('worklet failure releases both contexts and captured audio', async () => {
  const h = harness({ workletFails: true });
  h.send(start);
  await waitFor(() => h.reports.some((message) => message.status === 'error'));
  assert.ok(h.tracks.every((track) => track.stopped));
  assert.ok(h.contexts.every((ctx) => ctx.closed));
  assert.equal(h.timers.size, 0);
});

test('initial paused state blocks audio before the first player tick', async () => {
  const h = harness();
  try {
    h.send({ ...start, paused: true, rate: 1 });
    await waitFor(() => h.reports.some((r) => r.status === 'running'));
    assert.ok(h.contexts.every((ctx) => ctx.resumed));
    const before = h.sockets[0].sent.length;
    h.frame();
    assert.equal(h.sockets[0].sent.length, before);
  } finally { await h.stop(); }
});

test('stop during getUserMedia discards its late stream without starting audio or reconnects', async () => {
  let resolveStream;
  let opening = false;
  const pending = new Promise((resolve) => { resolveStream = resolve; });
  const h = harness({ beforeStreamReady: () => { opening = true; return pending; } });
  h.send(start);
  await waitFor(() => opening);
  h.send({ type: 'capture.stop' });
  resolveStream();
  await waitFor(() => h.tracks.length === 1 && h.tracks[0].stopped);
  assert.equal(h.sockets.length, 0);
  assert.equal(h.contexts.length, 0);
  assert.equal(h.timers.size, 0);
});

test('stop during worklet startup releases audio without opening a socket', async () => {
  let resolveWorklet;
  const pending = new Promise((resolve) => { resolveWorklet = resolve; });
  const h = harness({ beforeWorkletReady: () => pending });
  h.send(start);
  await waitFor(() => h.contexts.length === 2);
  h.send({ type: 'capture.stop' });
  resolveWorklet();
  await waitFor(() => h.contexts.every((ctx) => ctx.closed));
  assert.ok(h.tracks.every((track) => track.stopped));
  assert.equal(h.sockets.length, 0);
  assert.equal(h.timers.size, 0);
});

for (const failure of ['ended', 'processor']) {
  test(`${failure} failure releases resources and reports the lost capture`, async () => {
    const h = harness();
    await started(h);
    if (failure === 'ended') h.tracks[0].handlers.ended();
    else h.nodes[0].onprocessorerror();
    await waitFor(() => h.reports.some((r) => r.status === 'error'));
    assert.ok(h.contexts.every((ctx) => ctx.closed));
    assert.ok(h.tracks.every((track) => track.stopped));
    assert.equal(h.timers.size, 0);
  });
}

test('content scripts and other extensions cannot start or stop capture', async () => {
  const h = harness();
  await started(h);
  h.receive({ type: 'capture.stop' }, { id: 'other-extension' }, () => {});
  h.receive({ type: 'capture.stop' }, { id: 'maigpfdicmnmilihmhnfalbcchkpobab', tab: { id: 7 } }, () => {});
  await new Promise(setImmediate);
  assert.ok(h.contexts.every((ctx) => !ctx.closed));
  await h.stop();
});

test('video change flushes old audio and adopts live state for new frames', async () => {
  const h = harness();
  try {
    await started(h);
    const ws = h.sockets[0];
    ws.message(final);
    h.send({ type: 'player.tick', mediaTimeMs: 0, paused: false, rate: 1, videoId: 'next', isLive: true });
    assert.equal(ws.sent.at(-1).type, 'control.flush');
    assert.equal(h.nodes[0].port.messages.at(-1).type, 'reset');
    const before = h.reports.length;
    ws.message({ type: 'mt.final', segment_id: 1, text: 'old video', target: 'es' });
    assert.equal(h.reports.length, before);
    h.frame();
    const frame = new DataView(ws.sent.at(-1));
    assert.equal(frame.getUint8(2) & 3, 3);
    assert.equal(frame.getUint32(8, true), 0);
  } finally { await h.stop(); }
});
