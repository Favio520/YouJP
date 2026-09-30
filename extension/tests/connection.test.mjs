import assert from 'node:assert/strict';
import { test } from 'node:test';
import { fileURLToPath } from 'node:url';
import { runInNewContext } from 'node:vm';
import { buildSync } from 'esbuild';

const source = buildSync({
  entryPoints: [fileURLToPath(new URL('../src/connection.ts', import.meta.url))],
  bundle: true, write: false, platform: 'node', format: 'cjs',
}).outputFiles[0].text;

function harness(callbacks = {}) {
  const sockets = [], retries = [], timers = new Map();
  let timerId = 0;
  class WebSocket {
    static OPEN = 1;
    constructor() {
      this.handlers = {};
      this.readyState = 0;
      this.bufferedAmount = 0;
      this.sent = [];
      sockets.push(this);
    }
    addEventListener(type, handler) { this.handlers[type] = handler; }
    emit(type, event) { this.handlers[type]?.(event); }
    send(message) { this.sent.push(message); }
    close() { this.readyState = 3; this.emit('close', { code: 1000 }); }
    ready() {
      this.readyState = 1;
      this.emit('open');
      this.emit('message', { data: JSON.stringify({ type: 'session.ready',
        protocol_version: 2, sample_rate: 16000, frame_ms: 100, session_id: 'test' }) });
    }
  }
  const module = { exports: {} };
  runInNewContext(source, {
    module, WebSocket, ArrayBuffer,
    setTimeout: (fn) => { const id = ++timerId; timers.set(id, fn); return id; },
    clearTimeout: (id) => timers.delete(id),
  });
  const session = new module.exports.ReconnectingSession({
    url: 'ws://localhost:8770/stream', handshake: () => ({ type: 'session.start' }),
    onReady: () => callbacks.onReady?.(session),
    onMessage() {}, onFatal() {},
    onRetry: (...args) => { retries.push(args); callbacks.onRetry?.(session); },
  });
  return { session, sockets, timers, retries };
}

test('starting twice keeps one active websocket and one handshake timeout', () => {
  const h = harness();
  h.session.start();
  h.session.start();
  assert.equal(h.sockets.length, 1);
  assert.equal(h.timers.size, 1);
  h.session.stop();
  assert.equal(h.sockets[0].readyState, 3);
  assert.equal(h.timers.size, 0);
});

test('stopping from the ready callback does not leave a heartbeat behind', () => {
  const h = harness({ onReady: (session) => session.stop() });
  h.session.start();
  h.sockets[0].ready();
  assert.equal(h.timers.size, 0);
  assert.equal(h.sockets[0].readyState, 3);
});

test('stopping from the retry callback prevents a new reconnect timer', () => {
  const h = harness({ onRetry: (session) => session.stop() });
  h.session.start();
  h.sockets[0].emit('error');
  assert.equal(h.retries.length, 1);
  assert.equal(h.timers.size, 0);
  h.session.start();
  assert.equal(h.sockets.length, 1);
});

test('backpressure drops PCM but still permits control messages', () => {
  const h = harness();
  h.session.start();
  const ws = h.sockets[0];
  ws.ready();
  ws.bufferedAmount = 64_001;
  assert.equal(h.session.send(new ArrayBuffer(3200)), false);
  assert.equal(h.session.send({ type: 'control.flush', reason: 'seek', media_time_ms: 0 }), true);
  ws.bufferedAmount = 0;
  assert.equal(h.session.send(new ArrayBuffer(3200)), true);
  h.session.stop();
  assert.equal(h.timers.size, 0);
});
