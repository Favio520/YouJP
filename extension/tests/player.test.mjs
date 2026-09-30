import assert from 'node:assert/strict';
import { test } from 'node:test';
import { fileURLToPath } from 'node:url';
import { runInNewContext } from 'node:vm';
import { buildSync } from 'esbuild';

const source = buildSync({
  entryPoints: [fileURLToPath(new URL('../src/player.ts', import.meta.url))],
  bundle: true, write: false, platform: 'browser', format: 'iife', globalName: 'player',
}).outputFiles[0].text;

function harness() {
  let video = null, mutated, tick;
  const location = { search: '', pathname: '/watch' };
  const player = { classList: { contains: () => false } };
  const context = { location, URLSearchParams,
    document: { body: {}, querySelector: (selector) => selector.includes('video') ? video : player },
    window: { setInterval(fn) { tick = fn; }, clearInterval() {} },
    MutationObserver: class {
      constructor(fn) { mutated = fn; }
      observe() {} disconnect() {}
    },
  };
  runInNewContext(source, context);
  return { api: context.player, location, player,
    setVideo(next) { video = next; mutated?.(); },
    tick() { tick(); },
  };
}

test('video identity follows standard videos, Shorts and live URLs', () => {
  const h = harness();
  h.location.search = '?v=normal';
  assert.equal(h.api.currentVideoId(), 'normal');
  h.location.search = '';
  for (const prefix of ['shorts', 'live', 'embed']) {
    h.location.pathname = `/${prefix}/different`;
    assert.equal(h.api.currentVideoId(), 'different');
  }
  h.location.pathname = '/';
  assert.equal(h.api.currentVideoId(), '');
});

test('unloaded metadata and a hidden live badge do not classify VOD as live', () => {
  const h = harness();
  assert.equal(h.api.isLive({ duration: NaN }), false);
  assert.equal(h.api.isLive({ duration: 100 }), false);
  assert.equal(h.api.isLive({ duration: Infinity }), true);
  h.player.classList.contains = (name) => name === 'ytp-live';
  assert.equal(h.api.isLive({ duration: 100 }), true);
});

test('watcher reports the initial rate and pauses capture after the video is removed', () => {
  const h = harness();
  const listeners = new Set();
  h.setVideo({ currentTime: 5, paused: false, playbackRate: 2, duration: 100,
    addEventListener(name) { listeners.add(name); },
    removeEventListener(name) { listeners.delete(name); },
  });
  const warnings = [], ticks = [];
  const stop = h.api.watchPlayer({ onRateWarning: (rate) => warnings.push(rate),
    onTick: (snap) => ticks.push(snap), onFlush() {},
  });
  assert.deepEqual(warnings, [2]);
  h.tick();
  assert.equal(ticks.at(-1).paused, false);
  h.setVideo(null);
  h.tick();
  assert.equal(ticks.at(-1).paused, true);
  assert.equal(ticks.at(-1).rate, 1);
  assert.equal(listeners.size, 0);
  stop();
});
