/**
 * Prueba del AudioWorkletProcessor fuera del navegador.
 *
 * `process()` recibe bloques de 128 muestras, pero una trama son 1600: hay que
 * acumular entre llamadas, y ahí es donde viven los errores de índice. Como el
 * worklet corre en el hilo de audio, un fallo suyo se manifiesta como
 * chasquidos o como audio desplazado, nunca como una excepción visible.
 *
 *   cd extension && node --test tests/
 */

import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { test } from 'node:test';
import { fileURLToPath } from 'node:url';
import path from 'node:path';

const here = path.dirname(fileURLToPath(import.meta.url));
const source = readFileSync(path.join(here, '..', 'public', 'pcm-worklet.js'), 'utf8');

const QUANTUM = 128;
const FRAME = 1600;

/** Carga el worklet con los globales del navegador sustituidos por dobles. */
function loadProcessor() {
  let Registered = null;
  const scope = {
    AudioWorkletProcessor: class {
      constructor() {
        this.port = {
          postMessage(buffer, transfer) {
            scope.__frames.push(new Int16Array(buffer.slice(0)));
            void transfer;
          },
        };
      }
    },
    registerProcessor(_name, cls) {
      Registered = cls;
    },
    __frames: [],
  };

  const factory = new Function(
    'AudioWorkletProcessor',
    'registerProcessor',
    `${source}\nreturn registerProcessor;`,
  );
  factory(scope.AudioWorkletProcessor, scope.registerProcessor);
  return { Processor: Registered, frames: scope.__frames };
}

function feed(processor, channels, totalSamples, fill) {
  for (let offset = 0; offset < totalSamples; offset += QUANTUM) {
    const block = [];
    for (let c = 0; c < channels; c++) {
      const data = new Float32Array(QUANTUM);
      for (let i = 0; i < QUANTUM; i++) data[i] = fill(offset + i, c);
      block.push(data);
    }
    assert.equal(processor.process([block], [[]], {}), true);
  }
}

test('emite tramas de 1600 muestras y ni una más', () => {
  const { Processor, frames } = loadProcessor();
  const p = new Processor({ processorOptions: { frameSamples: FRAME } });

  // 12,5 bloques por trama: 25 bloques son exactamente dos tramas.
  feed(p, 1, QUANTUM * 25, () => 0);
  assert.equal(frames.length, 2);
  assert.equal(frames[0].length, FRAME);
});

test('no pierde ni duplica muestras al cruzar bloques', () => {
  const { Processor, frames } = loadProcessor();
  const p = new Processor({ processorOptions: { frameSamples: FRAME } });

  // Rampa determinista: cada muestra lleva su propio índice codificado.
  const value = (i) => (i % 1000) / 1000;
  feed(p, 1, QUANTUM * 25, value);

  const salida = [...frames[0], ...frames[1]];
  assert.equal(salida.length, FRAME * 2);
  for (let i = 0; i < salida.length; i++) {
    const esperado = Math.round(value(i) * 32767);
    assert.equal(salida[i], esperado, `muestra ${i} desplazada`);
  }
});

test('mezcla a mono promediando los canales', () => {
  const { Processor, frames } = loadProcessor();
  const p = new Processor({ processorOptions: { frameSamples: FRAME } });

  // Izquierdo a 1,0 y derecho a 0,0: quedarse solo con un canal daría 32767 o 0
  // en vez de la media. Con paneo real eso sería perder medio diálogo.
  feed(p, 2, QUANTUM * 13, (_i, c) => (c === 0 ? 1.0 : 0.0));

  assert.equal(frames.length, 1);
  assert.equal(frames[0][0], Math.round(0.5 * 32767));
  assert.equal(frames[0][FRAME - 1], Math.round(0.5 * 32767));
});

test('recorta sin desbordar el rango de Int16', () => {
  const { Processor, frames } = loadProcessor();
  const p = new Processor({ processorOptions: { frameSamples: FRAME } });

  feed(p, 1, QUANTUM * 13, (i) => (i % 2 === 0 ? 3.5 : -3.5));

  assert.equal(frames[0][0], 32767);
  assert.equal(frames[0][1], -32767);
});

test('sobrevive a una entrada vacía', () => {
  const { Processor, frames } = loadProcessor();
  const p = new Processor({ processorOptions: { frameSamples: FRAME } });

  // Antes de que se conecte la fuente, `process` recibe listas vacías.
  assert.equal(p.process([], [[]], {}), true);
  assert.equal(p.process([[]], [[]], {}), true);
  assert.equal(frames.length, 0);
});

test('usa la misma escala que el backend', () => {
  const { Processor, frames } = loadProcessor();
  const p = new Processor({ processorOptions: { frameSamples: FRAME } });

  // 32767, no 32768: con escalas distintas en cada lado queda un sesgo del
  // 0,003 % que hace que los tests de ida y vuelta "casi" pasen.
  feed(p, 1, QUANTUM * 13, () => 1.0);
  assert.equal(frames[0][0], 32767);
});
