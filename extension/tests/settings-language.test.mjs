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
  }));
  for (const label of ['Settings language', 'Subtitle settings', 'Close', 'Japanese text size',
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
  });
  const visit = (node) => {
    if (!React.isValidElement(node)) return;
    if (node.props.value === 'en' && node.props.onPick) node.props.onPick('es');
    if (node.type === 'button' && node.props.children === 'Reset') node.props.onClick();
    React.Children.forEach(node.props.children, visit);
  };
  visit(tree);
  assert.deepEqual(changes[0], { settingsLanguage: 'es' });
  assert.deepEqual(changes[1], { ...DEFAULT_SETTINGS, settingsLanguage: 'en' });
});
