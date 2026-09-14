/**
 * Recoge el audio del grafo y lo entrega en tramas de tamaño fijo como Int16.
 *
 * Corre en el hilo de audio, así que aquí no se puede hacer nada que asigne
 * memoria de forma imprevisible ni que bloquee: un fallo de tiempo real aquí se
 * oye como un chasquido en la pestaña del usuario.
 *
 * Tres detalles que importan:
 *
 * 1. `process()` recibe bloques de 128 muestras. A 16 kHz son 8 ms, así que una
 *    trama de 100 ms son 12,5 bloques: hay que acumular entre llamadas, y por
 *    eso el buffer intermedio.
 *
 * 2. La escala Int16 es 32767 en los dos sentidos, la misma que usa
 *    `youjp/ws/codec.py`. Con 32767 al codificar y 32768 al decodificar queda un
 *    sesgo de escala del 0,003 %: inaudible, pero convierte el test de ida y
 *    vuelta en algo que "casi" pasa.
 *
 * 3. El buffer se transfiere en vez de copiarse (`postMessage` con lista de
 *    transferencia), para no generar basura en el hilo de audio.
 */

const INT16_SCALE = 32767;

class PcmCollector extends AudioWorkletProcessor {
  constructor(options) {
    super();
    const { frameSamples = 1600 } = options.processorOptions ?? {};
    this.frameSamples = frameSamples;
    this.buffer = new Float32Array(frameSamples);
    this.filled = 0;
  }

  /**
   * Mezcla todos los canales a mono. La captura de pestaña llega en estéreo y
   * quedarse solo con el izquierdo perdería la mitad del diálogo en cuanto haya
   * cualquier paneo.
   */
  static downmix(input, target) {
    const channels = input.length;
    const frames = input[0].length;
    if (channels === 1) {
      target.set(input[0]);
      return frames;
    }
    for (let i = 0; i < frames; i++) {
      let sum = 0;
      for (let c = 0; c < channels; c++) sum += input[c][i];
      target[i] = sum / channels;
    }
    return frames;
  }

  process(inputs) {
    const input = inputs[0];
    // Sin entrada conectada todavía, o silencio estructural: devolver true
    // mantiene vivo el procesador.
    if (!input || input.length === 0 || !input[0] || input[0].length === 0) {
      return true;
    }

    if (!this.mixed || this.mixed.length < input[0].length) {
      this.mixed = new Float32Array(input[0].length);
    }
    const count = PcmCollector.downmix(input, this.mixed);

    let offset = 0;
    while (offset < count) {
      const room = this.frameSamples - this.filled;
      const take = Math.min(room, count - offset);
      this.buffer.set(this.mixed.subarray(offset, offset + take), this.filled);
      this.filled += take;
      offset += take;

      if (this.filled === this.frameSamples) {
        const out = new Int16Array(this.frameSamples);
        for (let i = 0; i < this.frameSamples; i++) {
          const s = Math.max(-1, Math.min(1, this.buffer[i]));
          out[i] = Math.round(s * INT16_SCALE);
        }
        this.port.postMessage(out.buffer, [out.buffer]);
        this.filled = 0;
      }
    }
    return true;
  }
}

registerProcessor('pcm-collector', PcmCollector);
