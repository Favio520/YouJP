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

const { DEFAULT_SETTINGS, normalizeSettings, saveSettings, loadSettings } = load('../src/settings.ts');
const { SettingsPanel } = load('../src/ui/SettingsPanel.tsx');

test('settings language migrates safely and is independent of the translation target', () => {
  for (const value of [undefined, 'fr', null, 42]) {
    assert.equal(normalizeSettings({ settingsLanguage: value }).settingsLanguage, 'es');
  }
  const settings = normalizeSettings({ settingsLanguage: 'en', targetLanguage: 'es' });
  assert.equal(settings.settingsLanguage, 'en');
  assert.equal(settings.targetLanguage, 'es');
});

test('settings language survives a storage round trip', async () => {
  let stored = {};
  globalThis.chrome = { storage: { local: {
    async set(value) { stored = value; }, async get() { return stored; },
  } } };
  try {
    await saveSettings({ ...DEFAULT_SETTINGS, settingsLanguage: 'en' });
    assert.equal((await loadSettings()).settingsLanguage, 'en');
  } finally { delete globalThis.chrome; }
});

test('English settings translate labels, tooltips and accessibility text', () => {
  const html = renderToStaticMarkup(React.createElement(SettingsPanel, {
    settings: { ...DEFAULT_SETTINGS, settingsLanguage: 'en', position: { x: 50, y: 50 } },
    onChange() {}, onClose() {},
    video: { phase: 'none', progress: 0, source: '', enabled: true, message: '', live: false }, onVideoAction() {},
  }));
  for (const label of ['Interface language', 'Subtitle settings', 'Close', 'Japanese text size',
    'Translate into', 'Translation only', 'Reset to bottom center', 'All kanji']) {
    assert.ok(html.includes(label), label);
  }
  assert.doesNotMatch(html, /Ajustes|Cerrar|Solo traducción|Restablecer|Siempre/);
});

test('language choice updates immediately and reset preserves the selected language', () => {
  const changes = [];
  const tree = SettingsPanel({
    settings: { ...DEFAULT_SETTINGS, settingsLanguage: 'en' },
    onChange(patch) { changes.push(patch); }, onClose() {},
    video: { phase: 'none', progress: 0, source: '', enabled: true, message: '', live: false }, onVideoAction() {},
  });
  const visit = (node) => {
    if (!React.isValidElement(node)) return;
    if (node.props.value === 'en' && node.props.onPick) node.props.onPick('es');
    if (node.type === 'button' && node.props['aria-label'] === 'Reset settings') node.props.onClick();
    React.Children.forEach(node.props.children, visit);
  };
  visit(tree);
  assert.ok(changes.some((change) => JSON.stringify(change) === JSON.stringify({ settingsLanguage: 'es' })));
  assert.ok(changes.some((change) => JSON.stringify(change) === JSON.stringify({ ...DEFAULT_SETTINGS, settingsLanguage: 'en' })));
});

test('the video card names the action for every state', () => {
  const render = (video, language = 'es') => renderToStaticMarkup(React.createElement(SettingsPanel, {
    settings: { ...DEFAULT_SETTINGS, settingsLanguage: language },
    onChange() {}, onClose() {}, onVideoAction() {},
    video: { phase: 'none', progress: 0, source: '', enabled: true, message: '', live: false, ...video },
  }));
  assert.match(render({}), />Traducir el vídeo</);
  const working = render({ phase: 'working', progress: 0.42, source: 'captions' });
  assert.match(working, />Detener</);
  assert.match(working, /42 %/);
  assert.match(render({ phase: 'ready', enabled: true }), />Apagar subtítulos</);
  assert.match(render({ phase: 'ready', enabled: false }), />Encender subtítulos</);
  assert.match(render({ phase: 'error', message: 'Cancelado.' }, 'en'), />Try again</);
  const live = render({ live: true, phase: 'ready' });
  assert.doesNotMatch(live, /youjp-video-action/);
});
