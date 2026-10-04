import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { test } from 'node:test';
import { fileURLToPath } from 'node:url';
import { buildSync } from 'esbuild';
import React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';

const require = createRequire(import.meta.url);
function load(relative) {
  const result = buildSync({
    entryPoints: [fileURLToPath(new URL(relative, import.meta.url))],
    bundle: true, write: false, platform: 'node', format: 'cjs',
    external: ['react', 'react/jsx-runtime'], jsx: 'automatic',
  });
  const module = { exports: {} };
  new Function('require', 'module', 'exports', result.outputFiles[0].text)(require, module, module.exports);
  return module.exports;
}

const { DEFAULT_SETTINGS, normalizeSettings } = load('../src/settings.ts');
const { SettingsPanel } = load('../src/ui/SettingsPanel.tsx');
const { grammarClass } = load('../src/ui/Subtitle.tsx');
const { Icon } = load('../src/ui/Icon.tsx');
const { ICONS } = load('../src/ui/iconShapes.ts');

const panel = (settings) => renderToStaticMarkup(React.createElement(SettingsPanel, {
  settings, onChange() {}, onClose() {}, onVideoAction() {},
  video: { phase: 'none', progress: 0, source: '', enabled: true, message: '', live: false },
}));

test('the ribbon style is the default and unknown values fall back to it', () => {
  assert.equal(DEFAULT_SETTINGS.skin, 'ribbon');
  for (const value of [undefined, null, 'neon', 7]) assert.equal(normalizeSettings({ skin: value }).skin, 'ribbon');
  assert.equal(normalizeSettings({ skin: 'paper' }).skin, 'paper');
  assert.equal(normalizeSettings({ skin: 'grammar' }).skin, 'grammar');
});

test('settings saved before styles existed keep their values and get the ribbon', () => {
  const migrated = normalizeSettings({ jaSize: 36, backdrop: 'solid' });
  assert.equal(migrated.skin, 'ribbon');
  assert.equal(migrated.jaSize, 36);
  assert.equal(migrated.backdrop, 'solid');
});

test('the panel lists the three styles and offers the background except for paper', () => {
  const ribbon = panel({ ...DEFAULT_SETTINGS, skin: 'ribbon' });
  for (const name of ['Cinta', 'Papel', 'Gramática']) assert.ok(ribbon.includes(name), name);
  assert.ok(ribbon.includes('Fondo'));
  assert.doesNotMatch(panel({ ...DEFAULT_SETTINGS, skin: 'paper' }), />Fondo</);
  assert.ok(panel({ ...DEFAULT_SETTINGS, skin: 'grammar' }).includes('Fondo'));
  assert.match(panel({ ...DEFAULT_SETTINGS, settingsLanguage: 'en' }), /Ribbon/);
});

test('grammar categories come from the analysis, not from guesses', () => {
  const kind = (pos) => grammarClass({ pos });
  assert.equal(kind(['名詞']), 'n');
  assert.equal(kind(['動詞']), 'v');
  assert.equal(kind(['形容詞']), 'adj');
  assert.equal(kind(['副詞']), 'adv');
  assert.equal(kind(['助詞']), 'p');
  assert.equal(kind(['助動詞']), 'aux');
  assert.equal(kind(['記号']), 'o');
  assert.equal(kind([]), 'o');
});

test('every icon has shapes and renders as an svg', () => {
  for (const name of ['history', 'settings', 'move', 'close', 'reset', 'translate']) {
    assert.ok(ICONS[name].length > 0, name);
    const html = renderToStaticMarkup(React.createElement(Icon, { name }));
    assert.match(html, /^<svg[^>]*viewBox="0 0 24 24"/);
  }
});
