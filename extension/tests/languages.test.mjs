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

const { DEFAULT_SETTINGS, normalizeSettings, toCssVars } = load('../src/settings.ts');
const { SettingsPanel } = load('../src/ui/SettingsPanel.tsx');
const { WordCard } = load('../src/ui/WordCard.tsx');
const { TranscriptPanel } = load('../src/ui/TranscriptPanel.tsx');

test('legacy Spanish-only settings migrate while keeping layout', () => {
  const settings = normalizeSettings({ esSize: 30, languages: 'es', position: { x: 40, y: 60 } });
  assert.equal(settings.targetLanguage, 'es');
  assert.equal(settings.translationSize, 30);
  assert.equal(settings.languages, 'translation');
  assert.deepEqual(settings.position, { x: 40, y: 60 });
  assert.equal(toCssVars(settings)['--youjp-es-size'], '30px');
  assert.equal('esSize' in settings, false);
});

test('English and visibility settings are independent', () => {
  const settings = normalizeSettings({ targetLanguage: 'en', languages: 'ja', translationSize: 25, esSize: 30 });
  assert.equal(settings.targetLanguage, 'en');
  assert.equal(settings.languages, 'ja');
  assert.equal(settings.translationSize, 25);
});

test('missing or unsupported target uses Spanish', () => {
  for (const stored of [null, undefined, {}, { targetLanguage: 'fr' }]) {
    assert.equal(normalizeSettings(stored).targetLanguage, 'es');
  }
});

test('settings panel offers both targets and neutral display controls', () => {
  const html = renderToStaticMarkup(React.createElement(SettingsPanel, {
    settings: { ...DEFAULT_SETTINGS, targetLanguage: 'en' }, onChange() {}, onClose() {},
  }));
  assert.match(html, /Español/);
  assert.match(html, /English/);
  assert.match(html, /Solo traducción/);
  assert.doesNotMatch(html, /Solo español|Tamaño del español/);
});

const token = {
  surface: '猫', lemma: '猫', kana: 'ねこ', romaji: 'neko', chain: [], pos_label: '',
  entry: { headword: '猫', common: true, freq_rank: null,
    senses: [{ pos: [], glosses_es: ['gato'], glosses_en: ['cat'] }] },
};
test('dictionary follows target language', () => {
  const render = (target) => renderToStaticMarkup(React.createElement(WordCard, { token, target, onClose() {} }));
  assert.match(render('es'), />gato</);
  assert.match(render('en'), />cat</);
  assert.doesNotMatch(render('en'), />gato</);
});

test('transcript retains and labels the language of each earlier translation', () => {
  const lines = [
    { id: 1, ja: '猫', translation: 'gato', target: 'es', tokens: [], mediaStartMs: 1000 },
    { id: 2, ja: '犬', translation: 'dog', target: 'en', tokens: [], mediaStartMs: 2000 },
  ];
  const html = renderToStaticMarkup(React.createElement(TranscriptPanel, {
    lines, position: null, showTranslation: true, onMove() {}, onResetPosition() {}, onSeek() {}, onClose() {},
  }));
  assert.match(html, /lang="es"/);
  assert.match(html, /lang="en"/);
  assert.match(html, /gato/);
  assert.match(html, /dog/);
});
