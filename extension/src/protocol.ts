/** Wire types are generated from protocol/schema.json; only the codec lives here. */
export * from './generated/protocol';
export type { SensePayload as Sense, DictPayload as DictEntry, ErrorMessage as ServerError } from './generated/protocol';
import { AUDIO_VERSION, SAMPLE_RATE, FRAME_MS, HEADER_SIZE, MAGIC } from './generated/protocol';

export const FRAME_SAMPLES = (SAMPLE_RATE * FRAME_MS) / 1000;

export interface FrameHeader {
  seq: number;
  mediaTimeMs: number;
  captureMs: number;
  flags: number;
}

/** 16-byte little-endian header followed by mono Int16 PCM. */
export function buildFrame(pcm: ArrayBuffer, header: FrameHeader): ArrayBuffer {
  const out = new ArrayBuffer(HEADER_SIZE + pcm.byteLength);
  const view = new DataView(out);
  view.setUint8(0, MAGIC);
  view.setUint8(1, AUDIO_VERSION);
  view.setUint8(2, header.flags);
  view.setUint8(3, 0);
  view.setUint32(4, header.seq >>> 0, true);
  view.setUint32(8, Math.max(0, Math.round(header.mediaTimeMs)) >>> 0, true);
  view.setUint32(12, Math.max(0, Math.round(header.captureMs)) >>> 0, true);
  new Uint8Array(out, HEADER_SIZE).set(new Uint8Array(pcm));
  return out;
}
