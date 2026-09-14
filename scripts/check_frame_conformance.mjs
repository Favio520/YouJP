/**
 * Conformidad del codec entre TypeScript y Python.
 *
 * Genera una trama con el mismo código que usa la extensión y la escribe en
 * disco; `check_frame_conformance.py` la decodifica con el código del backend y
 * comprueba que sale lo que entró.
 *
 * Merece un test propio porque un desajuste aquí no da un error: da audio que
 * suena a ruido blanco y una transcripción sin sentido. El sospechoso habitual
 * es olvidar el `true` de `setUint32(..., littleEndian)`.
 *
 *   node scripts/check_frame_conformance.mjs <fichero de salida>
 */

import { writeFileSync } from 'node:fs';
import { buildFrame, FRAME_SAMPLES, HEADER_SIZE } from './.frame-codec.mjs';

const out = process.argv[2];
if (!out) {
  console.error('uso: node check_frame_conformance.mjs <salida.bin>');
  process.exit(2);
}

// Valores elegidos para que un error de orden de bytes salte a la vista.
const HEADER = { seq: 0x01020304, mediaTimeMs: 1_117_420, captureMs: 3_400, flags: 0b10 };

// Rampa determinista de -1 a 1 sobre una trama completa.
const pcm = new Int16Array(FRAME_SAMPLES);
for (let i = 0; i < FRAME_SAMPLES; i++) {
  const s = (i / (FRAME_SAMPLES - 1)) * 2 - 1;
  pcm[i] = Math.round(Math.max(-1, Math.min(1, s)) * 32767);
}

const frame = buildFrame(pcm.buffer, HEADER);
writeFileSync(out, Buffer.from(frame));

console.log(
  JSON.stringify({
    bytes: frame.byteLength,
    header_size: HEADER_SIZE,
    samples: FRAME_SAMPLES,
    ...HEADER,
    first_sample: pcm[0],
    last_sample: pcm[FRAME_SAMPLES - 1],
  }),
);
