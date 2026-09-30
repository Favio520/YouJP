import assert from 'node:assert/strict';
import { test } from 'node:test';
import { mkdtempSync, rmSync, writeFileSync } from 'node:fs';
import { createRequire } from 'node:module';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { buildSync } from 'esbuild';

// El historial se pinta en el servidor de React: basta para comprobar la
// estructura sin navegador. CJS porque react-dom/server usa require internos.
const root = fileURLToPath(new URL('..', import.meta.url));
const bundle = buildSync({
  stdin: {
    contents: `
      import { createElement } from 'react';
      import { renderToStaticMarkup } from 'react-dom/server';
      import { TranscriptPanel } from './src/ui/TranscriptPanel';
      import { WordInspector } from './src/ui/WordInspector';
      export const render = (props) => renderToStaticMarkup(createElement(TranscriptPanel, props));
      export const renderInspector = (props) => renderToStaticMarkup(createElement(WordInspector, props));
    `,
    resolveDir: root, loader: 'tsx',
  },
  bundle: true, write: false, platform: 'node', format: 'cjs', jsx: 'automatic',
  alias: { '@': root }, logLevel: 'silent',
}).outputFiles[0].text;
const dir = mkdtempSync(join(tmpdir(), 'youjp-transcript-'));
const file = join(dir, 'transcript.cjs');
writeFileSync(file, bundle);
const { render, renderInspector } = createRequire(import.meta.url)(file);
rmSync(dir, { recursive: true, force: true });

const entry = {
  id: 1, headword: '勉強', readings: ['べんきょう'], common: true, freq_rank: 1,
  senses: [{ pos: ['n', 'vs'], glosses_es: ['estudio'], glosses_en: ['study'] }],
};
const token = (i, surface, clickable, extra = {}) => ({
  i, span: [0, 0], surface, lemma: surface, kana: '', romaji: '', pos: [], pos_label: '',
  chain: [], clickable, entry: clickable ? entry : null, ...extra,
});
const lines = [
  { id: 10, ja: '勉強する', translation: 'estudiar', target: 'es', mediaStartMs: 65_000,
    tokens: [token(0, '勉強', true, { kana: 'べんきょう' }), token(1, 'する', false)] },
  { id: 11, ja: '勉強だ', translation: '', target: null, mediaStartMs: 70_000,
    tokens: [token(0, '勉強', true), token(1, 'だ', false)] },
];
const props = (extra = {}) => ({
  lines, position: null, onMove() {}, onResetPosition() {}, onSeek() {}, onClose() {},
  showTranslation: true, textSize: 16, furigana: 'off', selected: null, onSelect() {},
  ...extra,
});

test('English interface also translates history and dictionary independently of gloss language', () => {
  const html = render(props({ language: 'en' }));
  assert.match(html, /Session history/);
  assert.doesNotMatch(html, /Historial|Cerrar|frases/);
  const inspector = renderInspector({ token: lines[0].tokens[0], target: 'es', language: 'en',
    position: null, onMove() {}, onResetPosition() {}, onClose() {} });
  assert.match(inspector, /Dictionary/);
  assert.match(inspector, /Definition of 勉強/);
  assert.match(inspector, /Meaning/);
  assert.match(inspector, /estudio/);
  assert.doesNotMatch(inspector, /Consulta de palabra|Significado|sustantivo/);
});

function assertNoNestedButtons(html) {
  let depth = 0;
  for (const [tag] of html.matchAll(/<\/?button\b/g)) {
    depth += tag.startsWith('</') ? -1 : 1;
    assert.ok(depth <= 1, 'un botón no puede contener otro');
  }
}

test('history words are clickable like live subtitles, without nested buttons', () => {
  const html = render(props());
  assert.equal(html.match(/class="youjp-token"/g)?.length, 2, 'una palabra pulsable por frase');
  assert.equal(html.match(/youjp-token youjp-token--plain/g)?.length, 2, 'las partículas no se pulsan');
  assert.match(html, /<button[^>]*class="youjp-transcript-time"[^>]*>1:05<\/button>/);
  assertNoNestedButtons(html);
  assert.doesNotMatch(html, /youjp-card/, 'sin selección no hay tarjeta');
});

test('selected history word opens a separate inspector and highlights only that line', () => {
  const selected = { lineId: 11, token: lines[1].tokens[0], from: 'transcript' };
  const html = render(props({ selected }));
  assert.doesNotMatch(html, /youjp-card/, 'la tarjeta no ocupa espacio en el historial');
  assert.equal(html.match(/youjp-token--active/g)?.length, 1, 'misma posición en otra frase no se resalta');
  assert.ok(html.indexOf('youjp-token--active') > html.indexOf('>1:10<'), 'se resalta en la frase 11');
  const inspector = renderInspector({ token: selected.token, target: 'es', position: null,
    onMove() {}, onResetPosition() {}, onClose() {} });
  assert.match(inspector, /aria-label="Consulta de palabra"/);
  assert.match(inspector, /aria-label="Definición de 勉強"/);
  assert.match(inspector, /Diccionario/);
  assertNoNestedButtons(html);
});

test('a word selected in the live subtitles does not open a card in the history', () => {
  const selected = { lineId: 11, token: lines[1].tokens[0], from: 'subtitles' };
  const html = render(props({ selected }));
  assert.doesNotMatch(html, /youjp-transcript-card/);
  assert.doesNotMatch(html, /youjp-token--active/);
});

test('history honours the furigana setting', () => {
  assert.doesNotMatch(render(props()), /<ruby>/);
  assert.match(render(props({ furigana: 'all' })), /<ruby>勉強<rt>べんきょう<\/rt><\/ruby>/);
});

test('history text size is applied to its own panel', () => {
  assert.match(render(props({ textSize: 25 })), /--youjp-transcript-size:25px/);
});
